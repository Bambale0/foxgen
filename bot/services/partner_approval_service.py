from __future__ import annotations

import asyncio
import html
import logging
import os
from typing import Any

from aiogram import Bot, types

from bot import db as db_backend
from bot.config import config
from bot.database import DATABASE_PATH, get_or_create_user

logger = logging.getLogger(__name__)

PARTNER_APPLICATION_AVAILABLE = "available"
PARTNER_APPLICATION_PENDING = "pending"
PARTNER_APPLICATION_APPROVED = "approved"
PARTNER_APPLICATION_REJECTED = "rejected"

_SCHEMA_READY = False
_SCHEMA_LOCK: asyncio.Lock | None = None
_REFERRAL_GUARD_INSTALLED = False
_ORIGINAL_PROCESS_REFERRAL_CLICK = None
_ORIGINAL_ATTACH_REFERRAL_IN_TRANSACTION = None


def _schema_lock() -> asyncio.Lock:
    global _SCHEMA_LOCK
    if _SCHEMA_LOCK is None:
        _SCHEMA_LOCK = asyncio.Lock()
    return _SCHEMA_LOCK


def _postgres_dsn() -> str:
    dsn = str(os.getenv("DATABASE_URL", "") or "").strip()
    if dsn.lower().startswith("postgresql+asyncpg://"):
        return "postgresql://" + dsn[len("postgresql+asyncpg://") :]
    return dsn


async def ensure_partner_approval_schema() -> None:
    """Create the partner application state machine storage once per process."""

    global _SCHEMA_READY
    if _SCHEMA_READY:
        return

    async with _schema_lock():
        if _SCHEMA_READY:
            return

        if db_backend.is_postgres():
            import psycopg

            dsn = _postgres_dsn()
            if not dsn:
                raise RuntimeError("DATABASE_URL is required for PostgreSQL")
            async with await psycopg.AsyncConnection.connect(dsn) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS partner_applications (
                            id BIGSERIAL PRIMARY KEY,
                            user_id BIGINT NOT NULL UNIQUE REFERENCES users(id),
                            status TEXT NOT NULL DEFAULT 'pending',
                            source TEXT,
                            requested_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            reviewed_at TIMESTAMP,
                            reviewed_by_telegram_id BIGINT,
                            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                    await cur.execute(
                        "CREATE INDEX IF NOT EXISTS idx_partner_applications_status_requested "
                        "ON partner_applications(status, requested_at DESC)"
                    )
                    await conn.commit()
        else:
            async with db_backend.connect(DATABASE_PATH) as db:
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS partner_applications (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL UNIQUE,
                        status TEXT NOT NULL DEFAULT 'pending',
                        source TEXT,
                        requested_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        reviewed_at TIMESTAMP,
                        reviewed_by_telegram_id INTEGER,
                        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(id)
                    )
                    """
                )
                await db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_partner_applications_status_requested "
                    "ON partner_applications(status, requested_at DESC)"
                )
                await db.commit()

        _SCHEMA_READY = True


def _application_payload(row: Any | None) -> dict[str, Any] | None:
    if not row:
        return None
    keys = set(row.keys())
    return {
        "id": int(row["id"]),
        "user_id": int(row["user_id"]),
        "telegram_id": int(row["telegram_id"]) if "telegram_id" in keys else None,
        "username": (row["username"] or "") if "username" in keys else "",
        "first_name": (row["first_name"] or "") if "first_name" in keys else "",
        "last_name": (row["last_name"] or "") if "last_name" in keys else "",
        "referral_code": (row["referral_code"] or "") if "referral_code" in keys else "",
        "status": str(row["status"] or PARTNER_APPLICATION_PENDING),
        "source": (row["source"] or "") if "source" in keys else "",
        "requested_at": row["requested_at"] if "requested_at" in keys else None,
        "reviewed_at": row["reviewed_at"] if "reviewed_at" in keys else None,
        "reviewed_by_telegram_id": (
            int(row["reviewed_by_telegram_id"])
            if "reviewed_by_telegram_id" in keys and row["reviewed_by_telegram_id"]
            else None
        ),
    }


async def get_partner_application_state(telegram_id: int) -> dict[str, Any]:
    """Return server-side partner access state for one Telegram account."""

    await ensure_partner_approval_schema()
    user = await get_or_create_user(int(telegram_id))

    # Existing activated partners are grandfathered automatically. The existing
    # partner_agreed_at field stays the financial system's activation flag.
    if user.partner_agreed_at:
        return {
            "status": PARTNER_APPLICATION_APPROVED,
            "is_partner": True,
            "application_id": None,
            "can_apply": False,
        }

    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT id, user_id, status, source, requested_at, reviewed_at,
                   reviewed_by_telegram_id
            FROM partner_applications
            WHERE user_id = ?
            LIMIT 1
            """,
            (user.id,),
        )
        row = await cursor.fetchone()

    if not row:
        return {
            "status": PARTNER_APPLICATION_AVAILABLE,
            "is_partner": False,
            "application_id": None,
            "can_apply": True,
        }

    status = str(row["status"] or PARTNER_APPLICATION_AVAILABLE)
    if status not in {
        PARTNER_APPLICATION_PENDING,
        PARTNER_APPLICATION_APPROVED,
        PARTNER_APPLICATION_REJECTED,
    }:
        status = PARTNER_APPLICATION_AVAILABLE

    return {
        "status": status,
        "is_partner": status == PARTNER_APPLICATION_APPROVED,
        "application_id": int(row["id"]),
        "can_apply": status in {
            PARTNER_APPLICATION_AVAILABLE,
            PARTNER_APPLICATION_REJECTED,
        },
        "requested_at": row["requested_at"],
        "reviewed_at": row["reviewed_at"],
    }


