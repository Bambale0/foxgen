from uuid import UUID

import pytest

from foxgen.application.submissions import GenerationSnapshot, SubmissionService
from foxgen.core.errors import ErrorCode, SubmissionError
from foxgen.domain.models import GenerationStatus, MediaKind


class FakeRepository:
    def __init__(self) -> None:
        self.items: dict[tuple[int, str], GenerationSnapshot] = {}
        self.admissions = 0

    async def find_by_idempotency(
        self,
        *,
        user_id: int,
        idempotency_key: str,
    ) -> GenerationSnapshot | None:
        return self.items.get((user_id, idempotency_key))

    async def admit(
        self,
        *,
        user_id: int,
        username: str | None,
        idempotency_key: str,
        request_hash: str,
        model_slug: str,
        media_kind: MediaKind,
        prompt: str | None,
        input_payload: dict[str, object],
        user_concurrency_limit: int,
        global_concurrency_limit: int,
    ) -> tuple[GenerationSnapshot, bool]:
        del username, media_kind, prompt, input_payload, user_concurrency_limit
        del global_concurrency_limit
        key = (user_id, idempotency_key)
        existing = self.items.get(key)
        if existing is not None:
            return existing, False
        generation = GenerationSnapshot(
            id=UUID("22222222-2222-2222-2222-222222222222"),
            user_id=user_id,
            model_slug=model_slug,
            status=GenerationStatus.QUEUED,
            request_hash=request_hash,
        )
        self.items[key] = generation
        self.admissions += 1
        return generation, True


class FakeRateLimiter:
    def __init__(self) -> None:
        self.calls = 0

    async def check(self, user_id: int) -> None:
        assert user_id > 0
        self.calls += 1


@pytest.mark.asyncio
async def test_same_idempotency_key_is_queued_once() -> None:
    repository = FakeRepository()
    limiter = FakeRateLimiter()
    service = SubmissionService(repository=repository, rate_limiter=limiter)

    first = await service.submit(
        user_id=42,
        username="fox",
        model_slug="seedream-5-pro",
        input_data={"prompt": "A premium fox portrait"},
        idempotency_key="request-0001",
    )
    second = await service.submit(
        user_id=42,
        username="fox",
        model_slug="seedream-5-pro",
        input_data={"prompt": "A premium fox portrait"},
        idempotency_key="request-0001",
    )

    assert first.status == GenerationStatus.QUEUED
    assert first.replayed is False
    assert second.status == GenerationStatus.QUEUED
    assert second.replayed is True
    assert repository.admissions == 1
    assert limiter.calls == 1


@pytest.mark.asyncio
async def test_same_idempotency_key_rejects_different_request() -> None:
    repository = FakeRepository()
    service = SubmissionService(
        repository=repository,
        rate_limiter=FakeRateLimiter(),
    )

    await service.submit(
        user_id=42,
        username=None,
        model_slug="seedream-5-pro",
        input_data={"prompt": "First prompt"},
        idempotency_key="request-0001",
    )

    with pytest.raises(SubmissionError) as error:
        await service.submit(
            user_id=42,
            username=None,
            model_slug="seedream-5-pro",
            input_data={"prompt": "Different prompt"},
            idempotency_key="request-0001",
        )

    assert error.value.code == ErrorCode.IDEMPOTENCY_CONFLICT
