"""Единый сервис реферальной логики.

Все проверки, привязки и логирование реферальных событий
проходят через этот модуль. Другие части кода (handlers, database)
должны вызывать функции отсюда, а не дублировать логику.
"""

import logging
import html
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import aiohttp

from bot import db as db_backend
from bot.config import config


# ---------------------------------------------------------------------------
# Парсинг реферального кода из start_param (deep link)
# ---------------------------------------------------------------------------
def referral_code_from_start_param(start_param: Any) -> str:
    """Извлекает реферальный код из start_param Telegram Mini App.

    Поддерживаемые форматы:
      - ref_CODE             → CODE
      - feed_ID_ref_CODE     → CODE
      - remix_ID_ref_CODE    → CODE
      - posts_ID_ref_CODE    → CODE
      - profile_ID_ref_CODE  → CODE (or profile code itself)
      - prompt_ID            → "" (no referral)
      - start=CODE / startapp=CODE  → CODE

    Возвращает пустую строку, если код не найден.
    Это ЕДИНСТВЕННАЯ точка парсинга start_param для рефералов.
    """
    raw = str(start_param or "").strip()
    if not raw:
        return ""

    raw = raw.removeprefix("start=").removeprefix("startapp=").strip()

    if raw.startswith("ref_"):
        return raw.replace("ref_", "", 1).strip().upper()

    if raw.startswith(("profile_", "posts_")):
        payload = raw.split("_", 1)[1]
        profile_code, sep, referral_code = payload.partition("_ref_")
        return (referral_code if sep else profile_code).strip().upper()

    for prefix in ("feed_", "remix_", "prompt_"):
        if raw.startswith(prefix):
            _, sep, referral_code = raw.replace(prefix, "", 1).partition("_ref_")
            return referral_code.strip().upper() if sep else ""

    return ""
