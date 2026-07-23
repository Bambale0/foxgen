import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol
from uuid import UUID

from foxgen.core.errors import ErrorCode, ProviderError, SubmissionError
from foxgen.domain.models import GenerationStatus
from foxgen.providers.kie.client import TaskCreated, TaskRecord
from foxgen.providers.kie.registry import ModelRegistry


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    id: UUID
    event_type: str
    aggregate_id: UUID
    payload: dict[str, object]
    attempts: int


@dataclass(frozen=True, slots=True)
class GenerationWorkItem:
    id: UUID
    user_id: int
    model_slug: str
    status: GenerationStatus
    input_payload: dict[str, object]
    provider_task_id: str | None


@dataclass(frozen=True, slots=True)
class ProviderEventSnapshot:
    id: UUID
    provider_task_id: str
    payload: dict[str, object]
    processed: bool


@dataclass(frozen=True, slots=True)
class NormalizedProviderState:
    status: GenerationStatus | None
    result_payload: dict[str, object] | None
    error_code: str | None


class LifecycleTaskClient(Protocol):
    async def create_task(
        self,
        *,
        model: str,
        input_data: dict[str, object],
        callback_url: str | None = None,
    ) -> TaskCreated: ...

    async def get_task(self, task_id: str) -> TaskRecord: ...


class LifecycleRepository(Protocol):
    async def claim_outbox(
        self,
        *,
        worker_id: str,
        limit: int,
        lease_seconds: int,
    ) -> tuple[OutboxMessage, ...]: ...

    async def complete_outbox(self, event_id: UUID) -> None: ...

    async def retry_outbox(
        self,
        *,
        event_id: UUID,
        error: str,
        delay: timedelta,
        max_attempts: int,
    ) -> None: ...

    async def get_generation(self, generation_id: UUID) -> GenerationWorkItem | None: ...

    async def find_generation_by_provider_task_id(
        self,
        provider_task_id: str,
    ) -> GenerationWorkItem | None: ...

    async def transition_generation(
        self,
        *,
        generation_id: UUID,
        expected: frozenset[GenerationStatus],
        target: GenerationStatus,
        provider_task_id: str | None = None,
        result_payload: dict[str, object] | None = None,
        error_code: str | None = None,
    ) -> GenerationWorkItem: ...

    async def get_provider_event(self, event_id: UUID) -> ProviderEventSnapshot | None: ...

    async def mark_provider_event_processed(self, event_id: UUID) -> None: ...

    async def list_pollable(self, limit: int) -> tuple[GenerationWorkItem, ...]: ...

    async def schedule_next_poll(
        self,
        *,
        generation_id: UUID,
        delay: timedelta,
    ) -> None: ...


