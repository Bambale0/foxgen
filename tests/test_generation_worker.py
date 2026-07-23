from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import pytest

from foxgen.application.lifecycle import (
    GenerationWorkItem,
    GenerationWorker,
    OutboxMessage,
    ProviderEventSnapshot,
)
from foxgen.core.errors import ErrorCode, ProviderError
from foxgen.domain.models import GenerationStatus
from foxgen.providers.kie.client import TaskCreated, TaskRecord


GENERATION_ID = UUID("33333333-3333-3333-3333-333333333333")
OUTBOX_ID = UUID("44444444-4444-4444-4444-444444444444")
PROVIDER_EVENT_ID = UUID("55555555-5555-5555-5555-555555555555")


class FakeLifecycleRepository:
    def __init__(self, message: OutboxMessage | None = None) -> None:
        self.message = message
        self.generation = GenerationWorkItem(
            id=GENERATION_ID,
            user_id=42,
            model_slug="seedream-5-pro",
            status=GenerationStatus.QUEUED,
            input_payload={"prompt": "A fox"},
            provider_task_id=None,
        )
        self.provider_event: ProviderEventSnapshot | None = None
        self.completed_events: list[UUID] = []
        self.retried_events: list[UUID] = []
        self.transitions: list[GenerationStatus] = []
        self.poll_schedules = 0

    async def claim_outbox(
        self,
        *,
        worker_id: str,
        limit: int,
        lease_seconds: int,
    ) -> tuple[OutboxMessage, ...]:
        del worker_id, limit, lease_seconds
        if self.message is None:
            return ()
        message = self.message
        self.message = None
        return (message,)

    async def complete_outbox(self, event_id: UUID) -> None:
        self.completed_events.append(event_id)

    async def retry_outbox(
        self,
        *,
        event_id: UUID,
        error: str,
        delay: timedelta,
        max_attempts: int,
    ) -> None:
        del error, delay, max_attempts
        self.retried_events.append(event_id)

    async def get_generation(self, generation_id: UUID) -> GenerationWorkItem | None:
        return self.generation if generation_id == self.generation.id else None

    async def find_generation_by_provider_task_id(
        self,
        provider_task_id: str,
    ) -> GenerationWorkItem | None:
        if self.generation.provider_task_id == provider_task_id:
            return self.generation
        return None

    async def transition_generation(
        self,
        *,
        generation_id: UUID,
        expected: frozenset[GenerationStatus],
        target: GenerationStatus,
        provider_task_id: str | None = None,
        result_payload: dict[str, object] | None = None,
        error_code: str | None = None,
    ) -> GenerationWorkItem:
        del result_payload, error_code
        assert generation_id == self.generation.id
        assert self.generation.status in expected
        self.generation = replace(
            self.generation,
            status=target,
            provider_task_id=provider_task_id or self.generation.provider_task_id,
        )
        self.transitions.append(target)
        return self.generation

    async def get_provider_event(self, event_id: UUID) -> ProviderEventSnapshot | None:
        if self.provider_event is not None and self.provider_event.id == event_id:
            return self.provider_event
        return None

    async def mark_provider_event_processed(self, event_id: UUID) -> None:
        assert self.provider_event is not None
        assert self.provider_event.id == event_id
        self.provider_event = replace(self.provider_event, processed=True)

    async def list_pollable(self, limit: int) -> tuple[GenerationWorkItem, ...]:
        del limit
        if self.generation.status == GenerationStatus.SUBMITTED:
            return (self.generation,)
        return ()

    async def schedule_next_poll(
        self,
        *,
        generation_id: UUID,
        delay: timedelta,
    ) -> None:
        assert generation_id == self.generation.id
        assert delay.total_seconds() > 0
        self.poll_schedules += 1


class FakeLifecycleClient:
    def __init__(
        self,
        *,
        create_error: ProviderError | None = None,
        task_record: TaskRecord | None = None,
    ) -> None:
        self.create_error = create_error
        self.task_record = task_record or TaskRecord(task_id="provider-task-1", state="processing")
        self.create_calls = 0
        self.poll_calls = 0

    async def create_task(
        self,
        *,
        model: str,
        input_data: dict[str, object],
        callback_url: str | None = None,
    ) -> TaskCreated:
        del input_data, callback_url
        assert model == "seedream/5-pro-text-to-image"
        self.create_calls += 1
        if self.create_error is not None:
            raise self.create_error
        return TaskCreated(task_id="provider-task-1")

    async def get_task(self, task_id: str) -> TaskRecord:
        assert task_id == "provider-task-1"
        self.poll_calls += 1
        return self.task_record


