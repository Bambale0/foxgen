from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from foxgen.application.lifecycle import GenerationWorkItem
from foxgen.core.errors import ErrorCode, SubmissionError
from foxgen.domain.models import GenerationStatus
from foxgen.infra.billing import settle_generation_charge
from foxgen.infra.database import Database, Generation, OutboxEvent
from foxgen.infra.lifecycle_repository import (
    SqlAlchemyLifecycleRepository,
    _generation_item,
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
                    if target == GenerationStatus.SUCCEEDED:
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
