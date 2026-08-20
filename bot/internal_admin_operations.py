from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from aiohttp import web

from bot import db as db_backend
from bot import internal_admin_api as base_api
from bot.internal_admin_user_commands import (
    CommandConflictError,
    CommandValidationError,
    _command_headers,
    _complete_command,
    _parse_command_payload,
    _reserve_command,
    internal_user_endpoint,
)

_ALLOWED_STATUSES = {
    "pending",
    "queued",
    "processing",
    "submitting",
    "completed",
    "failed",
}
_ALLOWED_TYPES = {"image", "video"}
_SENSITIVE_KEY_FRAGMENTS = (
    "token",
    "secret",
    "password",
    "authorization",
    "api_key",
    "apikey",
    "webhook",
    "callback",
)
_MAX_REQUEST_DEPTH = 5
_MAX_COLLECTION_ITEMS = 50
_MAX_STRING_LENGTH = 4000


def _service_envelope() -> dict[str, Any]:
    return base_api._service_envelope()


def _json_value(value: Any) -> Any:
    return base_api._json_value(value)


def _parse_operation_id(request: web.Request) -> int:
    raw_value = request.match_info.get("operation_id", "")
    try:
        operation_id = int(raw_value)
    except ValueError as exc:
        raise CommandValidationError("operation id must be an integer") from exc
    if operation_id <= 0:
        raise CommandValidationError("operation id must be positive")
    return operation_id