class GenerationWorker:
    def __init__(
        self,
        *,
        repository: LifecycleRepository,
        client: LifecycleTaskClient,
        registry: ModelRegistry | None = None,
        callback_url: str | None = None,
        worker_id: str = "foxgen-worker",
        batch_size: int = 10,
        lease_seconds: int = 120,
        max_attempts: int = 8,
        poll_interval: timedelta = timedelta(seconds=20),
    ) -> None:
        self._repository = repository
        self._client = client
        self._registry = registry or ModelRegistry()
        self._callback_url = callback_url
        self._worker_id = worker_id
        self._batch_size = batch_size
        self._lease_seconds = lease_seconds
        self._max_attempts = max_attempts
        self._poll_interval = poll_interval

    async def run_once(self) -> int:
        messages = await self._repository.claim_outbox(
            worker_id=self._worker_id,
            limit=self._batch_size,
            lease_seconds=self._lease_seconds,
        )
        for message in messages:
            await self._process_message(message)
        return len(messages)

    async def poll_once(self) -> int:
        generations = await self._repository.list_pollable(self._batch_size)
        for generation in generations:
            await self._poll_generation(generation)
        return len(generations)

    async def _process_message(self, message: OutboxMessage) -> None:
        try:
            if message.event_type == "generation.submit":
                await self._submit_generation(message)
            elif message.event_type == "kie.callback":
                await self._process_callback(message)
            else:
                raise SubmissionError(
                    ErrorCode.VALIDATION,
                    f"Unknown outbox event type: {message.event_type}",
                )
        except SubmissionError as exc:
            await self._repository.retry_outbox(
                event_id=message.id,
                error=str(exc),
                delay=_retry_delay(message.attempts),
                max_attempts=self._max_attempts,
            )
        except Exception as exc:
            await self._repository.retry_outbox(
                event_id=message.id,
                error=f"{type(exc).__name__}: {exc}",
                delay=_retry_delay(message.attempts),
                max_attempts=self._max_attempts,
            )

    async def _submit_generation(self, message: OutboxMessage) -> None:
        generation = await self._repository.get_generation(message.aggregate_id)
        if generation is None:
            raise SubmissionError(ErrorCode.TASK_NOT_FOUND, "Generation not found")
        if generation.status != GenerationStatus.QUEUED:
            await self._repository.complete_outbox(message.id)
            return

        model = self._registry.get(generation.model_slug)
        generation = await self._repository.transition_generation(
            generation_id=generation.id,
            expected=frozenset({GenerationStatus.QUEUED}),
            target=GenerationStatus.SUBMITTING,
        )

        # This event must never be replayed automatically after the billable POST starts.
        # If the process crashes after this point, the generation stays `submitting` and a
        # watchdog/operator can move it to `submission_unknown` without creating a duplicate.
        await self._repository.complete_outbox(message.id)

        try:
            task = await self._client.create_task(
                model=model.provider_model,
                input_data=generation.input_payload,
                callback_url=self._callback_url,
            )
        except ProviderError as exc:
            target = (
                GenerationStatus.SUBMISSION_UNKNOWN
                if exc.retryable
                else GenerationStatus.FAILED
            )
            await self._repository.transition_generation(
                generation_id=generation.id,
                expected=frozenset({GenerationStatus.SUBMITTING}),
                target=target,
                error_code=exc.code,
            )
            return
        except Exception:
            # The provider may have accepted the POST before the transport failed.
            await self._repository.transition_generation(
                generation_id=generation.id,
                expected=frozenset({GenerationStatus.SUBMITTING}),
                target=GenerationStatus.SUBMISSION_UNKNOWN,
                error_code=ErrorCode.SUBMISSION_UNKNOWN,
            )
            return

        await self._repository.transition_generation(
            generation_id=generation.id,
            expected=frozenset({GenerationStatus.SUBMITTING}),
            target=GenerationStatus.SUBMITTED,
            provider_task_id=task.task_id,
        )

    async def _process_callback(self, message: OutboxMessage) -> None:
        event_id_value = message.payload.get("provider_event_id")
        if not isinstance(event_id_value, str):
            raise SubmissionError(ErrorCode.VALIDATION, "provider_event_id is missing")
        event = await self._repository.get_provider_event(UUID(event_id_value))
        if event is None:
            raise SubmissionError(ErrorCode.TASK_NOT_FOUND, "Provider event not found")
        if event.processed:
            await self._repository.complete_outbox(message.id)
            return

        generation = await self._repository.find_generation_by_provider_task_id(
            event.provider_task_id
        )
        if generation is None:
            raise SubmissionError(
                ErrorCode.TASK_NOT_FOUND,
                f"Generation for provider task {event.provider_task_id} is not linked yet",
                retryable=True,
            )

        state = normalize_provider_payload(event.payload)
        if state.status is not None:
            await self._repository.transition_generation(
                generation_id=generation.id,
                expected=frozenset(
                    {
                        GenerationStatus.SUBMITTED,
                        GenerationStatus.SUBMISSION_UNKNOWN,
                    }
                ),
                target=state.status,
                result_payload=state.result_payload,
                error_code=state.error_code,
            )
        await self._repository.mark_provider_event_processed(event.id)
        await self._repository.complete_outbox(message.id)

    async def _poll_generation(self, generation: GenerationWorkItem) -> None:
        task_id = generation.provider_task_id
        if task_id is None:
            return
        try:
            task = await self._client.get_task(task_id)
        except ProviderError:
            await self._repository.schedule_next_poll(
                generation_id=generation.id,
                delay=self._poll_interval,
            )
            return

        state = normalize_task_record(task)
        if state.status is None:
            await self._repository.schedule_next_poll(
                generation_id=generation.id,
                delay=self._poll_interval,
            )
            return
        await self._repository.transition_generation(
            generation_id=generation.id,
            expected=frozenset({GenerationStatus.SUBMITTED}),
            target=state.status,
            result_payload=state.result_payload,
            error_code=state.error_code,
        )


def _retry_delay(attempts: int) -> timedelta:
    seconds = min(300, max(2, 2 ** min(attempts, 8)))
    return timedelta(seconds=seconds)


def normalize_task_record(task: TaskRecord) -> NormalizedProviderState:
    payload: dict[str, object] = {
        "taskId": task.task_id,
        "state": task.state or "",
        "result": task.result,
    }
    return normalize_provider_payload(payload)


def normalize_provider_payload(payload: dict[str, object]) -> NormalizedProviderState:
    nested = payload.get("data")
    source = nested if isinstance(nested, dict) else payload
    raw_state = source.get("state") or source.get("status") or source.get("taskStatus")
    state = str(raw_state or "").strip().lower()

    if state in {"success", "succeeded", "completed", "complete", "done"}:
        raw_result = source.get("resultJson") or source.get("result") or source.get("output")
        return NormalizedProviderState(
            status=GenerationStatus.SUCCEEDED,
            result_payload=_normalize_result(raw_result),
            error_code=None,
        )
    if state in {"failed", "failure", "error", "cancelled", "canceled"}:
        raw_error = source.get("failCode") or source.get("errorCode") or source.get("code")
        return NormalizedProviderState(
            status=GenerationStatus.FAILED,
            result_payload=None,
            error_code=str(raw_error or ErrorCode.PROVIDER_REJECTED),
        )
    return NormalizedProviderState(status=None, result_payload=None, error_code=None)


def _normalize_result(value: object) -> dict[str, object]:
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {"raw": value}
        return _normalize_result(decoded)
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    if isinstance(value, list):
        return {"items": value}
    if value is None:
        return {}
    return {"value": value}
