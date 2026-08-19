import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, update

from foxgen.domain.models import GenerationStatus, OutboxStatus
from foxgen.infra import billing_lifecycle_repository, lifecycle_repository
from foxgen.infra.database import Database, Generation, OutboxEvent


@pytest.fixture(autouse=True)
async def isolate_cross_layer_outbox() -> None:
    """Do not let durable outbox work from one E2E scenario leak into the next one."""

    if os.getenv("FOXGEN_RUN_E2E") != "1":
        return

    database = Database(os.environ["FOXGEN_DATABASE_URL"])
    try:
        async with database.session() as session:
            async with session.begin():
                await session.execute(
                    update(OutboxEvent)
                    .where(
                        OutboxEvent.status.in_(
                            (
                                OutboxStatus.PENDING.value,
                                OutboxStatus.PROCESSING.value,
                                OutboxStatus.RETRY_WAIT.value,
                            )
                        )
                    )
                    .values(
                        status=OutboxStatus.COMPLETED.value,
                        locked_at=None,
                        worker_id=None,
                        last_error=None,
                        failure_class=None,
                    )
                )
    finally:
        await database.close()


@pytest.fixture(autouse=True)
def make_provider_polling_immediately_due(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep production's 20s poll delay out of deterministic cross-layer E2E tests."""

    original_transition = lifecycle_repository.generation_transition_values
    original_list_pollable = lifecycle_repository.SqlAlchemyLifecycleRepository.list_pollable

    def immediate_transition_values(**kwargs: object) -> dict[str, object]:
        values = original_transition(**kwargs)  # type: ignore[arg-type]
        if kwargs.get("target") in {
            GenerationStatus.SUBMITTED,
            GenerationStatus.PROCESSING,
        }:
            values["next_poll_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
        return values

    async def immediate_list_pollable(
        repository: lifecycle_repository.SqlAlchemyLifecycleRepository,
        limit: int,
    ) -> tuple[object, ...]:
        # Some E2E submission paths retain the production poll timestamp before
        # reaching the shared repository. Force only test rows due immediately,
        # then exercise the real list_pollable query unchanged.
        async with repository._database.session() as session:
            async with session.begin():
                await session.execute(
                    update(Generation)
                    .where(
                        Generation.status.in_(
                            (
                                GenerationStatus.SUBMITTED.value,
                                GenerationStatus.PROCESSING.value,
                            )
                        )
                    )
                    .values(next_poll_at=func.now())
                )
        return await original_list_pollable(repository, limit)  # type: ignore[return-value]

    monkeypatch.setattr(
        lifecycle_repository,
        "generation_transition_values",
        immediate_transition_values,
    )
    monkeypatch.setattr(
        billing_lifecycle_repository,
        "generation_transition_values",
        immediate_transition_values,
    )
    monkeypatch.setattr(
        lifecycle_repository.SqlAlchemyLifecycleRepository,
        "list_pollable",
        immediate_list_pollable,
    )