@pytest.mark.asyncio
async def test_worker_submits_queued_generation_once() -> None:
    repository = FakeLifecycleRepository(
        OutboxMessage(
            id=OUTBOX_ID,
            event_type="generation.submit",
            aggregate_id=GENERATION_ID,
            payload={"generation_id": str(GENERATION_ID)},
            attempts=1,
        )
    )
    client = FakeLifecycleClient()
    worker = GenerationWorker(repository=repository, client=client)

    assert await worker.run_once() == 1
    assert client.create_calls == 1
    assert repository.generation.status == GenerationStatus.SUBMITTED
    assert repository.generation.provider_task_id == "provider-task-1"
    assert repository.completed_events == [OUTBOX_ID]
    assert repository.retried_events == []


@pytest.mark.asyncio
async def test_reclaimed_submit_event_does_not_repeat_billable_post() -> None:
    repository = FakeLifecycleRepository(
        OutboxMessage(
            id=OUTBOX_ID,
            event_type="generation.submit",
            aggregate_id=GENERATION_ID,
            payload={},
            attempts=2,
        )
    )
    repository.generation = replace(
        repository.generation,
        status=GenerationStatus.SUBMITTING,
    )
    client = FakeLifecycleClient()
    worker = GenerationWorker(repository=repository, client=client)

    assert await worker.run_once() == 1
    assert client.create_calls == 0
    assert repository.generation.status == GenerationStatus.SUBMITTING
    assert repository.completed_events == [OUTBOX_ID]
    assert repository.retried_events == []


@pytest.mark.asyncio
async def test_worker_marks_ambiguous_submission_unknown_without_retry() -> None:
    repository = FakeLifecycleRepository(
        OutboxMessage(
            id=OUTBOX_ID,
            event_type="generation.submit",
            aggregate_id=GENERATION_ID,
            payload={},
            attempts=1,
        )
    )
    client = FakeLifecycleClient(
        create_error=ProviderError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "timeout",
            retryable=True,
        )
    )
    worker = GenerationWorker(repository=repository, client=client)

    await worker.run_once()

    assert client.create_calls == 1
    assert repository.generation.status == GenerationStatus.SUBMISSION_UNKNOWN
    assert repository.completed_events == [OUTBOX_ID]
    assert repository.retried_events == []


@pytest.mark.asyncio
async def test_worker_processes_success_callback_idempotently() -> None:
    repository = FakeLifecycleRepository(
        OutboxMessage(
            id=OUTBOX_ID,
            event_type="kie.callback",
            aggregate_id=PROVIDER_EVENT_ID,
            payload={"provider_event_id": str(PROVIDER_EVENT_ID)},
            attempts=1,
        )
    )
    repository.generation = replace(
        repository.generation,
        status=GenerationStatus.SUBMITTED,
        provider_task_id="provider-task-1",
    )
    repository.provider_event = ProviderEventSnapshot(
        id=PROVIDER_EVENT_ID,
        provider_task_id="provider-task-1",
        payload={
            "taskId": "provider-task-1",
            "state": "success",
            "resultJson": '{"resultUrls":["https://example.com/result.png"]}',
        },
        processed=False,
    )
    worker = GenerationWorker(repository=repository, client=FakeLifecycleClient())

    await worker.run_once()

    assert repository.generation.status == GenerationStatus.SUCCEEDED
    assert repository.provider_event.processed is True
    assert repository.completed_events == [OUTBOX_ID]


@pytest.mark.asyncio
async def test_polling_fallback_completes_submitted_generation() -> None:
    repository = FakeLifecycleRepository()
    repository.generation = replace(
        repository.generation,
        status=GenerationStatus.SUBMITTED,
        provider_task_id="provider-task-1",
    )
    client = FakeLifecycleClient(
        task_record=TaskRecord(
            task_id="provider-task-1",
            state="success",
            result='{"resultUrls":["https://example.com/result.png"]}',
        )
    )
    worker = GenerationWorker(repository=repository, client=client)

    assert await worker.poll_once() == 1
    assert repository.generation.status == GenerationStatus.SUCCEEDED
    assert client.poll_calls == 1