from bot.database import (
    DATABASE_PATH,
    PARTNER_INVITER_BONUS,
    REFERRAL_ANTIFRAUD_BLOCK_CODES,
    REFERRAL_ANTIFRAUD_BLOCK_REFERRER_IDS,
    REFERRAL_ANTIFRAUD_BURST_MAX,
    REFERRAL_ANTIFRAUD_BURST_WINDOW_SECONDS,
    REFERRAL_ANTIFRAUD_MAX_PER_HOUR,
    REFERRAL_ANTIFRAUD_MAX_PER_DAY,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Разрешённые причины (reason) для referral_events
# ---------------------------------------------------------------------------
VALID_REASONS = frozenset(
    {
        "attached",
        "empty_code",
        "code_not_found",
        "self_ref",
        "already_has_referrer_same",
        "already_has_referrer_other",
        "already_paid",
        "completed_payment_exists",
        "admin_user",
        "blocked_code",
        "blocked_referrer",
        "hourly_limit",
        "daily_limit",
        "burst_autoban",
        "cycle_detected",
        "db_race_lost",
        "invalid_state",
        "error",
    }
)


# ---------------------------------------------------------------------------
# ReferralResult — структурированный результат попытки привязки
# ---------------------------------------------------------------------------
@dataclass
class ReferralResult:
    clicked_code: Optional[str] = None
    clicked_referrer_id: Optional[int] = None
    existing_referrer_id: Optional[int] = None
    referred_user_id: int = 0
    attached: bool = False
    reason: str = "empty_code"
    is_self_click: bool = False
    is_repeat_click: bool = False
    notify_partner: bool = False
    # Дополнительные детали для логирования / отчётов
    referrer_telegram_id: Optional[int] = None
    source: Optional[str] = None
    start_param: Optional[str] = None

    def __post_init__(self):
        if self.reason not in VALID_REASONS:
            raise ValueError(f"Invalid referral reason: {self.reason}")


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------
async def _referral_chain_contains(
    db: db_backend.Connection,
    start_user_id: int,
    target_user_id: int,
) -> bool:
    """Проверяет, есть ли target_user_id в цепочке рефералов start_user_id."""
    from bot.database import _referral_chain_contains as _chain_fn

    return await _chain_fn(
        db, start_user_id=start_user_id, target_user_id=target_user_id
    )


async def _is_referral_burst_limit_reached(
    db: db_backend.Connection,
    referrer_id: int,
) -> bool:
    if REFERRAL_ANTIFRAUD_BURST_MAX <= 0 or REFERRAL_ANTIFRAUD_BURST_WINDOW_SECONDS <= 0:
        return False

    cursor = await db.execute(
        "SELECT COUNT(*) AS cnt FROM referrals WHERE referrer_id = ? AND created_at >= datetime('now', ?)",
        (referrer_id, f"-{REFERRAL_ANTIFRAUD_BURST_WINDOW_SECONDS} seconds"),
    )
    count = int((await cursor.fetchone())["cnt"])
    return count >= REFERRAL_ANTIFRAUD_BURST_MAX - 1


async def _autoban_referrer_for_burst(
    db: db_backend.Connection,
    referrer_id: int,
) -> None:
    await db.execute(
        """
        UPDATE users
        SET is_banned = 1,
            banned_at = CURRENT_TIMESTAMP,
            banned_by_telegram_id = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (referrer_id,),
    )


async def _notify_admins_about_referral_burst_autoban(
    *,
    referrer_id: int,
    referrer_telegram_id: int | None,
    referral_code: str,
    burst_count: int,
    window_seconds: int,
    visitor_telegram_id: int,
    source: str | None,
    start_param: str | None,
) -> None:
    admin_ids = config.admin_ids
    bot_token = (config.BOT_TOKEN or "").strip()
    if not admin_ids or not bot_token:
        return

    text = (
        "🚨 <b>Автобан по реферальному антифроду</b>\n\n"
        f"Партнёр user_id: <code>{referrer_id}</code>\n"
        f"Telegram ID: <code>{referrer_telegram_id or '—'}</code>\n"
        f"Рефкод: <code>{html.escape(referral_code)}</code>\n"
        f"Сработавший порог: <code>{burst_count}</code> за <code>{window_seconds}</code> сек.\n"
        f"Последний visitor Telegram ID: <code>{visitor_telegram_id}</code>\n"
        f"Источник: <code>{html.escape(source or '—')}</code>\n"
        f"start_param: <code>{html.escape(start_param or '—')}</code>"
    )
    timeout = aiohttp.ClientTimeout(total=15)
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for admin_id in admin_ids:
            try:
                async with session.post(
                    url,
                    json={
                        "chat_id": admin_id,
                        "text": text,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                ) as response:
                    await response.read()
                    if response.status >= 400:
                        logger.warning(
                            "Failed to notify admin about referral burst autoban: admin_id=%s status=%s",
                            admin_id,
                            response.status,
                        )
            except Exception:
                logger.exception(
                    "Failed to notify admin about referral burst autoban admin_id=%s",
                    admin_id,
                )


async def _ensure_referral_events_table(db: db_backend.Connection) -> None:
    """Создаёт таблицу referral_events, если её нет (idempotent).

    На PostgreSQL использует прямой psycopg-курсор, потому что aiosqlite-адаптер
    пропускает DDL-запросы (translate_sql возвращает None для CREATE TABLE/INDEX).
    На SQLite — через обычный db.execute.
    """
    if db_backend.is_postgres():
        import os

        import psycopg

        dsn = os.getenv("DATABASE_URL", "")
        async with await psycopg.AsyncConnection.connect(dsn) as raw_conn:
            async with raw_conn.cursor() as cur:
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS referral_events (
                        id BIGSERIAL PRIMARY KEY,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        visitor_user_id BIGINT,
                        visitor_telegram_id BIGINT NOT NULL,
                        clicked_code TEXT,
                        clicked_referrer_id BIGINT,
                        existing_referrer_id BIGINT,
                        attached BOOLEAN DEFAULT FALSE,
                        reason TEXT NOT NULL,
                        source TEXT,
                        start_param TEXT,
                        is_self_click BOOLEAN DEFAULT FALSE,
                        is_repeat_click BOOLEAN DEFAULT FALSE,
                        metadata JSONB DEFAULT '{}'::jsonb
                    )
                """)
                for idx_stmt in [
                    "CREATE INDEX IF NOT EXISTS idx_referral_events_created_at ON referral_events(created_at)",
                    "CREATE INDEX IF NOT EXISTS idx_referral_events_visitor_telegram_id ON referral_events(visitor_telegram_id)",
                    "CREATE INDEX IF NOT EXISTS idx_referral_events_clicked_referrer_id ON referral_events(clicked_referrer_id)",
                    "CREATE INDEX IF NOT EXISTS idx_referral_events_reason ON referral_events(reason)",
                    "CREATE INDEX IF NOT EXISTS idx_referral_events_attached ON referral_events(attached)",
                    "CREATE INDEX IF NOT EXISTS idx_referral_events_clicked_code ON referral_events(clicked_code)",
                ]:
                    await cur.execute(idx_stmt)
                await raw_conn.commit()
        return

    # SQLite path
    await db.execute("""
        CREATE TABLE IF NOT EXISTS referral_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            visitor_user_id INTEGER,
            visitor_telegram_id INTEGER NOT NULL,
            clicked_code TEXT,
            clicked_referrer_id INTEGER,
            existing_referrer_id INTEGER,
            attached INTEGER DEFAULT 0,
            reason TEXT NOT NULL,
            source TEXT,
            start_param TEXT,
            is_self_click INTEGER DEFAULT 0,
            is_repeat_click INTEGER DEFAULT 0,
            metadata TEXT DEFAULT '{}'
        )
    """)

    for idx_name, idx_col in [
        ("idx_referral_events_created_at", "created_at"),
        ("idx_referral_events_visitor_telegram_id", "visitor_telegram_id"),
        ("idx_referral_events_clicked_referrer_id", "clicked_referrer_id"),
        ("idx_referral_events_reason", "reason"),
        ("idx_referral_events_attached", "attached"),
        ("idx_referral_events_clicked_code", "clicked_code"),
    ]:
        try:
            await db.execute(
                f"CREATE INDEX IF NOT EXISTS {idx_name} ON referral_events({idx_col})"
            )
        except db_backend.OperationalError:
            pass


async def _ensure_partner_commissions_table(db: db_backend.Connection) -> None:
    """Создаёт таблицу partner_commissions, если её нет (idempotent).

    На PostgreSQL таблица уже создана через _ensure_postgres_helpers().
    """
    if db_backend.is_postgres():
        return

    await db.execute("""
        CREATE TABLE IF NOT EXISTS partner_commissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id INTEGER NOT NULL,
            order_id TEXT NOT NULL,
            referrer_id INTEGER NOT NULL,
            referred_id INTEGER NOT NULL,
            level INTEGER NOT NULL,
            base_amount_rub REAL NOT NULL,
            percent REAL NOT NULL,
            amount_rub REAL NOT NULL,
            tier TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(transaction_id, referrer_id, level)
        )
    """)

    for idx_name, idx_col in [
        ("idx_partner_commissions_referrer_id", "referrer_id"),
        ("idx_partner_commissions_referred_id", "referred_id"),
        ("idx_partner_commissions_transaction_id", "transaction_id"),
        ("idx_partner_commissions_created_at", "created_at"),
    ]:
        try:
            await db.execute(
                f"CREATE INDEX IF NOT EXISTS {idx_name} ON partner_commissions({idx_col})"
            )
        except db_backend.OperationalError:
            pass


async def init_referral_tables_if_needed() -> None:
    """Вызывается из init_db() для гарантии, что таблицы есть."""
    async with db_backend.connect(DATABASE_PATH) as db:
        await _ensure_referral_events_table(db)
        await _ensure_partner_commissions_table(db)
        await db.commit()


# ---------------------------------------------------------------------------
# Запись события в referral_events
# ---------------------------------------------------------------------------
async def record_referral_event(
    result: ReferralResult,
    visitor_telegram_id: int,
    visitor_user_id: Optional[int] = None,
    metadata: Optional[dict[str, Any]] = None,
    db: Any = None,
) -> None:
    """Логирует любое обращение по реферальной ссылке в referral_events.

    Если передан ``db`` (открытое соединение), использует его без коммита —
    событие будет закоммичено в составе внешней транзакции.
    Если ``db`` не передан, открывает новое соединение и коммитит сразу.
    """
    import json

    if db is not None:
        # Таблица referral_events гарантированно создана в _ensure_postgres_helpers()
        # при первом подключении к PG. Дополнительный вызов _ensure_referral_events_table
        # открывает отдельное psycopg-соединение, что избыточно и может ломать транзакцию.
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)

        is_postgres = db_backend.is_postgres()
        try:
            await db.execute(
                """
                INSERT INTO referral_events (
                    visitor_user_id, visitor_telegram_id, clicked_code,
                    clicked_referrer_id, existing_referrer_id, attached,
                    reason, source, start_param, is_self_click, is_repeat_click, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    visitor_user_id,
                    visitor_telegram_id,
                    result.clicked_code,
                    result.clicked_referrer_id,
                    result.existing_referrer_id,
                    str(result.attached).upper() if is_postgres else (1 if result.attached else 0),
                    result.reason,
                    result.source,
                    result.start_param,
                    str(result.is_self_click).upper() if is_postgres else (1 if result.is_self_click else 0),
                    str(result.is_repeat_click).upper() if is_postgres else (1 if result.is_repeat_click else 0),
                    meta_json,
                ),
            )
        except Exception:
            logger.exception(
                "Failed to record referral event: visitor=%s reason=%s",
                visitor_telegram_id,
                result.reason,
            )
        return

    # Fallback: own connection (when called outside a transaction)
    async with db_backend.connect(DATABASE_PATH) as own_db:
        # Таблица гарантированно существует через _ensure_postgres_helpers()
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)

        is_postgres = db_backend.is_postgres()

        try:
            await own_db.execute(
                """
                INSERT INTO referral_events (
                    visitor_user_id, visitor_telegram_id, clicked_code,
                    clicked_referrer_id, existing_referrer_id, attached,
                    reason, source, start_param, is_self_click, is_repeat_click, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    visitor_user_id,
                    visitor_telegram_id,
                    result.clicked_code,
                    result.clicked_referrer_id,
                    result.existing_referrer_id,
                    str(result.attached).upper() if is_postgres else (1 if result.attached else 0),
                    result.reason,
                    result.source,
                    result.start_param,
                    str(result.is_self_click).upper() if is_postgres else (1 if result.is_self_click else 0),
                    str(result.is_repeat_click).upper() if is_postgres else (1 if result.is_repeat_click else 0),
                    meta_json,
                ),
            )
            await own_db.commit()
        except Exception:
            logger.exception(
                "Failed to record referral event: visitor=%s reason=%s",
                visitor_telegram_id,
                result.reason,
            )


