from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from foxgen.application.lifecycle import GenerationWorkItem
from foxgen.core.errors import ErrorCode, SubmissionError
from foxgen.domain.models import GenerationStatus


class UnknownResolutionAction(StrEnum):
    SUBMITTED = "submitted"
    PROCESSING = "processing"
    RESULT_READY = "result_ready"
    FAILED = "failed"


STUCK_GENERATION_STATUSES: frozenset[GenerationStatus] = frozenset(
    {
        GenerationStatus.SUBMISSION_UNKNOWN,
        GenerationStatus.PROCESSING,
        GenerationStatus.RESULT_READY,
        GenerationStatus.STORING_MEDIA,
        GenerationStatus.DELIVERY_PENDING,
    }
)


class GenerationOperationsRepository(Protocol):
    async def get_owned_generation(
        self,
        *,
        generation_id: UUID,
        user_id: int,
    ) -> GenerationWorkItem: ...

    async def get_generation(self, generation_id: UUID) -> GenerationWorkItem | None: ...

    async def cancel_before_submission(
        self,
        *,
        generation_id: UUID,
        user_id: int,
    ) -> GenerationWorkItem: ...

    async def transition_generation(
        self,
        *,
        generation_id: UUID,
        expected: frozenset[GenerationStatus],
        target: GenerationStatus,
        provider_task_id: str | None = None,
        result_payload: dict[str, object] | None = None,
        error_code: str | None = None,
        failure_stage: str | None = None,
        status_reason: str | None = None,
    ) -> GenerationWorkItem: ...

    async def list_stuck_generations(
        self,
        *,
        statuses: frozenset[GenerationStatus],
        older_than: datetime,
        limit: int,
    ) -> tuple[GenerationWorkItem, ...]: ...


class GenerationOperationsService:
    def __init__(self, repository: GenerationOperationsRepository) -> None:
        self._repository = repository

    async def get_for_user(
        self,
        *,
        generation_id: UUID,
        user_id: int,
    ) -> GenerationWorkItem:
        return await self._repository.get_owned_generation(
            generation_id=generation_id,
            user_id=user_id,
        )

    async def cancel_for_user(
        self,
        *,
        generation_id: UUID,
        user_id: int,
    ) -> GenerationWorkItem:
        return await self._repository.cancel_before_submission(
            generation_id=generation_id,
            user_id=user_id,
        )

    async def resolve_submission_unknown(
        self,
        *,
        generation_id: UUID,
        action: UnknownResolutionAction,
        provider_task_id: str | None,
        result_payload: dict[str, object] | None,
        reason: str,
    ) -> GenerationWorkItem:
        generation = await self._repository.get_generation(generation_id)
        if generation is None:
            raise SubmissionError(ErrorCode.TASK_NOT_FOUND, "Генерация не найдена.")
        if generation.status != GenerationStatus.SUBMISSION_UNKNOWN:
            raise SubmissionError(
                ErrorCode.IDEMPOTENCY_CONFLICT,
                "Ручное разрешение доступно только для submission_unknown.",
                details={"status": generation.status.value},
            )

        normalized_reason = reason.strip()[:128] or "operator_resolution"
        if action == UnknownResolutionAction.FAILED:
            return await self._repository.transition_generation(
                generation_id=generation_id,
                expected=frozenset({GenerationStatus.SUBMISSION_UNKNOWN}),
                target=GenerationStatus.FAILED,
                error_code="manual_submission_resolution_failed",
                failure_stage="submission",
                status_reason=normalized_reason,
            )

        task_id = (provider_task_id or "").strip()
        if not task_id:
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "Для подтверждения принятой задачи нужен provider_task_id.",
            )
        submitted = await self._repository.transition_generation(
            generation_id=generation_id,
            expected=frozenset({GenerationStatus.SUBMISSION_UNKNOWN}),
            target=GenerationStatus.SUBMITTED,
            provider_task_id=task_id,
            status_reason=f"{normalized_reason}:submitted",
        )
        if action == UnknownResolutionAction.SUBMITTED:
            return submitted
        if action == UnknownResolutionAction.PROCESSING:
            return await self._repository.transition_generation(
                generation_id=generation_id,
                expected=frozenset({GenerationStatus.SUBMITTED}),
                target=GenerationStatus.PROCESSING,
                provider_task_id=task_id,
                status_reason=f"{normalized_reason}:processing",
            )
        if result_payload is None:
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "Для result_ready нужен проверенный result_payload провайдера.",
            )
        return await self._repository.transition_generation(
            generation_id=generation_id,
            expected=frozenset({GenerationStatus.SUBMITTED}),
            target=GenerationStatus.RESULT_READY,
            provider_task_id=task_id,
            result_payload=result_payload,
            status_reason=f"{normalized_reason}:result_ready",
        )

    async def list_stuck(
        self,
        *,
        older_than_minutes: int,
        limit: int,
        now: datetime | None = None,
    ) -> tuple[GenerationWorkItem, ...]:
        if older_than_minutes < 1:
            raise ValueError("older_than_minutes must be positive")
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        current = now or datetime.now(timezone.utc)
        return await self._repository.list_stuck_generations(
            statuses=STUCK_GENERATION_STATUSES,
            older_than=current - timedelta(minutes=older_than_minutes),
            limit=limit,
        )
