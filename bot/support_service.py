from __future__ import annotations

import asyncio
import html
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from aiogram import Bot

from bot import db as db_backend
from bot.internal_admin_support_schema import ensure_internal_admin_support_schema

logger = logging.getLogger(__name__)

OUTBOX_POLL_SECONDS = 2.0
OUTBOX_MAX_ATTEMPTS = 5
_WORKER_TASK: asyncio.Task[None] | None = None


@dataclass(slots=True)
class SupportAttachment:
    kind: str
    telegram_file_id: str
    file_name: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None


async def _ensure_user(
    *,
    telegram_id: int,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
) -> int:
    async with db_backend.connect() as connection:
        connection.row_factory = db_backend.Row
        cursor = await connection.execute(
            """
            INSERT INTO users (telegram_id, username, first_name, last_name, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (telegram_id) DO UPDATE SET
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id
            """,
            (telegram_id, username, first_name, last_name),
        )
        row = await cursor.fetchone()
        await connection.commit()
    if not row:
        raise RuntimeError("support user was not created")
    return int(row["id"])


async def create_support_ticket(
    *,
    telegram_id: int,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
    subject: str,
    body: str,
    telegram_message_id: int | None,
    attachments: list[SupportAttachment] | None = None,
) -> int:
    await ensure_internal_admin_support_schema()
    user_id = await _ensure_user(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
    )
    normalized_subject = " ".join(subject.split()).strip()[:160] or "Обращение пользователя"
    normalized_body = body.strip()[:8000]

    async with db_backend.connect() as connection:
        connection.row_factory = db_backend.Row
        ticket_cursor = await connection.execute(
            """
            INSERT INTO support_tickets (
                user_id, subject, status, priority, source, last_user_message_at
            ) VALUES (?, ?, 'new', 'normal', 'telegram', CURRENT_TIMESTAMP)
            RETURNING id
            """,
            (user_id, normalized_subject),
        )
        ticket_row = await ticket_cursor.fetchone()
        if not ticket_row:
            raise RuntimeError("support ticket was not created")
        ticket_id = int(ticket_row["id"])

        message_cursor = await connection.execute(
            """
            INSERT INTO support_messages (
                ticket_id, sender_type, sender_id, body,
                telegram_message_id, delivery_status
            ) VALUES (?, 'user', ?, ?, ?, 'stored')
            RETURNING id
            """,
            (ticket_id, str(telegram_id), normalized_body, telegram_message_id),
        )
        message_row = await message_cursor.fetchone()
        if not message_row:
            raise RuntimeError("support message was not created")
        message_id = int(message_row["id"])

        for attachment in attachments or []:
            await connection.execute(
                """
                INSERT INTO support_attachments (
                    message_id, kind, telegram_file_id, file_name, mime_type, size_bytes
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    attachment.kind,
                    attachment.telegram_file_id,
                    attachment.file_name,
                    attachment.mime_type,
                    attachment.size_bytes,
                ),
            )
        await connection.commit()
    return ticket_id


async def append_user_message(
    *,
    ticket_id: int,
    telegram_id: int,
    body: str,
    telegram_message_id: int | None,
    attachments: list[SupportAttachment] | None = None,
) -> int:
    await ensure_internal_admin_support_schema()
    async with db_backend.connect() as connection:
        connection.row_factory = db_backend.Row
        cursor = await connection.execute(
            """
            SELECT st.id
            FROM support_tickets st
            JOIN users u ON u.id = st.user_id
            WHERE st.id = ? AND u.telegram_id = ? AND st.status <> 'closed'
            FOR UPDATE OF st
            """,
            (ticket_id, telegram_id),
        )
        if not await cursor.fetchone():
            raise LookupError("support ticket not found")

        message_cursor = await connection.execute(
            """
            INSERT INTO support_messages (
                ticket_id, sender_type, sender_id, body,
                telegram_message_id, delivery_status
            ) VALUES (?, 'user', ?, ?, ?, 'stored')
            RETURNING id
            """,
            (ticket_id, str(telegram_id), body.strip()[:8000], telegram_message_id),
        )
        message_row = await message_cursor.fetchone()
        if not message_row:
            raise RuntimeError("support message was not created")
        message_id = int(message_row["id"])
        for attachment in attachments or []:
            await connection.execute(
                """
                INSERT INTO support_attachments (
                    message_id, kind, telegram_file_id, file_name, mime_type, size_bytes
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    attachment.kind,
                    attachment.telegram_file_id,
                    attachment.file_name,
                    attachment.mime_type,
                    attachment.size_bytes,
                ),
            )
        await connection.commit()
    return message_id


