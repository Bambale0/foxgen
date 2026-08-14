from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

import pytest

from foxgen.application.lifecycle import GenerationWorkItem, GenerationWorker, OutboxMessage
from foxgen.domain.models import GenerationStatus
from foxgen.providers.kie.client import TaskCreated, TaskRecord


OUTBOX_ID = UUID("77777777-7777-7777-7777-777777777777")
REFERENCE_ID = UUID("88888888-8888-8888-8888-888888888888")


class FakeRepository:
    def __init__(self) -> None:
        self.message: OutboxMessage | None = OutboxMessage(
            id=OUTBOX_ID,
            event_type="reference.delete",
            aggregate_id=REFERENCE_ID,
            payload={"reference_id": str(REFERENCE_ID)},
            attempts=1,
        )
        self.completed: list[UUID] = []
        self.retried: list[tuple[UUID, bool]] = []

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
        result = self.message
        self.message = None
        return (result,)

    async def complete_outbox(self, event_id: UUID) -> None:
        self.completed.append(event_id)

    async def retry_outbox(
        self,
        *,
        event_id: UUID,
        error: str,
        delay: timedelta,
        max_attempts: int,
        retryable: bool,
        failure_class: str,
    ) -> None:
        del error, delay, max_attempts, failure_class
        self.retried.append((event_id, retryable))

    async def get_generation(self, generation_id: UUID) -> GenerationWorkItem | None:
        del generation_id
        return None

    async def find_generation_by_provider_task_id(
        self,
        provider_task_id: str,
    ) -> GenerationWorkItem | None:
        del provider_task_id
        return None

    async def transition_generation(self, **kwargs: object) -> GenerationWorkItem:
        del kwargs
        raise AssertionError("not used")

    async def get_provider_event(self, event_id: UUID):
        del event_id
        return None

    async def mark_provider_event_processed(self, event_id: UUID) -> None:
        del event_id

    async def list_pollable(self, limit: int) -> tuple[GenerationWorkItem, ...]:
        del limit
        return ()

    async def schedule_next_poll(self, *, generation_id: UUID, delay: timedelta) -> None:
        del generation_id, delay

    async def list_stale_submitting(
        self,
        *,
        older_than: datetime,
        limit: int,
    ) -> tuple[GenerationWorkItem, ...]:
        del older_than, limit
        return ()


class FakeClient:
    async def create_task(
        self,
        *,
        model: str,
        input_data: dict[str, object],
        callback_url: str | None = None,
    ) -> TaskCreated:
        del model, input_data, callback_url
        raise AssertionError("not used")

    async def get_task(self, task_id: str) -> TaskRecord:
        del task_id
        raise AssertionError("not used")


class FakeReferenceDeleteProcessor:
    def __init__(self) -> None:
        self.deleted: list[UUID] = []

    async def delete(self, asset_id: UUID) -> None:
        self.deleted.append(asset_id)


@pytest.mark.asyncio
async def test_worker_completes_reference_delete_after_storage_processor() -> None:
    repository = FakeRepository()
    processor = FakeReferenceDeleteProcessor()
    worker = GenerationWorker(
        repository=repository,
        client=FakeClient(),
        reference_delete_processor=processor,
    )

    assert await worker.run_once() == 1
    assert processor.deleted == [REFERENCE_ID]
    assert repository.completed == [OUTBOX_ID]
    assert repository.retried == []
