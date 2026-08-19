from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

from bot import db as db_backend
from bot.internal_admin_notification_schema import ensure_internal_admin_notification_schema
from bot.internal_admin_notifications import _decode_json_object, send_campaign_message

logger = logging.getLogger(__name__)

POLL_SECONDS = 1.0
LEASE_SECONDS = 90
MAX_ATTEMPTS = 5
BATCH_DELAY_SECONDS = 0.05
_WORKER_TASK: asyncio.Task[None] | None = None


async def _recover_expired_leases() -> int:
    async with db_backend.connect() as connection:
        cursor = await connection.execute(
            """
            UPDATE notification_deliveries d
            SET status = 'failed', lease_until = NULL,
                next_attempt_at = CURRENT_TIMESTAMP,
                last_error = COALESCE(last_error, 'delivery lease expired'),
                updated_at = CURRENT_TIMESTAMP
            FROM notification_campaigns c
            WHERE c.id = d.campaign_id
              AND c.status = 'running'
              AND d.status = 'sending'
              AND d.lease_until < CURRENT_TIMESTAMP
            """
        )
        await connection.commit()
        return int(cursor.rowcount or 0)


async def _claim_delivery() -> dict[str, Any] | None:
    lease_until = datetime.utcnow() + timedelta(seconds=LEASE_SECONDS)
    async with db_backend.connect() as connection:
        connection.row_factory = db_backend.Row
        cursor = await connection.execute(
            """
            SELECT
                d.id, d.campaign_id, d.telegram_id, d.attempts,
                c.message, c.status AS campaign_status
            FROM notification_deliveries d
            JOIN notification_campaigns c ON c.id = d.campaign_id
            WHERE c.status = 'running'
              AND d.status IN ('queued', 'failed')
              AND d.next_attempt_at <= CURRENT_TIMESTAMP
              AND d.attempts < ?
            ORDER BY d.id
            FOR UPDATE OF d SKIP LOCKED
            LIMIT 1
            """,
            (MAX_ATTEMPTS,),
        )
        row = await cursor.fetchone()
        if not row:
            await connection.rollback()
            return None
        await connection.execute(
            """
            UPDATE notification_deliveries
            SET status = 'sending', attempts = attempts + 1,
                lease_until = ?, last_error = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (lease_until, row["id"]),
        )
        await connection.commit()
    item = dict(row)
    item["attempts"] = int(item["attempts"] or 0) + 1
    return item


async def _mark_sent(delivery_id: int, message_id: int) -> None:
    async with db_backend.connect() as connection:
        await connection.execute(
            """
            UPDATE notification_deliveries
            SET status = 'sent', telegram_message_id = ?, sent_at = CURRENT_TIMESTAMP,
                lease_until = NULL, last_error = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (message_id, delivery_id),
        )
        await connection.commit()


async def _mark_blocked(delivery_id: int, error: Exception) -> None:
    async with db_backend.connect() as connection:
        await connection.execute(
            """
            UPDATE notification_deliveries
            SET status = 'blocked', lease_until = NULL, last_error = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (f"{type(error).__name__}: {str(error)[:500]}", delivery_id),
        )
        await connection.commit()


async def _mark_failed(delivery_id: int, attempts: int, error: Exception) -> None:
    terminal = attempts >= MAX_ATTEMPTS
    retry_after = getattr(error, "retry_after", None)
    if retry_after is not None:
        delay_seconds = max(1, int(retry_after))
    else:
        delay_seconds = min(15 * 60, 5 * (2 ** max(attempts - 1, 0)))
    next_attempt = datetime.utcnow() + timedelta(seconds=delay_seconds)
    async with db_backend.connect() as connection:
        await connection.execute(
            """
            UPDATE notification_deliveries
            SET status = ?, lease_until = NULL, next_attempt_at = ?,
                last_error = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                "failed",
                next_attempt,
                f"{type(error).__name__}: {str(error)[:500]}"
                + (" [dead-letter]" if terminal else ""),
                delivery_id,
            ),
        )
        await connection.commit()


