from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import aiohttp

from bot import database
from bot import db as db_backend
from bot.config import config
from bot.max_catalog import MaxPresetManager, max_preset_manager
from bot.max_store import _balance_connection, apply_max_balance_delta, ensure_max_schema, ensure_max_user

logger = logging.getLogger(__name__)

_SCHEMA_LOCK: asyncio.Lock | None = None
_SCHEMA_READY: set[str] = set()


@dataclass(frozen=True)
class MaxPaymentOrder:
    order_id: str
    max_user_id: int
    package_id: str
    credits: float
    amount_rub: float
    provider: str
    provider_payment_id: str | None
    checkout_url: str | None
    status: str
    promo_code: str = ""
    promo_bonus_credits: int = 0


def _schema_lock() -> asyncio.Lock:
    global _SCHEMA_LOCK
    if _SCHEMA_LOCK is None:
        _SCHEMA_LOCK = asyncio.Lock()
    return _SCHEMA_LOCK


def _schema_key() -> str:
    if db_backend.is_postgres():
        return f"postgres:{db_backend.DATABASE_URL}:max-payments"
    return f"sqlite:{database.DATABASE_PATH}:max-payments"


def _schema_statements() -> tuple[str, ...]:
    return (
        """
        CREATE TABLE IF NOT EXISTS max_payment_orders (
            order_id TEXT PRIMARY KEY,
            max_user_id BIGINT NOT NULL,
            package_id TEXT NOT NULL,
            credits REAL NOT NULL CHECK(credits > 0),
            amount_rub REAL NOT NULL CHECK(amount_rub > 0),
            provider TEXT NOT NULL,
            provider_payment_id TEXT,
            checkout_url TEXT,
            status TEXT NOT NULL DEFAULT 'created',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            FOREIGN KEY (max_user_id) REFERENCES max_users(max_user_id) ON DELETE CASCADE
        )
        """,
        (
            "CREATE INDEX IF NOT EXISTS idx_max_payment_orders_pending "
            "ON max_payment_orders(status, created_at)"
        ),
        """
        CREATE TABLE IF NOT EXISTS max_referrals (
            invited_max_user_id BIGINT PRIMARY KEY,
            referrer_max_user_id BIGINT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CHECK(invited_max_user_id <> referrer_max_user_id),
            FOREIGN KEY (invited_max_user_id) REFERENCES max_users(max_user_id) ON DELETE CASCADE,
            FOREIGN KEY (referrer_max_user_id) REFERENCES max_users(max_user_id) ON DELETE CASCADE
        )
        """,
        (
            "CREATE INDEX IF NOT EXISTS idx_max_referrals_referrer "
            "ON max_referrals(referrer_max_user_id, created_at)"
        ),
    )


async def _create_postgres_schema(db: db_backend.Connection) -> None:
    raw = getattr(db, "_conn", None)
    if raw is None:
        raise RuntimeError("PostgreSQL connection does not expose migration handle")
    async with raw.cursor() as cursor:
        for statement in _schema_statements():
            await cursor.execute(statement)
    await raw.commit()


async def ensure_max_payment_schema() -> None:
    await ensure_max_schema()
    key = _schema_key()
    if key in _SCHEMA_READY:
        return
    async with _schema_lock():
        if key in _SCHEMA_READY:
            return
        async with db_backend.connect() as db:
            if db_backend.is_postgres():
                await _create_postgres_schema(db)
            else:
                for statement in _schema_statements():
                    await db.execute(statement)
                await db.commit()
        _SCHEMA_READY.add(key)


def _mapping_rows(db: db_backend.Connection) -> None:
    db.row_factory = db_backend.Row


def _to_order(row: Any | None) -> MaxPaymentOrder | None:
    if row is None:
        return None
    return MaxPaymentOrder(
        order_id=str(row["order_id"]),
        max_user_id=int(row["max_user_id"]),
        package_id=str(row["package_id"]),
        credits=float(row["credits"]),
        amount_rub=float(row["amount_rub"]),
        provider=str(row["provider"]),
        provider_payment_id=(
            str(row["provider_payment_id"]) if row["provider_payment_id"] else None
        ),
        checkout_url=str(row["checkout_url"]) if row["checkout_url"] else None,
        status=str(row["status"]),
    )


def _partner_config(catalog: MaxPresetManager) -> dict[str, float]:
    from bot.business_rules import get_business_rules
    rules = get_business_rules()
    return {key: float(rules[key]) for key in (
        "level1_percent", "level2_percent", "new_user_bonus_credits",
        "inviter_bonus_credits", "rub_per_credit",
    )}


