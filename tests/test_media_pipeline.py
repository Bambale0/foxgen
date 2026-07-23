from dataclasses import replace
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

import pytest

from foxgen.application.delivery import (
    DeliveryGeneration,
    DeliverySnapshot,
    MediaAssetSnapshot,
    MediaPipeline,
)
from foxgen.application.lifecycle import OutboxMessage
from foxgen.application.media import DownloadedMedia, StoredMedia
from foxgen.domain.models import DeliveryStatus, GenerationStatus


GENERATION_ID = UUID("66666666-6666-6666-6666-666666666666")
ARCHIVE_EVENT_ID = UUID("77777777-7777-7777-7777-777777777777")
DELIVERY_EVENT_ID = UUID("88888888-8888-8888-8888-888888888888")
DELIVERY_ID = UUID("99999999-9999-9999-9999-999999999999")
ASSET_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
SOURCE_URL = "https://cdn.example.com/result.png"


class FakePipelineRepository:
    def __init__(self) -> None:
        self.generation = DeliveryGeneration(
            id=GENERATION_ID,
            user_id=42,
            status=GenerationStatus.SUCCEEDED,
            result_payload={"resultUrls": [SOURCE_URL]},
        )
        self.assets: dict[str, MediaAssetSnapshot] = {}
        self.delivery: DeliverySnapshot | None = None
        self.completed_events: list[UUID] = []
        self.sent_message_ids: list[int] = []
        self.unknown_error: str | None = None

    async def get_delivery_generation(
        self,
        generation_id: UUID,
    ) -> DeliveryGeneration | None:
        return self.generation if generation_id == GENERATION_ID else None

    async def find_media_asset(
        self,
        *,
        generation_id: UUID,
        source_url: str,
    ) -> MediaAssetSnapshot | None:
        assert generation_id == GENERATION_ID
        return self.assets.get(source_url)

    async def record_media_asset(
        self,
        *,
        generation_id: UUID,
        source_url: str,
        storage_key: str,
        content_type: str,
        size_bytes: int,
        checksum_sha256: str,
    ) -> MediaAssetSnapshot:
        asset = MediaAssetSnapshot(
            id=ASSET_ID,
            generation_id=generation_id,
            source_url=source_url,
            storage_key=storage_key,
            content_type=content_type,
            size_bytes=size_bytes,
            checksum_sha256=checksum_sha256,
        )
        self.assets[source_url] = asset
        return asset

    async def list_media_assets(
        self,
        generation_id: UUID,
    ) -> tuple[MediaAssetSnapshot, ...]:
        assert generation_id == GENERATION_ID
        return tuple(self.assets.values())

    async def ensure_delivery(
        self,
        *,
        generation_id: UUID,
        recipient_id: int,
    ) -> DeliverySnapshot:
        assert generation_id == GENERATION_ID
        self.delivery = DeliverySnapshot(
            id=DELIVERY_ID,
            generation_id=generation_id,
            recipient_id=recipient_id,
            status=DeliveryStatus.PENDING,
        )
        return self.delivery

    async def get_delivery(self, generation_id: UUID) -> DeliverySnapshot | None:
        assert generation_id == GENERATION_ID
        return self.delivery

    async def begin_delivery(
        self,
        *,
        delivery_id: UUID,
        outbox_event_id: UUID,
    ) -> bool:
        assert self.delivery is not None
        assert delivery_id == self.delivery.id
        assert self.delivery.status == DeliveryStatus.PENDING
        self.delivery = replace(self.delivery, status=DeliveryStatus.SENDING)
        self.completed_events.append(outbox_event_id)
        return True

    async def mark_delivery_sent(
        self,
        *,
        delivery_id: UUID,
        message_ids: list[int],
    ) -> None:
        assert self.delivery is not None
        assert delivery_id == self.delivery.id
        self.delivery = replace(self.delivery, status=DeliveryStatus.SENT)
        self.sent_message_ids = message_ids

    async def mark_delivery_unknown(
        self,
        *,
        delivery_id: UUID,
        error: str,
    ) -> None:
        assert self.delivery is not None
        assert delivery_id == self.delivery.id
        self.delivery = replace(self.delivery, status=DeliveryStatus.DELIVERY_UNKNOWN)
        self.unknown_error = error

    async def complete_outbox(self, event_id: UUID) -> None:
        self.completed_events.append(event_id)


