from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from aiohttp import web

from bot import db as db_backend
from bot import internal_admin_api as base_api
from bot.handlers.payments import _complete_transaction, _resolve_payment_state
from bot.internal_admin_user_commands import (
    CommandConflictError,
    CommandValidationError,
    _command_headers,
    _complete_command,
    _parse_command_payload,
    _reserve_command,
    internal_user_endpoint,
)
from bot.payment_utils import TELEGRAM_STARS_PROVIDER

_ALLOWED_STATUSES = {"pending", "processing", "completed", "failed"}
_ALLOWED_PROVIDERS = {
    "cryptobot",
    "cryptopay",
    "yookassa",
    "lava",
    TELEGRAM_STARS_PROVIDER,
}


def _service_envelope() -> dict[str, Any]:
    return base_api._service_envelope()


def _json_value(value: Any) -> Any:
    return base_api._json_value(value)


def _parse_payment_id(request: web.Request) -> int:
    raw_value = request.match_info.get("payment_id", "")
    try:
        payment_id = int(raw_value)
    except ValueError as exc:
        raise CommandValidationError("payment id must be an integer") from exc
    if payment_id <= 0:
        raise CommandValidationError("payment id must be positive")
    return payment_id


def _parse_positive_int(value: str | None, *, field: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise CommandValidationError(f"{field} must be an integer") from exc
    if parsed <= 0:
        raise CommandValidationError(f"{field} must be positive")
    return parsed


def _parse_created_at(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _payment_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    keys = set(row.keys())
    return {
        "id": int(row["id"]),
        "order_id": str(row["order_id"]),
        "payment_id": str(row["payment_id"]) if row["payment_id"] else None,
        "provider": str(row["provider"] or "cryptobot"),
        "status": str(row["status"] or "pending"),
        "user_id": int(row["user_id"]),
        "telegram_id": int(row["telegram_id"]) if row["telegram_id"] else None,
        "username": row["username"] if "username" in keys else None,
        "first_name": row["first_name"] if "first_name" in keys else None,
        "last_name": row["last_name"] if "last_name" in keys else None,
        "credits": int(row["credits"] or 0),
        "amount_rub": float(row["amount_rub"] or 0),
        "currency": "XTR" if str(row["provider"]) == TELEGRAM_STARS_PROVIDER else "RUB",
        "promo_code": row["promo_code"] if "promo_code" in keys else None,
        "promo_bonus_credits": int(row["promo_bonus_credits"] or 0)
        if "promo_bonus_credits" in keys
        else 0,
        "created_at": _json_value(row["created_at"]),
        "user_balance": float(row["user_balance"] or 0)
        if "user_balance" in keys
        else None,
    }


_PAYMENT_SELECT = """
    SELECT
        t.id,
        t.order_id,
        t.payment_id,
        t.provider,
        t.status,
        t.user_id,
        t.credits,
        t.amount_rub,
        t.promo_code,
        t.promo_bonus_credits,
        t.created_at,
        u.telegram_id,
        u.username,
        u.first_name,
        u.last_name,
        u.credits AS user_balance
    FROM transactions t
    JOIN users u ON u.id = t.user_id
"""


async def _fetch_payment(payment_id: int) -> Mapping[str, Any] | None:
    rows = await base_api._fetch_all(
        f"{_PAYMENT_SELECT} WHERE t.id = ? LIMIT 1",
        (payment_id,),
    )
    return rows[0] if rows else None


async def _record_payment_event(
    connection: db_backend.Connection,
    *,
    transaction_id: int,
    event_type: str,
    status: str | None,
    provider_status: str | None,
    source: str,
    actor_id: str | None,
    request_id: str | None,
    idempotency_key: str | None,
    details: Mapping[str, object] | None = None,
) -> None:
    await connection.execute(
        """
        INSERT INTO internal_admin_payment_events (
            transaction_id, event_type, status, provider_status, source,
            actor_type, actor_id, request_id, idempotency_key, details
        ) VALUES (?, ?, ?, ?, ?, 'admin', ?, ?, ?, CAST(? AS JSONB))
        """,
        (
            transaction_id,
            event_type,
            status,
            provider_status,
            source,
            actor_id,
            request_id,
            idempotency_key,
            json.dumps(dict(details or {}), ensure_ascii=False),
        ),
    )


def _require_confirmation(actual: Any, expected: str) -> None:
    if str(actual or "") != expected:
        raise CommandConflictError(f"confirmation must equal {expected}")


def _command_response(payload: dict[str, Any]) -> web.Response:
    response_status = int(payload.get("_http_status", 200))
    body = {key: value for key, value in payload.items() if key != "_http_status"}
    return web.json_response(body, status=response_status)


def _external_state_public(state: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "provider": str(state.get("provider") or ""),
        "provider_status": str(state.get("status") or "unknown"),
        "paid": bool(state.get("paid")),
        "failed": bool(state.get("failed")),
        "error": str(state.get("error"))[:500] if state.get("error") else None,
    }


async def _resolve_external_state(payment: Mapping[str, Any]) -> dict[str, Any]:
    provider = str(payment["provider"] or "cryptobot").lower()
    if provider == TELEGRAM_STARS_PROVIDER:
        return {
            "provider": provider,
            "status": "local_only",
            "paid": str(payment["status"]) == "completed",
            "failed": str(payment["status"]) == "failed",
        }

    transaction = SimpleNamespace(
        provider=provider,
        payment_id=payment["payment_id"],
        order_id=payment["order_id"],
        created_at=_parse_created_at(payment["created_at"]),
    )
    return await _resolve_payment_state(transaction)


@internal_user_endpoint
async def payments_handler(request: web.Request) -> web.Response:
    if request.method != "GET":
        return web.json_response({"error": "method_not_allowed"}, status=405)

    limit = base_api._parse_page_limit(request)
    cursor_id = base_api.decode_cursor(request.query.get("cursor"))
    query = (request.query.get("query") or "").strip()
    if len(query) > 160:
        raise CommandValidationError("query is too long")
    status_filter = (request.query.get("status") or "").strip().lower()
    if status_filter and status_filter not in _ALLOWED_STATUSES:
        raise CommandValidationError("unsupported payment status")
    provider_filter = (request.query.get("provider") or "").strip().lower()
    if provider_filter and provider_filter not in _ALLOWED_PROVIDERS:
        raise CommandValidationError("unsupported payment provider")
    user_id = _parse_positive_int(request.query.get("user_id"), field="user_id")

    clauses: list[str] = []
    parameters: list[Any] = []
    if cursor_id is not None:
        clauses.append("t.id < ?")
        parameters.append(cursor_id)
    if query:
        pattern = f"%{query.lower()}%"
        clauses.append(
            "(CAST(t.id AS TEXT) = ? OR LOWER(t.order_id) LIKE ? "
            "OR LOWER(COALESCE(t.payment_id, '')) LIKE ? "
            "OR CAST(u.telegram_id AS TEXT) = ? "
            "OR LOWER(COALESCE(u.username, '')) LIKE ?)"
        )
        parameters.extend([query, pattern, pattern, query, pattern])
    if status_filter:
        clauses.append("LOWER(t.status) = ?")
        parameters.append(status_filter)
    if provider_filter:
        clauses.append("LOWER(t.provider) = ?")
        parameters.append(provider_filter)
    if user_id is not None:
        clauses.append("t.user_id = ?")
        parameters.append(user_id)

    where_sql = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    parameters.append(limit + 1)
    rows = await base_api._fetch_all(
        f"{_PAYMENT_SELECT}{where_sql} ORDER BY t.id DESC LIMIT ?",
        tuple(parameters),
    )
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    items = [_payment_from_row(row) for row in page_rows]
    next_cursor = (
        base_api.encode_cursor(int(page_rows[-1]["id"]))
        if has_more and page_rows
        else None
    )
    return web.json_response(
        {**_service_envelope(), "items": items, "next_cursor": next_cursor}
    )


@internal_user_endpoint
async def payment_detail_handler(request: web.Request) -> web.Response:
    payment_id = _parse_payment_id(request)
    payment = await _fetch_payment(payment_id)
    if payment is None:
        raise web.HTTPNotFound(text="payment_not_found")

    events = await base_api._fetch_all(
        """
        SELECT
            id, event_type, status, provider_status, source, actor_type,
            actor_id, request_id, idempotency_key, details, created_at
        FROM internal_admin_payment_events
        WHERE transaction_id = ?
        ORDER BY created_at ASC, id ASC
        """,
        (payment_id,),
    )
    normalized_events: list[dict[str, Any]] = [
        {
            "id": f"synthetic-created-{payment_id}",
            "event_type": "transaction.snapshot",
            "status": payment["status"],
            "provider_status": None,
            "source": "historical_snapshot",
            "actor_type": "system",
            "actor_id": None,
            "request_id": None,
            "details": {
                "order_id": payment["order_id"],
                "provider": payment["provider"],
                "credits": payment["credits"],
                "amount_rub": payment["amount_rub"],
            },
            "created_at": _json_value(payment["created_at"]),
        }
    ]
    for event in events:
        details = event["details"]
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except json.JSONDecodeError:
                details = {}
        normalized_events.append(
            {
                "id": int(event["id"]),
                "event_type": event["event_type"],
                "status": event["status"],
                "provider_status": event["provider_status"],
                "source": event["source"],
                "actor_type": event["actor_type"],
                "actor_id": event["actor_id"],
                "request_id": event["request_id"],
                "details": details if isinstance(details, dict) else {},
                "created_at": _json_value(event["created_at"]),
            }
        )
    normalized_events.sort(key=lambda event: str(event["created_at"] or ""))
    return web.json_response(
        {
            **_service_envelope(),
            "data": _payment_from_row(payment),
            "events": normalized_events,
        }
    )


async def _finish_command(
    *,
    idempotency_key: str,
    response_payload: dict[str, Any],
    event: dict[str, Any],
) -> None:
    async with db_backend.connect() as connection:
        await _record_payment_event(connection, **event)
        await _complete_command(
            connection,
            idempotency_key=idempotency_key,
            response_payload=response_payload,
        )
        await connection.commit()


@internal_user_endpoint
async def recheck_payment_handler(request: web.Request) -> web.Response:
    payment_id = _parse_payment_id(request)
    payload = _parse_command_payload(request, require_amount=False)
    raw_payload = json.loads(bytes(request.get("internal_body", b"{}")).decode("utf-8"))
    _require_confirmation(raw_payload.get("confirmation"), f"RECHECK {payment_id}")
    idempotency_key, admin_user_id, request_id = _command_headers(request)

    payment = await _fetch_payment(payment_id)
    if payment is None:
        raise web.HTTPNotFound(text="payment_not_found")

    async with db_backend.connect() as connection:
        existing = await _reserve_command(
            connection,
            idempotency_key=idempotency_key,
            action="payment.recheck",
            user_id=payment_id,
            admin_user_id=admin_user_id,
            request_id=request_id,
            payload=payload,
        )
        if existing is not None:
            await connection.rollback()
            return _command_response(existing)
        await connection.commit()

    state = await _resolve_external_state(payment)
    public_state = _external_state_public(state)
    response_payload = {
        **_service_envelope(),
        "data": {
            "payment_id": payment_id,
            "local_status": payment["status"],
            **public_state,
        },
    }
    await _finish_command(
        idempotency_key=idempotency_key,
        response_payload=response_payload,
        event={
            "transaction_id": payment_id,
            "event_type": "provider.rechecked",
            "status": str(payment["status"]),
            "provider_status": public_state["provider_status"],
            "source": "admin_recheck",
            "actor_id": admin_user_id,
            "request_id": request_id,
            "idempotency_key": idempotency_key,
            "details": {
                "reason": payload["reason"],
                "comment": payload.get("comment"),
                "paid": public_state["paid"],
                "failed": public_state["failed"],
                "error": public_state["error"],
            },
        },
    )
    return web.json_response(response_payload)


@internal_user_endpoint
async def reprocess_payment_handler(request: web.Request) -> web.Response:
    payment_id = _parse_payment_id(request)
    payload = _parse_command_payload(request, require_amount=False)
    raw_payload = json.loads(bytes(request.get("internal_body", b"{}")).decode("utf-8"))
    _require_confirmation(raw_payload.get("confirmation"), f"REPROCESS {payment_id}")
    idempotency_key, admin_user_id, request_id = _command_headers(request)

    payment = await _fetch_payment(payment_id)
    if payment is None:
        raise web.HTTPNotFound(text="payment_not_found")

    async with db_backend.connect() as connection:
        existing = await _reserve_command(
            connection,
            idempotency_key=idempotency_key,
            action="payment.reprocess",
            user_id=payment_id,
            admin_user_id=admin_user_id,
            request_id=request_id,
            payload=payload,
        )
        if existing is not None:
            await connection.rollback()
            return _command_response(existing)
        await connection.commit()

    try:
        state = await _resolve_external_state(payment)
        public_state = _external_state_public(state)
        action = "no_change"
        completion: dict[str, Any] | None = None

        if str(payment["status"]) == "completed":
            action = "already_completed"
        elif public_state["provider_status"] in {"lookup_error", "service_disabled"}:
            raise CommandConflictError(
                f"provider status is unavailable: {public_state['provider_status']}"
            )
        elif str(payment["provider"]) == TELEGRAM_STARS_PROVIDER:
            raise CommandConflictError(
                "Telegram Stars pending payments cannot be reconstructed without a successful_payment update"
            )
        elif public_state["paid"]:
            if str(payment["status"]) in {"failed", "processing"}:
                async with db_backend.connect() as connection:
                    await connection.execute(
                        """
                        UPDATE transactions
                        SET status = 'pending'
                        WHERE id = ? AND status IN ('failed', 'processing')
                        """,
                        (payment_id,),
                    )
                    await connection.commit()
            completion = await _complete_transaction(str(payment["order_id"]), bot=None)
            if not completion.get("ok"):
                raise CommandConflictError(
                    f"atomic completion failed: {completion.get('reason') or 'unknown'}"
                )
            action = (
                "already_completed"
                if completion.get("already_completed")
                else "completed"
            )
        elif public_state["failed"]:
            async with db_backend.connect() as connection:
                cursor = await connection.execute(
                    """
                    UPDATE transactions
                    SET status = 'failed'
                    WHERE id = ? AND status IN ('pending', 'processing')
                    """,
                    (payment_id,),
                )
                await connection.commit()
            action = "marked_failed" if cursor.rowcount else "already_failed"
        else:
            action = "still_pending"

        refreshed = await _fetch_payment(payment_id)
        if refreshed is None:
            raise RuntimeError("payment disappeared after reprocessing")
        response_payload = {
            **_service_envelope(),
            "data": {
                "payment": _payment_from_row(refreshed),
                "action": action,
                "provider_state": public_state,
            },
        }
        await _finish_command(
            idempotency_key=idempotency_key,
            response_payload=response_payload,
            event={
                "transaction_id": payment_id,
                "event_type": "payment.reprocessed",
                "status": str(refreshed["status"]),
                "provider_status": public_state["provider_status"],
                "source": "admin_reprocess",
                "actor_id": admin_user_id,
                "request_id": request_id,
                "idempotency_key": idempotency_key,
                "details": {
                    "reason": payload["reason"],
                    "comment": payload.get("comment"),
                    "action": action,
                },
            },
        )
        return web.json_response(response_payload)
    except Exception as exc:
        failure_payload = {
            **_service_envelope(),
            "error": "payment_reprocess_failed",
            "detail": str(exc)[:500],
            "_http_status": 409 if isinstance(exc, CommandConflictError) else 502,
        }
        await _finish_command(
            idempotency_key=idempotency_key,
            response_payload=failure_payload,
            event={
                "transaction_id": payment_id,
                "event_type": "payment.reprocessed",
                "status": str(payment["status"]),
                "provider_status": None,
                "source": "admin_reprocess",
                "actor_id": admin_user_id,
                "request_id": request_id,
                "idempotency_key": idempotency_key,
                "details": {
                    "reason": payload["reason"],
                    "comment": payload.get("comment"),
                    "error": type(exc).__name__,
                },
            },
        )
        return _command_response(failure_payload)
