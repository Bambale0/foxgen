from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from foxgen.core.errors import ErrorCode, SubmissionError


@dataclass(frozen=True, slots=True)
class ReconciliationFinding:
    code: str
    severity: str
    generation_id: UUID | None
    resource_id: UUID | None
    status: str | None
    details: dict[str, object]


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    findings: tuple[ReconciliationFinding, ...]
    fixed_codes: tuple[str, ...]


class DeliveryResolutionAction(StrEnum):
    MARK_SENT = "mark_sent"
    RETRY = "retry"
    FAILED = "failed"


class ReconciliationRepository(Protocol):
    async def list_reconciliation_findings(
        self,
        *,
        limit: int,
    ) -> tuple[ReconciliationFinding, ...]: ...

    async def apply_safe_reconciliation(
        self,
        *,
        limit: int,
    ) -> tuple[str, ...]: ...

    async def resolve_delivery_unknown_sent(
        self,
        *,
        generation_id: UUID,
        message_ids: list[int],
        reason: str,
    ) -> None: ...

    async def requeue_delivery_unknown(
        self,
        *,
        generation_id: UUID,
        idempotency_key: str,
        reason: str,
    ) -> None: ...

    async def fail_delivery_unknown(
        self,
        *,
        generation_id: UUID,
        reason: str,
    ) -> None: ...


class ReconciliationService:
    def __init__(self, repository: ReconciliationRepository) -> None:
        self._repository = repository

    async def report(self, *, limit: int) -> tuple[ReconciliationFinding, ...]:
        _validate_limit(limit)
        return await self._repository.list_reconciliation_findings(limit=limit)

    async def run_safe(self, *, limit: int) -> ReconciliationResult:
        _validate_limit(limit)
        fixed_codes = await self._repository.apply_safe_reconciliation(limit=limit)
        findings = await self._repository.list_reconciliation_findings(limit=limit)
        return ReconciliationResult(findings=findings, fixed_codes=fixed_codes)

    async def resolve_delivery_unknown(
        self,
        *,
        generation_id: UUID,
        action: DeliveryResolutionAction,
        message_ids: list[int] | None,
        confirmed_not_sent: bool,
        idempotency_key: str | None,
        reason: str,
    ) -> None:
        normalized_reason = reason.strip()[:128]
        if len(normalized_reason) < 3:
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "Укажите проверяемую причину операторского решения.",
            )

        if action == DeliveryResolutionAction.MARK_SENT:
            normalized_ids = [item for item in (message_ids or []) if item > 0]
            if not normalized_ids:
                raise SubmissionError(
                    ErrorCode.VALIDATION,
                    "Для mark_sent нужны подтверждённые Telegram message ID.",
                )
            await self._repository.resolve_delivery_unknown_sent(
                generation_id=generation_id,
                message_ids=normalized_ids,
                reason=normalized_reason,
            )
            return

        if action == DeliveryResolutionAction.RETRY:
            if not confirmed_not_sent:
                raise SubmissionError(
                    ErrorCode.VALIDATION,
                    "Повторная доставка требует подтверждения, что сообщение не было отправлено.",
                )
            key = (idempotency_key or "").strip()
            if not 8 <= len(key) <= 128:
                raise SubmissionError(
                    ErrorCode.VALIDATION,
                    "Для повторной доставки нужен idempotency_key длиной 8–128 символов.",
                )
            await self._repository.requeue_delivery_unknown(
                generation_id=generation_id,
                idempotency_key=key,
                reason=normalized_reason,
            )
            return

        await self._repository.fail_delivery_unknown(
            generation_id=generation_id,
            reason=normalized_reason,
        )


def _validate_limit(limit: int) -> None:
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
