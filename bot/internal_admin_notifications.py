from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiohttp import web

from bot import db as db_backend
from bot import internal_admin_api as base_api
from bot.internal_admin_user_commands import (
    CommandConflictError,
    CommandValidationError,
    _command_headers,
    internal_user_endpoint,
)

_CAMPAIGN_STATUSES = {
    "draft",
    "scheduled",
    "running",
    "completed",
    "cancelled",
    "failed",
}
_SEGMENT_TYPES = {
    "all",
    "paid",
    "unpaid",
    "recent",
    "inactive",
    "balance_gte",
    "balance_lt",
    "explicit",
}


def _service_envelope() -> dict[str, Any]:
    return base_api._service_envelope()


def _json_value(value: Any) -> Any:
    return base_api._json_value(value)


def _signed_json_object(request: web.Request) -> dict[str, Any]:
    body = bytes(request.get("internal_body", b""))
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CommandValidationError("request body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise CommandValidationError("request body must be an object")
    return payload


def _parse_campaign_id(request: web.Request) -> int:
    raw = request.match_info.get("campaign_id", "")
    try:
        campaign_id = int(raw)
    except ValueError as exc:
        raise CommandValidationError("campaign id must be an integer") from exc
    if campaign_id <= 0:
        raise CommandValidationError("campaign id must be positive")
    return campaign_id


def _required_text(payload: Mapping[str, Any], key: str, *, minimum: int, maximum: int) -> str:
    value = str(payload.get(key) or "").strip()
    if not minimum <= len(value) <= maximum:
        raise CommandValidationError(
            f"{key} must contain between {minimum} and {maximum} characters"
        )
    return value


def _validate_button_url(value: Any) -> str | None:
    if value in (None, ""):
        return None
    url = str(value).strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "tg"}:
        raise CommandValidationError("button_url must use https:// or tg://")
    if parsed.scheme == "https" and not parsed.netloc:
        raise CommandValidationError("button_url must contain a host")
    return url


