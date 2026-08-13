from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from foxgen.admin.errors import AdminConflictError, AdminError
from foxgen.admin.policy import AdminContext
from foxgen.admin.security import redact_secrets
from foxgen.infra.admin_models import AdminAuditEvent, AdminCommand
from foxgen.infra.database import Database


AdminOperation = Callable[[AsyncSession], Awaitable[dict[str, object]]]


@dataclass(frozen=True, slots=True)
class CommandResult:
    payload: dict[str, object]
    replayed: bool


def request_hash(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class AdminCommandExecutor:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def execute(
        self,
        *,
        context: AdminContext,
        action: str,
        target_id: str | None,
        idempotency_key: str,
        request_payload: dict[str, object],
        operation: AdminOperation,
    ) -> CommandResult:
        if not idempotency_key or len(idempotency_key) > 160:
            raise AdminError(
                "invalid_idempotency_key",
                "Idempotency-Key must contain 1-160 characters",
                status_code=422,
            )
        fingerprint = request_hash(request_payload)
        lock_key = f"admin:{context.user_id}:{action}:{idempotency_key}"

        stored_error: AdminError | None = None
        result: dict[str, object] = {}
        replayed = False

        async with self._database.session() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": lock_key},
                )
                existing = await session.scalar(
                    select(AdminCommand).where(
                        AdminCommand.admin_user_id == context.user_id,
                        AdminCommand.action == action,
                        AdminCommand.idempotency_key == idempotency_key,
                    )
                )
                if existing is not None:
                    if existing.request_hash != fingerprint:
                        raise AdminConflictError(
                            "Idempotency-Key was already used with a different request",
                            details={"action": action, "target_id": target_id},
                        )
                    if existing.status == "reserved":
                        raise AdminConflictError(
                            "The same admin command is still in progress",
                            details={"action": action, "request_id": existing.request_id},
                        )
                    replayed = True
                    stored_payload = existing.response_payload or {}
                    if existing.status == "failed":
                        stored_error = AdminError(
                            existing.error_code or "admin_command_failed",
                            str(stored_payload.get("message", "Admin command failed")),
                            status_code=int(stored_payload.get("status_code", 400)),
                            details=_dict_object(stored_payload.get("details")),
                        )
                    else:
                        result = _dict_object(stored_payload)
                else:
                    command = AdminCommand(
                        idempotency_key=idempotency_key,
                        admin_user_id=context.user_id,
                        request_id=context.request_id,
                        action=action,
                        target_id=target_id,
                        request_hash=fingerprint,
                        request_payload=_dict_object(redact_secrets(request_payload)),
                        response_payload=None,
                        status="reserved",
                    )
                    session.add(command)
                    await session.flush()

                    try:
                        async with session.begin_nested():
                            result = await operation(session)
                    except AdminError as exc:
                        stored_error = exc
                        command.status = "failed"
                        command.error_code = exc.code
                        command.response_payload = {
                            "message": exc.message,
                            "status_code": exc.status_code,
                            "details": _dict_object(redact_secrets(exc.details)),
                        }
                        self._audit(
                            session,
                            context=context,
                            action=action,
                            target_id=target_id,
                            outcome="failed",
                            payload=command.response_payload,
                        )
                    except Exception as exc:
                        stored_error = AdminError(
                            "admin_internal_error",
                            "Admin command failed safely",
                            status_code=500,
                        )
                        command.status = "failed"
                        command.error_code = "admin_internal_error"
                        command.response_payload = {
                            "message": "Admin command failed safely",
                            "status_code": 500,
                            "details": {"exception_type": type(exc).__name__},
                        }
                        self._audit(
                            session,
                            context=context,
                            action=action,
                            target_id=target_id,
                            outcome="failed",
                            payload=command.response_payload,
                        )
                    else:
                        command.status = "succeeded"
                        command.response_payload = _dict_object(redact_secrets(result))
                        self._audit(
                            session,
                            context=context,
                            action=action,
                            target_id=target_id,
                            outcome="succeeded",
                            payload=command.response_payload,
                        )

        if stored_error is not None:
            raise stored_error
        return CommandResult(payload=result, replayed=replayed)

    async def audit_read(
        self,
        *,
        context: AdminContext,
        action: str,
        target_id: str | None,
        payload: dict[str, object] | None = None,
    ) -> None:
        async with self._database.session() as session:
            async with session.begin():
                self._audit(
                    session,
                    context=context,
                    action=action,
                    target_id=target_id,
                    outcome="read",
                    payload=_dict_object(redact_secrets(payload or {})),
                )

    @staticmethod
    def _audit(
        session: AsyncSession,
        *,
        context: AdminContext,
        action: str,
        target_id: str | None,
        outcome: str,
        payload: dict[str, object],
    ) -> None:
        session.add(
            AdminAuditEvent(
                admin_user_id=context.user_id,
                request_id=context.request_id,
                action=action,
                target_id=target_id,
                outcome=outcome,
                payload=payload,
            )
        )


def _dict_object(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    return {}
