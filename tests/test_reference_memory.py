from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from foxgen.application.media import DownloadedMedia, StoredMedia
from foxgen.application.reference_memory import (
    ReferenceAssetSnapshot,
    ReferenceDeleteProcessor,
    ReferenceMemoryService,
)
from foxgen.bot.generation_capabilities import VideoGenerationType
from foxgen.bot.generation_draft import (
    default_image_flow_data,
    saved_reference_ids,
    stored_media,
    temporary_storage_keys,
)
from foxgen.bot.generation_keyboards import image_reference_keyboard, video_media_keyboard
from foxgen.core.errors import SubmissionError


ASSET_ID = UUID("11111111-1111-1111-1111-111111111111")
NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)


class FakeInputSource:
    def __init__(self, media: DownloadedMedia) -> None:
        self.media = media
        self.described: list[str] = []

    async def describe(self, storage_key: str) -> DownloadedMedia:
        self.described.append(storage_key)
        assert storage_key.startswith("inputs/")
        return self.media


class FakeStorage:
    def __init__(self) -> None:
        self.stored: list[str] = []
        self.deleted: list[str] = []

    async def store(self, *, key: str, media: DownloadedMedia) -> StoredMedia:
        self.stored.append(key)
        return StoredMedia(
            storage_key=key,
            content_type=media.content_type,
            size_bytes=media.size_bytes,
            checksum_sha256=media.checksum_sha256,
        )

    async def delete(self, storage_key: str) -> None:
        self.deleted.append(storage_key)


class FakeUrlSigner:
    async def url(self, asset_id: UUID) -> str:
        return f"https://foxgen.example/v1/reference-media/{asset_id}?signed=1"


class FakeRepository:
    def __init__(self) -> None:
        self.asset = ReferenceAssetSnapshot(
            id=ASSET_ID,
            user_id=42,
            storage_key=f"references/42/{ASSET_ID.hex}.png",
            content_type="image/png",
            size_bytes=128,
            checksum_sha256="a" * 64,
            status="uploading",
            created_at=NOW,
        )
        self.created = True
        self.delete_pending = False
        self.deleted = False

    async def reserve(self, **kwargs: object) -> tuple[ReferenceAssetSnapshot, bool]:
        self.asset = replace(
            self.asset,
            id=kwargs["asset_id"],
            user_id=int(kwargs["user_id"]),
            storage_key=str(kwargs["storage_key"]),
            content_type=str(kwargs["content_type"]),
            size_bytes=int(kwargs["size_bytes"]),
            checksum_sha256=str(kwargs["checksum_sha256"]),
        )
        return self.asset, self.created

    async def activate(self, asset_id: UUID) -> ReferenceAssetSnapshot:
        assert asset_id == self.asset.id
        self.asset = replace(self.asset, status="active")
        return self.asset

    async def mark_failed(self, asset_id: UUID) -> None:
        assert asset_id == self.asset.id
        self.asset = replace(self.asset, status="failed")

    async def list_active(
        self,
        *,
        user_id: int,
        offset: int,
        limit: int,
    ) -> tuple[tuple[ReferenceAssetSnapshot, ...], int, int]:
        del offset, limit
        if self.asset.user_id == user_id and self.asset.status == "active":
            return (self.asset,), 1, self.asset.size_bytes
        return (), 0, 0

    async def get_active_many(
        self,
        *,
        user_id: int,
        asset_ids: tuple[UUID, ...],
    ) -> tuple[ReferenceAssetSnapshot, ...]:
        if (
            self.asset.user_id == user_id
            and self.asset.status == "active"
            and self.asset.id in asset_ids
        ):
            return (self.asset,)
        return ()

    async def schedule_delete(
        self,
        *,
        user_id: int,
        asset_id: UUID,
    ) -> ReferenceAssetSnapshot:
        assert user_id == self.asset.user_id
        assert asset_id == self.asset.id
        self.delete_pending = True
        self.asset = replace(self.asset, status="delete_pending")
        return self.asset

    async def get_delete_pending(self, asset_id: UUID) -> ReferenceAssetSnapshot | None:
        if self.delete_pending and asset_id == self.asset.id:
            return self.asset
        return None

    async def mark_deleted(self, asset_id: UUID) -> None:
        assert asset_id == self.asset.id
        self.deleted = True
        self.asset = replace(self.asset, status="deleted")


def _media(tmp_path: Path) -> DownloadedMedia:
    path = tmp_path / "ref.png"
    path.write_bytes(b"png")
    return DownloadedMedia(
        path=path,
        filename="ref.png",
        content_type="image/png",
        size_bytes=128,
        checksum_sha256="a" * 64,
    )