async def latest_open_ticket_id(telegram_id: int) -> int | None:
    await ensure_internal_admin_support_schema()
    async with db_backend.connect() as connection:
        connection.row_factory = db_backend.Row
        cursor = await connection.execute(
            """
            SELECT st.id
            FROM support_tickets st
            JOIN users u ON u.id = st.user_id
            WHERE u.telegram_id = ? AND st.status <> 'closed'
            ORDER BY st.updated_at DESC, st.id DESC
            LIMIT 1
            """,
            (telegram_id,),
        )
        row = await cursor.fetchone()
    return int(row["id"]) if row else None


async def _claim_outbox_item() -> dict[str, Any] | None:
    async with db_backend.connect() as connection:
        connection.row_factory = db_backend.Row
        cursor = await connection.execute(
            """
            SELECT
                o.id, o.ticket_id, o.message_id, o.telegram_id,
                o.attempts, m.body
            FROM support_outbox o
            JOIN support_messages m ON m.id = o.message_id
            WHERE o.status IN ('queued', 'failed')
              AND o.next_attempt_at <= CURRENT_TIMESTAMP
              AND o.attempts < ?
            ORDER BY o.id
            FOR UPDATE OF o SKIP LOCKED
            LIMIT 1
            """,
            (OUTBOX_MAX_ATTEMPTS,),
        )
        row = await cursor.fetchone()
        if not row:
            await connection.rollback()
            return None
        await connection.execute(
            """
            UPDATE support_outbox
            SET status = 'sending', attempts = attempts + 1, last_error = NULL
            WHERE id = ?
            """,
            (row["id"],),
        )
        await connection.commit()
    return dict(row)


async def _mark_outbox_sent(
    outbox_id: int,
    message_id: int,
    telegram_message_id: int,
) -> None:
    async with db_backend.connect() as connection:
        await connection.execute(
            """
            UPDATE support_outbox
            SET status = 'sent', sent_at = CURRENT_TIMESTAMP,
                telegram_message_id = ?, last_error = NULL
            WHERE id = ?
            """,
            (telegram_message_id, outbox_id),
        )
        await connection.execute(
            """
            UPDATE support_messages
            SET delivery_status = 'sent', telegram_message_id = ?
            WHERE id = ?
            """,
            (telegram_message_id, message_id),
        )
        await connection.commit()


async def _mark_outbox_failed(
    outbox_id: int,
    message_id: int,
    attempts: int,
    error: Exception,
) -> None:
    terminal = attempts + 1 >= OUTBOX_MAX_ATTEMPTS
    delay_seconds = min(300, 2 ** max(attempts, 0) * 5)
    next_attempt = datetime.utcnow() + timedelta(seconds=delay_seconds)
    async with db_backend.connect() as connection:
        await connection.execute(
            """
            UPDATE support_outbox
            SET status = ?, next_attempt_at = ?, last_error = ?
            WHERE id = ?
            """,
            (
                "cancelled" if terminal else "failed",
                next_attempt,
                f"{type(error).__name__}: {str(error)[:500]}",
                outbox_id,
            ),
        )
        await connection.execute(
            "UPDATE support_messages SET delivery_status = 'failed' WHERE id = ?",
            (message_id,),
        )
        await connection.commit()


async def support_outbox_worker(bot: Bot) -> None:
    await ensure_internal_admin_support_schema()
    logger.info("Support outbox worker started")
    while True:
        item = None
        try:
            item = await _claim_outbox_item()
            if item is None:
                await asyncio.sleep(OUTBOX_POLL_SECONDS)
                continue
            sent = await bot.send_message(
                chat_id=int(item["telegram_id"]),
                text=(
                    f"💬 <b>Ответ поддержки по обращению #{item['ticket_id']}</b>\n\n"
                    f"{html.escape(str(item['body']))}"
                ),
            )
            await _mark_outbox_sent(
                int(item["id"]),
                int(item["message_id"]),
                int(sent.message_id),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Support outbox delivery failed")
            if item is not None:
                await _mark_outbox_failed(
                    int(item["id"]),
                    int(item["message_id"]),
                    int(item["attempts"]),
                    exc,
                )
            await asyncio.sleep(OUTBOX_POLL_SECONDS)


def ensure_support_outbox_worker(bot: Bot) -> asyncio.Task[None]:
    global _WORKER_TASK
    if _WORKER_TASK is None or _WORKER_TASK.done():
        _WORKER_TASK = asyncio.create_task(
            support_outbox_worker(bot),
            name="support-outbox-worker",
        )
    return _WORKER_TASK