async def get_partner_application(application_id: int) -> dict[str, Any] | None:
    await ensure_partner_approval_schema()
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT pa.id, pa.user_id, pa.status, pa.source, pa.requested_at,
                   pa.reviewed_at, pa.reviewed_by_telegram_id,
                   u.telegram_id, u.username, u.first_name, u.last_name,
                   u.referral_code
            FROM partner_applications pa
            JOIN users u ON u.id = pa.user_id
            WHERE pa.id = ?
            LIMIT 1
            """,
            (int(application_id),),
        )
        return _application_payload(await cursor.fetchone())


async def submit_partner_application(
    telegram_id: int,
    *,
    source: str,
) -> dict[str, Any]:
    """Create or re-submit a partner application idempotently and race-safely."""

    await ensure_partner_approval_schema()
    user = await get_or_create_user(int(telegram_id))
    if user.partner_agreed_at:
        return {
            "ok": True,
            "created": False,
            "status": PARTNER_APPLICATION_APPROVED,
            "is_partner": True,
            "application_id": None,
        }

    clean_source = str(source or "unknown").strip()[:32] or "unknown"
    created = False
    async with db_backend.connect(DATABASE_PATH, timeout=15) as db:
        db.row_factory = db_backend.Row
        await db.execute("BEGIN IMMEDIATE")
        try:
            # Re-submission is allowed only from rejected -> pending. The
            # conditional update makes concurrent re-submits single-winner.
            update_cursor = await db.execute(
                """
                UPDATE partner_applications
                SET status = 'pending', source = ?, requested_at = CURRENT_TIMESTAMP,
                    reviewed_at = NULL, reviewed_by_telegram_id = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ? AND status = 'rejected'
                """,
                (clean_source, user.id),
            )
            if update_cursor.rowcount == 1:
                created = True
            else:
                # Initial submission: only one concurrent request can insert.
                insert_cursor = await db.execute(
                    """
                    INSERT INTO partner_applications (
                        user_id, status, source, requested_at, reviewed_at,
                        reviewed_by_telegram_id, updated_at
                    )
                    VALUES (?, 'pending', ?, CURRENT_TIMESTAMP, NULL, NULL, CURRENT_TIMESTAMP)
                    ON CONFLICT(user_id) DO NOTHING
                    """,
                    (user.id, clean_source),
                )
                created = insert_cursor.rowcount == 1

            cursor = await db.execute(
                "SELECT id, status FROM partner_applications WHERE user_id = ? LIMIT 1",
                (user.id,),
            )
            row = await cursor.fetchone()
            if not row:
                await db.rollback()
                raise RuntimeError("Partner application row was not created")
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    status = str(row["status"] or PARTNER_APPLICATION_PENDING)
    return {
        "ok": True,
        "created": created,
        "status": status,
        "is_partner": status == PARTNER_APPLICATION_APPROVED,
        "application_id": int(row["id"]),
    }


async def review_partner_application(
    application_id: int,
    *,
    approve: bool,
    admin_telegram_id: int,
) -> dict[str, Any]:
    """Atomically approve/reject a pending application exactly once."""

    await ensure_partner_approval_schema()
    target_status = (
        PARTNER_APPLICATION_APPROVED if approve else PARTNER_APPLICATION_REJECTED
    )

    async with db_backend.connect(DATABASE_PATH, timeout=15) as db:
        db.row_factory = db_backend.Row
        await db.execute("BEGIN IMMEDIATE")
        try:
            cursor = await db.execute(
                """
                SELECT pa.id, pa.user_id, pa.status, pa.source, pa.requested_at,
                       pa.reviewed_at, pa.reviewed_by_telegram_id,
                       u.telegram_id, u.username, u.first_name, u.last_name,
                       u.referral_code
                FROM partner_applications pa
                JOIN users u ON u.id = pa.user_id
                WHERE pa.id = ?
                LIMIT 1
                """,
                (int(application_id),),
            )
            row = await cursor.fetchone()
            if not row:
                await db.rollback()
                return {"ok": False, "reason": "not_found"}

            current_status = str(row["status"] or "")
            if current_status != PARTNER_APPLICATION_PENDING:
                await db.rollback()
                payload = _application_payload(row) or {}
                return {
                    "ok": False,
                    "reason": "already_processed",
                    "status": current_status,
                    "application": payload,
                }

            update_cursor = await db.execute(
                """
                UPDATE partner_applications
                SET status = ?, reviewed_at = CURRENT_TIMESTAMP,
                    reviewed_by_telegram_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'pending'
                """,
                (target_status, int(admin_telegram_id), int(application_id)),
            )
            if update_cursor.rowcount != 1:
                await db.rollback()
                return {"ok": False, "reason": "race_lost"}

            if approve:
                await db.execute(
                    """
                    UPDATE users
                    SET partner_agreed_at = COALESCE(partner_agreed_at, CURRENT_TIMESTAMP),
                        partner_tier = 'basic',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (int(row["user_id"]),),
                )

            await db.commit()
        except Exception:
            await db.rollback()
            raise

    application = await get_partner_application(int(application_id))
    return {
        "ok": True,
        "status": target_status,
        "application": application,
    }