class FakeDownloader:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def download(self, url: str) -> DownloadedMedia:
        self.calls.append(url)
        temporary = NamedTemporaryFile(delete=False)
        temporary.write(b"fox-image")
        temporary.close()
        return DownloadedMedia(
            path=Path(temporary.name),
            filename="result.png",
            content_type="image/png",
            size_bytes=9,
            checksum_sha256="a" * 64,
        )


class FakeStorage:
    def __init__(self) -> None:
        self.stored_keys: list[str] = []

    async def store(self, *, key: str, media: DownloadedMedia) -> StoredMedia:
        assert media.path.exists()
        self.stored_keys.append(key)
        return StoredMedia(
            storage_key=key,
            content_type=media.content_type,
            size_bytes=media.size_bytes,
            checksum_sha256=media.checksum_sha256,
        )

    async def presigned_url(self, storage_key: str) -> str:
        return f"https://storage.example.com/{storage_key}?signature=test"


class FakeSender:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[int, list[str]]] = []

    async def send(
        self,
        *,
        recipient_id: int,
        urls: list[str],
        caption: str,
    ) -> list[int]:
        assert "Генерация готова" in caption
        self.calls.append((recipient_id, urls))
        if self.error is not None:
            raise self.error
        return [1234]


@pytest.mark.asyncio
async def test_archive_downloads_stores_and_enqueues_delivery() -> None:
    repository = FakePipelineRepository()
    downloader = FakeDownloader()
    storage = FakeStorage()
    pipeline = MediaPipeline(
        repository=repository,
        downloader=downloader,
        storage=storage,
        sender=FakeSender(),
    )

    await pipeline.process(
        OutboxMessage(
            id=ARCHIVE_EVENT_ID,
            event_type="generation.archive",
            aggregate_id=GENERATION_ID,
            payload={},
            attempts=1,
        )
    )

    assert downloader.calls == [SOURCE_URL]
    assert len(storage.stored_keys) == 1
    assert repository.assets[SOURCE_URL].storage_key == storage.stored_keys[0]
    assert repository.delivery is not None
    assert repository.delivery.recipient_id == 42
    assert repository.completed_events == [ARCHIVE_EVENT_ID]


@pytest.mark.asyncio
async def test_delivery_uses_presigned_storage_url_and_marks_sent() -> None:
    repository = FakePipelineRepository()
    repository.assets[SOURCE_URL] = MediaAssetSnapshot(
        id=ASSET_ID,
        generation_id=GENERATION_ID,
        source_url=SOURCE_URL,
        storage_key="generations/id/result.png",
        content_type="image/png",
        size_bytes=9,
        checksum_sha256="a" * 64,
    )
    await repository.ensure_delivery(generation_id=GENERATION_ID, recipient_id=42)
    sender = FakeSender()
    pipeline = MediaPipeline(
        repository=repository,
        downloader=FakeDownloader(),
        storage=FakeStorage(),
        sender=sender,
    )

    await pipeline.process(
        OutboxMessage(
            id=DELIVERY_EVENT_ID,
            event_type="generation.deliver",
            aggregate_id=GENERATION_ID,
            payload={},
            attempts=1,
        )
    )

    assert sender.calls[0][0] == 42
    assert sender.calls[0][1][0].startswith("https://storage.example.com/")
    assert repository.delivery is not None
    assert repository.delivery.status == DeliveryStatus.SENT
    assert repository.sent_message_ids == [1234]
    assert repository.completed_events == [DELIVERY_EVENT_ID]


@pytest.mark.asyncio
async def test_ambiguous_telegram_send_is_not_automatically_replayed() -> None:
    repository = FakePipelineRepository()
    repository.assets[SOURCE_URL] = MediaAssetSnapshot(
        id=ASSET_ID,
        generation_id=GENERATION_ID,
        source_url=SOURCE_URL,
        storage_key="generations/id/result.png",
        content_type="image/png",
        size_bytes=9,
        checksum_sha256="a" * 64,
    )
    await repository.ensure_delivery(generation_id=GENERATION_ID, recipient_id=42)
    pipeline = MediaPipeline(
        repository=repository,
        downloader=FakeDownloader(),
        storage=FakeStorage(),
        sender=FakeSender(RuntimeError("response lost")),
    )

    await pipeline.process(
        OutboxMessage(
            id=DELIVERY_EVENT_ID,
            event_type="generation.deliver",
            aggregate_id=GENERATION_ID,
            payload={},
            attempts=1,
        )
    )

    assert repository.delivery is not None
    assert repository.delivery.status == DeliveryStatus.DELIVERY_UNKNOWN
    assert repository.unknown_error is not None
    assert repository.completed_events == [DELIVERY_EVENT_ID]
