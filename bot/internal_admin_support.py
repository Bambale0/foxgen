from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from aiohttp import web

from bot import db as db_backend
from bot import internal_admin_api as base_api
from bot.internal_admin_user_commands import (
    CommandConflictError,
    CommandValidationError,
    _command_headers,
    _complete_command,
    _reserve_command,
    internal_user_endpoint,
)

_ALLOWED_STATUSES = {"new", "in_progress", "waiting_user", "resolved", "closed"}
_ALLOWED_PRIORITIES = {"low", "normal", "high", "urgent"}
TicketMutation = Callable[
    [db_backend.Connection, Mapping[str, Any], Mapping[str, Any], str],
    Awaitable[None],
]


def _service_envelope() -> dict[str, Any]:
    return base_api._service_envelope()


def _json_value(value: Any) -> Any:
    return base_api._json_value(value)


def _parse_ticket_id(request: web.Request) -> int:
    raw = request.match_info.get("ticket_id", "")
    try:
        ticket_id = int(raw)
    except ValueError as exc:
        raise CommandValidationError("ticket id must be an integer") from exc
    if ticket_id <= 0:
        raise CommandValidationError("ticket id must be positive")
    return ticket_id


def _signed_payload(request: web.Request) -> dict[str, Any]:
    body = bytes(request.get("internal_body", b""))
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CommandValidationError("request body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise CommandValidationError("request body must be an object")
    return payload


def _reason(payload: Mapping[str, Any]) -> str:
    value = str(payload.get("reason") or "").strip()
    if not 5 <= len(value) <= 500:
        raise CommandValidationError("reason must contain between 5 and 500 characters")
    return value


def _require_confirmation(payload: Mapping[str, Any], expected: str) -> None:
    if str(payload.get("confirmation") or "") != expected:
        raise CommandConflictError(f"confirmation must equal {expected}")


def _ticket_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "user_id": int(row["user_id"]),
        "telegram_id": int(row["telegram_id"]),
        "username": row["username"],
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "subject": row["subject"],
        "status": row["status"],
        "priority": row["priority"],
        "assigned_admin_id": row["assigned_admin_id"],
        "linked_payment_id": row["linked_payment_id"],
        "linked_operation_id": row["linked_operation_id"],
        "source": row["source"],
        "created_at": _json_value(row["created_at"]),
        "updated_at": _json_value(row["updated_at"]),
        "last_user_message_at": _json_value(row["last_user_message_at"]),
        "last_admin_message_at": _json_value(row["last_admin_message_at"]),
        "closed_at": _json_value(row["closed_at"]),
        "messages_count": int(row["messages_count"] or 0),
        "attachments_count": int(row["attachments_count"] or 0),
    }


_TICKET_SELECT = """
    SELECT
        st.id, st.user_id, u.telegram_id, u.username, u.first_name, u.last_name,
        st.subject, st.status, st.priority, st.assigned_admin_id,
        st.linked_payment_id, st.linked_operation_id, st.source,
        st.created_at, st.updated_at, st.last_user_message_at,
        st.last_admin_message_at, st.closed_at,
        (SELECT COUNT(*) FROM support_messages sm WHERE sm.ticket_id = st.id) AS messages_count,
        (
            SELECT COUNT(*)
            FROM support_attachments sa
            JOIN support_messages sm ON sm.id = sa.message_id
            WHERE sm.ticket_id = st.id
        ) AS attachments_count
    FROM support_tickets st
    JOIN users u ON u.id = st.user_id
"""


async def _fetch_ticket(
    ticket_id: int,
    *,
    connection: db_backend.Connection | None = None,
    for_update: bool = False,
) -> Mapping[str, Any] | None:
    suffix = " FOR UPDATE OF st" if for_update else ""
    if connection is not None:
        connection.row_factory = db_backend.Row
        cursor = await connection.execute(
            f"{_TICKET_SELECT} WHERE st.id = ?{suffix}",
            (ticket_id,),
        )
        return await cursor.fetchone()
    rows = await base_api._fetch_all(
        f"{_TICKET_SELECT} WHERE st.id = ?{suffix}",
        (ticket_id,),
    )
    return rows[0] if rows else None