# ---------------------------------------------------------------------------
# Единая функция проверки и привязки реферала (validate + attach)
# ---------------------------------------------------------------------------
async def process_referral_click(
    visitor_telegram_id: int,
    referral_code: str | None,
    *,
    source: str | None = None,
    start_param: str | None = None,
) -> ReferralResult:
    """Главная точка входа: проверяет и привязывает реферала.

    Эта функция ДОЛЖНА использоваться всеми путями:
      - /start ref_CODE
      - miniapp start_param
      - feed_/remix_/posts_ deep links
      - новый пользователь при регистрации
      - существующий пользователь без referred_by

    Возвращает ReferralResult, который говорит:
      - была ли привязка (attached)
      - причина (reason)
      - нужно ли уведомлять партнёра (notify_partner)
    """
    code = str(referral_code or "").strip().upper()

    # Базовый результат для пустого кода
    if not code:
        result = ReferralResult(
            clicked_code=None,
            reason="empty_code",
            referred_user_id=0,
            source=source,
            start_param=start_param,
        )
        await record_referral_event(result, visitor_telegram_id)
        return result

    async with db_backend.connect(DATABASE_PATH, timeout=15) as db:
        db.row_factory = db_backend.Row

        async def _record_and_commit(
            result: ReferralResult,
            visitor_user_id: int | None = None,
        ) -> ReferralResult:
            await record_referral_event(
                result,
                visitor_telegram_id,
                visitor_user_id,
                db=db,
            )
            await db.commit()
            return result

        # 1. Ищем реферера по коду
        referrer_cursor = await db.execute(
            "SELECT id, telegram_id, referral_code, COALESCE(is_banned, 0) AS is_banned FROM users WHERE referral_code = ?",
            (code,),
        )
        referrer_row = await referrer_cursor.fetchone()

        if not referrer_row:
            result = ReferralResult(
                clicked_code=code,
                reason="code_not_found",
                source=source,
                start_param=start_param,
            )
            return await _record_and_commit(result)

        referrer_id = int(referrer_row["id"])
        referrer_telegram_id = int(referrer_row["telegram_id"])
        if referrer_row["is_banned"]:
            result = ReferralResult(
                clicked_code=code,
                clicked_referrer_id=referrer_id,
                referrer_telegram_id=referrer_telegram_id,
                reason="blocked_referrer",
                source=source,
                start_param=start_param,
            )
            return await _record_and_commit(result)

        # 2. Ищем посетителя
        visitor_cursor = await db.execute(
            """
            SELECT
                u.id, u.telegram_id, u.referred_by,
                COALESCE(u.has_paid, 0) AS has_paid,
                EXISTS(
                    SELECT 1 FROM transactions t
                    WHERE t.user_id = u.id AND t.status = 'completed'
                    LIMIT 1
                ) AS has_completed_payment
            FROM users u
            WHERE u.telegram_id = ?
            """,
            (visitor_telegram_id,),
        )
        visitor_row = await visitor_cursor.fetchone()

        if not visitor_row:
            # Пользователь ещё не создан — это ок, вызывающий код создаст пользователя
            # и затем вызовет process_referral_click_in_transaction
            result = ReferralResult(
                clicked_code=code,
                clicked_referrer_id=referrer_id,
                referrer_telegram_id=referrer_telegram_id,
                reason="invalid_state",  # вызывающий должен создать user и повторить
                source=source,
                start_param=start_param,
            )
            return await _record_and_commit(result)

        visitor_user_id = int(visitor_row["id"])
        existing_referrer_id = (
            int(visitor_row["referred_by"]) if visitor_row["referred_by"] else None
        )

        if config.is_admin(int(visitor_row["telegram_id"])):
            result = ReferralResult(
                clicked_code=code,
                clicked_referrer_id=referrer_id,
                existing_referrer_id=existing_referrer_id,
                referred_user_id=visitor_user_id,
                reason="admin_user",
                source=source,
                start_param=start_param,
            )
            return await _record_and_commit(result, visitor_user_id)

        # 3. Self-ref
        if visitor_row["telegram_id"] == referrer_telegram_id:
            result = ReferralResult(
                clicked_code=code,
                clicked_referrer_id=referrer_id,
                existing_referrer_id=existing_referrer_id,
                referred_user_id=visitor_user_id,
                is_self_click=True,
                reason="self_ref",
                source=source,
                start_param=start_param,
            )
            return await _record_and_commit(result, visitor_user_id)

        # 4. Уже привязан к тому же рефереру
        if existing_referrer_id and existing_referrer_id == referrer_id:
            result = ReferralResult(
                clicked_code=code,
                clicked_referrer_id=referrer_id,
                existing_referrer_id=existing_referrer_id,
                referred_user_id=visitor_user_id,
                is_repeat_click=True,
                reason="already_has_referrer_same",
                source=source,
                start_param=start_param,
            )
            return await _record_and_commit(result, visitor_user_id)

        # 5. Уже привязан к другому рефереру
        if existing_referrer_id:
            result = ReferralResult(
                clicked_code=code,
                clicked_referrer_id=referrer_id,
                existing_referrer_id=existing_referrer_id,
                referred_user_id=visitor_user_id,
                reason="already_has_referrer_other",
                source=source,
                start_param=start_param,
            )
            return await _record_and_commit(result, visitor_user_id)

        # 6. Уже платил
        if visitor_row["has_paid"] or visitor_row["has_completed_payment"]:
            reason = (
                "completed_payment_exists"
                if visitor_row["has_completed_payment"]
                else "already_paid"
            )
            result = ReferralResult(
                clicked_code=code,
                clicked_referrer_id=referrer_id,
                existing_referrer_id=existing_referrer_id,
                referred_user_id=visitor_user_id,
                reason=reason,
                source=source,
                start_param=start_param,
            )
            return await _record_and_commit(result, visitor_user_id)

        # 7. Blocklist
        if code in REFERRAL_ANTIFRAUD_BLOCK_CODES:
            result = ReferralResult(
                clicked_code=code,
                clicked_referrer_id=referrer_id,
                existing_referrer_id=existing_referrer_id,
                referred_user_id=visitor_user_id,
                reason="blocked_code",
                source=source,
                start_param=start_param,
            )
            return await _record_and_commit(result, visitor_user_id)

        if referrer_id in REFERRAL_ANTIFRAUD_BLOCK_REFERRER_IDS:
            result = ReferralResult(
                clicked_code=code,
                clicked_referrer_id=referrer_id,
                existing_referrer_id=existing_referrer_id,
                referred_user_id=visitor_user_id,
                reason="blocked_referrer",
                source=source,
                start_param=start_param,
            )
            return await _record_and_commit(result, visitor_user_id)

        # 8. Антифрод-лимиты
        hourly_cursor = await db.execute(
            "SELECT COUNT(*) AS cnt FROM referrals WHERE referrer_id = ? AND created_at >= datetime('now', '-1 hour')",
            (referrer_id,),
        )
        hourly_count = int((await hourly_cursor.fetchone())["cnt"])
        if hourly_count >= REFERRAL_ANTIFRAUD_MAX_PER_HOUR:
            result = ReferralResult(
                clicked_code=code,
                clicked_referrer_id=referrer_id,
                existing_referrer_id=existing_referrer_id,
                referred_user_id=visitor_user_id,
                reason="hourly_limit",
                source=source,
                start_param=start_param,
            )
            return await _record_and_commit(result, visitor_user_id)

        daily_cursor = await db.execute(
            "SELECT COUNT(*) AS cnt FROM referrals WHERE referrer_id = ? AND created_at >= datetime('now', '-1 day')",
            (referrer_id,),
        )
        daily_count = int((await daily_cursor.fetchone())["cnt"])
        if daily_count >= REFERRAL_ANTIFRAUD_MAX_PER_DAY:
            result = ReferralResult(
                clicked_code=code,
                clicked_referrer_id=referrer_id,
                existing_referrer_id=existing_referrer_id,
                referred_user_id=visitor_user_id,
                reason="daily_limit",
                source=source,
                start_param=start_param,
            )
            return await _record_and_commit(result, visitor_user_id)

        if await _is_referral_burst_limit_reached(db, referrer_id):
            await _autoban_referrer_for_burst(db, referrer_id)
            burst_count = REFERRAL_ANTIFRAUD_BURST_MAX
            result = ReferralResult(
                clicked_code=code,
                clicked_referrer_id=referrer_id,
                existing_referrer_id=existing_referrer_id,
                referred_user_id=visitor_user_id,
                referrer_telegram_id=referrer_telegram_id,
                reason="burst_autoban",
                source=source,
                start_param=start_param,
            )
            await _notify_admins_about_referral_burst_autoban(
                referrer_id=referrer_id,
                referrer_telegram_id=referrer_telegram_id,
                referral_code=code,
                burst_count=burst_count,
                window_seconds=REFERRAL_ANTIFRAUD_BURST_WINDOW_SECONDS,
                visitor_telegram_id=visitor_telegram_id,
                source=source,
                start_param=start_param,
            )
            return await _record_and_commit(result, visitor_user_id)

        # 9. Cycle detection
        if await _referral_chain_contains(db, start_user_id=referrer_id, target_user_id=visitor_user_id):
            result = ReferralResult(
                clicked_code=code,
                clicked_referrer_id=referrer_id,
                existing_referrer_id=existing_referrer_id,
                referred_user_id=visitor_user_id,
                reason="cycle_detected",
                source=source,
                start_param=start_param,
            )
            return await _record_and_commit(result, visitor_user_id)

        # 10. ПРИВЯЗКА: атомарный UPDATE + INSERT + бонус рефереру
        update_cursor = await db.execute(
            """
            UPDATE users
            SET referred_by = ?, updated_at = CURRENT_TIMESTAMP
            WHERE telegram_id = ?
              AND referred_by IS NULL
              AND id != ?
              AND COALESCE(has_paid, 0) = 0
              AND NOT EXISTS (
                  SELECT 1 FROM transactions t
                  WHERE t.user_id = users.id AND t.status = 'completed'
                  LIMIT 1
              )
            """,
            (referrer_id, visitor_telegram_id, referrer_id),
        )
        if update_cursor.rowcount != 1:
            await db.rollback()
            result = ReferralResult(
                clicked_code=code,
                clicked_referrer_id=referrer_id,
                existing_referrer_id=existing_referrer_id,
                referred_user_id=visitor_user_id,
                reason="db_race_lost",
                source=source,
                start_param=start_param,
            )
            return await _record_and_commit(result, visitor_user_id)

        insert_cursor = await db.execute(
            "INSERT OR IGNORE INTO referrals (referrer_id, referred_id, bonus_credits) VALUES (?, ?, 3)",
            (referrer_id, visitor_user_id),
        )
        if insert_cursor.rowcount != 1:
            await db.rollback()
            result = ReferralResult(
                clicked_code=code,
                clicked_referrer_id=referrer_id,
                existing_referrer_id=existing_referrer_id,
                referred_user_id=visitor_user_id,
                reason="db_race_lost",
                source=source,
                start_param=start_param,
            )
            return await _record_and_commit(result, visitor_user_id)

        # Начисляем бонус рефереру
        await db.execute(
            "UPDATE users SET credits = credits + ?, referral_earned = referral_earned + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (PARTNER_INVITER_BONUS, PARTNER_INVITER_BONUS, referrer_id),
        )

        result = ReferralResult(
            clicked_code=code,
            clicked_referrer_id=referrer_id,
            existing_referrer_id=existing_referrer_id,
            referred_user_id=visitor_user_id,
            attached=True,
            reason="attached",
            notify_partner=True,
            referrer_telegram_id=referrer_telegram_id,
            source=source,
            start_param=start_param,
        )
        await _record_and_commit(result, visitor_user_id)

        logger.info(
            "Referral attached: visitor=%s code=%s referrer_id=%s",
            visitor_telegram_id,
            code,
            referrer_id,
        )
        return result


