from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from foxgen.application.delivery import (
    DeliveryGeneration,
    DeliverySnapshot,
    MediaAssetSnapshot,
)
from foxgen.application.lifecycle import (
    GenerationWorkItem,
    OutboxMessage,
    ProviderEventSnapshot,
)
from foxgen.core.errors import ErrorCode, SubmissionError
from foxgen.domain.models import (
    DeliveryStatus,
    GenerationStatus,
    MediaAssetStatus,
    OutboxStatus,
)
from foxgen.infra.database import (
    Database,
    Generation,
    GenerationDelivery,
    MediaAsset,
    OutboxEvent,
    ProviderEvent,
)


def _generation_item(generation: Generation) -> GenerationWorkItem:
    return GenerationWorkItem(
        id=generation.id,
        user_id=generation.user_id,
        model_slug=generation.model_slug,
        status=GenerationStatus(generation.status),
        input_payload=dict(generation.input_payload),
        result_payload=(
            dict(generation.result_payload) if generation.result_payload is not None else None
        ),
        provider_task_id=generation.provider_task_id,
    )


def _outbox_message(event: OutboxEvent) -> OutboxMessage:
    return OutboxMessage(
        id=event.id,
        event_type=event.event_type,
        aggregate_id=event.aggregate_id,
        payload=dict(event.payload),
        attempts=event.attempts,
    )


def _asset_snapshot(asset: MediaAsset) -> MediaAssetSnapshot:
    return MediaAssetSnapshot(
        id=asset.id,
        generation_id=asset.generation_id,
        source_url=asset.source_url,
        storage_key=asset.storage_key,
        content_type=asset.content_type,
        size_bytes=asset.size_bytes,
        checksum_sha256=asset.checksum_sha256,
    )


def _delivery_snapshot(delivery: GenerationDelivery) -> DeliverySnapshot:
    return DeliverySnapshot(
        id=delivery.id,
        generation_id=delivery.generation_id,
        recipient_id=delivery.recipient_id,
        status=DeliveryStatus(delivery.status),
    )


class SqlAlchemyLifecycleRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def claim_outbox(
        self,
        *,
        worker_id: str,
        limit: int,
        lease_seconds: int,
    ) -> tuple[OutboxMessage, ...]:
        now = datetime.now(timezone.utc)
        stale_before = now - timedelta(seconds=lease_seconds)
        async with self._database.session() as session:
            async with session.begin():
                events = tuple(
                    (
                        await session.scalars(
                            select(OutboxEvent)
                            .where(
                                or_(
                                    and_(
                                        OutboxEvent.status == OutboxStatus.PENDING.value,
                                        OutboxEvent.available_at <= now,
                                    ),
                                    and_(
                                        OutboxEvent.status == OutboxStatus.PROCESSING.value,
                                        OutboxEvent.locked_at.is_not(None),
                                        OutboxEvent.locked_at < stale_before,
                                    ),
                                )
                            )
                            .order_by(OutboxEvent.available_at, OutboxEvent.created_at)
                            .with_for_update(skip_locked=True)
                            .limit(limit)
                        )
                    ).all()
                )
                for event in events:
                    event.status = OutboxStatus.PROCESSING
                    event.worker_id = worker_id
                    event.locked_at = now
                    event.attempts += 1
                await session.flush()
                return tuple(_outbox_message(event) for event in events)

    async def complete_outbox(self, event_id: UUID) -> None:
        await self._set_outbox_state(
            event_id=event_id,
            status=OutboxStatus.COMPLETED,
            available_at=None,
            last_error=None,
        )

    async def retry_outbox(
        self,
        *,
        event_id: UUID,
        error: str,
        delay: timedelta,
        max_attempts: int,
    ) -> None:
        async with self._database.session() as session:
            async with session.begin():
                event = await session.get(OutboxEvent, event_id, with_for_update=True)
                if event is None:
                    return
                if event.attempts >= max_attempts:
                    event.status = OutboxStatus.FAILED
                else:
                    event.status = OutboxStatus.PENDING
                    event.available_at = datetime.now(timezone.utc) + delay
                event.last_error = error[:10_000]
                event.locked_at = None
                event.worker_id = None

    async def _set_outbox_state(
        self,
        *,
        event_id: UUID,
        status: OutboxStatus,
        available_at: datetime | None,
        last_error: str | None,
    ) -> None:
        values: dict[str, object] = {
            "status": status.value,
            "locked_at": None,
            "worker_id": None,
            "last_error": last_error,
            "updated_at": func.now(),
        }
        if available_at is not None:
            values["available_at"] = available_at
        async with self._database.session() as session:
            async with session.begin():
                await session.execute(
                    update(OutboxEvent).where(OutboxEvent.id == event_id).values(**values)
                )

    async def get_generation(self, generation_id: UUID) -> GenerationWorkItem | None:
        async with self._database.session() as session:
            generation = await session.get(Generation, generation_id)
            return _generation_item(generation) if generation is not None else None

    async def find_generation_by_provider_task_id(
        self,
        provider_task_id: str,
    ) -> GenerationWorkItem | None:
        async with self._database.session() as session:
            generation = await session.scalar(
                select(Generation).where(Generation.provider_task_id == provider_task_id)
            )
            return _generation_item(generation) if generation is not None else None

    async def transition_generation(
        self,
        *,
        generation_id: UUID,
        expected: frozenset[GenerationStatus],
        target: GenerationStatus,
        provider_task_id: str | None = None,
        result_payload: dict[str, object] | None = None,
        error_code: str | None = None,
    ) -> GenerationWorkItem:
        values: dict[str, object] = {
            "status": target.value,
            "error_code": error_code,
            "updated_at": func.now(),
        }
        if provider_task_id is not None:
            values["provider_task_id"] = provider_task_id
        if result_payload is not None:
            values["result_payload"] = result_payload
        if target == GenerationStatus.SUBMITTED:
            values["submitted_at"] = func.now()
            values["next_poll_at"] = datetime.now(timezone.utc) + timedelta(seconds=20)
        if target in {
            GenerationStatus.SUCCEEDED,
            GenerationStatus.FAILED,
            GenerationStatus.CANCELLED,
        }:
            values["completed_at"] = func.now()
            values["next_poll_at"] = None

        async with self._database.session() as session:
            async with session.begin():
                changed = await session.scalar(
                    update(Generation)
                    .where(
                        Generation.id == generation_id,
                        Generation.status.in_(tuple(status.value for status in expected)),
                    )
                    .values(**values)
                    .returning(Generation)
                )
                generation = changed
                if generation is None:
                    generation = await session.get(Generation, generation_id)
                if generation is None:
                    raise SubmissionError(
                        ErrorCode.TASK_NOT_FOUND,
                        "Локальная задача генерации не найдена.",
                    )

                if changed is not None and target == GenerationStatus.SUCCEEDED:
                    await session.execute(
                        pg_insert(OutboxEvent)
                        .values(
                            event_type="generation.archive",
                            aggregate_id=generation.id,
                            deduplication_key=f"generation.archive:{generation.id}",
                            payload={"generation_id": str(generation.id)},
                        )
                        .on_conflict_do_nothing(
                            index_elements=[OutboxEvent.deduplication_key]
                        )
                    )
                return _generation_item(generation)

    async def record_provider_event(
        self,
        *,
        provider: str,
        provider_task_id: str,
        event_hash: str,
        payload: dict[str, object],
    ) -> bool:
        async with self._database.session() as session:
            async with session.begin():
                inserted = await session.scalar(
                    pg_insert(ProviderEvent)
                    .values(
                        provider=provider,
                        provider_task_id=provider_task_id,
                        event_hash=event_hash,
                        payload=payload,
                    )
                    .on_conflict_do_nothing(index_elements=[ProviderEvent.event_hash])
                    .returning(ProviderEvent)
                )
                if inserted is None:
                    return False

                await session.execute(
                    pg_insert(OutboxEvent)
                    .values(
                        event_type="kie.callback",
                        aggregate_id=inserted.id,
                        deduplication_key=f"kie.callback:{inserted.event_hash}",
                        payload={"provider_event_id": str(inserted.id)},
                    )
                    .on_conflict_do_nothing(
                        index_elements=[OutboxEvent.deduplication_key]
                    )
                )
                return True

    async def get_provider_event(self, event_id: UUID) -> ProviderEventSnapshot | None:
        async with self._database.session() as session:
            event = await session.get(ProviderEvent, event_id)
            if event is None:
                return None
            return ProviderEventSnapshot(
                id=event.id,
                provider_task_id=event.provider_task_id,
                payload=dict(event.payload),
                processed=event.processed_at is not None,
            )

    async def mark_provider_event_processed(self, event_id: UUID) -> None:
        async with self._database.session() as session:
            async with session.begin():
                await session.execute(
                    update(ProviderEvent)
                    .where(ProviderEvent.id == event_id)
                    .values(processed_at=func.now())
                )

    async def list_pollable(self, limit: int) -> tuple[GenerationWorkItem, ...]:
        now = datetime.now(timezone.utc)
        async with self._database.session() as session:
            generations = tuple(
                (
                    await session.scalars(
                        select(Generation)
                        .where(
                            Generation.status == GenerationStatus.SUBMITTED.value,
                            Generation.provider_task_id.is_not(None),
                            or_(
                                Generation.next_poll_at.is_(None),
                                Generation.next_poll_at <= now,
                            ),
                        )
                        .order_by(Generation.next_poll_at, Generation.submitted_at)
                        .limit(limit)
                    )
                ).all()
            )
            return tuple(_generation_item(generation) for generation in generations)

    async def schedule_next_poll(
        self,
        *,
        generation_id: UUID,
        delay: timedelta,
    ) -> None:
        now = datetime.now(timezone.utc)
        async with self._database.session() as session:
            async with session.begin():
                await session.execute(
                    update(Generation)
                    .where(Generation.id == generation_id)
                    .values(
                        last_polled_at=now,
                        next_poll_at=now + delay,
                        updated_at=func.now(),
                    )
                )

    async def list_stale_submitting(
        self,
        *,
        older_than: datetime,
        limit: int,
    ) -> tuple[GenerationWorkItem, ...]:
        async with self._database.session() as session:
            generations = tuple(
                (
                    await session.scalars(
                        select(Generation)
                        .where(
                            Generation.status == GenerationStatus.SUBMITTING.value,
                            Generation.updated_at < older_than,
                        )
                        .order_by(Generation.updated_at)
                        .limit(limit)
                    )
                ).all()
            )
            return tuple(_generation_item(generation) for generation in generations)

    async def get_delivery_generation(
        self,
        generation_id: UUID,
    ) -> DeliveryGeneration | None:
        async with self._database.session() as session:
            generation = await session.get(Generation, generation_id)
            if generation is None:
                return None
            return DeliveryGeneration(
                id=generation.id,
                user_id=generation.user_id,
                status=GenerationStatus(generation.status),
                result_payload=(
                    dict(generation.result_payload)
                    if generation.result_payload is not None
                    else None
                ),
            )

    async def find_media_asset(
        self,
        *,
        generation_id: UUID,
        source_url: str,
    ) -> MediaAssetSnapshot | None:
        async with self._database.session() as session:
            asset = await session.scalar(
                select(MediaAsset).where(
                    MediaAsset.generation_id == generation_id,
                    MediaAsset.source_url == source_url,
                )
            )
            return _asset_snapshot(asset) if asset is not None else None

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
        async with self._database.session() as session:
            async with session.begin():
                inserted = await session.scalar(
                    pg_insert(MediaAsset)
                    .values(
                        generation_id=generation_id,
                        source_url=source_url,
                        storage_key=storage_key,
                        content_type=content_type,
                        size_bytes=size_bytes,
                        checksum_sha256=checksum_sha256,
                        status=MediaAssetStatus.STORED.value,
                    )
                    .on_conflict_do_nothing(
                        index_elements=[MediaAsset.generation_id, MediaAsset.source_url]
                    )
                    .returning(MediaAsset)
                )
                asset = inserted
                if asset is None:
                    asset = await session.scalar(
                        select(MediaAsset).where(
                            MediaAsset.generation_id == generation_id,
                            MediaAsset.source_url == source_url,
                        )
                    )
                if asset is None:
                    raise SubmissionError(
                        ErrorCode.PROVIDER_PROTOCOL,
                        "Не удалось сохранить метаданные результата генерации.",
                    )
                return _asset_snapshot(asset)

    async def list_media_assets(
        self,
        generation_id: UUID,
    ) -> tuple[MediaAssetSnapshot, ...]:
        async with self._database.session() as session:
            assets = tuple(
                (
                    await session.scalars(
                        select(MediaAsset)
                        .where(
                            MediaAsset.generation_id == generation_id,
                            MediaAsset.status == MediaAssetStatus.STORED.value,
                        )
                        .order_by(MediaAsset.created_at, MediaAsset.id)
                    )
                ).all()
            )
            return tuple(_asset_snapshot(asset) for asset in assets)

    async def ensure_delivery(
        self,
        *,
        generation_id: UUID,
        recipient_id: int,
    ) -> DeliverySnapshot:
        async with self._database.session() as session:
            async with session.begin():
                inserted = await session.scalar(
                    pg_insert(GenerationDelivery)
                    .values(
                        generation_id=generation_id,
                        recipient_id=recipient_id,
                        status=DeliveryStatus.PENDING.value,
                    )
                    .on_conflict_do_nothing(
                        index_elements=[GenerationDelivery.generation_id]
                    )
                    .returning(GenerationDelivery)
                )
                delivery = inserted
                if delivery is None:
                    delivery = await session.scalar(
                        select(GenerationDelivery).where(
                            GenerationDelivery.generation_id == generation_id
                        )
                    )
                if delivery is None:
                    raise SubmissionError(
                        ErrorCode.PROVIDER_PROTOCOL,
                        "Не удалось создать доставку результата.",
                    )
                await session.execute(
                    pg_insert(OutboxEvent)
                    .values(
                        event_type="generation.deliver",
                        aggregate_id=generation_id,
                        deduplication_key=f"generation.deliver:{generation_id}",
                        payload={"generation_id": str(generation_id)},
                    )
                    .on_conflict_do_nothing(
                        index_elements=[OutboxEvent.deduplication_key]
                    )
                )
                return _delivery_snapshot(delivery)

    async def get_delivery(self, generation_id: UUID) -> DeliverySnapshot | None:
        async with self._database.session() as session:
            delivery = await session.scalar(
                select(GenerationDelivery).where(
                    GenerationDelivery.generation_id == generation_id
                )
            )
            return _delivery_snapshot(delivery) if delivery is not None else None

    async def begin_delivery(
        self,
        *,
        delivery_id: UUID,
        outbox_event_id: UUID,
    ) -> bool:
        async with self._database.session() as session:
            async with session.begin():
                delivery = await session.scalar(
                    update(GenerationDelivery)
                    .where(
                        GenerationDelivery.id == delivery_id,
                        GenerationDelivery.status == DeliveryStatus.PENDING.value,
                    )
                    .values(
                        status=DeliveryStatus.SENDING.value,
                        attempts=GenerationDelivery.attempts + 1,
                        updated_at=func.now(),
                    )
                    .returning(GenerationDelivery)
                )
                await session.execute(
                    update(OutboxEvent)
                    .where(OutboxEvent.id == outbox_event_id)
                    .values(
                        status=OutboxStatus.COMPLETED.value,
                        locked_at=None,
                        worker_id=None,
                        last_error=None,
                        updated_at=func.now(),
                    )
                )
                return delivery is not None

    async def mark_delivery_sent(
        self,
        *,
        delivery_id: UUID,
        message_ids: list[int],
    ) -> None:
        async with self._database.session() as session:
            async with session.begin():
                await session.execute(
                    update(GenerationDelivery)
                    .where(GenerationDelivery.id == delivery_id)
                    .values(
                        status=DeliveryStatus.SENT.value,
                        telegram_message_ids=message_ids,
                        sent_at=func.now(),
                        last_error=None,
                        updated_at=func.now(),
                    )
                )

    async def mark_delivery_unknown(
        self,
        *,
        delivery_id: UUID,
        error: str,
    ) -> None:
        async with self._database.session() as session:
            async with session.begin():
                await session.execute(
                    update(GenerationDelivery)
                    .where(GenerationDelivery.id == delivery_id)
                    .values(
                        status=DeliveryStatus.DELIVERY_UNKNOWN.value,
                        last_error=error[:10_000],
                        updated_at=func.now(),
                    )
                )
