import hashlib
import json
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from foxgen.core.errors import ErrorCode, ProviderError, SubmissionError
from foxgen.domain.models import GenerationStatus, MediaKind, ModelSpec
from foxgen.providers.kie.client import TaskCreated
from foxgen.providers.kie.contracts import InputContract, validate_input
from foxgen.providers.kie.registry import ModelRegistry


@dataclass(frozen=True, slots=True)
class GenerationSnapshot:
    id: UUID
    user_id: int
    model_slug: str
    status: GenerationStatus
    request_hash: str
    provider_task_id: str | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class SubmissionReceipt:
    generation_id: UUID
    model_slug: str
    provider_model: str
    status: GenerationStatus
    provider_task_id: str | None
    replayed: bool


class GenerationRepository(Protocol):
    async def find_by_idempotency(
        self,
        *,
        user_id: int,
        idempotency_key: str,
    ) -> GenerationSnapshot | None: ...

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
    ) -> tuple[GenerationSnapshot, bool]: ...

    async def transition(
        self,
        *,
        generation_id: UUID,
        expected: frozenset[GenerationStatus],
        target: GenerationStatus,
        provider_task_id: str | None = None,
        error_code: str | None = None,
    ) -> GenerationSnapshot: ...


class SubmissionRateLimiter(Protocol):
    async def check(self, user_id: int) -> None: ...


class TaskClient(Protocol):
    async def create_task(
        self,
        *,
        model: str,
        input_data: dict[str, object],
        callback_url: str | None = None,
    ) -> TaskCreated: ...


class NoopSubmissionRateLimiter:
    async def check(self, user_id: int) -> None:
        del user_id


def request_fingerprint(*, model_slug: str, input_payload: dict[str, object]) -> str:
    canonical = json.dumps(
        {"model": model_slug, "input": input_payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _receipt(
    generation: GenerationSnapshot,
    model: ModelSpec,
    *,
    replayed: bool,
) -> SubmissionReceipt:
    return SubmissionReceipt(
        generation_id=generation.id,
        model_slug=model.slug,
        provider_model=model.provider_model,
        status=generation.status,
        provider_task_id=generation.provider_task_id,
        replayed=replayed,
    )


class SubmissionService:
    def __init__(
        self,
        *,
        repository: GenerationRepository,
        client: TaskClient,
        rate_limiter: SubmissionRateLimiter,
        registry: ModelRegistry | None = None,
        callback_url: str | None = None,
        user_concurrency_limit: int = 2,
        global_concurrency_limit: int = 20,
    ) -> None:
        self._repository = repository
        self._client = client
        self._rate_limiter = rate_limiter
        self._registry = registry or ModelRegistry()
        self._callback_url = callback_url
        self._user_concurrency_limit = user_concurrency_limit
        self._global_concurrency_limit = global_concurrency_limit

    async def submit(
        self,
        *,
        user_id: int,
        username: str | None,
        model_slug: str,
        input_data: dict[str, object],
        idempotency_key: str,
    ) -> SubmissionReceipt:
        model = self._registry.get(model_slug)
        if model.contract == InputContract.PASSTHROUGH:
            raise SubmissionError(
                ErrorCode.AUTHORIZATION,
                "Эта модель пока доступна только в каталоге и не включена для платных задач.",
            )

        normalized = validate_input(model.contract, input_data)
        request_hash = request_fingerprint(model_slug=model.slug, input_payload=normalized)

        existing = await self._repository.find_by_idempotency(
            user_id=user_id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            self._assert_same_request(existing, request_hash)
            return _receipt(existing, model, replayed=True)

        await self._rate_limiter.check(user_id)
        generation, created = await self._repository.admit(
            user_id=user_id,
            username=username,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            model_slug=model.slug,
            media_kind=model.media_kind,
            prompt=str(normalized.get("prompt")) if normalized.get("prompt") is not None else None,
            input_payload=normalized,
            user_concurrency_limit=self._user_concurrency_limit,
            global_concurrency_limit=self._global_concurrency_limit,
        )
        if not created:
            self._assert_same_request(generation, request_hash)
            return _receipt(generation, model, replayed=True)

        generation = await self._repository.transition(
            generation_id=generation.id,
            expected=frozenset({GenerationStatus.QUEUED}),
            target=GenerationStatus.SUBMITTING,
        )
        try:
            task = await self._client.create_task(
                model=model.provider_model,
                input_data=normalized,
                callback_url=self._callback_url,
            )
        except ProviderError as exc:
            if exc.retryable:
                generation = await self._repository.transition(
                    generation_id=generation.id,
                    expected=frozenset({GenerationStatus.SUBMITTING}),
                    target=GenerationStatus.SUBMISSION_UNKNOWN,
                    error_code=exc.code,
                )
                return _receipt(generation, model, replayed=False)

            await self._repository.transition(
                generation_id=generation.id,
                expected=frozenset({GenerationStatus.SUBMITTING}),
                target=GenerationStatus.FAILED,
                error_code=exc.code,
            )
            raise

        generation = await self._repository.transition(
            generation_id=generation.id,
            expected=frozenset({GenerationStatus.SUBMITTING}),
            target=GenerationStatus.SUBMITTED,
            provider_task_id=task.task_id,
        )
        return _receipt(generation, model, replayed=False)

    @staticmethod
    def _assert_same_request(generation: GenerationSnapshot, request_hash: str) -> None:
        if generation.request_hash != request_hash:
            raise SubmissionError(
                ErrorCode.IDEMPOTENCY_CONFLICT,
                "Этот Idempotency-Key уже использован для другого запроса.",
                details={"generation_id": str(generation.id)},
            )
