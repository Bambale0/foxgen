from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from foxgen.application.media import DownloadedMedia, StoredMedia
from foxgen.core.errors import ErrorCode, SubmissionError


@dataclass(frozen=True, slots=True)
class ReferenceAssetSnapshot:
    id: UUID
    user_id: int
    storage_key: str
    content_type: str
    size_bytes: int
    checksum_sha256: str
    status: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ReferenceMemoryItem:
    id: UUID
    content_type: str
    size_bytes: int
    created_at: datetime
    preview_url: str


@dataclass(frozen=True, slots=True)
class ReferenceMemoryPage:
    items: tuple[ReferenceMemoryItem, ...]
    total: int
    used_bytes: int
    max_items: int
    max_bytes: int


@dataclass(frozen=True, slots=True)
class ReferenceSaveResult:
    item: ReferenceMemoryItem
    duplicate: bool


class TemporaryInputSource(Protocol):
    async def describe(self, storage_key: str) -> DownloadedMedia: ...


class ReferenceObjectStorage(Protocol):
    async def store(self, *, key: str, media: DownloadedMedia) -> StoredMedia: ...

    async def delete(self, storage_key: str) -> None: ...

    async def presigned_url(self, storage_key: str) -> str: ...


class ReferenceMemoryRepository(Protocol):
    async def reserve(
        self,
        *,
        asset_id: UUID,
        user_id: int,
        username: str | None,
        storage_key: str,
        content_type: str,
        size_bytes: int,
        checksum_sha256: str,
        max_items: int,
        max_bytes: int,
    ) -> tuple[ReferenceAssetSnapshot, bool]: ...

    async def activate(self, asset_id: UUID) -> ReferenceAssetSnapshot: ...

    async def mark_failed(self, asset_id: UUID) -> None: ...

    async def list_active(
        self,
        *,
        user_id: int,
        offset: int,
        limit: int,
    ) -> tuple[tuple[ReferenceAssetSnapshot, ...], int, int]: ...

    async def get_active_many(
        self,
        *,
        user_id: int,
        asset_ids: tuple[UUID, ...],
    ) -> tuple[ReferenceAssetSnapshot, ...]: ...

    async def schedule_delete(
        self,
        *,
        user_id: int,
        asset_id: UUID,
    ) -> ReferenceAssetSnapshot: ...

    async def get_delete_pending(self, asset_id: UUID) -> ReferenceAssetSnapshot | None: ...

    async def mark_deleted(self, asset_id: UUID) -> None: ...


class ReferenceMemoryService:
    def __init__(
        self,
        *,
        repository: ReferenceMemoryRepository,
        input_source: TemporaryInputSource,
        storage: ReferenceObjectStorage,
        max_items: int,
        max_bytes: int,
    ) -> None:
        self._repository = repository
        self._input_source = input_source
        self._storage = storage
        self._max_items = max_items
        self._max_bytes = max_bytes

    async def save_from_temporary_input(
        self,
        *,
        user_id: int,
        username: str | None,
        storage_key: str,
    ) -> ReferenceSaveResult:
        if user_id <= 0:
            raise SubmissionError(ErrorCode.VALIDATION, "Не удалось определить пользователя.")
        if not storage_key.startswith("inputs/"):
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "В память можно сохранить только текущий приватный входной файл.",
            )

        media = await self._input_source.describe(storage_key)
        if not media.content_type.startswith("image/"):
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "В память референсов можно сохранять только изображения.",
            )
        if media.size_bytes > self._max_bytes:
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "Изображение превышает общий лимит памяти референсов.",
            )

        asset_id = uuid4()
        persistent_key = _reference_storage_key(
            user_id=user_id,
            asset_id=asset_id,
            content_type=media.content_type,
        )
        reserved, created = await self._repository.reserve(
            asset_id=asset_id,
            user_id=user_id,
            username=username,
            storage_key=persistent_key,
            content_type=media.content_type,
            size_bytes=media.size_bytes,
            checksum_sha256=media.checksum_sha256,
            max_items=self._max_items,
            max_bytes=self._max_bytes,
        )
        if not created:
            return ReferenceSaveResult(
                item=await self._item(reserved),
                duplicate=True,
            )

        try:
            await self._storage.store(key=reserved.storage_key, media=media)
            active = await self._repository.activate(reserved.id)
        except Exception:
            await self._repository.mark_failed(reserved.id)
            try:
                await self._storage.delete(reserved.storage_key)
            except Exception:
                pass
            raise
        return ReferenceSaveResult(item=await self._item(active), duplicate=False)

    async def list(
        self,
        *,
        user_id: int,
        offset: int = 0,
        limit: int = 20,
    ) -> ReferenceMemoryPage:
        if user_id <= 0:
            raise SubmissionError(ErrorCode.VALIDATION, "Не удалось определить пользователя.")
        if offset < 0 or limit < 1 or limit > 100:
            raise SubmissionError(ErrorCode.VALIDATION, "Некорректная страница памяти референсов.")
        assets, total, used_bytes = await self._repository.list_active(
            user_id=user_id,
            offset=offset,
            limit=limit,
        )
        return ReferenceMemoryPage(
            items=tuple([await self._item(asset) for asset in assets]),
            total=total,
            used_bytes=used_bytes,
            max_items=self._max_items,
            max_bytes=self._max_bytes,
        )

    async def resolve(
        self,
        *,
        user_id: int,
        asset_ids: tuple[UUID, ...],
    ) -> tuple[ReferenceMemoryItem, ...]:
        if not asset_ids:
            return ()
        if len(asset_ids) > 50 or len(set(asset_ids)) != len(asset_ids):
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "Список референсов повреждён или содержит дубликаты.",
            )
        assets = await self._repository.get_active_many(user_id=user_id, asset_ids=asset_ids)
        by_id = {asset.id: asset for asset in assets}
        missing = [asset_id for asset_id in asset_ids if asset_id not in by_id]
        if missing:
            raise SubmissionError(
                ErrorCode.AUTHORIZATION,
                "Один или несколько сохранённых референсов недоступны.",
            )
        return tuple([await self._item(by_id[asset_id]) for asset_id in asset_ids])

    async def delete(self, *, user_id: int, asset_id: UUID) -> None:
        await self._repository.schedule_delete(user_id=user_id, asset_id=asset_id)

    async def _item(self, asset: ReferenceAssetSnapshot) -> ReferenceMemoryItem:
        return ReferenceMemoryItem(
            id=asset.id,
            content_type=asset.content_type,
            size_bytes=asset.size_bytes,
            created_at=asset.created_at,
            preview_url=await self._storage.presigned_url(asset.storage_key),
        )


class ReferenceDeleteProcessor:
    """Idempotently delete S3 bytes after a transactional reference.delete outbox event."""

    def __init__(
        self,
        *,
        repository: ReferenceMemoryRepository,
        storage: ReferenceObjectStorage,
    ) -> None:
        self._repository = repository
        self._storage = storage

    async def delete(self, asset_id: UUID) -> None:
        asset = await self._repository.get_delete_pending(asset_id)
        if asset is None:
            return
        await self._storage.delete(asset.storage_key)
        await self._repository.mark_deleted(asset.id)


def _reference_storage_key(*, user_id: int, asset_id: UUID, content_type: str) -> str:
    suffix = mimetypes.guess_extension(content_type.partition(";")[0].strip()) or ".img"
    if len(suffix) > 12 or not suffix.startswith("."):
        suffix = ".img"
    return f"references/{user_id}/{asset_id.hex}{suffix.lower()}"
