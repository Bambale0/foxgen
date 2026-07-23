from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from foxgen.application.lifecycle import (
    GenerationWorkItem,
    OutboxMessage,
    ProviderEventSnapshot,
)
from foxgen.core.errors import ErrorCode, SubmissionError
from foxgen.domain.models import GenerationStatus, OutboxStatus
from foxgen.infra.database import Database, Generation, OutboxEvent, ProviderEvent


def _generation_item(generation: Generation) -> GenerationWorkItem:
    return GenerationWorkItem(
        id=generation.id,
        user_id=generation.user_id,
        model_slug=generation.model_slug,
        status=GenerationStatus(generation.status),
        input_payload=dict(generation.input_payload),
        provider_task_id=generation.provider_task_id,
    )


def _outbox_message(event: OutboxEvent) -> OutboxMessage:
    return OutboxMessage(
        id=event.id,
        event_type=event.event_type,
        aggregate_id=event.aggregate_id,
        payload=dict(event.payload),
        attempts=event.attempts,
    )


class SqlAlchemyLifecycleRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def claim_outbox(
        self,
        *,
        worker_id: str,
        limit: int,
        lease_seconds: int,
    ) -> tuple[OutboxMessage, ...]:
        now = datetime.now(timezone.utc)
        stale_before = now - timedelta(seconds=lease_seconds)
        async with self._database.session() as session:
            async with session.begin():
                events = tuple(
                    (
                        await session.scalars(
                            select(OutboxEvent)
                            .where(
                                or_(
                                    and_(
                                        OutboxEvent.status == OutboxStatus.PENDING.value,
                                        OutboxEvent.available_at <= now,
                                    ),
                                    and_(
                                        OutboxEvent.status == OutboxStatus.PROCESSING.value,
                                        OutboxEvent.locked_at.is_not(None),
                                        OutboxEvent.locked_at < stale_before,
                                    ),
                                )
                            )
                            .order_by(OutboxEvent.available_at, OutboxEvent.created_at)
                            .with_for_update(skip_locked=True)
                            .limit(limit)
                        )
                    ).all()
                )
                for event in events:
                    event.status = OutboxStatus.PROCESSING
                    event.worker_id = worker_id
                    event.locked_at = now
                    event.attempts += 1
                await session.flush()
                return tuple(_outbox_message(event) for event in events)

    async def complete_outbox(self, event_id: UUID) -> None:
        await self._set_outbox_state(
            event_id=event_id,
            status=OutboxStatus.COMPLETED,
            available_at=None,
            last_error=None,
        )

    async def retry_outbox(
        self,
        *,
        event_id: UUID,
        error: str,
        delay: timedelta,
        max_attempts: int,
    ) -> None:
        async with self._database.session() as session:
            async with session.begin():
                event = await session.get(OutboxEvent, event_id, with_for_update=True)
                if event is None:
                    return
                if event.attempts >= max_attempts:
                    event.status = OutboxStatus.FAILED
                else:
                    event.status = OutboxStatus.PENDING
                    event.available_at = datetime.now(timezone.utc) + delay
                event.last_error = error[:10_000]
                event.locked_at = None
                event.worker_id = None

    async def _set_outbox_state(
        self,
        *,
        event_id: UUID,
        status: OutboxStatus,
        available_at: datetime | None,
        last_error: str | None,
    ) -> None:
        values: dict[str, object] = {
            "status": status.value,
            "locked_at": None,
            "worker_id": None,
            "last_error": last_error,
            "updated_at": func.now(),
        }
        if available_at is not None:
            values["available_at"] = available_at
        async with self._database.session() as session:
            async with session.begin():
                await session.execute(
                    update(OutboxEvent).where(OutboxEvent.id == event_id).values(**values)
                )

    async def get_generation(self, generation_id: UUID) -> GenerationWorkItem | None:
        async with self._database.session() as session:
            generation = await session.get(Generation, generation_id)
            return _generation_item(generation) if generation is not None else None

    async def find_generation_by_provider_task_id(
        self,
        provider_task_id: str,
    ) -> GenerationWorkItem | None:
        async with self._database.session() as session:
            generation = await session.scalar(
                select(Generation).where(
                    Generation.provider_task_id == provider_task_id
                )
            )
            return _generation_item(generation) if generation is not None else None

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
        values: dict[str, object] = {
            "status": target.value,
            "error_code": error_code,
            "updated_at": func.now(),
        }
        if provider_task_id is not None:
            values["provider_task_id"] = provider_task_id
        if result_payload is not None:
            values["result_payload"] = result_payload
        if target == GenerationStatus.SUBMITTED:
            values["submitted_at"] = func.now()
            values["next_poll_at"] = datetime.now(timezone.utc) + timedelta(seconds=20)
        if target in {
            GenerationStatus.SUCCEEDED,
            GenerationStatus.FAILED,
            GenerationStatus.CANCELLED,
        }:
            values["completed_at"] = func.now()
            values["next_poll_at"] = None

        async with self._database.session() as session:
            async with session.begin():
                generation = await session.scalar(
                    update(Generation)
                    .where(
                        Generation.id == generation_id,
                        Generation.status.in_(tuple(status.value for status in expected)),
                    )
                    .values(**values)
                    .returning(Generation)
                )
                if generation is None:
                    generation = await session.get(Generation, generation_id)
                if generation is None:
                    raise SubmissionError(
                        ErrorCode.TASK_NOT_FOUND,
                        "Локальная задача генерации не найдена.",
                    )
                return _generation_item(generation)

    async def record_provider_event(
        self,
        *,
        provider: str,
        provider_task_id: str,
        event_hash: str,
        payload: dict[str, object],
    ) -> bool:
        async with self._database.session() as session:
            async with session.begin():
                inserted = await session.scalar(
                    pg_insert(ProviderEvent)
                    .values(
                        provider=provider,
                        provider_task_id=provider_task_id,
                        event_hash=event_hash,
                        payload=payload,
                    )
                    .on_conflict_do_nothing(index_elements=[ProviderEvent.event_hash])
                    .returning(ProviderEvent)
                )
                if inserted is None:
                    return False

                await session.execute(
                    pg_insert(OutboxEvent)
                    .values(
                        event_type="kie.callback",
                        aggregate_id=inserted.id,
                        deduplication_key=f"kie.callback:{inserted.event_hash}",
                        payload={"provider_event_id": str(inserted.id)},
                    )
                    .on_conflict_do_nothing(
                        index_elements=[OutboxEvent.deduplication_key]
                    )
                )
                return True

    async def get_provider_event(self, event_id: UUID) -> ProviderEventSnapshot | None:
        async with self._database.session() as session:
            event = await session.get(ProviderEvent, event_id)
            if event is None:
                return None
            return ProviderEventSnapshot(
                id=event.id,
                provider_task_id=event.provider_task_id,
                payload=dict(event.payload),
                processed=event.processed_at is not None,
            )

    async def mark_provider_event_processed(self, event_id: UUID) -> None:
        async with self._database.session() as session:
            async with session.begin():
                await session.execute(
                    update(ProviderEvent)
                    .where(ProviderEvent.id == event_id)
                    .values(processed_at=func.now())
                )

    async def list_pollable(self, limit: int) -> tuple[GenerationWorkItem, ...]:
        now = datetime.now(timezone.utc)
        async with self._database.session() as session:
            generations = tuple(
                (
                    await session.scalars(
                        select(Generation)
                        .where(
                            Generation.status == GenerationStatus.SUBMITTED.value,
                            Generation.provider_task_id.is_not(None),
                            or_(
                                Generation.next_poll_at.is_(None),
                                Generation.next_poll_at <= now,
                            ),
                        )
                        .order_by(Generation.next_poll_at, Generation.submitted_at)
                        .limit(limit)
                    )
                ).all()
            )
            return tuple(_generation_item(generation) for generation in generations)

    async def schedule_next_poll(
        self,
        *,
        generation_id: UUID,
        delay: timedelta,
    ) -> None:
        now = datetime.now(timezone.utc)
        async with self._database.session() as session:
            async with session.begin():
                await session.execute(
                    update(Generation)
                    .where(Generation.id == generation_id)
                    .values(
                        last_polled_at=now,
                        next_poll_at=now + delay,
                        updated_at=func.now(),
                    )
                )
