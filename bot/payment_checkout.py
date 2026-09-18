"""Persist payment ownership before requesting an external checkout."""

from __future__ import annotations

import json
import time
import logging
from bot import db as db_backend
from bot.database import create_transaction
from bot.services.yookassa_service import yookassa_service

CHECKOUT_DDL = """
CREATE TABLE IF NOT EXISTS payment_checkout_intents (
    channel TEXT NOT NULL,
    order_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL,
    next_attempt_at DOUBLE PRECISION NOT NULL DEFAULT 0,
    PRIMARY KEY(channel, order_id)
)
"""


async def save_checkout_intent(channel, order_id, payload):
    async with db_backend.connect() as connection:
        if not db_backend.is_postgres():
            await connection.execute(CHECKOUT_DDL)
        await connection.execute(
            "INSERT INTO payment_checkout_intents(channel,order_id,payload_json,created_at) VALUES (?,?,?,?) "
            "ON CONFLICT(channel,order_id) DO UPDATE SET payload_json=excluded.payload_json, "
            "created_at=excluded.created_at WHERE payment_checkout_intents.payload_json='{}'",
            (channel, order_id, json.dumps(payload), time.time()),
        )
        await connection.commit()


async def get_checkout_intent(channel, order_id, *, for_recovery=True):
    async with db_backend.connect() as connection:
        if not db_backend.is_postgres():
            await connection.execute(CHECKOUT_DDL)
        connection.row_factory = db_backend.Row
        row = await (
            await connection.execute(
                "SELECT payload_json,created_at FROM payment_checkout_intents WHERE channel=? AND order_id=?",
                (channel, order_id),
            )
        ).fetchone()
        if not row:
            return None
        # YooKassa guarantees repeated creation keys for only 24 hours.
        # Leave an hour of safety; older ambiguity requires provider lookup,
        # never another POST that could create a second payment.
        if for_recovery and time.time() - float(row["created_at"]) >= 23 * 3600:
            logging.getLogger(__name__).error(
                "payment_checkout channel=%s order_id=%s outcome=manual_reconciliation_required",
                channel,
                order_id,
            )
            return None
        return json.loads(row["payload_json"])


async def recover_telegram_checkout(order_id):
    payload = await get_checkout_intent("telegram", order_id)
    if not payload:
        return None
    result = await yookassa_service.create_payment(**payload)
    if result and result.get("Success"):
        async with db_backend.connect() as connection:
            await connection.execute(
                "UPDATE transactions SET payment_id=? WHERE order_id=? "
                "AND (payment_id='' OR payment_id IS NULL)",
                (result["PaymentId"], order_id),
            )
            connection.row_factory = db_backend.Row
            row = await (
                await connection.execute(
                    "SELECT payment_id FROM transactions WHERE order_id=?",
                    (order_id,),
                )
            ).fetchone()
            if row is None or row["payment_id"] != result["PaymentId"]:
                raise RuntimeError("Checkout payment identity was not saved")
            await connection.commit()
    return result


async def create_telegram_checkout(
    *,
    user_id,
    credits,
    promo_code_id=None,
    promo_code=None,
    promo_bonus_credits=0,
    **payload,
):
    order_id = payload["order_id"]
    created = await create_transaction(
        order_id=order_id,
        user_id=user_id,
        credits=credits,
        amount_rub=payload["amount_rub"],
        provider="yookassa",
        payment_id="",
        promo_code_id=promo_code_id,
        promo_code=promo_code,
        promo_bonus_credits=promo_bonus_credits,
    )
    if not created:
        raise RuntimeError("Не удалось сохранить заказ. Попробуйте снова.")
    await save_checkout_intent("telegram", order_id, payload)
    return await recover_telegram_checkout(order_id)


async def record_reconciliation_attempt(channel, order_id):
    async with db_backend.connect() as connection:
        if not db_backend.is_postgres():
            await connection.execute(CHECKOUT_DDL)
        await connection.execute(
            "INSERT INTO payment_checkout_intents(channel,order_id,payload_json,created_at,next_attempt_at) "
            "VALUES (?,?,'{}',0,?) ON CONFLICT(channel,order_id) "
            "DO UPDATE SET next_attempt_at=excluded.next_attempt_at",
            (channel, order_id, time.time()),
        )
        await connection.commit()


PROMO_DDL = """
CREATE TABLE IF NOT EXISTS payment_promo_redemptions (
    channel TEXT NOT NULL,
    order_id TEXT NOT NULL,
    promo_code_id BIGINT NOT NULL,
    bonus_credits INTEGER NOT NULL,
    PRIMARY KEY(channel,order_id)
)
"""


async def redeem_max_checkout_promo(connection, order):
    if not db_backend.is_postgres():
        await connection.execute(PROMO_DDL)
    connection.row_factory = db_backend.Row
    row = await (
        await connection.execute(
            "SELECT payload_json FROM payment_checkout_intents WHERE channel='max' AND order_id=?",
            (order.order_id,),
        )
    ).fetchone()
    metadata = json.loads(row["payload_json"]).get("metadata", {}) if row else {}
    promo_id = int(metadata.get("promo_code_id") or 0)
    bonus = int(metadata.get("promo_bonus_credits") or 0)
    if not promo_id or bonus <= 0:
        return
    inserted = await connection.execute(
        "INSERT INTO payment_promo_redemptions(channel,order_id,promo_code_id,bonus_credits) "
        "VALUES ('max',?,?,?) ON CONFLICT(channel,order_id) DO NOTHING",
        (order.order_id, promo_id, bonus),
    )
    if inserted.rowcount == 1:
        await connection.execute(
            "UPDATE promo_codes SET usage_count=usage_count+1, total_bonus_credits=total_bonus_credits+?, "
            "total_amount_rub=total_amount_rub+?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (bonus, order.amount_rub, promo_id),
        )
