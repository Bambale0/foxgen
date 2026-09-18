"""One merchant webhook; channel and owner come from local payment records."""

from __future__ import annotations

import logging
import time

from aiohttp import web
from bot import db as db_backend
from bot.database import complete_payment_atomic, update_transaction_status
from bot.services.yookassa_service import yookassa_service

logger = logging.getLogger(__name__)


async def handle_webhook(request):
    started = time.monotonic()
    try:
        data = await request.json()
        if not isinstance(data, dict):
            return web.Response(status=400)
        event = data.get("event")
        if event not in {
            "payment.succeeded",
            "payment.canceled",
            "payment.waiting_for_capture",
        }:
            return web.Response(status=200)
        obj = data.get("object")
        payment_id = str(obj.get("id") or "").strip() if isinstance(obj, dict) else ""
        if not payment_id or len(payment_id) > 128 or "/" in payment_id:
            return web.Response(status=400)
        channel = request.app.get("max_channel")
        async with db_backend.connect() as connection:
            connection.row_factory = db_backend.Row
            telegram_order = await (
                await connection.execute(
                    "SELECT order_id FROM transactions WHERE provider='yookassa' AND payment_id=?",
                    (payment_id,),
                )
            ).fetchone()
            max_order = None
            if channel is not None:
                max_order = await (
                    await connection.execute(
                        "SELECT order_id FROM max_payment_orders WHERE provider='yookassa' AND provider_payment_id=?",
                        (payment_id,),
                    )
                ).fetchone()
        if telegram_order and max_order:
            logger.error(
                "payment_webhook payment_id=%s outcome=ambiguous_owner", payment_id
            )
            return web.Response(status=409)
        if not telegram_order and not max_order and channel is not None:
            recovered = await channel.payments.bind_remote_order(payment_id)
            if recovered:
                max_order = {"order_id": recovered.order_id}
        if max_order:
            result = await channel.payments.complete_order(max_order["order_id"])
            retry = result.get("status") in {
                "lookup_error",
                "provider_pending",
                "pending",
            }
            logger.info(
                "payment_webhook channel=max order_id=%s outcome=%s duration_ms=%.1f",
                max_order["order_id"],
                result.get("status"),
                (time.monotonic() - started) * 1000,
            )
            return web.Response(status=503 if retry else 200)
        payment = await yookassa_service.get_payment(payment_id)
        if payment is None:
            return web.Response(status=503)
        if not telegram_order:
            order_id = yookassa_service.extract_order_id(payment.get("Raw"))
            if order_id:
                async with db_backend.connect() as connection:
                    connection.row_factory = db_backend.Row
                    telegram_order = await (
                        await connection.execute(
                            "SELECT order_id FROM transactions WHERE provider='yookassa' AND order_id=? "
                            "AND (payment_id='' OR payment_id IS NULL)",
                            (order_id,),
                        )
                    ).fetchone()
                    if telegram_order and payment.get("paid"):
                        await connection.execute(
                            "UPDATE transactions SET payment_id=? WHERE order_id=? "
                            "AND (payment_id='' OR payment_id IS NULL)",
                            (payment_id, order_id),
                        )
                        await connection.commit()
        if not telegram_order:
            logger.warning(
                "payment_webhook payment_id=%s outcome=unknown_order", payment_id
            )
            return web.Response(status=200)
        order_id = telegram_order["order_id"]
        if payment.get("paid"):
            result = await complete_payment_atomic(order_id)
            if not result.get("ok"):
                return web.Response(status=503)
        elif payment.get("failed"):
            await update_transaction_status(order_id, "failed")
        logger.info(
            "payment_webhook channel=telegram order_id=%s outcome=%s duration_ms=%.1f",
            order_id,
            payment.get("status"),
            (time.monotonic() - started) * 1000,
        )
        return web.Response(status=200)
    except (ValueError, UnicodeError):
        return web.Response(status=400)
    except Exception:
        logger.exception("payment_webhook outcome=temporary_failure")
        return web.Response(status=503)