def _account_url(application: dict[str, Any]) -> str:
    username = str(application.get("username") or "").strip().lstrip("@")
    if username:
        return f"https://t.me/{username}"
    return f"tg://user?id={int(application['telegram_id'])}"


async def notify_admins_about_partner_application(
    bot: Bot | None,
    application_id: int,
) -> None:
    """Send the review card to every configured administrator."""

    if bot is None:
        logger.warning("Partner application %s created without bot instance", application_id)
        return

    application = await get_partner_application(application_id)
    if not application:
        return

    telegram_id = int(application["telegram_id"])
    username = str(application.get("username") or "").strip().lstrip("@")
    full_name = " ".join(
        value
        for value in (
            str(application.get("first_name") or "").strip(),
            str(application.get("last_name") or "").strip(),
        )
        if value
    )
    display_name = full_name or (f"@{username}" if username else "—")
    account_url = _account_url(application)

    text = (
        "🤝 <b>Новая заявка в партнёрскую программу</b>\n\n"
        f"Заявка: <code>#{application_id}</code>\n"
        f"Пользователь: <b>{html.escape(display_name)}</b>\n"
        f"Telegram ID: <code>{telegram_id}</code>\n"
        f"Username: <code>{html.escape('@' + username if username else '—')}</code>\n"
        f"Источник: <code>{html.escape(str(application.get('source') or '—'))}</code>\n"
        f"Аккаунт: <a href=\"{html.escape(account_url, quote=True)}\">открыть профиль</a>\n\n"
        "До решения администратора реферальная ссылка не активна."
    )
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(text="👤 Открыть аккаунт", url=account_url),
            ],
            [
                types.InlineKeyboardButton(
                    text="✅ Активировать кабинет",
                    callback_data=f"partner_app_approve_{application_id}",
                ),
                types.InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"partner_app_reject_{application_id}",
                ),
            ],
        ]
    )

    for admin_id in config.admin_ids:
        try:
            await bot.send_message(
                admin_id,
                text,
                parse_mode="HTML",
                reply_markup=keyboard,
                disable_web_page_preview=True,
            )
        except Exception:
            logger.exception(
                "Failed to send partner application %s to admin %s",
                application_id,
                admin_id,
            )