# ---------------------------------------------------------------------------
# Функция для использования внутри транзакции (когда пользователь только создан)
# ---------------------------------------------------------------------------
async def attach_referral_in_transaction(
    db: db_backend.Connection,
    visitor_telegram_id: int,
    visitor_user_id: int,
    referral_code: str | None,
    *,
    source: str | None = None,
    start_param: str | None = None,
) -> ReferralResult:
    """Привязывает реферала внутри уже открытой транзакции.

    Используется при создании нового пользователя, когда транзакция уже открыта.
    Не открывает новое соединение — работает с переданным db.
    """
    code = str(referral_code or "").strip().upper()

    if not code:
        result = ReferralResult(
            clicked_code=None,
            referred_user_id=visitor_user_id,
            reason="empty_code",
            source=source,
            start_param=start_param,
        )
        await record_referral_event(result, visitor_telegram_id, visitor_user_id, db=db)
        return result

    db.row_factory = db_backend.Row

    # Ищем реферера (без фильтра telegram_id — self-ref проверяем ниже)
    referrer_cursor = await db.execute(
        "SELECT id, telegram_id, COALESCE(is_banned, 0) AS is_banned FROM users WHERE referral_code = ?",
        (code,),
    )
    referrer_row = await referrer_cursor.fetchone()

    if not referrer_row:
        result = ReferralResult(
            clicked_code=code,
            referred_user_id=visitor_user_id,
            reason="code_not_found",
            source=source,
            start_param=start_param,
        )
        await record_referral_event(result, visitor_telegram_id, visitor_user_id, db=db)
        return result

    referrer_id = int(referrer_row["id"])
    referrer_telegram_id = int(referrer_row["telegram_id"])
    if referrer_row["is_banned"]:
        result = ReferralResult(
            clicked_code=code,
            clicked_referrer_id=referrer_id,
            referred_user_id=visitor_user_id,
            referrer_telegram_id=referrer_telegram_id,
            reason="blocked_referrer",
            source=source,
            start_param=start_param,
        )
        await record_referral_event(result, visitor_telegram_id, visitor_user_id, db=db)
        return result

    # Self-ref
    if referrer_telegram_id == visitor_telegram_id:
        result = ReferralResult(
            clicked_code=code,
            clicked_referrer_id=referrer_id,
            referred_user_id=visitor_user_id,
            is_self_click=True,
            reason="self_ref",
            source=source,
            start_param=start_param,
        )
        await record_referral_event(result, visitor_telegram_id, visitor_user_id, db=db)
        return result

    # Blocklist
    if code in REFERRAL_ANTIFRAUD_BLOCK_CODES:
        result = ReferralResult(
            clicked_code=code,
            clicked_referrer_id=referrer_id,
            referred_user_id=visitor_user_id,
            reason="blocked_code",
            source=source,
            start_param=start_param,
        )
        await record_referral_event(result, visitor_telegram_id, visitor_user_id, db=db)
        return result

    if referrer_id in REFERRAL_ANTIFRAUD_BLOCK_REFERRER_IDS:
        result = ReferralResult(
            clicked_code=code,
            clicked_referrer_id=referrer_id,
            referred_user_id=visitor_user_id,
            reason="blocked_referrer",
            source=source,
            start_param=start_param,
        )
        await record_referral_event(result, visitor_telegram_id, visitor_user_id, db=db)
        return result

    # Hourly limit
    hourly_cursor = await db.execute(
        "SELECT COUNT(*) AS cnt FROM referrals WHERE referrer_id = ? AND created_at >= datetime('now', '-1 hour')",
        (referrer_id,),
    )
    hourly_count = int((await hourly_cursor.fetchone())["cnt"])
    if hourly_count >= REFERRAL_ANTIFRAUD_MAX_PER_HOUR:
        result = ReferralResult(
            clicked_code=code,
            clicked_referrer_id=referrer_id,
            referred_user_id=visitor_user_id,
            reason="hourly_limit",
            source=source,
            start_param=start_param,
        )
        await record_referral_event(result, visitor_telegram_id, visitor_user_id, db=db)
        return result

    # Daily limit
    daily_cursor = await db.execute(
        "SELECT COUNT(*) AS cnt FROM referrals WHERE referrer_id = ? AND created_at >= datetime('now', '-1 day')",
        (referrer_id,),
    )
    daily_count = int((await daily_cursor.fetchone())["cnt"])
    if daily_count >= REFERRAL_ANTIFRAUD_MAX_PER_DAY:
        result = ReferralResult(
            clicked_code=code,
            clicked_referrer_id=referrer_id,
            referred_user_id=visitor_user_id,
            reason="daily_limit",
            source=source,
            start_param=start_param,
        )
        await record_referral_event(result, visitor_telegram_id, visitor_user_id, db=db)
        return result

    if await _is_referral_burst_limit_reached(db, referrer_id):
        await _autoban_referrer_for_burst(db, referrer_id)
        burst_count = REFERRAL_ANTIFRAUD_BURST_MAX
        result = ReferralResult(
            clicked_code=code,
            clicked_referrer_id=referrer_id,
            referred_user_id=visitor_user_id,
            referrer_telegram_id=referrer_telegram_id,
            reason="burst_autoban",
            source=source,
            start_param=start_param,
        )
        await _notify_admins_about_referral_burst_autoban(
            referrer_id=referrer_id,
            referrer_telegram_id=referrer_telegram_id,
            referral_code=code,
            burst_count=burst_count,
            window_seconds=REFERRAL_ANTIFRAUD_BURST_WINDOW_SECONDS,
            visitor_telegram_id=visitor_telegram_id,
            source=source,
            start_param=start_param,
        )
        await record_referral_event(result, visitor_telegram_id, visitor_user_id, db=db)
        return result

    # Cycle detection
    if await _referral_chain_contains(db, start_user_id=referrer_id, target_user_id=visitor_user_id):
        result = ReferralResult(
            clicked_code=code,
            clicked_referrer_id=referrer_id,
            referred_user_id=visitor_user_id,
            reason="cycle_detected",
            source=source,
            start_param=start_param,
        )
        await record_referral_event(result, visitor_telegram_id, visitor_user_id, db=db)
        return result

    # Атомарная привязка
    update_cursor = await db.execute(
        """
        UPDATE users
        SET referred_by = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND referred_by IS NULL AND id != ?
        """,
        (referrer_id, visitor_user_id, referrer_id),
    )

    if update_cursor.rowcount != 1:
        result = ReferralResult(
            clicked_code=code,
            clicked_referrer_id=referrer_id,
            referred_user_id=visitor_user_id,
            reason="db_race_lost",
            source=source,
            start_param=start_param,
        )
        await record_referral_event(result, visitor_telegram_id, visitor_user_id, db=db)
        return result

    insert_cursor = await db.execute(
        "INSERT OR IGNORE INTO referrals (referrer_id, referred_id, bonus_credits) VALUES (?, ?, 3)",
        (referrer_id, visitor_user_id),
    )

    if insert_cursor.rowcount != 1:
        result = ReferralResult(
            clicked_code=code,
            clicked_referrer_id=referrer_id,
            referred_user_id=visitor_user_id,
            reason="db_race_lost",
            source=source,
            start_param=start_param,
        )
        await record_referral_event(result, visitor_telegram_id, visitor_user_id, db=db)
        return result

    # Начисляем бонус рефереру
    await db.execute(
        "UPDATE users SET credits = credits + ?, referral_earned = referral_earned + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (PARTNER_INVITER_BONUS, PARTNER_INVITER_BONUS, referrer_id),
    )

    result = ReferralResult(
        clicked_code=code,
        clicked_referrer_id=referrer_id,
        referred_user_id=visitor_user_id,
        attached=True,
        reason="attached",
        notify_partner=True,
        referrer_telegram_id=referrer_telegram_id,
        source=source,
        start_param=start_param,
    )
    await record_referral_event(result, visitor_telegram_id, visitor_user_id, db=db)

    logger.info(
        "Referral attached in transaction: visitor=%s code=%s referrer_id=%s",
        visitor_telegram_id,
        code,
        referrer_id,
    )
    return result


