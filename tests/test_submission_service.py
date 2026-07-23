from dataclasses import replace
from uuid import UUID

import pytest

from foxgen.application.submissions import GenerationSnapshot, SubmissionService
from foxgen.core.errors import ErrorCode, ProviderError, SubmissionError
from foxgen.domain.models import GenerationStatus, MediaKind
from foxgen.providers.kie.client import TaskCreated


class FakeRepository:
    def __init__(self) -> None:
        self.items: dict[tuple[int, str], GenerationSnapshot] = {}
        self.by_id: dict[UUID, tuple[int, str]] = {}
        self.transitions: list[GenerationStatus] = []

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
        self.by_id[generation.id] = key
        return generation, True

    async def transition(
        self,
        *,
        generation_id: UUID,
        expected: frozenset[GenerationStatus],
        target: GenerationStatus,
        provider_task_id: str | None = None,
        error_code: str | None = None,
    ) -> GenerationSnapshot:
        key = self.by_id[generation_id]
        current = self.items[key]
        assert current.status in expected
        updated = replace(
            current,
            status=target,
            provider_task_id=provider_task_id or current.provider_task_id,
            error_code=error_code,
        )
        self.items[key] = updated
        self.transitions.append(target)
        return updated


class FakeRateLimiter:
    def __init__(self) -> None:
        self.calls = 0

    async def check(self, user_id: int) -> None:
        assert user_id > 0
        self.calls += 1


class FakeTaskClient:
    def __init__(self, error: ProviderError | None = None) -> None:
        self.error = error
        self.calls: list[str] = []

    async def create_task(
        self,
        *,
        model: str,
        input_data: dict[str, object],
        callback_url: str | None = None,
    ) -> TaskCreated:
        del input_data, callback_url
        self.calls.append(model)
        if self.error is not None:
            raise self.error
        return TaskCreated(task_id="provider-task-1")


@pytest.mark.asyncio
async def test_same_idempotency_key_submits_provider_once() -> None:
    repository = FakeRepository()
    limiter = FakeRateLimiter()
    client = FakeTaskClient()
    service = SubmissionService(
        repository=repository,
        client=client,
        rate_limiter=limiter,
    )

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

    assert first.status == GenerationStatus.SUBMITTED
    assert second.status == GenerationStatus.SUBMITTED
    assert second.replayed is True
    assert client.calls == ["seedream/5-pro-text-to-image"]
    assert limiter.calls == 1


@pytest.mark.asyncio
async def test_same_idempotency_key_rejects_different_request() -> None:
    repository = FakeRepository()
    service = SubmissionService(
        repository=repository,
        client=FakeTaskClient(),
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


@pytest.mark.asyncio
async def test_ambiguous_provider_failure_is_not_resubmitted() -> None:
    repository = FakeRepository()
    client = FakeTaskClient(
        ProviderError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "timeout",
            retryable=True,
        )
    )
    service = SubmissionService(
        repository=repository,
        client=client,
        rate_limiter=FakeRateLimiter(),
    )

    first = await service.submit(
        user_id=42,
        username=None,
        model_slug="seedream-5-pro",
        input_data={"prompt": "A fox"},
        idempotency_key="request-0001",
    )
    replay = await service.submit(
        user_id=42,
        username=None,
        model_slug="seedream-5-pro",
        input_data={"prompt": "A fox"},
        idempotency_key="request-0001",
    )

    assert first.status == GenerationStatus.SUBMISSION_UNKNOWN
    assert replay.status == GenerationStatus.SUBMISSION_UNKNOWN
    assert replay.replayed is True
    assert client.calls == ["seedream/5-pro-text-to-image"]
    assert repository.transitions == [
        GenerationStatus.SUBMITTING,
        GenerationStatus.SUBMISSION_UNKNOWN,
    ]
