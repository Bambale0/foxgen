"""Durable buyer notifications, committed together with payment credits."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress

from aiohttp import web

from bot import db as db_backend

logger = logging.getLogger(__name__)

OUTBOX_DDL = """
CREATE TABLE IF NOT EXISTS payment_notification_outbox (
    channel TEXT NOT NULL,
    order_id TEXT NOT NULL,
    recipient_id BIGINT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at DOUBLE PRECISION NOT NULL DEFAULT 0,
    last_error TEXT,
    PRIMARY KEY(channel, order_id)
)
"""


async def enqueue_payment_notification(
    connection, *, channel, order_id, recipient_id, message
):
    await connection.execute(
        "INSERT INTO payment_notification_outbox "
        "(channel, order_id, recipient_id, message) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(channel, order_id) DO NOTHING",
        (channel, order_id, int(recipient_id), message),
    )


async def ensure_sqlite_outbox(connection):
    # Production DDL belongs exclusively to the ordered migration registry.
    if not db_backend.is_postgres():
        await connection.execute(OUTBOX_DDL)


async def deliver_payment_notifications(app, *, limit=50):
    channels = [
        name
        for name, client in (
            ("telegram", app.get("bot")),
            ("max", app.get("max_client")),
        )
        if client is not None
    ]
    if not channels:
        return
    now = time.time()
    from bot.business_rules import get_business_rules

    rules = get_business_rules()
    lease_seconds = 120  # immutable claim lease; delivery deadline is shorter
    max_attempts = int(rules["notification_max_attempts"])
    async with db_backend.connect() as connection:
        await ensure_sqlite_outbox(connection)
        connection.row_factory = db_backend.Row
        rows = await (
            await connection.execute(
                "SELECT * FROM payment_notification_outbox "
                "WHERE channel IN (" + ",".join("?" for _ in channels) + ") "
                "AND status IN ('pending', 'sending') AND next_attempt_at <= ? "
                "ORDER BY next_attempt_at, order_id LIMIT ?",
                (*channels, now, int(limit)),
            )
        ).fetchall()
        await connection.commit()
    for row in rows:
        channel = row["channel"]
        client = app.get("bot" if channel == "telegram" else "max_client")
        if client is None:
            continue
        async with db_backend.connect() as connection:
            claimed = await connection.execute(
                "UPDATE payment_notification_outbox SET status='sending', "
                "attempts=attempts+1, next_attempt_at=? "
                "WHERE channel=? AND order_id=? "
                "AND status IN ('pending', 'sending') AND next_attempt_at <= ?",
                (now + lease_seconds, channel, row["order_id"], now),
            )
            await connection.commit()
            if claimed.rowcount != 1:
                continue
        status, error = "delivered", None
        try:
            kwargs = {"parse_mode": "HTML"} if channel == "telegram" else {}
            await asyncio.wait_for(
                client.send_message(int(row["recipient_id"]), row["message"], **kwargs),
                timeout=60,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = type(exc).__name__
            status = "failed" if int(row["attempts"]) + 1 >= max_attempts else "pending"
        delay = min(
            rules["notification_retry_max_seconds"],
            rules["notification_retry_base_seconds"]
            * 2 ** min(int(row["attempts"]), 20),
        )
        async with db_backend.connect() as connection:
            await connection.execute(
                "UPDATE payment_notification_outbox SET status=?, last_error=?, next_attempt_at=? "
                "WHERE channel=? AND order_id=? AND status='sending' AND next_attempt_at=?",
                (
                    status,
                    error,
                    time.time() + delay,
                    channel,
                    row["order_id"],
                    now + lease_seconds,
                ),
            )
            await connection.commit()
        logger.info(
            "payment_delivery channel=%s order_id=%s outcome=%s error_type=%s",
            channel,
            row["order_id"],
            status,
            error or "-",
        )


def setup_payment_delivery(app: web.Application):
    async def context(runtime):
        async with db_backend.connect() as connection:
            await ensure_sqlite_outbox(connection)
            await connection.commit()

        async def worker():
            while True:
                try:
                    await deliver_payment_notifications(runtime)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("payment_delivery worker tick failed")
                from bot.business_rules import get_business_rules

                await asyncio.sleep(get_business_rules()["notification_poll_seconds"])

        from bot.payment_readiness import register_payment_worker

        task = register_payment_worker("delivery", asyncio.create_task(worker()))
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app.cleanup_ctx.append(context)