async def notify_user_about_partner_review(
    bot: Bot | None,
    application: dict[str, Any] | None,
    *,
    approved: bool,
) -> None:
    if bot is None or not application or not application.get("telegram_id"):
        return

    telegram_id = int(application["telegram_id"])
    if approved:
        text = (
            "✅ <b>Партнёрский кабинет активирован</b>\n\n"
            "Администратор одобрил заявку. Теперь вам доступны полноценный "
            "партнёрский кабинет, статистика и реферальная ссылка."
        )
    else:
        text = (
            "❌ <b>Заявка в партнёрскую программу отклонена</b>\n\n"
            "Партнёрская ссылка не активирована. При необходимости вы сможете "
            "подать заявку повторно из раздела «Партнёрам»."
        )

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="🤝 Открыть партнёрский раздел",
                    callback_data="menu_partner",
                )
            ]
        ]
    )
    try:
        await bot.send_message(
            telegram_id,
            text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    except Exception:
        logger.exception("Failed to notify user %s about partner review", telegram_id)


async def _query_referrer_approval(connection: Any, code: str) -> bool:
    connection.row_factory = db_backend.Row
    cursor = await connection.execute(
        """
        SELECT telegram_id, partner_agreed_at
        FROM users
        WHERE referral_code = ?
        LIMIT 1
        """,
        (code,),
    )
    row = await cursor.fetchone()
    if not row:
        return True  # let the canonical referral service report code_not_found
    telegram_id = int(row["telegram_id"])
    return bool(row["partner_agreed_at"]) or config.is_admin(telegram_id)


async def _referrer_is_approved_by_code(
    referral_code: str,
    *,
    db: Any | None = None,
) -> bool:
    code = str(referral_code or "").strip().upper()
    if not code:
        return False
    if db is not None:
        return await _query_referrer_approval(db, code)
    async with db_backend.connect(DATABASE_PATH) as connection:
        return await _query_referrer_approval(connection, code)


async def _blocked_referral_result(
    referral_service: Any,
    *,
    visitor_telegram_id: int,
    code: str,
    source: str | None,
    start_param: str | None,
    visitor_user_id: int | None = None,
    db: Any | None = None,
):
    result = referral_service.ReferralResult(
        clicked_code=code,
        referred_user_id=int(visitor_user_id or 0),
        reason="blocked_referrer",
        source=source,
        start_param=start_param,
    )
    await referral_service.record_referral_event(
        result,
        int(visitor_telegram_id),
        visitor_user_id,
        db=db,
    )
    return result


def install_partner_referral_approval_guard() -> None:
    """Require admin-approved partner status before a referral code can attach."""

    global _REFERRAL_GUARD_INSTALLED
    global _ORIGINAL_PROCESS_REFERRAL_CLICK
    global _ORIGINAL_ATTACH_REFERRAL_IN_TRANSACTION

    if _REFERRAL_GUARD_INSTALLED:
        return

    from bot.services import referral_service

    _ORIGINAL_PROCESS_REFERRAL_CLICK = referral_service.process_referral_click
    _ORIGINAL_ATTACH_REFERRAL_IN_TRANSACTION = referral_service.attach_referral_in_transaction

    async def guarded_process_referral_click(
        visitor_telegram_id: int,
        referral_code: str | None,
        *,
        source: str | None = None,
        start_param: str | None = None,
    ):
        code = str(referral_code or "").strip().upper()
        if code and not await _referrer_is_approved_by_code(code):
            return await _blocked_referral_result(
                referral_service,
                visitor_telegram_id=visitor_telegram_id,
                code=code,
                source=source,
                start_param=start_param,
            )
        return await _ORIGINAL_PROCESS_REFERRAL_CLICK(
            visitor_telegram_id,
            referral_code,
            source=source,
            start_param=start_param,
        )

    async def guarded_attach_referral_in_transaction(
        db: Any,
        visitor_telegram_id: int,
        visitor_user_id: int,
        referral_code: str | None,
        *,
        source: str | None = None,
        start_param: str | None = None,
    ):
        code = str(referral_code or "").strip().upper()
        if code and not await _referrer_is_approved_by_code(code, db=db):
            return await _blocked_referral_result(
                referral_service,
                visitor_telegram_id=visitor_telegram_id,
                visitor_user_id=visitor_user_id,
                code=code,
                source=source,
                start_param=start_param,
                db=db,
            )
        return await _ORIGINAL_ATTACH_REFERRAL_IN_TRANSACTION(
            db,
            visitor_telegram_id,
            visitor_user_id,
            referral_code,
            source=source,
            start_param=start_param,
        )

    referral_service.process_referral_click = guarded_process_referral_click
    referral_service.attach_referral_in_transaction = guarded_attach_referral_in_transaction
    _REFERRAL_GUARD_INSTALLED = True
