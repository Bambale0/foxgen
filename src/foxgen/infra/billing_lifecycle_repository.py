from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from foxgen.application.lifecycle import GenerationWorkItem
from foxgen.core.errors import ErrorCode, SubmissionError
from foxgen.domain.models import GenerationStatus, OutboxStatus
from foxgen.infra.billing import settle_generation_charge
from foxgen.infra.database import Database, Generation, OutboxEvent
from foxgen.infra.lifecycle_repository import (
    SqlAlchemyLifecycleRepository,
    _generation_item,
    generation_transition_values,
    validate_transition_set,
)


class BillingAwareLifecycleRepository(SqlAlchemyLifecycleRepository):
    """Lifecycle repository that settles money in the same transaction as state changes."""

    def __init__(self, database: Database) -> None:
        super().__init__(database)
        self._billing_database = database

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
        validate_transition_set(expected, target)
        values = generation_transition_values(
            target=target,
            provider_task_id=provider_task_id,
            result_payload=result_payload,
            error_code=error_code,
            failure_stage=failure_stage,
            status_reason=status_reason,
        )

        async with self._billing_database.session() as session:
            async with session.begin():
                changed = await session.scalar(
                    update(Generation)
                    .where(
                        Generation.id == generation_id,
                        Generation.status.in_(tuple(status.value for status in expected)),
                    )
                    .values(**values)
                    .returning(Generation)
                )
                generation = changed
                if generation is None:
                    generation = await session.get(Generation, generation_id)
                if generation is None:
                    raise SubmissionError(
                        ErrorCode.TASK_NOT_FOUND,
                        "Локальная задача генерации не найдена.",
                    )

                if changed is not None:
                    await settle_generation_charge(
                        session,
                        generation_id=generation.id,
                        target=target,
                    )
                    if target == GenerationStatus.RESULT_READY:
                        await session.execute(
                            pg_insert(OutboxEvent)
                            .values(
                                event_type="generation.archive",
                                aggregate_id=generation.id,
                                deduplication_key=f"generation.archive:{generation.id}",
                                payload={"generation_id": str(generation.id)},
                            )
                            .on_conflict_do_nothing(
                                index_elements=[OutboxEvent.deduplication_key]
                            )
                        )
                return _generation_item(generation)

    async def get_owned_generation(
        self,
        *,
        generation_id: UUID,
        user_id: int,
    ) -> GenerationWorkItem:
        async with self._billing_database.session() as session:
            generation = await session.scalar(
                select(Generation).where(
                    Generation.id == generation_id,
                    Generation.user_id == user_id,
                )
            )
            if generation is None:
                raise SubmissionError(
                    ErrorCode.TASK_NOT_FOUND,
                    "Генерация не найдена.",
                )
            return _generation_item(generation)

    async def cancel_before_submission(
        self,
        *,
        generation_id: UUID,
        user_id: int,
    ) -> GenerationWorkItem:
        async with self._billing_database.session() as session:
            async with session.begin():
                generation = await session.scalar(
                    select(Generation)
                    .where(
                        Generation.id == generation_id,
                        Generation.user_id == user_id,
                    )
                    .with_for_update()
                )
                if generation is None:
                    raise SubmissionError(
                        ErrorCode.TASK_NOT_FOUND,
                        "Генерация не найдена.",
                    )
                current = GenerationStatus(generation.status)
                if current == GenerationStatus.CANCELLED:
                    return _generation_item(generation)
                if current not in {GenerationStatus.DRAFT, GenerationStatus.QUEUED}:
                    raise SubmissionError(
                        ErrorCode.IDEMPOTENCY_CONFLICT,
                        "Отмена возможна только до начала отправки задачи провайдеру.",
                        details={"status": current.value},
                    )

                validate_transition_set(frozenset({current}), GenerationStatus.CANCELLED)
                await session.execute(
                    update(Generation)
                    .where(
                        Generation.id == generation.id,
                        Generation.status == current.value,
                    )
                    .values(
                        **generation_transition_values(
                            target=GenerationStatus.CANCELLED,
                            status_reason="cancelled_by_user_before_submission",
                        )
                    )
                )
                await settle_generation_charge(
                    session,
                    generation_id=generation.id,
                    target=GenerationStatus.CANCELLED,
                )
                await session.execute(
                    update(OutboxEvent)
                    .where(
                        OutboxEvent.aggregate_id == generation.id,
                        OutboxEvent.event_type == "generation.submit",
                        OutboxEvent.status.in_(
                            (
                                OutboxStatus.PENDING.value,
                                OutboxStatus.PROCESSING.value,
                            )
                        ),
                    )
                    .values(
                        status=OutboxStatus.COMPLETED.value,
                        locked_at=None,
                        worker_id=None,
                        last_error=None,
                        updated_at=func.now(),
                    )
                )
                await session.refresh(generation)
                return _generation_item(generation)

    async def list_stuck_generations(
        self,
        *,
        statuses: frozenset[GenerationStatus],
        older_than: datetime,
        limit: int,
    ) -> tuple[GenerationWorkItem, ...]:
        if not statuses:
            return ()
        async with self._billing_database.session() as session:
            generations = tuple(
                (
                    await session.scalars(
                        select(Generation)
                        .where(
                            Generation.status.in_(tuple(status.value for status in statuses)),
                            Generation.status_changed_at < older_than,
                        )
                        .order_by(Generation.status_changed_at, Generation.id)
                        .limit(limit)
                    )
                ).all()
            )
            return tuple(_generation_item(generation) for generation in generations)