async def _refresh_campaign(campaign_id: int) -> None:
    async with db_backend.connect() as connection:
        connection.row_factory = db_backend.Row
        cursor = await connection.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE status = 'queued') AS queued,
                COUNT(*) FILTER (WHERE status = 'sending') AS sending,
                COUNT(*) FILTER (WHERE status = 'sent') AS sent,
                COUNT(*) FILTER (
                    WHERE status = 'failed' AND attempts < ?
                ) AS retryable_failed,
                COUNT(*) FILTER (
                    WHERE status = 'failed' AND attempts >= ?
                ) AS terminal_failed,
                COUNT(*) FILTER (WHERE status = 'blocked') AS blocked,
                COUNT(*) FILTER (WHERE status = 'cancelled') AS cancelled
            FROM notification_deliveries
            WHERE campaign_id = ?
            """,
            (MAX_ATTEMPTS, MAX_ATTEMPTS, campaign_id),
        )
        row = await cursor.fetchone()
        if not row:
            return
        queued = int(row["queued"] or 0)
        sending = int(row["sending"] or 0)
        retryable_failed = int(row["retryable_failed"] or 0)
        terminal_failed = int(row["terminal_failed"] or 0)
        sent = int(row["sent"] or 0)
        blocked = int(row["blocked"] or 0)
        cancelled = int(row["cancelled"] or 0)
        pending = queued + sending + retryable_failed
        await connection.execute(
            """
            UPDATE notification_campaigns
            SET queued_count = ?, sent_count = ?, failed_count = ?,
                blocked_count = ?, cancelled_count = ?,
                status = CASE
                    WHEN status = 'cancelled' THEN status
                    WHEN ? = 0 THEN 'completed'
                    ELSE status
                END,
                completed_at = CASE
                    WHEN status <> 'cancelled' AND ? = 0
                    THEN COALESCE(completed_at, CURRENT_TIMESTAMP)
                    ELSE completed_at
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                queued + retryable_failed,
                sent,
                terminal_failed,
                blocked,
                cancelled,
                pending,
                pending,
                campaign_id,
            ),
        )
        await connection.commit()


async def notification_campaign_worker(bot: Bot) -> None:
    await ensure_internal_admin_notification_schema()
    recovered = await _recover_expired_leases()
    logger.info("Notification campaign worker started; recovered_leases=%s", recovered)

    while True:
        item: dict[str, Any] | None = None
        try:
            item = await _claim_delivery()
            if item is None:
                await _recover_expired_leases()
                await asyncio.sleep(POLL_SECONDS)
                continue

            campaign_id = int(item["campaign_id"])
            delivery_id = int(item["id"])
            try:
                sent = await send_campaign_message(
                    bot,
                    int(item["telegram_id"]),
                    _decode_json_object(item["message"]),
                )
                await _mark_sent(delivery_id, int(sent.message_id))
            except (TelegramForbiddenError, TelegramBadRequest) as exc:
                message = str(exc).lower()
                if any(
                    marker in message
                    for marker in (
                        "bot was blocked",
                        "chat not found",
                        "user is deactivated",
                        "forbidden",
                    )
                ):
                    await _mark_blocked(delivery_id, exc)
                else:
                    await _mark_failed(delivery_id, int(item["attempts"]), exc)
            except TelegramRetryAfter as exc:
                await _mark_failed(delivery_id, int(item["attempts"]), exc)
            except Exception as exc:
                logger.exception("Notification delivery failed")
                await _mark_failed(delivery_id, int(item["attempts"]), exc)

            await _refresh_campaign(campaign_id)
            await asyncio.sleep(BATCH_DELAY_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Notification worker iteration failed")
            if item is not None:
                try:
                    await _refresh_campaign(int(item["campaign_id"]))
                except Exception:
                    logger.exception("Failed to refresh notification campaign after worker error")
            await asyncio.sleep(POLL_SECONDS)


def ensure_notification_campaign_worker(bot: Bot) -> asyncio.Task[None]:
    global _WORKER_TASK
    if _WORKER_TASK is None or _WORKER_TASK.done():
        _WORKER_TASK = asyncio.create_task(
            notification_campaign_worker(bot),
            name="notification-campaign-worker",
        )
    return _WORKER_TASK