def _validate_message(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CommandValidationError("message must be an object")
    text = str(value.get("text") or "").strip()
    if not 1 <= len(text) <= 4096:
        raise CommandValidationError("message.text must contain between 1 and 4096 characters")
    button_label = str(value.get("button_label") or "").strip() or None
    if button_label and len(button_label) > 64:
        raise CommandValidationError("message.button_label is too long")
    button_url = _validate_button_url(value.get("button_url"))
    if bool(button_label) != bool(button_url):
        raise CommandValidationError("button_label and button_url must be supplied together")
    return {
        "text": text,
        "button_label": button_label,
        "button_url": button_url,
        "disable_web_page_preview": bool(value.get("disable_web_page_preview", True)),
    }


def _normalize_explicit_ids(value: Any) -> list[int]:
    if not isinstance(value, list) or not value:
        raise CommandValidationError("explicit segment requires telegram_ids")
    if len(value) > 1000:
        raise CommandValidationError("explicit segment supports at most 1000 telegram_ids")
    result: list[int] = []
    seen: set[int] = set()
    for item in value:
        try:
            telegram_id = int(item)
        except (TypeError, ValueError) as exc:
            raise CommandValidationError("telegram_ids must contain integers") from exc
        if telegram_id <= 0:
            raise CommandValidationError("telegram_ids must be positive")
        if telegram_id not in seen:
            seen.add(telegram_id)
            result.append(telegram_id)
    return result


def _validate_segment(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CommandValidationError("segment must be an object")
    segment_type = str(value.get("type") or "").strip().lower()
    if segment_type not in _SEGMENT_TYPES:
        raise CommandValidationError("unsupported segment type")
    segment: dict[str, Any] = {"type": segment_type}
    if segment_type in {"recent", "inactive"}:
        try:
            days = int(value.get("days", 30))
        except (TypeError, ValueError) as exc:
            raise CommandValidationError("segment.days must be an integer") from exc
        if not 1 <= days <= 3650:
            raise CommandValidationError("segment.days must be between 1 and 3650")
        segment["days"] = days
    elif segment_type in {"balance_gte", "balance_lt"}:
        try:
            amount = int(value.get("amount"))
        except (TypeError, ValueError) as exc:
            raise CommandValidationError("segment.amount must be an integer") from exc
        if amount < 0:
            raise CommandValidationError("segment.amount cannot be negative")
        segment["amount"] = amount
    elif segment_type == "explicit":
        segment["telegram_ids"] = _normalize_explicit_ids(value.get("telegram_ids"))
    return segment


def _segment_query(segment: Mapping[str, Any], *, count_only: bool) -> tuple[str, tuple[Any, ...]]:
    select_sql = "COUNT(*) AS audience_count" if count_only else "u.id, u.telegram_id"
    sql = f"SELECT {select_sql} FROM users u"
    clauses = ["COALESCE(u.is_banned, 0) = 0", "u.telegram_id IS NOT NULL"]
    parameters: list[Any] = []
    segment_type = str(segment["type"])

    if segment_type == "paid":
        clauses.append("COALESCE(u.has_paid, FALSE) = TRUE")
    elif segment_type == "unpaid":
        clauses.append("COALESCE(u.has_paid, FALSE) = FALSE")
    elif segment_type == "recent":
        clauses.append(
            "EXISTS (SELECT 1 FROM generation_tasks gt WHERE gt.user_id = u.id "
            "AND gt.created_at >= CURRENT_TIMESTAMP - (? * INTERVAL '1 day'))"
        )
        parameters.append(int(segment["days"]))
    elif segment_type == "inactive":
        clauses.append(
            "NOT EXISTS (SELECT 1 FROM generation_tasks gt WHERE gt.user_id = u.id "
            "AND gt.created_at >= CURRENT_TIMESTAMP - (? * INTERVAL '1 day'))"
        )
        parameters.append(int(segment["days"]))
    elif segment_type == "balance_gte":
        clauses.append("COALESCE(u.credits, 0) >= ?")
        parameters.append(int(segment["amount"]))
    elif segment_type == "balance_lt":
        clauses.append("COALESCE(u.credits, 0) < ?")
        parameters.append(int(segment["amount"]))
    elif segment_type == "explicit":
        telegram_ids = list(segment["telegram_ids"])
        placeholders = ",".join("?" for _ in telegram_ids)
        clauses.append(f"u.telegram_id IN ({placeholders})")
        parameters.extend(telegram_ids)

    sql += " WHERE " + " AND ".join(clauses)
    if not count_only:
        sql += " ORDER BY u.id"
    return sql, tuple(parameters)


def _decode_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _campaign_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "name": str(row["name"]),
        "channel": str(row["channel"]),
        "status": str(row["status"]),
        "segment": _decode_json_object(row["segment"]),
        "message": _decode_json_object(row["message"]),
        "audience_count": int(row["audience_count"] or 0),
        "queued_count": int(row["queued_count"] or 0),
        "sent_count": int(row["sent_count"] or 0),
        "failed_count": int(row["failed_count"] or 0),
        "blocked_count": int(row["blocked_count"] or 0),
        "cancelled_count": int(row["cancelled_count"] or 0),
        "created_by": row["created_by"],
        "reason": row["reason"],
        "request_id": row["request_id"],
        "scheduled_at": _json_value(row["scheduled_at"]),
        "started_at": _json_value(row["started_at"]),
        "completed_at": _json_value(row["completed_at"]),
        "cancelled_at": _json_value(row["cancelled_at"]),
        "created_at": _json_value(row["created_at"]),
        "updated_at": _json_value(row["updated_at"]),
    }


async def _fetch_campaign(campaign_id: int) -> Mapping[str, Any] | None:
    rows = await base_api._fetch_all(
        "SELECT * FROM notification_campaigns WHERE id = ? LIMIT 1",
        (campaign_id,),
    )
    return rows[0] if rows else None


async def _audience_count(segment: Mapping[str, Any]) -> int:
    sql, params = _segment_query(segment, count_only=True)
    rows = await base_api._fetch_all(sql, params)
    return int(rows[0]["audience_count"] or 0) if rows else 0


def _reply_markup(message: Mapping[str, Any]) -> InlineKeyboardMarkup | None:
    label = message.get("button_label")
    url = message.get("button_url")
    if not label or not url:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=str(label), url=str(url))]]
    )


