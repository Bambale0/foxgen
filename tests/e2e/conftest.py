from datetime import datetime, timezone

import pytest

from foxgen.domain.models import GenerationStatus
from foxgen.infra import billing_lifecycle_repository, lifecycle_repository


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
