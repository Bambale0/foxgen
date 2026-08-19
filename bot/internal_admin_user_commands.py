from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from functools import wraps
from typing import Any, Awaitable, Callable

from aiohttp import web

from bot import db as db_backend
from bot import internal_admin_api as base_api

logger = logging.getLogger(__name__)

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]
MAX_REASON_LENGTH = 500
MAX_COMMENT_LENGTH = 1000
MAX_BALANCE_ADJUSTMENT = 1_000_000


class CommandValidationError(ValueError):
    pass


class CommandConflictError(RuntimeError):
    pass


def _json_value(value: Any) -> Any:
    return base_api._json_value(value)


def _row_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _json_value(row[key]) for key in row.keys()}


def _service_envelope() -> dict[str, Any]:
    return base_api._service_envelope()


async def _authorize_request(request: web.Request) -> tuple[bytes, web.Response | None]:
    if request.method not in {"GET", "POST"}:
        return b"", web.json_response({"error": "method_not_allowed"}, status=405)
    if not base_api.INTERNAL_API_SECRET:
        logger.error("Internal admin user API rejected request: secret is not configured")
        return b"", web.json_response({"error": "service_unavailable"}, status=503)

    peer_ip = base_api._request_peer_ip(request)
    if not base_api.is_allowed_internal_peer(peer_ip):
        logger.warning("Internal admin user API rejected peer: %s", peer_ip or "unknown")
        return b"", web.json_response({"error": "forbidden"}, status=403)

    body = await request.read()
    if not base_api.verify_internal_signature(
        secret=base_api.INTERNAL_API_SECRET,
        timestamp=request.headers.get("X-Internal-Timestamp", ""),
        method=request.method,
        request_path=request.raw_path,
        signature=request.headers.get("X-Internal-Signature", ""),
        body=body,
    ):
        logger.warning("Internal admin user API rejected invalid HMAC from %s", peer_ip)
        return body, web.json_response({"error": "unauthorized"}, status=401)

    if request.method == "POST":
        for header in ("Idempotency-Key", "X-Admin-User-Id", "X-Request-Id"):
            value = request.headers.get(header, "").strip()
            if not 8 <= len(value) <= 128:
                return body, web.json_response({"error": f"invalid_{header.lower()}"}, status=400)
    return body, None


def internal_user_endpoint(handler: Handler) -> Handler:
    @wraps(handler)
    async def wrapped(request: web.Request) -> web.StreamResponse:
        body, authorization_error = await _authorize_request(request)
        if authorization_error is not None:
            return authorization_error
        request["internal_body"] = body
        try:
            return await handler(request)
        except base_api.InvalidCursorError:
            return web.json_response({"error": "invalid_cursor"}, status=400)
        except CommandValidationError as exc:
            return web.json_response({"error": "invalid_command", "detail": str(exc)}, status=400)
        except CommandConflictError as exc:
            return web.json_response({"error": "command_conflict", "detail": str(exc)}, status=409)
        except web.HTTPException:
            raise
        except Exception:
            logger.exception("Internal admin user endpoint failed: %s", request.path)
            return web.json_response({"error": "internal_error"}, status=500)

    return wrapped


def _parse_bool_filter(value: str | None) -> bool | None:
    if value is None or value == "":
        return None
    normalized = value.strip().lower()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    raise CommandValidationError("is_banned must be true or false")


def _parse_user_id(request: web.Request) -> int:
    raw_value = request.match_info.get("user_id", "")
    try:
        user_id = int(raw_value)
    except ValueError as exc:
        raise CommandValidationError("user id must be an integer") from exc
    if user_id <= 0:
        raise CommandValidationError("user id must be positive")
    return user_id


