from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID

import pytest

from foxgen.application.generation_ops import (
    GenerationOperationsService,
    STUCK_GENERATION_STATUSES,
    UnknownResolutionAction,
)
from foxgen.application.lifecycle import GenerationWorkItem
from foxgen.core.errors import ErrorCode, SubmissionError
from foxgen.domain.models import GenerationStatus


GENERATION_ID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)


class FakeOperationsRepository:
    def __init__(self) -> None:
        self.item = GenerationWorkItem(
            id=GENERATION_ID,
            user_id=42,
            model_slug="seedream-5-pro",
            status=GenerationStatus.SUBMISSION_UNKNOWN,
            input_payload={},
            result_payload=None,
            provider_task_id=None,
        )
        self.transitions: list[tuple[GenerationStatus, str | None]] = []
        self.stuck_query: tuple[frozenset[GenerationStatus], datetime, int] | None = None

    async def get_owned_generation(
        self,
        *,
        generation_id: UUID,
        user_id: int,
    ) -> GenerationWorkItem:
        assert generation_id == GENERATION_ID
        assert user_id == 42
        return self.item

    async def get_generation(self, generation_id: UUID) -> GenerationWorkItem | None:
        return self.item if generation_id == GENERATION_ID else None

    async def cancel_before_submission(
        self,
        *,
        generation_id: UUID,
        user_id: int,
    ) -> GenerationWorkItem:
        assert generation_id == GENERATION_ID
        assert user_id == 42
        self.item = replace(self.item, status=GenerationStatus.CANCELLED)
        return self.item

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
    ) -> GenerationWorkItem:
        del error_code, failure_stage, status_reason
        assert generation_id == GENERATION_ID
        assert self.item.status in expected
        self.item = replace(
            self.item,
            status=target,
            provider_task_id=provider_task_id or self.item.provider_task_id,
            result_payload=(result_payload if result_payload is not None else self.item.result_payload),
        )
        self.transitions.append((target, provider_task_id))
        return self.item

    async def list_stuck_generations(
        self,
        *,
        statuses: frozenset[GenerationStatus],
        older_than: datetime,
        limit: int,
    ) -> tuple[GenerationWorkItem, ...]:
        self.stuck_query = (statuses, older_than, limit)
        return (self.item,)


@pytest.mark.asyncio
async def test_result_ready_resolution_captures_acceptance_before_result_stage() -> None:
    repository = FakeOperationsRepository()
    service = GenerationOperationsService(repository)
    result = {"resultUrls": ["https://example.com/result.png"]}

    resolved = await service.resolve_submission_unknown(
        generation_id=GENERATION_ID,
        action=UnknownResolutionAction.RESULT_READY,
        provider_task_id="provider-confirmed",
        result_payload=result,
        reason="dashboard verified",
    )

    assert repository.transitions == [
        (GenerationStatus.SUBMITTED, "provider-confirmed"),
        (GenerationStatus.RESULT_READY, "provider-confirmed"),
    ]
    assert resolved.status == GenerationStatus.RESULT_READY
    assert resolved.result_payload == result


@pytest.mark.asyncio
async def test_unknown_resolution_requires_provider_task_for_accepted_actions() -> None:
    service = GenerationOperationsService(FakeOperationsRepository())

    with pytest.raises(SubmissionError) as captured:
        await service.resolve_submission_unknown(
            generation_id=GENERATION_ID,
            action=UnknownResolutionAction.PROCESSING,
            provider_task_id=None,
            result_payload=None,
            reason="checked provider",
        )

    assert captured.value.code == ErrorCode.VALIDATION


@pytest.mark.asyncio
async def test_failed_unknown_resolution_is_terminal_without_fake_provider_id() -> None:
    repository = FakeOperationsRepository()
    service = GenerationOperationsService(repository)

    resolved = await service.resolve_submission_unknown(
        generation_id=GENERATION_ID,
        action=UnknownResolutionAction.FAILED,
        provider_task_id=None,
        result_payload=None,
        reason="provider confirms no task",
    )

    assert resolved.status == GenerationStatus.FAILED
    assert repository.transitions == [(GenerationStatus.FAILED, None)]


@pytest.mark.asyncio
async def test_stuck_report_uses_explicit_statuses_and_cutoff() -> None:
    repository = FakeOperationsRepository()
    service = GenerationOperationsService(repository)

    items = await service.list_stuck(
        older_than_minutes=30,
        limit=100,
        now=NOW,
    )

    assert items == (repository.item,)
    assert repository.stuck_query == (
        STUCK_GENERATION_STATUSES,
        datetime(2026, 7, 25, 11, 30, tzinfo=timezone.utc),
        100,
    )