# ---------------------------------------------------------------------------
# Валидация без привязки (для диагностики)
# ---------------------------------------------------------------------------
async def validate_referral_attach(
    visitor_telegram_id: int,
    referral_code: str | None,
) -> ReferralResult:
    """Только проверяет возможность привязки, НЕ выполняет её.

    Полезна для UI / диагностики перед фактической привязкой.
    """
    code = str(referral_code or "").strip().upper()
    if not code:
        return ReferralResult(reason="empty_code")

    async with db_backend.connect(DATABASE_PATH, timeout=15) as db:
        db.row_factory = db_backend.Row

        referrer_cursor = await db.execute(
            "SELECT id, telegram_id FROM users WHERE referral_code = ?",
            (code,),
        )
        referrer_row = await referrer_cursor.fetchone()
        if not referrer_row:
            return ReferralResult(clicked_code=code, reason="code_not_found")

        referrer_id = int(referrer_row["id"])
        referrer_telegram_id = int(referrer_row["telegram_id"])

        visitor_cursor = await db.execute(
            "SELECT id, referred_by, COALESCE(has_paid, 0) AS has_paid FROM users WHERE telegram_id = ?",
            (visitor_telegram_id,),
        )
        visitor_row = await visitor_cursor.fetchone()
        if not visitor_row:
            return ReferralResult(
                clicked_code=code,
                clicked_referrer_id=referrer_id,
                reason="invalid_state",
            )

        visitor_user_id = int(visitor_row["id"])
        existing = int(visitor_row["referred_by"]) if visitor_row["referred_by"] else None

        if referrer_telegram_id == visitor_telegram_id:
            return ReferralResult(
                clicked_code=code,
                clicked_referrer_id=referrer_id,
                existing_referrer_id=existing,
                referred_user_id=visitor_user_id,
                is_self_click=True,
                reason="self_ref",
            )

        if existing:
            if existing == referrer_id:
                return ReferralResult(
                    clicked_code=code,
                    clicked_referrer_id=referrer_id,
                    existing_referrer_id=existing,
                    referred_user_id=visitor_user_id,
                    is_repeat_click=True,
                    reason="already_has_referrer_same",
                )
            return ReferralResult(
                clicked_code=code,
                clicked_referrer_id=referrer_id,
                existing_referrer_id=existing,
                referred_user_id=visitor_user_id,
                reason="already_has_referrer_other",
            )

        if visitor_row["has_paid"]:
            return ReferralResult(
                clicked_code=code,
                clicked_referrer_id=referrer_id,
                referred_user_id=visitor_user_id,
                reason="already_paid",
            )

        # Валидация прошла — но привязку не делаем
        return ReferralResult(
            clicked_code=code,
            clicked_referrer_id=referrer_id,
            referred_user_id=visitor_user_id,
            reason="attached",  # потенциально может быть привязан
        )
