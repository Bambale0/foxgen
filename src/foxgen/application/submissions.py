import hashlib
import json
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from foxgen.core.errors import ErrorCode, SubmissionError
from foxgen.domain.models import GenerationStatus, MediaKind, ModelSpec
from foxgen.providers.kie.contracts import validate_input
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


class SubmissionRateLimiter(Protocol):
    async def check(self, user_id: int) -> None: ...


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
        rate_limiter: SubmissionRateLimiter,
        registry: ModelRegistry | None = None,
        user_concurrency_limit: int = 2,
        global_concurrency_limit: int = 20,
    ) -> None:
        self._repository = repository
        self._rate_limiter = rate_limiter
        self._registry = registry or ModelRegistry()
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
        if not model.production_ready:
            raise SubmissionError(
                ErrorCode.AUTHORIZATION,
                (
                    "Эта модель доступна только в каталоге: её точный контракт "
                    "ещё не прошёл production-проверку."
                ),
                details={
                    "model_slug": model.slug,
                    "provider_id_verified": model.provider_id_verified,
                    "schema_verified": model.schema_verified,
                    "enabled_for_submission": model.enabled_for_submission,
                },
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
        self._assert_same_request(generation, request_hash)
        return _receipt(generation, model, replayed=not created)

    @staticmethod
    def _assert_same_request(generation: GenerationSnapshot, request_hash: str) -> None:
        if generation.request_hash != request_hash:
            raise SubmissionError(
                ErrorCode.IDEMPOTENCY_CONFLICT,
                "Этот Idempotency-Key уже использован для другого запроса.",
                details={"generation_id": str(generation.id)},
            )