def _parse_optional_int(value: Any, *, field: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise CommandValidationError(f"{field} must be an integer") from exc
    if result <= 0:
        raise CommandValidationError(f"{field} must be positive")
    return result


async def _ticket_detail_from_connection(
    connection: db_backend.Connection,
    ticket_id: int,
) -> dict[str, Any]:
    ticket = await _fetch_ticket(ticket_id, connection=connection)
    if ticket is None:
        raise web.HTTPNotFound(text="ticket_not_found")
    connection.row_factory = db_backend.Row
    message_cursor = await connection.execute(
        """
        SELECT id, sender_type, sender_id, body, telegram_message_id,
               delivery_status, created_at
        FROM support_messages
        WHERE ticket_id = ?
        ORDER BY created_at, id
        """,
        (ticket_id,),
    )
    messages = await message_cursor.fetchall()
    attachment_cursor = await connection.execute(
        """
        SELECT sa.id, sa.message_id, sa.kind, sa.telegram_file_id,
               sa.file_name, sa.mime_type, sa.size_bytes, sa.created_at
        FROM support_attachments sa
        JOIN support_messages sm ON sm.id = sa.message_id
        WHERE sm.ticket_id = ?
        ORDER BY sa.id
        """,
        (ticket_id,),
    )
    attachments = await attachment_cursor.fetchall()
    attachments_by_message: dict[int, list[dict[str, Any]]] = {}
    for attachment in attachments:
        attachments_by_message.setdefault(int(attachment["message_id"]), []).append(
            {
                "id": int(attachment["id"]),
                "kind": attachment["kind"],
                "telegram_file_id": attachment["telegram_file_id"],
                "file_name": attachment["file_name"],
                "mime_type": attachment["mime_type"],
                "size_bytes": attachment["size_bytes"],
                "created_at": _json_value(attachment["created_at"]),
            }
        )
    return {
        "ticket": _ticket_from_row(ticket),
        "messages": [
            {
                "id": int(message["id"]),
                "sender_type": message["sender_type"],
                "sender_id": message["sender_id"],
                "body": message["body"],
                "telegram_message_id": message["telegram_message_id"],
                "delivery_status": message["delivery_status"],
                "created_at": _json_value(message["created_at"]),
                "attachments": attachments_by_message.get(int(message["id"]), []),
            }
            for message in messages
        ],
    }


async def _ticket_detail(ticket_id: int) -> dict[str, Any]:
    async with db_backend.connect() as connection:
        return await _ticket_detail_from_connection(connection, ticket_id)


@internal_user_endpoint
async def tickets_handler(request: web.Request) -> web.Response:
    if request.method != "GET":
        return web.json_response({"error": "method_not_allowed"}, status=405)
    limit = base_api._parse_page_limit(request)
    cursor_id = base_api.decode_cursor(request.query.get("cursor"))
    query = (request.query.get("query") or "").strip()
    if len(query) > 160:
        raise CommandValidationError("query is too long")
    status_filter = (request.query.get("status") or "").strip().lower()
    if status_filter and status_filter not in _ALLOWED_STATUSES:
        raise CommandValidationError("unsupported ticket status")
    priority = (request.query.get("priority") or "").strip().lower()
    if priority and priority not in _ALLOWED_PRIORITIES:
        raise CommandValidationError("unsupported ticket priority")
    assignee = (request.query.get("assigned_admin_id") or "").strip()

    clauses: list[str] = []
    parameters: list[Any] = []
    if cursor_id is not None:
        clauses.append("st.id < ?")
        parameters.append(cursor_id)
    if query:
        pattern = f"%{query.lower()}%"
        clauses.append(
            "(CAST(st.id AS TEXT) = ? OR CAST(u.telegram_id AS TEXT) = ? "
            "OR LOWER(COALESCE(u.username, '')) LIKE ? "
            "OR LOWER(st.subject) LIKE ?)"
        )
        parameters.extend([query, query, pattern, pattern])
    if status_filter:
        clauses.append("st.status = ?")
        parameters.append(status_filter)
    if priority:
        clauses.append("st.priority = ?")
        parameters.append(priority)
    if assignee:
        clauses.append("st.assigned_admin_id = ?")
        parameters.append(assignee)

    where_sql = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    parameters.append(limit + 1)
    rows = await base_api._fetch_all(
        f"{_TICKET_SELECT}{where_sql} ORDER BY st.id DESC LIMIT ?",
        tuple(parameters),
    )
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = (
        base_api.encode_cursor(int(page_rows[-1]["id"]))
        if has_more and page_rows
        else None
    )
    return web.json_response(
        {
            **_service_envelope(),
            "items": [_ticket_from_row(row) for row in page_rows],
            "next_cursor": next_cursor,
        }
    )


@internal_user_endpoint
async def ticket_detail_handler(request: web.Request) -> web.Response:
    return web.json_response(
        {**_service_envelope(), "data": await _ticket_detail(_parse_ticket_id(request))}
    )


async def _run_ticket_command(
    request: web.Request,
    *,
    action: str,
    mutate: TicketMutation,
) -> web.Response:
    ticket_id = _parse_ticket_id(request)
    payload = _signed_payload(request)
    reason = _reason(payload)
    idempotency_key, admin_user_id, request_id = _command_headers(request)

    async with db_backend.connect() as connection:
        existing = await _reserve_command(
            connection,
            idempotency_key=idempotency_key,
            action=f"ticket.{action}",
            user_id=ticket_id,
            admin_user_id=admin_user_id,
            request_id=request_id,
            payload={
                "reason": reason,
                **{key: value for key, value in payload.items() if key != "confirmation"},
            },
        )
        if existing is not None:
            await connection.rollback()
            response_status = int(existing.get("_http_status", 200))
            response_body = {
                key: value for key, value in existing.items() if key != "_http_status"
            }
            return web.json_response(response_body, status=response_status)

        ticket = await _fetch_ticket(ticket_id, connection=connection, for_update=True)
        if ticket is None:
            await connection.rollback()
            raise web.HTTPNotFound(text="ticket_not_found")
        await mutate(connection, ticket, payload, admin_user_id)
        detail = await _ticket_detail_from_connection(connection, ticket_id)
        response_payload = {**_service_envelope(), "data": detail}
        await _complete_command(
            connection,
            idempotency_key=idempotency_key,
            response_payload=response_payload,
        )
        await connection.commit()
    return web.json_response(response_payload)


@internal_user_endpoint
async def assign_ticket_handler(request: web.Request) -> web.Response:
    ticket_id = _parse_ticket_id(request)
    payload = _signed_payload(request)
    _require_confirmation(payload, f"ASSIGN {ticket_id}")

    async def mutate(
        connection: db_backend.Connection,
        _ticket: Mapping[str, Any],
        body: Mapping[str, Any],
        _admin: str,
    ) -> None:
        assignee = str(body.get("assigned_admin_id") or "").strip() or None
        if assignee and len(assignee) > 128:
            raise CommandValidationError("assigned_admin_id is too long")
        await connection.execute(
            """
            UPDATE support_tickets
            SET assigned_admin_id = ?,
                status = CASE WHEN status = 'new' THEN 'in_progress' ELSE status END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (assignee, ticket_id),
        )

    return await _run_ticket_command(request, action="assign", mutate=mutate)


@internal_user_endpoint
async def update_ticket_handler(request: web.Request) -> web.Response:
    ticket_id = _parse_ticket_id(request)
    payload = _signed_payload(request)
    _require_confirmation(payload, f"UPDATE {ticket_id}")

    async def mutate(
        connection: db_backend.Connection,
        _ticket: Mapping[str, Any],
        body: Mapping[str, Any],
        _admin: str,
    ) -> None:
        status_value = str(body.get("status") or "").strip().lower()
        priority = str(body.get("priority") or "").strip().lower()
        if status_value and status_value not in _ALLOWED_STATUSES:
            raise CommandValidationError("unsupported ticket status")
        if priority and priority not in _ALLOWED_PRIORITIES:
            raise CommandValidationError("unsupported ticket priority")

        payment_present = "linked_payment_id" in body
        operation_present = "linked_operation_id" in body
        payment_id = (
            _parse_optional_int(body.get("linked_payment_id"), field="linked_payment_id")
            if payment_present
            else None
        )
        operation_id = (
            _parse_optional_int(body.get("linked_operation_id"), field="linked_operation_id")
            if operation_present
            else None
        )
        if payment_id is not None:
            cursor = await connection.execute(
                "SELECT id FROM transactions WHERE id = ?",
                (payment_id,),
            )
            if not await cursor.fetchone():
                raise CommandValidationError("linked payment does not exist")
        if operation_id is not None:
            cursor = await connection.execute(
                "SELECT id FROM generation_tasks WHERE id = ?",
                (operation_id,),
            )
            if not await cursor.fetchone():
                raise CommandValidationError("linked operation does not exist")

        await connection.execute(
            """
            UPDATE support_tickets
            SET status = COALESCE(NULLIF(?, ''), status),
                priority = COALESCE(NULLIF(?, ''), priority),
                linked_payment_id = CASE WHEN ? THEN ? ELSE linked_payment_id END,
                linked_operation_id = CASE WHEN ? THEN ? ELSE linked_operation_id END,
                closed_at = CASE
                    WHEN ? = 'closed' THEN CURRENT_TIMESTAMP
                    WHEN ? <> '' AND ? <> 'closed' THEN NULL
                    ELSE closed_at
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                status_value,
                priority,
                payment_present,
                payment_id,
                operation_present,
                operation_id,
                status_value,
                status_value,
                status_value,
                ticket_id,
            ),
        )

    return await _run_ticket_command(request, action="update", mutate=mutate)


