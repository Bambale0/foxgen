from __future__ import annotations

from typing import Any

from aiohttp import web

from bot import db as db_backend
from bot import internal_admin_notifications as notifications
from bot.internal_admin_user_commands import (
    CommandConflictError,
    CommandValidationError,
    _command_headers,
    internal_user_endpoint,
)


def _test_result(
    *,
    campaign_id: int,
    telegram_id: int,
    status: str,
    message_id: int | None,
    error: str | None,
) -> tuple[dict[str, Any], int]:
    payload = {
        **notifications._service_envelope(),
        "data": {
            "campaign_id": campaign_id,
            "telegram_id": telegram_id,
            "status": status,
            "telegram_message_id": message_id,
            "error": error,
        },
    }
    if status == "failed":
        return payload, 502
    if status == "sending":
        return payload, 202
    return payload, 200


@internal_user_endpoint
async def test_campaign_handler(request: web.Request) -> web.Response:
    """Send a test notification exactly once per idempotency key.

    The reservation and Telegram call share one database transaction. A
    concurrent request with the same key waits on the unique constraint and
    then returns the committed result instead of sending a duplicate message.
    If the process dies before commit, PostgreSQL rolls the reservation back.
    """

    campaign_id = notifications._parse_campaign_id(request)
    payload = notifications._signed_json_object(request)
    if payload.get("confirmation") != f"TEST {campaign_id}":
        raise CommandConflictError(f"confirmation must equal TEST {campaign_id}")
    try:
        telegram_id = int(payload.get("telegram_id"))
    except (TypeError, ValueError) as exc:
        raise CommandValidationError("telegram_id must be an integer") from exc
    if telegram_id <= 0:
        raise CommandValidationError("telegram_id must be positive")

    idempotency_key, admin_user_id, request_id = _command_headers(request)
    campaign = await notifications._fetch_campaign(campaign_id)
    if campaign is None:
        raise web.HTTPNotFound(text="campaign_not_found")

    async with db_backend.connect() as connection:
        connection.row_factory = db_backend.Row
        reserve_cursor = await connection.execute(
            """
            INSERT INTO notification_test_sends (
                campaign_id, telegram_id, status, requested_by,
                request_id, idempotency_key
            ) VALUES (?, ?, 'sending', ?, ?, ?)
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING id
            """,
            (
                campaign_id,
                telegram_id,
                admin_user_id,
                request_id,
                idempotency_key,
            ),
        )
        reservation = await reserve_cursor.fetchone()
        if reservation is None:
            existing_cursor = await connection.execute(
                """
                SELECT telegram_id, status, telegram_message_id, error
                FROM notification_test_sends
                WHERE idempotency_key = ?
                LIMIT 1
                """,
                (idempotency_key,),
            )
            existing = await existing_cursor.fetchone()
            await connection.rollback()
            if existing is None:
                raise RuntimeError("notification test reservation disappeared")
            response_payload, response_status = _test_result(
                campaign_id=campaign_id,
                telegram_id=int(existing["telegram_id"]),
                status=str(existing["status"]),
                message_id=(
                    int(existing["telegram_message_id"])
                    if existing["telegram_message_id"] is not None
                    else None
                ),
                error=str(existing["error"]) if existing["error"] else None,
            )
            return web.json_response(response_payload, status=response_status)

        status = "sent"
        message_id: int | None = None
        error: str | None = None
        try:
            sent = await notifications.send_campaign_message(
                request.app["bot"],
                telegram_id,
                notifications._decode_json_object(campaign["message"]),
            )
            message_id = int(sent.message_id)
        except Exception as exc:
            status = "failed"
            error = f"{type(exc).__name__}: {str(exc)[:500]}"

        await connection.execute(
            """
            UPDATE notification_test_sends
            SET status = ?, telegram_message_id = ?, error = ?
            WHERE id = ?
            """,
            (status, message_id, error, reservation["id"]),
        )
        await connection.commit()

    response_payload, response_status = _test_result(
        campaign_id=campaign_id,
        telegram_id=telegram_id,
        status=status,
        message_id=message_id,
        error=error,
    )
    return web.json_response(response_payload, status=response_status)