def _parse_optional_positive_int(value: str | None, *, field: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise CommandValidationError(f"{field} must be an integer") from exc
    if parsed <= 0:
        raise CommandValidationError(f"{field} must be positive")
    return parsed


def _parse_request_data(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not value:
        return {}
    try:
        if isinstance(value, (bytes, bytearray)):
            text = bytes(value).decode("utf-8")
        else:
            text = str(value)
        parsed = json.loads(text)
    except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_result_urls(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return [str(value)]
    if isinstance(parsed, list):
        return [str(item) for item in parsed if item]
    return [str(value)]


def _sanitize_value(value: Any, *, depth: int = 0, key: str = "") -> Any:
    normalized_key = key.lower().replace("-", "_")
    if any(fragment in normalized_key for fragment in _SENSITIVE_KEY_FRAGMENTS):
        return "[redacted]"
    if depth >= _MAX_REQUEST_DEPTH:
        return "[truncated]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:_MAX_STRING_LENGTH]
    if isinstance(value, Mapping):
        return {
            str(child_key): _sanitize_value(
                child_value,
                depth=depth + 1,
                key=str(child_key),
            )
            for child_key, child_value in list(value.items())[:_MAX_COLLECTION_ITEMS]
        }
    if isinstance(value, (list, tuple)):
        return [
            _sanitize_value(item, depth=depth + 1)
            for item in list(value)[:_MAX_COLLECTION_ITEMS]
        ]
    return str(value)[:_MAX_STRING_LENGTH]


def _operation_from_row(
    row: Mapping[str, Any],
    *,
    include_details: bool = False,
) -> dict[str, Any]:
    keys = set(row.keys())
    item: dict[str, Any] = {
        "id": int(row["id"]),
        "task_id": str(row["task_id"]),
        "user_id": int(row["user_id"]),
        "telegram_id": int(row["telegram_id"]) if row["telegram_id"] else None,
        "username": row["username"] if "username" in keys else None,
        "first_name": row["first_name"] if "first_name" in keys else None,
        "last_name": row["last_name"] if "last_name" in keys else None,
        "type": row["type"],
        "preset_id": row["preset_id"],
        "model": row["model"],
        "status": row["status"],
        "cost": int(row["cost"] or 0),
        "duration": row["duration"],
        "aspect_ratio": row["aspect_ratio"],
        "parent_generation_id": row["parent_generation_id"],
        "action_type": row["action_type"],
        "created_at": _json_value(row["created_at"]),
        "completed_at": _json_value(row["completed_at"]),
        "updated_at": _json_value(row["updated_at"]),
        "refunded_credits": int(row["refunded_credits"] or 0),
    }
    item["refundable_credits"] = max(
        int(item["cost"]) - int(item["refunded_credits"]),
        0,
    )
    if include_details:
        item.update(
            {
                "prompt": row["prompt"],
                "result_url": row["result_url"],
                "result_urls": _sanitize_value(_parse_result_urls(row["result_urls"])),
                "request": _sanitize_value(_parse_request_data(row["request_data"])),
            }
        )
    return item


_OPERATION_SELECT = """
    SELECT
        gt.id,
        gt.task_id,
        gt.user_id,
        gt.telegram_id,
        u.username,
        u.first_name,
        u.last_name,
        gt.type,
        gt.preset_id,
        gt.model,
        gt.status,
        gt.cost,
        gt.duration,
        gt.aspect_ratio,
        gt.prompt,
        gt.result_url,
        gt.result_urls,
        gt.request_data,
        gt.parent_generation_id,
        gt.action_type,
        gt.created_at,
        gt.completed_at,
        gt.updated_at,
        COALESCE((
            SELECT SUM(e.amount)
            FROM internal_admin_operation_events e
            WHERE e.operation_id = gt.id
              AND e.event_type = 'credits.refund'
              AND e.status = 'success'
        ), 0) AS refunded_credits
    FROM generation_tasks gt
    JOIN users u ON u.id = gt.user_id
"""


async def _fetch_operation(
    operation_id: int,
    *,
    for_update: bool = False,
) -> Mapping[str, Any] | None:
    suffix = " FOR UPDATE OF gt, u" if for_update else ""
    async with db_backend.connect() as connection:
        connection.row_factory = db_backend.Row
        cursor = await connection.execute(
            f"{_OPERATION_SELECT} WHERE gt.id = ?{suffix}",
            (operation_id,),
        )
        return await cursor.fetchone()


async def _fetch_operation_in_connection(
    connection: db_backend.Connection,
    operation_id: int,
    *,
    for_update: bool,
) -> Mapping[str, Any] | None:
    connection.row_factory = db_backend.Row
    suffix = " FOR UPDATE OF gt, u" if for_update else ""
    cursor = await connection.execute(
        f"{_OPERATION_SELECT} WHERE gt.id = ?{suffix}",
        (operation_id,),
    )
    return await cursor.fetchone()


async def _operation_by_task_id(task_id: str) -> Mapping[str, Any] | None:
    rows = await base_api._fetch_all(
        f"{_OPERATION_SELECT} WHERE gt.task_id = ? ORDER BY gt.id DESC LIMIT 1",
        (task_id,),
    )
    return rows[0] if rows else None


async def _record_event(
    connection: db_backend.Connection,
    *,
    operation_id: int,
    event_type: str,
    status: str,
    actor_id: str | None,
    request_id: str | None,
    idempotency_key: str | None,
    amount: int | None = None,
    related_operation_id: int | None = None,
    details: Mapping[str, object] | None = None,
) -> None:
    await connection.execute(
        """
        INSERT INTO internal_admin_operation_events (
            operation_id, event_type, status, actor_type, actor_id,
            request_id, idempotency_key, amount, related_operation_id, details
        ) VALUES (?, ?, ?, 'admin', ?, ?, ?, ?, ?, CAST(? AS JSONB))
        """,
        (
            operation_id,
            event_type,
            status,
            actor_id,
            request_id,
            idempotency_key,
            amount,
            related_operation_id,
            json.dumps(dict(details or {}), ensure_ascii=False),
        ),
    )


def _require_confirmation(actual: Any, expected: str) -> None:
    if str(actual or "") != expected:
        raise CommandConflictError(f"confirmation must equal {expected}")


def _command_response(payload: dict[str, Any]) -> web.Response:
    response_status = int(payload.get("_http_status", 200))
    response_payload = {
        key: value for key, value in payload.items() if key != "_http_status"
    }
    return web.json_response(response_payload, status=response_status)


@internal_user_endpoint
async def operations_handler(request: web.Request) -> web.Response:
    if request.method != "GET":
        return web.json_response({"error": "method_not_allowed"}, status=405)

    limit = base_api._parse_page_limit(request)
    cursor_id = base_api.decode_cursor(request.query.get("cursor"))
    query = (request.query.get("query") or "").strip()
    if len(query) > 120:
        raise CommandValidationError("query is too long")

    status_filter = (request.query.get("status") or "").strip().lower()
    if status_filter and status_filter not in _ALLOWED_STATUSES:
        raise CommandValidationError("unsupported operation status")
    type_filter = (request.query.get("type") or "").strip().lower()
    if type_filter and type_filter not in _ALLOWED_TYPES:
        raise CommandValidationError("unsupported operation type")
    user_id = _parse_optional_positive_int(
        request.query.get("user_id"),
        field="user_id",
    )

    clauses: list[str] = []
    parameters: list[Any] = []
    if cursor_id is not None:
        clauses.append("gt.id < ?")
        parameters.append(cursor_id)
    if query:
        pattern = f"%{query.lower()}%"
        clauses.append(
            "(CAST(gt.id AS TEXT) = ? OR LOWER(gt.task_id) LIKE ? "
            "OR CAST(gt.telegram_id AS TEXT) = ? "
            "OR LOWER(COALESCE(u.username, '')) LIKE ?)"
        )
        parameters.extend([query, pattern, query, pattern])
    if status_filter:
        clauses.append("LOWER(gt.status) = ?")
        parameters.append(status_filter)
    if type_filter:
        clauses.append("LOWER(gt.type) = ?")
        parameters.append(type_filter)
    if user_id is not None:
        clauses.append("gt.user_id = ?")
        parameters.append(user_id)

    where_sql = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    parameters.append(limit + 1)
    rows = await base_api._fetch_all(
        f"{_OPERATION_SELECT}{where_sql} ORDER BY gt.id DESC LIMIT ?",
        tuple(parameters),
    )
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    items = [_operation_from_row(row) for row in page_rows]
    next_cursor = (
        base_api.encode_cursor(int(page_rows[-1]["id"]))
        if has_more and page_rows
        else None
    )
    return web.json_response(
        {**_service_envelope(), "items": items, "next_cursor": next_cursor}
    )


@internal_user_endpoint
async def operation_detail_handler(request: web.Request) -> web.Response:
    operation_id = _parse_operation_id(request)
    row = await _fetch_operation(operation_id)
    if row is None:
        raise web.HTTPNotFound(text="operation_not_found")

    children = await base_api._fetch_all(
        """
        SELECT id, task_id, status, action_type, created_at, completed_at
        FROM generation_tasks
        WHERE parent_generation_id = ?
        ORDER BY id ASC
        """,
        (operation_id,),
    )
    return web.json_response(
        {
            **_service_envelope(),
            "data": _operation_from_row(row, include_details=True),
            "children": [
                {str(key): _json_value(child[key]) for key in child.keys()}
                for child in children
            ],
        }
    )


@internal_user_endpoint
async def operation_timeline_handler(request: web.Request) -> web.Response:
    operation_id = _parse_operation_id(request)
    row = await _fetch_operation(operation_id)
    if row is None:
        raise web.HTTPNotFound(text="operation_not_found")

    persisted = await base_api._fetch_all(
        """
        SELECT
            id, event_type, status, actor_type, actor_id, request_id,
            idempotency_key, amount, related_operation_id, details, created_at
        FROM internal_admin_operation_events
        WHERE operation_id = ?
        ORDER BY created_at ASC, id ASC
        """,
        (operation_id,),
    )
    items: list[dict[str, Any]] = [
        {
            "id": f"synthetic-created-{operation_id}",
            "event_type": "operation.created",
            "status": "success",
            "actor_type": "system",
            "actor_id": None,
            "request_id": None,
            "idempotency_key": None,
            "amount": None,
            "related_operation_id": row["parent_generation_id"],
            "details": {
                "task_id": row["task_id"],
                "type": row["type"],
                "model": row["model"],
                "action_type": row["action_type"],
            },
            "created_at": _json_value(row["created_at"]),
        }
    ]
    if row["completed_at"]:
        items.append(
            {
                "id": f"synthetic-final-{operation_id}",
                "event_type": "operation.finalized",
                "status": row["status"],
                "actor_type": "system",
                "actor_id": None,
                "request_id": None,
                "idempotency_key": None,
                "amount": None,
                "related_operation_id": None,
                "details": {},
                "created_at": _json_value(row["completed_at"]),
            }
        )

    for event in persisted:
        details = event["details"]
        if isinstance(details, str):
            details = _parse_request_data(details)
        items.append(
            {
                "id": int(event["id"]),
                "event_type": event["event_type"],
                "status": event["status"],
                "actor_type": event["actor_type"],
                "actor_id": event["actor_id"],
                "request_id": event["request_id"],
                "idempotency_key": event["idempotency_key"],
                "amount": event["amount"],
                "related_operation_id": event["related_operation_id"],
                "details": _sanitize_value(details or {}),
                "created_at": _json_value(event["created_at"]),
            }
        )
    items.sort(key=lambda item: str(item["created_at"] or ""))
    return web.json_response({**_service_envelope(), "items": items})


@internal_user_endpoint
async def refund_operation_handler(request: web.Request) -> web.Response:
    operation_id = _parse_operation_id(request)
    payload = _parse_command_payload(request, require_amount=True)
    amount = int(payload["amount"])
    if amount <= 0:
        raise CommandValidationError("refund amount must be positive")
    raw_payload = _parse_request_data(request.get("internal_body", b""))
    _require_confirmation(raw_payload.get("confirmation"), f"REFUND {amount}")
    idempotency_key, admin_user_id, request_id = _command_headers(request)

    async with db_backend.connect() as connection:
        existing = await _reserve_command(
            connection,
            idempotency_key=idempotency_key,
            action="operation.refund",
            user_id=operation_id,
            admin_user_id=admin_user_id,
            request_id=request_id,
            payload=payload,
        )
        if existing is not None:
            await connection.rollback()
            return _command_response(existing)

        operation = await _fetch_operation_in_connection(
            connection,
            operation_id,
            for_update=True,
        )
        if operation is None:
            await connection.rollback()
            raise web.HTTPNotFound(text="operation_not_found")
        original_cost = int(operation["cost"] or 0)
        refunded_before = int(operation["refunded_credits"] or 0)
        refundable = max(original_cost - refunded_before, 0)
        if original_cost <= 0:
            raise CommandConflictError("operation did not charge credits")
        if amount > refundable:
            raise CommandConflictError(
                f"refund exceeds remaining refundable credits ({refundable})"
            )

        await connection.execute(
            """
            UPDATE users
            SET credits = credits + ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (amount, int(operation["user_id"])),
        )
        await _record_event(
            connection,
            operation_id=operation_id,
            event_type="credits.refund",
            status="success",
            actor_id=admin_user_id,
            request_id=request_id,
            idempotency_key=idempotency_key,
            amount=amount,
            details={
                "reason": payload["reason"],
                "comment": payload.get("comment"),
            },
        )
        balance_cursor = await connection.execute(
            "SELECT credits FROM users WHERE id = ?",
            (int(operation["user_id"]),),
        )
        balance_row = await balance_cursor.fetchone()
        refunded_total = refunded_before + amount
        response_payload = {
            **_service_envelope(),
            "data": {
                "operation_id": operation_id,
                "user_id": int(operation["user_id"]),
                "telegram_id": int(operation["telegram_id"]),
                "amount": amount,
                "balance": int(balance_row["credits"] if balance_row else 0),
                "refunded_total": refunded_total,
                "refundable_remaining": max(original_cost - refunded_total, 0),
            },
        }
        await _complete_command(
            connection,
            idempotency_key=idempotency_key,
            response_payload=response_payload,
        )
        await connection.commit()
    return web.json_response(response_payload)