def _parse_command_payload(request: web.Request, *, require_amount: bool) -> dict[str, Any]:
    body = request.get("internal_body", b"")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CommandValidationError("request body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise CommandValidationError("request body must be an object")

    reason = str(payload.get("reason") or "").strip()
    if not 5 <= len(reason) <= MAX_REASON_LENGTH:
        raise CommandValidationError("reason must contain between 5 and 500 characters")
    comment_value = payload.get("comment")
    comment = None if comment_value is None else str(comment_value).strip() or None
    if comment and len(comment) > MAX_COMMENT_LENGTH:
        raise CommandValidationError("comment is too long")

    result: dict[str, Any] = {"reason": reason, "comment": comment}
    if require_amount:
        amount = payload.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise CommandValidationError("amount must be an integer")
        if amount == 0 or abs(amount) > MAX_BALANCE_ADJUSTMENT:
            raise CommandValidationError("amount is outside the allowed range")
        result["amount"] = amount
    return result


def _command_headers(request: web.Request) -> tuple[str, str, str]:
    return (
        request.headers["Idempotency-Key"].strip(),
        request.headers["X-Admin-User-Id"].strip(),
        request.headers["X-Request-Id"].strip(),
    )


async def _ensure_command_table(connection: db_backend.Connection) -> None:
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS internal_admin_commands (
            id BIGSERIAL PRIMARY KEY,
            idempotency_key TEXT UNIQUE NOT NULL,
            action TEXT NOT NULL,
            target_user_id BIGINT NOT NULL,
            admin_user_id TEXT NOT NULL,
            request_id TEXT NOT NULL,
            request_payload JSONB NOT NULL,
            response_payload JSONB,
            status TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        )
        """
    )
    await connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_internal_admin_commands_request_id ON internal_admin_commands(request_id)"
    )


async def _reserve_command(
    connection: db_backend.Connection,
    *,
    idempotency_key: str,
    action: str,
    user_id: int,
    admin_user_id: str,
    request_id: str,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    await _ensure_command_table(connection)
    cursor = await connection.execute(
        """
        INSERT INTO internal_admin_commands (
            idempotency_key, action, target_user_id, admin_user_id,
            request_id, request_payload, status
        ) VALUES (?, ?, ?, ?, ?, CAST(? AS JSONB), 'processing')
        ON CONFLICT (idempotency_key) DO NOTHING
        """,
        (
            idempotency_key,
            action,
            user_id,
            admin_user_id,
            request_id,
            json.dumps(payload, ensure_ascii=False),
        ),
    )
    if cursor.rowcount == 1:
        return None

    existing_cursor = await connection.execute(
        """
        SELECT action, target_user_id, status, response_payload
        FROM internal_admin_commands
        WHERE idempotency_key = ?
        """,
        (idempotency_key,),
    )
    existing = await existing_cursor.fetchone()
    if not existing:
        raise CommandConflictError("idempotency reservation was not found")
    if existing["action"] != action or int(existing["target_user_id"]) != user_id:
        raise CommandConflictError("idempotency key was already used for another command")
    if existing["status"] == "completed" and existing["response_payload"]:
        response_payload = existing["response_payload"]
        if isinstance(response_payload, str):
            response_payload = json.loads(response_payload)
        if isinstance(response_payload, dict):
            return response_payload
    raise CommandConflictError("command with this idempotency key is still processing")


async def _complete_command(
    connection: db_backend.Connection,
    *,
    idempotency_key: str,
    response_payload: dict[str, Any],
) -> None:
    await connection.execute(
        """
        UPDATE internal_admin_commands
        SET status = 'completed',
            response_payload = CAST(? AS JSONB),
            completed_at = CURRENT_TIMESTAMP
        WHERE idempotency_key = ?
        """,
        (json.dumps(response_payload, ensure_ascii=False), idempotency_key),
    )


async def _fetch_user_for_update(
    connection: db_backend.Connection,
    user_id: int,
) -> Mapping[str, Any] | None:
    connection.row_factory = db_backend.Row
    cursor = await connection.execute(
        """
        SELECT
            id, telegram_id, username, first_name, last_name, credits,
            has_paid, is_banned, created_at, updated_at
        FROM users
        WHERE id = ?
        FOR UPDATE
        """,
        (user_id,),
    )
    return await cursor.fetchone()


def _normalize_user(row: Mapping[str, Any]) -> dict[str, Any]:
    item = _row_dict(row)
    item["has_paid"] = bool(item.get("has_paid"))
    item["is_banned"] = bool(item.get("is_banned"))
    return item


@internal_user_endpoint
async def search_users_handler(request: web.Request) -> web.Response:
    if request.method != "GET":
        return web.json_response({"error": "method_not_allowed"}, status=405)
    limit = base_api._parse_page_limit(request)
    cursor_id = base_api.decode_cursor(request.query.get("cursor"))
    search_query = (request.query.get("query") or "").strip()
    if len(search_query) > 120:
        raise CommandValidationError("query is too long")
    is_banned = _parse_bool_filter(request.query.get("is_banned"))

    clauses: list[str] = []
    parameters: list[Any] = []
    if cursor_id is not None:
        clauses.append("id < ?")
        parameters.append(cursor_id)
    if search_query:
        pattern = f"%{search_query.lower()}%"
        clauses.append(
            "(" 
            "CAST(id AS TEXT) = ? OR CAST(telegram_id AS TEXT) = ? OR "
            "LOWER(COALESCE(username, '')) LIKE ? OR "
            "LOWER(COALESCE(first_name, '')) LIKE ? OR "
            "LOWER(COALESCE(last_name, '')) LIKE ?"
            ")"
        )
        parameters.extend([search_query, search_query, pattern, pattern, pattern])
    if is_banned is not None:
        clauses.append("COALESCE(is_banned, 0) = ?")
        parameters.append(1 if is_banned else 0)

    where_sql = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    parameters.append(limit + 1)
    rows = await base_api._fetch_all(
        f"""
        SELECT
            id, telegram_id, username, first_name, last_name, credits,
            has_paid, is_banned, created_at, updated_at
        FROM users
        {where_sql}
        ORDER BY id DESC
        LIMIT ?
        """,
        tuple(parameters),
    )
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    items = [_normalize_user(row) for row in page_rows]
    next_cursor = base_api.encode_cursor(int(page_rows[-1]["id"])) if has_more and page_rows else None
    return web.json_response({**_service_envelope(), "items": items, "next_cursor": next_cursor})


async def _change_block_state(request: web.Request, *, blocked: bool) -> web.Response:
    user_id = _parse_user_id(request)
    payload = _parse_command_payload(request, require_amount=False)
    idempotency_key, admin_user_id, request_id = _command_headers(request)
    action = "user.block" if blocked else "user.unblock"

    async with db_backend.connect() as connection:
        existing = await _reserve_command(
            connection,
            idempotency_key=idempotency_key,
            action=action,
            user_id=user_id,
            admin_user_id=admin_user_id,
            request_id=request_id,
            payload=payload,
        )
        if existing is not None:
            await connection.rollback()
            return web.json_response(existing)

        row = await _fetch_user_for_update(connection, user_id)
        if row is None:
            await connection.rollback()
            raise web.HTTPNotFound(text="user_not_found")
        await connection.execute(
            """
            UPDATE users
            SET is_banned = ?,
                banned_at = CASE WHEN ? = 1 THEN CURRENT_TIMESTAMP ELSE NULL END,
                banned_by_telegram_id = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (1 if blocked else 0, 1 if blocked else 0, user_id),
        )
        updated = await _fetch_user_for_update(connection, user_id)
        assert updated is not None
        response_payload = {**_service_envelope(), "data": _normalize_user(updated)}
        await _complete_command(
            connection,
            idempotency_key=idempotency_key,
            response_payload=response_payload,
        )
        await connection.commit()
    return web.json_response(response_payload)


