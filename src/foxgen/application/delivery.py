from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from foxgen.application.lifecycle import OutboxMessage
from foxgen.application.media import (
    MediaDownloader,
    MediaSender,
    MediaStorage,
    extract_result_urls,
    storage_key_for,
)
from foxgen.core.errors import ErrorCode, SubmissionError
from foxgen.domain.models import DeliveryStatus, GenerationStatus


@dataclass(frozen=True, slots=True)
class DeliveryGeneration:
    id: UUID
    user_id: int
    status: GenerationStatus
    result_payload: dict[str, object] | None


@dataclass(frozen=True, slots=True)
class MediaAssetSnapshot:
    id: UUID
    generation_id: UUID
    source_url: str
    storage_key: str
    content_type: str
    size_bytes: int
    checksum_sha256: str


@dataclass(frozen=True, slots=True)
class DeliverySnapshot:
    id: UUID
    generation_id: UUID
    recipient_id: int
    status: DeliveryStatus


class MediaPipelineRepository(Protocol):
    async def get_delivery_generation(
        self,
        generation_id: UUID,
    ) -> DeliveryGeneration | None: ...

    async def find_media_asset(
        self,
        *,
        generation_id: UUID,
        source_url: str,
    ) -> MediaAssetSnapshot | None: ...

    async def record_media_asset(
        self,
        *,
        generation_id: UUID,
        source_url: str,
        storage_key: str,
        content_type: str,
        size_bytes: int,
        checksum_sha256: str,
    ) -> MediaAssetSnapshot: ...

    async def list_media_assets(
        self,
        generation_id: UUID,
    ) -> tuple[MediaAssetSnapshot, ...]: ...

    async def ensure_delivery(
        self,
        *,
        generation_id: UUID,
        recipient_id: int,
    ) -> DeliverySnapshot: ...

    async def get_delivery(self, generation_id: UUID) -> DeliverySnapshot | None: ...

    async def begin_delivery(
        self,
        *,
        delivery_id: UUID,
        outbox_event_id: UUID,
    ) -> bool: ...

    async def mark_delivery_sent(
        self,
        *,
        delivery_id: UUID,
        message_ids: list[int],
    ) -> None: ...

    async def mark_delivery_unknown(
        self,
        *,
        delivery_id: UUID,
        error: str,
    ) -> None: ...

    async def complete_outbox(self, event_id: UUID) -> None: ...


class MediaPipeline:
    def __init__(
        self,
        *,
        repository: MediaPipelineRepository,
        downloader: MediaDownloader,
        storage: MediaStorage,
        sender: MediaSender,
    ) -> None:
        self._repository = repository
        self._downloader = downloader
        self._storage = storage
        self._sender = sender

    async def process(self, message: OutboxMessage) -> None:
        if message.event_type == "generation.archive":
            await self._archive(message)
            return
        if message.event_type == "generation.deliver":
            await self._deliver(message)
            return
        raise SubmissionError(
            ErrorCode.VALIDATION,
            f"Unknown media pipeline event: {message.event_type}",
        )

    async def _archive(self, message: OutboxMessage) -> None:
        generation = await self._repository.get_delivery_generation(message.aggregate_id)
        if generation is None:
            raise SubmissionError(ErrorCode.TASK_NOT_FOUND, "Generation not found")
        if generation.status != GenerationStatus.SUCCEEDED:
            await self._repository.complete_outbox(message.id)
            return
        if generation.result_payload is None:
            raise SubmissionError(
                ErrorCode.PROVIDER_PROTOCOL,
                "Успешная генерация не содержит результата для сохранения.",
            )

        source_urls = extract_result_urls(generation.result_payload)
        if not source_urls:
            raise SubmissionError(
                ErrorCode.PROVIDER_PROTOCOL,
                "Провайдер не вернул ссылок на результат генерации.",
            )

        for index, source_url in enumerate(source_urls):
            existing = await self._repository.find_media_asset(
                generation_id=generation.id,
                source_url=source_url,
            )
            if existing is not None:
                continue

            downloaded = await self._downloader.download(source_url)
            try:
                key = storage_key_for(
                    generation_id=str(generation.id),
                    index=index,
                    media=downloaded,
                )
                stored = await self._storage.store(key=key, media=downloaded)
                await self._repository.record_media_asset(
                    generation_id=generation.id,
                    source_url=source_url,
                    storage_key=stored.storage_key,
                    content_type=stored.content_type,
                    size_bytes=stored.size_bytes,
                    checksum_sha256=stored.checksum_sha256,
                )
            finally:
                downloaded.cleanup()

        await self._repository.ensure_delivery(
            generation_id=generation.id,
            recipient_id=generation.user_id,
        )
        await self._repository.complete_outbox(message.id)

    async def _deliver(self, message: OutboxMessage) -> None:
        delivery = await self._repository.get_delivery(message.aggregate_id)
        if delivery is None:
            raise SubmissionError(ErrorCode.TASK_NOT_FOUND, "Delivery not found")
        if delivery.status in {
            DeliveryStatus.SENT,
            DeliveryStatus.DELIVERY_UNKNOWN,
            DeliveryStatus.FAILED,
        }:
            await self._repository.complete_outbox(message.id)
            return
        if delivery.status != DeliveryStatus.PENDING:
            raise SubmissionError(
                ErrorCode.VALIDATION,
                f"Delivery is not ready: {delivery.status}",
                retryable=True,
            )

        assets = await self._repository.list_media_assets(delivery.generation_id)
        if not assets:
            raise SubmissionError(
                ErrorCode.TASK_NOT_FOUND,
                "Сохранённые медиафайлы для доставки не найдены.",
                retryable=True,
            )
        urls = [await self._storage.presigned_url(asset.storage_key) for asset in assets]

        started = await self._repository.begin_delivery(
            delivery_id=delivery.id,
            outbox_event_id=message.id,
        )
        if not started:
            return

        caption = f"✅ Генерация готова\nID: <code>{delivery.generation_id}</code>"
        try:
            message_ids = await self._sender.send(
                recipient_id=delivery.recipient_id,
                urls=urls,
                caption=caption,
            )
        except Exception as exc:
            # Telegram send is not idempotent. Do not automatically replay an ambiguous send.
            await self._repository.mark_delivery_unknown(
                delivery_id=delivery.id,
                error=f"{type(exc).__name__}: {exc}",
            )
            return

        await self._repository.mark_delivery_sent(
            delivery_id=delivery.id,
            message_ids=message_ids,
        )
