from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import select

from foxgen.application.suno_extend import SUNO_SOURCE_MODEL_SLUGS, SunoTrackRecord
from foxgen.domain.models import GenerationStatus, MediaAssetStatus
from foxgen.infra.database import Database, Generation, MediaAsset


class SqlAlchemySunoSourceRepository:
    """Read owner-scoped extendable Suno tracks from succeeded durable generations."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def list_sources(
        self,
        *,
        user_id: int,
        limit: int = 40,
    ) -> tuple[SunoTrackRecord, ...]:
        async with self._database.session() as session:
            generations = (
                await session.scalars(
                    select(Generation)
                    .where(
                        Generation.user_id == user_id,
                        Generation.status == GenerationStatus.SUCCEEDED,
                        Generation.model_slug.in_(SUNO_SOURCE_MODEL_SLUGS),
                    )
                    .order_by(Generation.created_at.desc(), Generation.id.desc())
                    .limit(max(1, min(limit, 100)))
                )
            ).all()
            items: list[SunoTrackRecord] = []
            for generation in generations:
                items.extend(await _records_for_generation(session, generation))
                if len(items) >= limit:
                    break
            return tuple(items[:limit])

    async def get_source(
        self,
        *,
        user_id: int,
        generation_id: UUID,
        audio_id: str,
    ) -> SunoTrackRecord | None:
        async with self._database.session() as session:
            generation = await session.scalar(
                select(Generation).where(
                    Generation.id == generation_id,
                    Generation.user_id == user_id,
                    Generation.status == GenerationStatus.SUCCEEDED,
                    Generation.model_slug.in_(SUNO_SOURCE_MODEL_SLUGS),
                )
            )
            if generation is None:
                return None
            records = await _records_for_generation(session, generation)
            return next((item for item in records if item.audio_id == audio_id), None)


async def _records_for_generation(session: Any, generation: Generation) -> list[SunoTrackRecord]:
    result = generation.result_payload
    if not isinstance(result, Mapping):
        return []
    raw_tracks = result.get("tracks")
    raw_urls = result.get("audioUrls")
    if not isinstance(raw_tracks, list) or not isinstance(raw_urls, list):
        return []

    stored_assets = (
        await session.scalars(
            select(MediaAsset).where(
                MediaAsset.generation_id == generation.id,
                MediaAsset.status == MediaAssetStatus.STORED,
            )
        )
    ).all()
    by_source = {asset.source_url: asset for asset in stored_assets}

    items: list[SunoTrackRecord] = []
    for index, raw_track in enumerate(raw_tracks):
        if not isinstance(raw_track, Mapping) or index >= len(raw_urls):
            continue
        audio_id = raw_track.get("id")
        audio_url = raw_urls[index]
        if not isinstance(audio_id, str) or not audio_id:
            continue
        if not isinstance(audio_url, str):
            continue
        asset = by_source.get(audio_url)
        if asset is None:
            continue
        title_value = raw_track.get("title")
        title = title_value.strip() if isinstance(title_value, str) and title_value.strip() else "Suno track"
        duration_value = raw_track.get("duration")
        duration: float | None = None
        if isinstance(duration_value, (int, float)) and not isinstance(duration_value, bool):
            numeric = float(duration_value)
            if numeric > 0:
                duration = numeric
        items.append(
            SunoTrackRecord(
                generation_id=generation.id,
                model_slug=generation.model_slug,
                audio_id=audio_id,
                title=title,
                duration_seconds=duration,
                storage_key=asset.storage_key,
                created_at=generation.created_at,
            )
        )
    return items