@internal_user_endpoint
async def block_user_handler(request: web.Request) -> web.Response:
    return await _change_block_state(request, blocked=True)


@internal_user_endpoint
async def unblock_user_handler(request: web.Request) -> web.Response:
    return await _change_block_state(request, blocked=False)


@internal_user_endpoint
async def adjust_user_balance_handler(request: web.Request) -> web.Response:
    user_id = _parse_user_id(request)
    payload = _parse_command_payload(request, require_amount=True)
    amount = int(payload["amount"])
    idempotency_key, admin_user_id, request_id = _command_headers(request)

    async with db_backend.connect() as connection:
        existing = await _reserve_command(
            connection,
            idempotency_key=idempotency_key,
            action="user.balance.adjust",
            user_id=user_id,
            admin_user_id=admin_user_id,
            request_id=request_id,
            payload=payload,
        )
        if existing is not None:
            await connection.rollback()
            return web.json_response(existing)

        row = await _fetch_user_for_update(connection, user_id)
        if row is None:
            await connection.rollback()
            raise web.HTTPNotFound(text="user_not_found")
        current_credits = int(row["credits"] or 0)
        if current_credits + amount < 0:
            await connection.rollback()
            raise CommandConflictError("balance adjustment would make credits negative")

        await connection.execute(
            """
            UPDATE users
            SET credits = credits + ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (amount, user_id),
        )
        updated = await _fetch_user_for_update(connection, user_id)
        assert updated is not None
        response_payload = {**_service_envelope(), "data": _normalize_user(updated)}
        await _complete_command(
            connection,
            idempotency_key=idempotency_key,
            response_payload=response_payload,
        )
        await connection.commit()
    return web.json_response(response_payload)
