from __future__ import annotations

import logging

from aiohttp import web

from bot import db as db_backend
from bot import internal_admin_operations as operations
from bot.internal_admin_operation_replay import run_replay
from bot.internal_admin_user_commands import (
    CommandConflictError,
    CommandValidationError,
    _command_headers,
    _complete_command,
    _parse_command_payload,
    _reserve_command,
    internal_user_endpoint,
)

logger = logging.getLogger(__name__)


def _provider_accepted(child: object) -> bool:
    try:
        status = str(child["status"] or "").strip().lower()  # type: ignore[index]
        task_id = str(child["task_id"] or "").strip()  # type: ignore[index]
    except (KeyError, TypeError):
        return False
    return bool(task_id) and status not in {"failed", "error", "rejected"}


@internal_user_endpoint
async def replay_operation_handler(request: web.Request) -> web.Response:
    """Replay an operation and persist a stable idempotent outcome."""

    operation_id = operations._parse_operation_id(request)
    payload = _parse_command_payload(request, require_amount=False)
    raw_payload = operations._parse_request_data(request.get("internal_body", b""))
    operations._require_confirmation(
        raw_payload.get("confirmation"),
        f"REPLAY {operation_id}",
    )
    idempotency_key, admin_user_id, request_id = _command_headers(request)

    source = await operations._fetch_operation(operation_id)
    if source is None:
        raise web.HTTPNotFound(text="operation_not_found")

    async with db_backend.connect() as connection:
        existing = await _reserve_command(
            connection,
            idempotency_key=idempotency_key,
            action="operation.replay",
            user_id=operation_id,
            admin_user_id=admin_user_id,
            request_id=request_id,
            payload=payload,
        )
        if existing is not None:
            await connection.rollback()
            return operations._command_response(existing)
        await connection.commit()

    try:
        child = await run_replay(
            source,
            admin_user_id=admin_user_id,
            request_id=request_id,
            idempotency_key=idempotency_key,
            reason=str(payload["reason"]),
            comment=payload.get("comment"),
        )
        if not _provider_accepted(child):
            raise CommandConflictError("provider rejected the replay operation")

        response_payload = {
            **operations._service_envelope(),
            "data": operations._operation_from_row(child, include_details=True),
        }
        async with db_backend.connect() as connection:
            await operations._record_event(
                connection,
                operation_id=operation_id,
                event_type="operation.replay",
                status="success",
                actor_id=admin_user_id,
                request_id=request_id,
                idempotency_key=idempotency_key,
                related_operation_id=int(child["id"]),
                details={
                    "reason": payload["reason"],
                    "comment": payload.get("comment"),
                },
            )
            await operations._record_event(
                connection,
                operation_id=int(child["id"]),
                event_type="operation.replayed_from",
                status="success",
                actor_id=admin_user_id,
                request_id=request_id,
                idempotency_key=idempotency_key,
                related_operation_id=operation_id,
                details={},
            )
            await _complete_command(
                connection,
                idempotency_key=idempotency_key,
                response_payload=response_payload,
            )
            await connection.commit()
        return web.json_response(response_payload)
    except Exception as exc:
        logger.exception(
            "Administrative operation replay failed: operation_id=%s",
            operation_id,
        )
        failure_payload = {
            **operations._service_envelope(),
            "error": "operation_replay_failed",
            "detail": str(exc)[:500],
            "_http_status": (
                409
                if isinstance(exc, (CommandValidationError, CommandConflictError))
                else 502
            ),
        }
        async with db_backend.connect() as connection:
            await operations._record_event(
                connection,
                operation_id=operation_id,
                event_type="operation.replay",
                status="failed",
                actor_id=admin_user_id,
                request_id=request_id,
                idempotency_key=idempotency_key,
                details={
                    "reason": payload["reason"],
                    "comment": payload.get("comment"),
                    "error": type(exc).__name__,
                },
            )
            await _complete_command(
                connection,
                idempotency_key=idempotency_key,
                response_payload=failure_payload,
            )
            await connection.commit()
        return operations._command_response(failure_payload)