@internal_user_endpoint
async def reply_ticket_handler(request: web.Request) -> web.Response:
    ticket_id = _parse_ticket_id(request)
    payload = _signed_payload(request)
    _require_confirmation(payload, f"REPLY {ticket_id}")

    async def mutate(
        connection: db_backend.Connection,
        ticket: Mapping[str, Any],
        body: Mapping[str, Any],
        admin_user_id: str,
    ) -> None:
        text = str(body.get("body") or "").strip()
        if not 1 <= len(text) <= 4000:
            raise CommandValidationError(
                "reply body must contain between 1 and 4000 characters"
            )
        if ticket["status"] == "closed":
            raise CommandConflictError("closed ticket cannot receive a reply")
        connection.row_factory = db_backend.Row
        cursor = await connection.execute(
            """
            INSERT INTO support_messages (
                ticket_id, sender_type, sender_id, body, delivery_status
            ) VALUES (?, 'admin', ?, ?, 'queued')
            RETURNING id
            """,
            (ticket_id, admin_user_id, text),
        )
        message = await cursor.fetchone()
        if not message:
            raise RuntimeError("support reply was not created")
        await connection.execute(
            """
            INSERT INTO support_outbox (
                ticket_id, message_id, telegram_id, status
            ) VALUES (?, ?, ?, 'queued')
            """,
            (ticket_id, int(message["id"]), int(ticket["telegram_id"])),
        )
        await connection.execute(
            """
            UPDATE support_tickets
            SET status = 'waiting_user', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (ticket_id,),
        )

    return await _run_ticket_command(request, action="reply", mutate=mutate)