async def send_campaign_message(bot: Bot, telegram_id: int, message: Mapping[str, Any]):
    text = str(message.get("text") or "")
    media_type = str(message.get("media_type") or "").strip().lower()
    media_file_id = str(message.get("media_file_id") or "").strip()
    parse_mode = message.get("parse_mode")
    parse_mode = str(parse_mode) if parse_mode else None
    reply_markup = _reply_markup(message)

    if media_type == "photo" and media_file_id:
        return await bot.send_photo(
            chat_id=telegram_id,
            photo=media_file_id,
            caption=text or None,
            parse_mode=parse_mode if text else None,
            reply_markup=reply_markup,
        )
    if media_type == "video" and media_file_id:
        return await bot.send_video(
            chat_id=telegram_id,
            video=media_file_id,
            caption=text or None,
            parse_mode=parse_mode if text else None,
            reply_markup=reply_markup,
        )
    return await bot.send_message(
        chat_id=telegram_id,
        text=text,
        parse_mode=parse_mode,
        disable_web_page_preview=bool(message.get("disable_web_page_preview", True)),
        reply_markup=reply_markup,
    )


@internal_user_endpoint
async def campaign_preview_handler(request: web.Request) -> web.Response:
    payload = _signed_json_object(request)
    segment = _validate_segment(payload.get("segment"))
    audience_count = await _audience_count(segment)
    return web.json_response(
        {**_service_envelope(), "data": {"segment": segment, "audience_count": audience_count}}
    )


@internal_user_endpoint
async def campaigns_handler(request: web.Request) -> web.Response:
    if request.method == "POST":
        payload = _signed_json_object(request)
        name = _required_text(payload, "name", minimum=3, maximum=160)
        reason = _required_text(payload, "reason", minimum=5, maximum=500)
        if payload.get("confirmation") != "SAVE CAMPAIGN":
            raise CommandConflictError("confirmation must equal SAVE CAMPAIGN")
        segment = _validate_segment(payload.get("segment"))
        message = _validate_message(payload.get("message"))
        idempotency_key, admin_user_id, request_id = _command_headers(request)
        audience_count = await _audience_count(segment)

        async with db_backend.connect() as connection:
            connection.row_factory = db_backend.Row
            cursor = await connection.execute(
                """
                INSERT INTO notification_campaigns (
                    name, segment, message, audience_count, created_by,
                    reason, request_id, idempotency_key
                ) VALUES (?, CAST(? AS JSONB), CAST(? AS JSONB), ?, ?, ?, ?, ?)
                ON CONFLICT (idempotency_key) DO UPDATE
                SET idempotency_key = EXCLUDED.idempotency_key
                RETURNING *
                """,
                (
                    name,
                    json.dumps(segment, ensure_ascii=False),
                    json.dumps(message, ensure_ascii=False),
                    audience_count,
                    admin_user_id,
                    reason,
                    request_id,
                    idempotency_key,
                ),
            )
            row = await cursor.fetchone()
            await connection.commit()
        if not row:
            raise RuntimeError("notification campaign was not created")
        return web.json_response({**_service_envelope(), "data": _campaign_from_row(row)})

    limit = base_api._parse_page_limit(request)
    cursor_id = base_api.decode_cursor(request.query.get("cursor"))
    status_filter = str(request.query.get("status") or "").strip().lower()
    if status_filter and status_filter not in _CAMPAIGN_STATUSES:
        raise CommandValidationError("unsupported campaign status")
    clauses: list[str] = []
    params: list[Any] = []
    if cursor_id is not None:
        clauses.append("id < ?")
        params.append(cursor_id)
    if status_filter:
        clauses.append("status = ?")
        params.append(status_filter)
    where_sql = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit + 1)
    rows = await base_api._fetch_all(
        f"SELECT * FROM notification_campaigns{where_sql} ORDER BY id DESC LIMIT ?",
        tuple(params),
    )
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = (
        base_api.encode_cursor(int(page_rows[-1]["id"])) if has_more and page_rows else None
    )
    return web.json_response(
        {
            **_service_envelope(),
            "items": [_campaign_from_row(row) for row in page_rows],
            "next_cursor": next_cursor,
        }
    )


