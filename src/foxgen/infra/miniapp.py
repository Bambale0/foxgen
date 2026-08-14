from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from foxgen.domain.models import MediaAssetStatus
from foxgen.infra.database import Database, Generation


class MediaUrlSigner(Protocol):
    async def presigned_url(self, storage_key: str) -> str: ...


@dataclass(frozen=True, slots=True)
class MiniAppMediaSnapshot:
    id: UUID
    url: str
    content_type: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class MiniAppGenerationSnapshot:
    id: UUID
    model_slug: str
    media_kind: str
    status: str
    prompt: str | None
    created_at: datetime
    completed_at: datetime | None
    error_code: str | None
    media: tuple[MiniAppMediaSnapshot, ...]


class SqlAlchemyMiniAppRepository:
    def __init__(self, database: Database, media_signer: MediaUrlSigner) -> None:
        self._database = database
        self._media_signer = media_signer

    async def list_recent(
        self,
        *,
        user_id: int,
        limit: int,
    ) -> tuple[MiniAppGenerationSnapshot, ...]:
        async with self._database.session() as session:
            items = tuple(
                (
                    await session.scalars(
                        select(Generation)
                        .where(Generation.user_id == user_id)
                        .options(selectinload(Generation.media_assets))
                        .order_by(Generation.created_at.desc(), Generation.id.desc())
                        .limit(limit)
                    )
                )
                .unique()
                .all()
            )
        return tuple([await self._snapshot(item) for item in items])

    async def get_for_user(
        self,
        *,
        generation_id: UUID,
        user_id: int,
    ) -> MiniAppGenerationSnapshot | None:
        async with self._database.session() as session:
            item = await session.scalar(
                select(Generation)
                .where(Generation.id == generation_id, Generation.user_id == user_id)
                .options(selectinload(Generation.media_assets))
            )
        if item is None:
            return None
        return await self._snapshot(item)

    async def _snapshot(self, generation: Generation) -> MiniAppGenerationSnapshot:
        media: list[MiniAppMediaSnapshot] = []
        for asset in generation.media_assets:
            if asset.status != MediaAssetStatus.STORED:
                continue
            url = await self._media_signer.presigned_url(asset.storage_key)
            media.append(
                MiniAppMediaSnapshot(
                    id=asset.id,
                    url=url,
                    content_type=asset.content_type,
                    size_bytes=asset.size_bytes,
                )
            )
        return MiniAppGenerationSnapshot(
            id=generation.id,
            model_slug=generation.model_slug,
            media_kind=str(generation.media_kind),
            status=str(generation.status),
            prompt=generation.prompt,
            created_at=generation.created_at,
            completed_at=generation.completed_at,
            error_code=generation.error_code,
            media=tuple(media),
        )
