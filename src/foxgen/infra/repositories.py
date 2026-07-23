from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from foxgen.application.submissions import GenerationSnapshot
from foxgen.core.errors import ErrorCode, SubmissionError
from foxgen.domain.models import ACTIVE_GENERATION_STATUSES, GenerationStatus, MediaKind
from foxgen.infra.database import Database, Generation, OutboxEvent, User


_ACTIVE_STATUS_VALUES = tuple(status.value for status in ACTIVE_GENERATION_STATUSES)


def _snapshot(generation: Generation) -> GenerationSnapshot:
    return GenerationSnapshot(
        id=generation.id,
        user_id=generation.user_id,
        model_slug=generation.model_slug,
        status=GenerationStatus(generation.status),
        request_hash=generation.request_hash,
        provider_task_id=generation.provider_task_id,
        error_code=generation.error_code,
    )


class SqlAlchemyGenerationRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def find_by_idempotency(
        self,
        *,
        user_id: int,
        idempotency_key: str,
    ) -> GenerationSnapshot | None:
        async with self._database.session() as session:
            generation = await session.scalar(
                select(Generation).where(
                    Generation.user_id == user_id,
                    Generation.idempotency_key == idempotency_key,
                )
            )
            return _snapshot(generation) if generation is not None else None

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
        async with self._database.session() as session:
            async with session.begin():
                existing = await session.scalar(
                    select(Generation).where(
                        Generation.user_id == user_id,
                        Generation.idempotency_key == idempotency_key,
                    )
                )
                if existing is not None:
                    return _snapshot(existing), False

                global_active = await session.scalar(
                    select(func.count(Generation.id)).where(
                        Generation.status.in_(_ACTIVE_STATUS_VALUES)
                    )
                )
                if int(global_active or 0) >= global_concurrency_limit:
                    raise SubmissionError(
                        ErrorCode.CONCURRENCY_LIMITED,
                        "Сервис достиг общего лимита одновременных генераций.",
                        retryable=True,
                    )

                user_active = await session.scalar(
                    select(func.count(Generation.id)).where(
                        Generation.user_id == user_id,
                        Generation.status.in_(_ACTIVE_STATUS_VALUES),
                    )
                )
                if int(user_active or 0) >= user_concurrency_limit:
                    raise SubmissionError(
                        ErrorCode.CONCURRENCY_LIMITED,
                        "Дождитесь завершения текущих генераций перед новым запуском.",
                        retryable=True,
                    )

                await session.execute(
                    pg_insert(User)
                    .values(id=user_id, username=username)
                    .on_conflict_do_nothing(index_elements=[User.id])
                )
                if username:
                    await session.execute(
                        update(User).where(User.id == user_id).values(username=username)
                    )

                insert_result = await session.execute(
                    pg_insert(Generation)
                    .values(
                        user_id=user_id,
                        idempotency_key=idempotency_key,
                        request_hash=request_hash,
                        media_kind=media_kind,
                        model_slug=model_slug,
                        prompt=prompt,
                        status=GenerationStatus.QUEUED.value,
                        input_payload=input_payload,
                    )
                    .on_conflict_do_nothing(
                        index_elements=[Generation.user_id, Generation.idempotency_key]
                    )
                    .returning(Generation)
                )
                generation = insert_result.scalar_one_or_none()
                if generation is not None:
                    await session.execute(
                        pg_insert(OutboxEvent)
                        .values(
                            event_type="generation.submit",
                            aggregate_id=generation.id,
                            deduplication_key=f"generation.submit:{generation.id}",
                            payload={"generation_id": str(generation.id)},
                        )
                        .on_conflict_do_nothing(
                            index_elements=[OutboxEvent.deduplication_key]
                        )
                    )
                    return _snapshot(generation), True

                existing = await session.scalar(
                    select(Generation).where(
                        Generation.user_id == user_id,
                        Generation.idempotency_key == idempotency_key,
                    )
                )
                if existing is None:
                    raise SubmissionError(
                        ErrorCode.PROVIDER_PROTOCOL,
                        "Не удалось зафиксировать локальную задачу генерации.",
                        retryable=True,
                    )
                return _snapshot(existing), False

    async def transition(
        self,
        *,
        generation_id: UUID,
        expected: frozenset[GenerationStatus],
        target: GenerationStatus,
        provider_task_id: str | None = None,
        error_code: str | None = None,
    ) -> GenerationSnapshot:
        values: dict[str, object] = {
            "status": target.value,
            "error_code": error_code,
            "updated_at": func.now(),
        }
        if provider_task_id is not None:
            values["provider_task_id"] = provider_task_id
        if target == GenerationStatus.SUBMITTED:
            values["submitted_at"] = func.now()

        async with self._database.session() as session:
            async with session.begin():
                generation = await session.scalar(
                    update(Generation)
                    .where(
                        Generation.id == generation_id,
                        Generation.status.in_(tuple(status.value for status in expected)),
                    )
                    .values(**values)
                    .returning(Generation)
                )
                if generation is None:
                    generation = await session.get(Generation, generation_id)
                if generation is None:
                    raise SubmissionError(
                        ErrorCode.TASK_NOT_FOUND,
                        "Локальная задача генерации не найдена.",
                    )
                return _snapshot(generation)