@internal_user_endpoint
async def campaign_detail_handler(request: web.Request) -> web.Response:
    campaign_id = _parse_campaign_id(request)
    row = await _fetch_campaign(campaign_id)
    if row is None:
        raise web.HTTPNotFound(text="campaign_not_found")
    deliveries = await base_api._fetch_all(
        """
        SELECT status, COUNT(*) AS count
        FROM notification_deliveries
        WHERE campaign_id = ?
        GROUP BY status
        ORDER BY status
        """,
        (campaign_id,),
    )
    tests = await base_api._fetch_all(
        """
        SELECT id, telegram_id, status, telegram_message_id, error,
               requested_by, request_id, created_at
        FROM notification_test_sends
        WHERE campaign_id = ?
        ORDER BY id DESC
        LIMIT 20
        """,
        (campaign_id,),
    )
    return web.json_response(
        {
            **_service_envelope(),
            "data": _campaign_from_row(row),
            "delivery_report": {str(item["status"]): int(item["count"]) for item in deliveries},
            "test_sends": [
                {
                    "id": int(item["id"]),
                    "telegram_id": int(item["telegram_id"]),
                    "status": item["status"],
                    "telegram_message_id": item["telegram_message_id"],
                    "error": item["error"],
                    "requested_by": item["requested_by"],
                    "request_id": item["request_id"],
                    "created_at": _json_value(item["created_at"]),
                }
                for item in tests
            ],
        }
    )


