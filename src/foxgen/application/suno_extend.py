from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from foxgen.application.submissions import SubmissionReceipt, SubmissionService
from foxgen.core.errors import ErrorCode, SubmissionError


SUNO_EXTEND_MODEL_SLUG = "suno-v5-extend"
SUNO_SOURCE_MODEL_SLUGS = frozenset({"suno-v5", "suno-v5-extend"})


@dataclass(frozen=True, slots=True)
class SunoTrackRecord:
    generation_id: UUID
    model_slug: str
    audio_id: str
    title: str
    duration_seconds: float | None
    storage_key: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SunoTrackSource:
    generation_id: UUID
    model_slug: str
    audio_id: str
    title: str
    duration_seconds: float | None
    preview_url: str
    created_at: datetime


class SunoSourceRepository(Protocol):
    async def list_sources(
        self,
        *,
        user_id: int,
        limit: int = 40,
    ) -> tuple[SunoTrackRecord, ...]: ...

    async def get_source(
        self,
        *,
        user_id: int,
        generation_id: UUID,
        audio_id: str,
    ) -> SunoTrackRecord | None: ...


class SunoMediaSigner(Protocol):
    async def presigned_url(self, storage_key: str) -> str: ...


class SunoExtendService:
    def __init__(
        self,
        *,
        sources: SunoSourceRepository,
        submission: SubmissionService,
        media_signer: SunoMediaSigner,
    ) -> None:
        self._sources = sources
        self._submission = submission
        self._media_signer = media_signer

    async def list_sources(
        self,
        *,
        user_id: int,
        limit: int = 40,
    ) -> tuple[SunoTrackSource, ...]:
        records = await self._sources.list_sources(user_id=user_id, limit=max(1, min(limit, 100)))
        items: list[SunoTrackSource] = []
        for record in records:
            items.append(await self._public_source(record))
        return tuple(items)

    async def get_source(
        self,
        *,
        user_id: int,
        generation_id: UUID,
        audio_id: str,
    ) -> SunoTrackSource | None:
        record = await self._sources.get_source(
            user_id=user_id,
            generation_id=generation_id,
            audio_id=audio_id,
        )
        if record is None:
            return None
        return await self._public_source(record)

    async def extend(
        self,
        *,
        user_id: int,
        username: str | None,
        source_generation_id: UUID,
        audio_id: str,
        input_data: dict[str, object],
        idempotency_key: str,
    ) -> SubmissionReceipt:
        source = await self._sources.get_source(
            user_id=user_id,
            generation_id=source_generation_id,
            audio_id=audio_id,
        )
        if source is None or source.model_slug not in SUNO_SOURCE_MODEL_SLUGS:
            # Do not reveal whether a foreign generation/audio ID exists.
            raise SubmissionError(
                ErrorCode.TASK_NOT_FOUND,
                "Исходный Suno-трек не найден среди ваших завершённых генераций.",
            )

        payload = dict(input_data)
        payload["source_generation_id"] = source_generation_id
        payload["audio_id"] = source.audio_id

        default_param_flag = bool(payload.get("default_param_flag", False))
        continue_at = payload.get("continue_at")
        if default_param_flag and source.duration_seconds is not None:
            if not isinstance(continue_at, (int, float)) or isinstance(continue_at, bool):
                raise SubmissionError(
                    ErrorCode.VALIDATION,
                    "Для кастомного продолжения укажите точку продолжения в секундах.",
                )
            if float(continue_at) >= source.duration_seconds:
                raise SubmissionError(
                    ErrorCode.VALIDATION,
                    "Точка продолжения должна быть раньше конца исходного трека.",
                    details={"duration_seconds": source.duration_seconds},
                )

        return await self._submission.submit(
            user_id=user_id,
            username=username,
            model_slug=SUNO_EXTEND_MODEL_SLUG,
            input_data=payload,
            idempotency_key=idempotency_key,
        )

    async def _public_source(self, record: SunoTrackRecord) -> SunoTrackSource:
        preview_url = await self._media_signer.presigned_url(record.storage_key)
        return SunoTrackSource(
            generation_id=record.generation_id,
            model_slug=record.model_slug,
            audio_id=record.audio_id,
            title=record.title,
            duration_seconds=record.duration_seconds,
            preview_url=preview_url,
            created_at=record.created_at,
        )