def _service(
    repository: FakeRepository,
    source: FakeInputSource,
    storage: FakeStorage,
) -> ReferenceMemoryService:
    return ReferenceMemoryService(
        repository=repository,
        input_source=source,
        storage=storage,
        url_signer=FakeUrlSigner(),
        max_items=50,
        max_bytes=1024,
    )


@pytest.mark.asyncio
async def test_reference_service_copies_explicit_input_to_durable_prefix(tmp_path: Path) -> None:
    repository = FakeRepository()
    storage = FakeStorage()
    service = _service(repository, FakeInputSource(_media(tmp_path)), storage)

    result = await service.save_from_temporary_input(
        user_id=42,
        username="fox",
        storage_key="inputs/42/source.png",
    )

    assert result.duplicate is False
    assert result.item.id == repository.asset.id
    assert repository.asset.status == "active"
    assert storage.stored == [repository.asset.storage_key]
    assert repository.asset.storage_key.startswith("references/42/")
    assert "/v1/reference-media/" in result.item.preview_url


@pytest.mark.asyncio
async def test_reference_save_rejects_foreign_temporary_prefix_before_read(tmp_path: Path) -> None:
    source = FakeInputSource(_media(tmp_path))
    service = _service(FakeRepository(), source, FakeStorage())

    with pytest.raises(SubmissionError):
        await service.save_from_temporary_input(
            user_id=42,
            username="fox",
            storage_key="inputs/99/private.png",
        )

    assert source.described == []


@pytest.mark.asyncio
async def test_duplicate_reference_reuses_existing_asset_without_second_copy(
    tmp_path: Path,
) -> None:
    repository = FakeRepository()
    repository.asset = replace(repository.asset, status="active")
    repository.created = False
    storage = FakeStorage()
    service = _service(repository, FakeInputSource(_media(tmp_path)), storage)

    result = await service.save_from_temporary_input(
        user_id=42,
        username=None,
        storage_key="inputs/42/source.png",
    )

    assert result.duplicate is True
    assert storage.stored == []


@pytest.mark.asyncio
async def test_resolve_is_owner_scoped_and_rejects_missing_reference(tmp_path: Path) -> None:
    repository = FakeRepository()
    repository.asset = replace(repository.asset, status="active")
    service = _service(repository, FakeInputSource(_media(tmp_path)), FakeStorage())

    resolved = await service.resolve(user_id=42, asset_ids=(repository.asset.id,))
    assert resolved[0].id == repository.asset.id

    with pytest.raises(SubmissionError):
        await service.resolve(user_id=99, asset_ids=(repository.asset.id,))


@pytest.mark.asyncio
async def test_delete_processor_is_idempotent_and_removes_durable_object(tmp_path: Path) -> None:
    repository = FakeRepository()
    repository.asset = replace(repository.asset, status="active")
    service = _service(repository, FakeInputSource(_media(tmp_path)), FakeStorage())
    await service.delete(user_id=42, asset_id=repository.asset.id)

    storage = FakeStorage()
    processor = ReferenceDeleteProcessor(repository=repository, storage=storage)
    await processor.delete(repository.asset.id)
    await processor.delete(repository.asset.id)

    assert repository.deleted is True
    assert storage.deleted == [repository.asset.storage_key]


def test_draft_keeps_temporary_and_saved_reference_locators_separate() -> None:
    data = default_image_flow_data(42)
    data["media"] = [
        {"kind": "image", "storage_key": "inputs/42/a.png"},
        {"kind": "image", "reference_id": str(ASSET_ID)},
    ]
    media = stored_media(data)
    assert temporary_storage_keys(media) == ("inputs/42/a.png",)
    assert saved_reference_ids(media) == (str(ASSET_ID),)


def test_reference_keyboards_expose_memory_from_compatible_screens() -> None:
    image_callbacks = {
        button.callback_data
        for row in image_reference_keyboard(count=0, max_count=14).inline_keyboard
        for button in row
    }
    assert "gw:i:refs:memory" in image_callbacks

    video_callbacks = {
        button.callback_data
        for row in video_media_keyboard(
            generation_type=VideoGenerationType.REFERENCES,
            count=0,
            max_count=6,
            can_continue=False,
        ).inline_keyboard
        for button in row
    }
    assert "gw:v:media:memory" in video_callbacks

    text_callbacks = {
        button.callback_data
        for row in video_media_keyboard(
            generation_type=VideoGenerationType.TEXT,
            count=0,
            max_count=0,
            can_continue=True,
        ).inline_keyboard
        for button in row
    }
    assert "gw:v:media:memory" not in text_callbacks