@internal_user_endpoint
async def test_campaign_handler(request: web.Request) -> web.Response:
    campaign_id = _parse_campaign_id(request)
    payload = _signed_json_object(request)
    if payload.get("confirmation") != f"TEST {campaign_id}":
        raise CommandConflictError(f"confirmation must equal TEST {campaign_id}")
    try:
        telegram_id = int(payload.get("telegram_id"))
    except (TypeError, ValueError) as exc:
        raise CommandValidationError("telegram_id must be an integer") from exc
    if telegram_id <= 0:
        raise CommandValidationError("telegram_id must be positive")
    idempotency_key, admin_user_id, request_id = _command_headers(request)
    campaign = await _fetch_campaign(campaign_id)
    if campaign is None:
        raise web.HTTPNotFound(text="campaign_not_found")

    async with db_backend.connect() as connection:
        connection.row_factory = db_backend.Row
        existing_cursor = await connection.execute(
            "SELECT * FROM notification_test_sends WHERE idempotency_key = ? LIMIT 1",
            (idempotency_key,),
        )
        existing = await existing_cursor.fetchone()
        if existing:
            return web.json_response(
                {
                    **_service_envelope(),
                    "data": {
                        "campaign_id": campaign_id,
                        "telegram_id": int(existing["telegram_id"]),
                        "status": existing["status"],
                        "telegram_message_id": existing["telegram_message_id"],
                        "error": existing["error"],
                    },
                }
            )

    status = "sent"
    message_id: int | None = None
    error: str | None = None
    try:
        sent = await send_campaign_message(
            request.app["bot"],
            telegram_id,
            _decode_json_object(campaign["message"]),
        )
        message_id = int(sent.message_id)
    except Exception as exc:
        status = "failed"
        error = f"{type(exc).__name__}: {str(exc)[:500]}"

    async with db_backend.connect() as connection:
        await connection.execute(
            """
            INSERT INTO notification_test_sends (
                campaign_id, telegram_id, status, telegram_message_id, error,
                requested_by, request_id, idempotency_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign_id,
                telegram_id,
                status,
                message_id,
                error,
                admin_user_id,
                request_id,
                idempotency_key,
            ),
        )
        await connection.commit()
    response_status = 200 if status == "sent" else 502
    return web.json_response(
        {
            **_service_envelope(),
            "data": {
                "campaign_id": campaign_id,
                "telegram_id": telegram_id,
                "status": status,
                "telegram_message_id": message_id,
                "error": error,
            },
        },
        status=response_status,
    )


@internal_user_endpoint
async def start_campaign_handler(request: web.Request) -> web.Response:
    campaign_id = _parse_campaign_id(request)
    payload = _signed_json_object(request)
    if payload.get("confirmation") != f"START {campaign_id}":
        raise CommandConflictError(f"confirmation must equal START {campaign_id}")
    _idempotency_key, _admin_user_id, _request_id = _command_headers(request)

    async with db_backend.connect() as connection:
        connection.row_factory = db_backend.Row
        cursor = await connection.execute(
            "SELECT * FROM notification_campaigns WHERE id = ? FOR UPDATE",
            (campaign_id,),
        )
        campaign = await cursor.fetchone()
        if not campaign:
            raise web.HTTPNotFound(text="campaign_not_found")
        if campaign["status"] not in {"draft", "scheduled", "running"}:
            raise CommandConflictError(
                f"campaign cannot be started from status {campaign['status']}"
            )
        if campaign["status"] in {"draft", "scheduled"}:
            segment = _decode_json_object(campaign["segment"])
            sql, params = _segment_query(segment, count_only=False)
            await connection.execute(
                f"""
                INSERT INTO notification_deliveries (campaign_id, user_id, telegram_id)
                SELECT ?, audience.id, audience.telegram_id
                FROM ({sql}) AS audience
                ON CONFLICT (campaign_id, telegram_id) DO NOTHING
                """,
                (campaign_id, *params),
            )
            count_cursor = await connection.execute(
                "SELECT COUNT(*) AS count FROM notification_deliveries WHERE campaign_id = ?",
                (campaign_id,),
            )
            count_row = await count_cursor.fetchone()
            audience_count = int(count_row["count"] or 0) if count_row else 0
            await connection.execute(
                """
                UPDATE notification_campaigns
                SET status = CASE WHEN ? = 0 THEN 'completed' ELSE 'running' END,
                    audience_count = ?, queued_count = ?,
                    started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                    completed_at = CASE WHEN ? = 0 THEN CURRENT_TIMESTAMP ELSE NULL END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (audience_count, audience_count, audience_count, audience_count, campaign_id),
            )
        await connection.commit()
    refreshed = await _fetch_campaign(campaign_id)
    return web.json_response(
        {**_service_envelope(), "data": _campaign_from_row(refreshed or campaign)}
    )


@internal_user_endpoint
async def cancel_campaign_handler(request: web.Request) -> web.Response:
    campaign_id = _parse_campaign_id(request)
    payload = _signed_json_object(request)
    if payload.get("confirmation") != f"CANCEL {campaign_id}":
        raise CommandConflictError(f"confirmation must equal CANCEL {campaign_id}")
    _command_headers(request)

    async with db_backend.connect() as connection:
        connection.row_factory = db_backend.Row
        cursor = await connection.execute(
            "SELECT status FROM notification_campaigns WHERE id = ? FOR UPDATE",
            (campaign_id,),
        )
        campaign = await cursor.fetchone()
        if not campaign:
            raise web.HTTPNotFound(text="campaign_not_found")
        if campaign["status"] in {"completed", "cancelled", "failed"}:
            raise CommandConflictError(
                f"campaign cannot be cancelled from status {campaign['status']}"
            )
        await connection.execute(
            """
            UPDATE notification_campaigns
            SET status = 'cancelled', cancelled_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (campaign_id,),
        )
        await connection.execute(
            """
            UPDATE notification_deliveries
            SET status = 'cancelled', lease_until = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE campaign_id = ?
              AND status IN ('queued', 'failed')
            """,
            (campaign_id,),
        )
        await connection.commit()
    refreshed = await _fetch_campaign(campaign_id)
    return web.json_response(
        {**_service_envelope(), "data": _campaign_from_row(refreshed or campaign)}
    )