async def _get_referrer(max_user_id: int, *, connection=None) -> int | None:
    if connection is None:
        await ensure_max_payment_schema()
    async with _balance_connection(connection) as db:
        _mapping_rows(db)
        cursor = await db.execute(
            "SELECT referrer_max_user_id FROM max_referrals WHERE invited_max_user_id = ?",
            (int(max_user_id),),
        )
        row = await cursor.fetchone()
    return int(row["referrer_max_user_id"]) if row else None


async def register_max_referral(
    invited_max_user_id: int,
    referrer_max_user_id: int,
    *,
    catalog: MaxPresetManager = max_preset_manager,
) -> bool:
    """Persist one MAX-only referral edge; inviter gift is awarded after first purchase."""
    invited = int(invited_max_user_id)
    referrer = int(referrer_max_user_id)
    if invited <= 0 or referrer <= 0 or invited == referrer:
        return False

    await ensure_max_user(invited)
    await ensure_max_user(referrer)
    await ensure_max_payment_schema()

    # Reject cycles through the existing referral chain.
    cursor_id: int | None = referrer
    for _ in range(20):
        if cursor_id is None:
            break
        if cursor_id == invited:
            return False
        cursor_id = await _get_referrer(cursor_id)

    async with db_backend.connect() as db:
        cursor = await db.execute(
            """
            INSERT INTO max_referrals (invited_max_user_id, referrer_max_user_id)
            VALUES (?, ?)
            ON CONFLICT(invited_max_user_id) DO NOTHING
            """,
            (invited, referrer),
        )
        await db.commit()
        created = int(getattr(cursor, "rowcount", 0) or 0) == 1
    if not created:
        return False

    return True


async def get_max_referral_stats(max_user_id: int) -> dict[str, float | int]:
    await ensure_max_payment_schema()
    async with db_backend.connect() as db:
        _mapping_rows(db)
        count_cursor = await db.execute(
            "SELECT COUNT(*) AS count FROM max_referrals WHERE referrer_max_user_id = ?",
            (int(max_user_id),),
        )
        count_row = await count_cursor.fetchone()
        earned_cursor = await db.execute(
            """
            SELECT COALESCE(SUM(amount_credits), 0) AS earned
            FROM max_transactions
            WHERE max_user_id = ?
              AND type IN ('referral_signup_inviter', 'referral_first_purchase_inviter', 'referral_purchase_l1', 'referral_purchase_l2')
            """,
            (int(max_user_id),),
        )
        earned_row = await earned_cursor.fetchone()
    return {
        "referrals": int(count_row["count"] if count_row else 0),
        "earned_credits": float(earned_row["earned"] if earned_row else 0),
    }


