import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import update

from foxgen.domain.models import GenerationStatus, OutboxStatus
from foxgen.infra import billing_lifecycle_repository, lifecycle_repository
from foxgen.infra.database import Database, OutboxEvent


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

    original = lifecycle_repository.generation_transition_values

    def immediate_transition_values(**kwargs: object) -> dict[str, object]:
        values = original(**kwargs)  # type: ignore[arg-type]
        if kwargs.get("target") in {
            GenerationStatus.SUBMITTED,
            GenerationStatus.PROCESSING,
        }:
            values["next_poll_at"] = datetime.now(timezone.utc)
        return values

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