async def _insert_payment_order(order: MaxPaymentOrder) -> None:
    await ensure_max_user(order.max_user_id)
    await ensure_max_payment_schema()
    async with db_backend.connect() as db:
        await db.execute(
            """
            INSERT INTO max_payment_orders (
                order_id, max_user_id, package_id, credits, amount_rub, provider,
                provider_payment_id, checkout_url, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order.order_id,
                order.max_user_id,
                order.package_id,
                order.credits,
                order.amount_rub,
                order.provider,
                order.provider_payment_id,
                order.checkout_url,
                order.status,
            ),
        )
        await db.commit()


async def get_max_payment_order(order_id: str) -> MaxPaymentOrder | None:
    await ensure_max_payment_schema()
    async with db_backend.connect() as db:
        _mapping_rows(db)
        cursor = await db.execute(
            "SELECT * FROM max_payment_orders WHERE order_id = ?",
            (str(order_id),),
        )
        return _to_order(await cursor.fetchone())


async def _set_payment_provider_data(
    order_id: str,
    *,
    payment_id: str,
    checkout_url: str,
) -> None:
    async with db_backend.connect() as db:
        await db.execute(
            """
            UPDATE max_payment_orders
            SET provider_payment_id = ?, checkout_url = ?, status = 'pending',
                updated_at = CURRENT_TIMESTAMP
            WHERE order_id = ? AND status = 'created'
            """,
            (payment_id, checkout_url, order_id),
        )
        await db.commit()


async def _set_payment_status(order_id: str, status: str) -> None:
    completed = ", completed_at = CURRENT_TIMESTAMP" if status == "completed" else ""
    async with db_backend.connect() as db:
        await db.execute(
            f"""
            UPDATE max_payment_orders
            SET status = ?, updated_at = CURRENT_TIMESTAMP{completed}
            WHERE order_id = ? AND status <> 'completed'
            """,
            (status, order_id),
        )
        await db.commit()


async def _pending_orders(limit: int = 50) -> list[MaxPaymentOrder]:
    await ensure_max_payment_schema()
    safe_limit = min(max(int(limit), 1), 200)
    async with db_backend.connect() as db:
        from bot.payment_checkout import CHECKOUT_DDL
        if not db_backend.is_postgres():
            await db.execute(CHECKOUT_DDL)
        _mapping_rows(db)
        cursor = await db.execute(
            """
            SELECT o.* FROM max_payment_orders o
            LEFT JOIN payment_checkout_intents p ON p.channel='max' AND p.order_id=o.order_id
            WHERE o.status IN ('created', 'pending')
            ORDER BY COALESCE(p.next_attempt_at,0), o.created_at ASC
            LIMIT ?
            """,
            (safe_limit,),
        )
        rows = await cursor.fetchall()
    return [order for row in rows if (order := _to_order(row)) is not None]


def _normalize_amount(value: Any) -> str:
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Invalid YooKassa payment amount") from exc
    if not amount.is_finite() or amount <= 0:
        raise ValueError("YooKassa payment amount must be positive")
    return format(amount, ".2f")


def _idempotence_key(order_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"happyfox:max:yookassa:{order_id}"))


class MaxYooKassaService:
    """MAX-owned YooKassa checkout/reconciliation on the isolated MAX ledger."""

    def __init__(
        self,
        *,
        return_url: str,
        shop_id: str | None = None,
        secret_key: str | None = None,
        api_base_url: str | None = None,
        timeout_seconds: int | None = None,
        catalog: MaxPresetManager = max_preset_manager,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self.return_url = str(return_url or "").strip()
        self.shop_id = str(shop_id if shop_id is not None else config.YOOKASSA_SHOP_ID).strip()
        self.secret_key = str(
            secret_key if secret_key is not None else config.YOOKASSA_SECRET_KEY
        ).strip()
        self.api_base_url = str(
            api_base_url if api_base_url is not None else config.YOOKASSA_API_BASE_URL
        ).rstrip("/")
        self.timeout_seconds = max(
            5,
            int(
                timeout_seconds
                if timeout_seconds is not None
                else config.YOOKASSA_REQUEST_TIMEOUT_SECONDS
            ),
        )
        self.catalog = catalog
        self.enabled = bool(
            self.shop_id
            and self.secret_key
            and self.return_url.startswith("https://")
        )
        self._session = session
        self._own_session = session is None

    async def close(self) -> None:
        if self._own_session and self._session is not None and not self._session.closed:
            await self._session.close()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                auth=aiohttp.BasicAuth(self.shop_id, self.secret_key),
                timeout=aiohttp.ClientTimeout(total=self.timeout_seconds),
                headers={"Accept": "application/json"},
            )
        return self._session

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        json_payload: dict[str, Any] | None = None,
        idempotence_key: str | None = None,
    ) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        headers = {"Content-Type": "application/json"}
        if idempotence_key:
            headers["Idempotence-Key"] = idempotence_key
        session = await self._get_session()
        try:
            async with session.request(
                method,
                f"{self.api_base_url}/{endpoint.lstrip('/')}",
                json=json_payload,
                headers=headers,
            ) as response:
                text = await response.text()
                if response.status < 200 or response.status >= 300:
                    logger.warning(
                        "MAX YooKassa request failed: method=%s endpoint=%s status=%s body=%s",
                        method,
                        endpoint,
                        response.status,
                        text[:500],
                    )
                    return None
                try:
                    payload = await response.json(content_type=None)
                except (ValueError, UnicodeError):
                    return None
                return payload if isinstance(payload, dict) else None
        except (aiohttp.ClientError, asyncio.TimeoutError):
            logger.exception("MAX YooKassa request error: endpoint=%s", endpoint)
            return None

    def _package(self, package_id: str) -> dict[str, Any]:
        for package in self.catalog.get_packages():
            if str(package.get("id")) == str(package_id):
                return dict(package)
        raise ValueError(f"Unknown MAX payment package: {package_id}")

    async def create_checkout(self, max_user_id: int, package_id: str, *, promo_code: str | None = None) -> MaxPaymentOrder:
        if not self.enabled:
            raise RuntimeError("MAX YooKassa is not configured")
        package = self._package(package_id)
        from bot.database import get_promo_code_by_code, get_promo_bonus_for_credits
        promo = await get_promo_code_by_code(promo_code, active_only=True) if promo_code else None
        if promo_code and promo is None:
            raise ValueError("Промокод не найден или выключен")
        promo_bonus = get_promo_bonus_for_credits(package["credits"]) if promo else 0
        credits = float(package["credits"]) + float(package.get("bonus_credits") or 0) + promo_bonus
        amount_rub = float(package["price_rub"])
        order_id = f"max_{uuid.uuid4().hex}"
        order = MaxPaymentOrder(
            order_id=order_id,
            max_user_id=int(max_user_id),
            package_id=str(package_id),
            credits=credits,
            amount_rub=amount_rub,
            provider="yookassa",
            provider_payment_id=None,
            checkout_url=None,
            status="created",
        )
        await _insert_payment_order(order)

        from bot.payment_checkout import save_checkout_intent
        payload = {
                "amount": {"value": _normalize_amount(amount_rub), "currency": "RUB"},
                "capture": True,
                "confirmation": {"type": "redirect", "return_url": self.return_url},
                "description": f"HappyFox MAX · {package.get('name') or package_id}"[:128],
                "metadata": {
                    "order_id": order_id,
                    "product": "happyfox-max",
                    "channel": "max",
                    "max_user_id": str(max_user_id),
                    **({"promo_code_id": str(promo.id), "promo_code": promo.code,
                        "promo_bonus_credits": str(promo_bonus)} if promo and promo_bonus else {}),
                },
            }
        await save_checkout_intent("max", order_id, payload)
        payment = await self._request(
            "POST", "payments", json_payload=payload,
            idempotence_key=_idempotence_key(order_id),
        )
        payment_id = str((payment or {}).get("id") or "").strip()
        confirmation = (payment or {}).get("confirmation") or {}
        checkout_url = str(
            confirmation.get("confirmation_url") or confirmation.get("url") or ""
        ).strip()
        if not payment_id or not checkout_url.startswith("https://"):
            raise RuntimeError("ЮKassa пока не ответила. Заказ сохранён, проверка продолжится автоматически.")

        await _set_payment_provider_data(
            order_id,
            payment_id=payment_id,
            checkout_url=checkout_url,
        )
        persisted = await get_max_payment_order(order_id)
        if persisted is None:
            raise RuntimeError("MAX payment order disappeared after checkout creation")
        from dataclasses import replace
        return replace(persisted, promo_code=promo.code if promo else "", promo_bonus_credits=promo_bonus)

    async def get_remote_payment(self, payment_id: str) -> dict[str, Any] | None:
        payment = await self._request("GET", f"payments/{str(payment_id).strip()}")
        if payment and str(payment.get("id") or "") == str(payment_id).strip():
            return payment
        return None

    @staticmethod
    def _verification_state(
        order: MaxPaymentOrder,
        payment: dict[str, Any],
    ) -> tuple[str, str | None]:
        status = str(payment.get("status") or "").strip().lower()
        if status in {"canceled", "cancelled", "failed", "rejected"}:
            return "failed", None
        paid = status == "succeeded" and payment.get("paid") is True
        if not paid:
            return "pending", None

        if str(payment.get("id") or "") != str(order.provider_payment_id or ""):
            return "invalid", "payment_id_mismatch"
        amount = payment.get("amount") or {}
        if str(amount.get("currency") or "").upper() != "RUB":
            return "invalid", "currency_mismatch"
        try:
            if _normalize_amount(amount.get("value")) != _normalize_amount(order.amount_rub):
                return "invalid", "amount_mismatch"
        except ValueError:
            return "invalid", "amount_invalid"
        metadata = payment.get("metadata") or {}
        if not isinstance(metadata, dict):
            return "invalid", "metadata_missing"
        if str(metadata.get("order_id") or "") != order.order_id:
            return "invalid", "order_id_mismatch"
        if str(metadata.get("product") or "") != "happyfox-max":
            return "invalid", "product_mismatch"
        if str(metadata.get("channel") or "") != "max":
            return "invalid", "channel_mismatch"
        if str(metadata.get("max_user_id") or "") != str(order.max_user_id):
            return "invalid", "max_user_mismatch"
        return "paid", None

    async def _award_purchase_referrals(self, order: MaxPaymentOrder, *, connection=None) -> None:
        from bot.payment_delivery import enqueue_payment_notification
        from bot.business_rules import referrer_message
        partner = _partner_config(self.catalog)
        rub_per_credit = partner["rub_per_credit"]
        if rub_per_credit <= 0:
            return
        level1 = await _get_referrer(order.max_user_id, connection=connection)
        if level1 is None:
            return

        inviter_bonus = float(partner.get("inviter_bonus_credits") or 0)
        new_gift_key = f"maxref:{order.max_user_id}:first-purchase-inviter:{level1}"
        legacy_gift_key = f"maxref:{order.max_user_id}:inviter:{level1}"
        if inviter_bonus > 0:
            prior_gift_cursor = await connection.execute(
                """
                SELECT 1
                FROM max_transactions
                WHERE idempotency_key IN (?, ?)
                LIMIT 1
                """,
                (new_gift_key, legacy_gift_key),
            )
            prior_order_cursor = await connection.execute(
                """
                SELECT 1
                FROM max_payment_orders
                WHERE max_user_id = ?
                  AND status = 'completed'
                  AND order_id <> ?
                LIMIT 1
                """,
                (int(order.max_user_id), order.order_id),
            )
            if await prior_gift_cursor.fetchone() is None and await prior_order_cursor.fetchone() is None:
                await apply_max_balance_delta(
                    level1,
                    inviter_bonus,
                    tx_type="referral_first_purchase_inviter",
                    idempotency_key=new_gift_key,
                    amount_rub=order.amount_rub,
                    payment_provider="yookassa",
                    connection=connection,
                    provider_order_id=order.provider_payment_id,
                    metadata={
                        "buyer_max_user_id": order.max_user_id,
                        "order_id": order.order_id,
                    },
                )
                await enqueue_payment_notification(
                    connection, channel="max", order_id=f"{order.order_id}:referrer:gift",
                    recipient_id=level1,
                    message=(
                        "🎁 <b>Подарок за реферала</b>\n\n"
                        f"Ваш реферал сделал первую покупку. Начислено: "
                        f"<code>{inviter_bonus:g}</code>🐾"
                    ),
                )

        level1_credits = round(
            order.amount_rub * partner["level1_percent"] / 100.0 / rub_per_credit,
            4,
        )
        if level1_credits > 0:
            await apply_max_balance_delta(
                level1,
                level1_credits,
                tx_type="referral_purchase_l1",
                idempotency_key=f"maxrefpay:{order.order_id}:l1:{level1}",
                amount_rub=order.amount_rub,
                payment_provider="yookassa",
                connection=connection,
                provider_order_id=order.provider_payment_id,
                metadata={
                    "buyer_max_user_id": order.max_user_id,
                    "order_id": order.order_id,
                },
            )

            await enqueue_payment_notification(
                connection, channel="max", order_id=f"{order.order_id}:referrer:1",
                recipient_id=level1, message=referrer_message(1, level1_credits, "🐾"),
            )

        level2 = await _get_referrer(level1, connection=connection)
        if level2 is None:
            return
        level2_credits = round(
            order.amount_rub * partner["level2_percent"] / 100.0 / rub_per_credit,
            4,
        )
        if level2_credits > 0:
            await apply_max_balance_delta(
                level2,
                level2_credits,
                tx_type="referral_purchase_l2",
                idempotency_key=f"maxrefpay:{order.order_id}:l2:{level2}",
                amount_rub=order.amount_rub,
                payment_provider="yookassa",
                connection=connection,
                provider_order_id=order.provider_payment_id,
                metadata={
                    "buyer_max_user_id": order.max_user_id,
                    "order_id": order.order_id,
                },
            )
            await enqueue_payment_notification(
                connection, channel="max", order_id=f"{order.order_id}:referrer:2",
                recipient_id=level2, message=referrer_message(2, level2_credits, "🐾"),
            )

    async def bind_remote_order(self, payment_id):
        """Recover a lost creation response using provider-confirmed metadata."""
        from dataclasses import replace
        payment = await self.get_remote_payment(payment_id)
        if not payment:
            return None
        metadata = payment.get("metadata") or {}
        if not isinstance(metadata, dict) or metadata.get("channel") != "max":
            return None
        order = await get_max_payment_order(str(metadata.get("order_id") or ""))
        if not order or order.provider_payment_id:
            return order if order and order.provider_payment_id == payment_id else None
        candidate = replace(order, provider_payment_id=payment_id)
        state, reason = self._verification_state(candidate, payment)
        if state != "paid":
            return None
        async with db_backend.connect() as connection:
            await connection.execute(
                "UPDATE max_payment_orders SET provider_payment_id=?, status='pending' "
                "WHERE order_id=? AND status='created' "
                "AND (provider_payment_id IS NULL OR provider_payment_id='')",
                (payment_id, order.order_id),
            )
            await connection.commit()
        fresh = await get_max_payment_order(order.order_id)
        return fresh if fresh and fresh.provider_payment_id == payment_id else None

    async def complete_order(self, order_id: str) -> dict[str, Any]:
        order = await get_max_payment_order(order_id)
        if order is None:
            return {"ok": False, "status": "not_found"}
        if order.status == "completed":
            return {
                "ok": True,
                "status": "completed",
                "already_completed": True,
                "order": order,
            }
        if order.status == "failed":
            return {"ok": False, "status": "failed", "order": order}
        if not order.provider_payment_id:
            from bot.payment_checkout import get_checkout_intent
            payload = await get_checkout_intent("max", order.order_id)
            if payload:
                recovered = await self._request(
                    "POST", "payments", json_payload=payload,
                    idempotence_key=_idempotence_key(order.order_id),
                )
                payment_id = str((recovered or {}).get("id") or "")
                checkout_url = str(((recovered or {}).get("confirmation") or {}).get("confirmation_url") or "")
                if payment_id and checkout_url.startswith("https://"):
                    await _set_payment_provider_data(order.order_id, payment_id=payment_id, checkout_url=checkout_url)
                    order = await get_max_payment_order(order.order_id) or order
            if not order.provider_payment_id:
                return {"ok": False, "status": "provider_pending", "order": order}

        payment = await self.get_remote_payment(order.provider_payment_id)
        if not payment:
            return {"ok": False, "status": "lookup_error", "order": order}
        state, reason = self._verification_state(order, payment)
        if state == "failed":
            await _set_payment_status(order.order_id, "failed")
            return {"ok": False, "status": "failed", "order": order}
        if state == "pending":
            return {"ok": False, "status": "pending", "order": order}
        if state != "paid":
            logger.error(
                "Refusing invalid MAX YooKassa success: order=%s reason=%s",
                order.order_id,
                reason,
            )
            return {
                "ok": False,
                "status": "verification_failed",
                "reason": reason,
                "order": order,
            }

        from bot.payment_delivery import (
            enqueue_payment_notification, ensure_sqlite_outbox,
        )
        from bot.business_rules import buyer_message
        async with db_backend.connect() as connection:
            connection.row_factory = db_backend.Row
            await ensure_sqlite_outbox(connection)
            await connection.execute("BEGIN IMMEDIATE")
            fresh = await (await connection.execute(
                "SELECT * FROM max_payment_orders WHERE order_id=?"
                + (" FOR UPDATE" if db_backend.is_postgres() else ""),
                (order.order_id,),
            )).fetchone()
            current = _to_order(fresh)
            if current is None or current.status == "failed":
                await connection.rollback()
                return {"ok": False, "status": "failed"}
            if current.status == "completed":
                await connection.rollback()
                return {"ok": True, "status": "completed", "already_completed": True, "order": current}
            balance = await apply_max_balance_delta(
                order.max_user_id, order.credits, tx_type="topup",
                idempotency_key=f"maxpay:{order.order_id}:credit",
                amount_rub=order.amount_rub, payment_provider="yookassa",
                provider_order_id=order.provider_payment_id,
                metadata={"order_id": order.order_id, "package_id": order.package_id},
                connection=connection,
            )
            await self._award_purchase_referrals(order, connection=connection)
            from bot.payment_checkout import redeem_max_checkout_promo
            await redeem_max_checkout_promo(connection, order)
            await connection.execute(
                "UPDATE max_payment_orders SET status='completed', "
                "completed_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE order_id=?",
                (order.order_id,),
            )
            await enqueue_payment_notification(
                connection, channel="max", order_id=order.order_id,
                recipient_id=order.max_user_id,
                message=buyer_message(order.credits, order.amount_rub),
            )
            await connection.commit()
        completed = await get_max_payment_order(order.order_id) or order
        return {"ok": True, "status": "completed", "already_completed": False,
                "balance": balance, "order": completed}

    async def reconcile_pending(self, limit: int = 50) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for order in await _pending_orders(limit):
            from bot.payment_checkout import record_reconciliation_attempt
            await record_reconciliation_attempt("max", order.order_id)
            try:
                result = await self.complete_order(order.order_id)
            except Exception:
                logger.exception("MAX payment reconciliation order failed: order_id=%s", order.order_id)
                continue
            if result.get("status") == "completed" and not result.get(
                "already_completed"
            ):
                results.append(result)
        return results
