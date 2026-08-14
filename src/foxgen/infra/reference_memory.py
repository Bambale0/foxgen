from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from foxgen.application.reference_memory import ReferenceAssetSnapshot
from foxgen.core.errors import ErrorCode, SubmissionError
from foxgen.infra.database import Database, OutboxEvent, ReferenceAsset, User


_ACTIVE_QUOTA_STATUSES = ("uploading", "active")


def _snapshot(asset: ReferenceAsset) -> ReferenceAssetSnapshot:
    return ReferenceAssetSnapshot(
        id=asset.id,
        user_id=asset.user_id,
        storage_key=asset.storage_key,
        content_type=asset.content_type,
        size_bytes=asset.size_bytes,
        checksum_sha256=asset.checksum_sha256,
        status=asset.status,
        created_at=asset.created_at,
    )


class SqlAlchemyReferenceMemoryRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

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
    ) -> tuple[ReferenceAssetSnapshot, bool]:
        async with self._database.session() as session:
            async with session.begin():
                await session.execute(
                    pg_insert(User)
                    .values(id=user_id, username=username)
                    .on_conflict_do_nothing(index_elements=[User.id])
                )
                await session.scalar(select(User).where(User.id == user_id).with_for_update())
                if username:
                    await session.execute(
                        update(User).where(User.id == user_id).values(username=username)
                    )

                existing = await session.scalar(
                    select(ReferenceAsset)
                    .where(
                        ReferenceAsset.user_id == user_id,
                        ReferenceAsset.checksum_sha256 == checksum_sha256,
                        ReferenceAsset.status == "active",
                    )
                    .order_by(ReferenceAsset.created_at.desc())
                    .limit(1)
                )
                if existing is not None:
                    return _snapshot(existing), False

                usage_row = (
                    await session.execute(
                        select(
                            func.count(ReferenceAsset.id),
                            func.coalesce(func.sum(ReferenceAsset.size_bytes), 0),
                        ).where(
                            ReferenceAsset.user_id == user_id,
                            ReferenceAsset.status.in_(_ACTIVE_QUOTA_STATUSES),
                        )
                    )
                ).one()
                item_count = int(usage_row[0] or 0)
                used_bytes = int(usage_row[1] or 0)
                if item_count >= max_items:
                    raise SubmissionError(
                        ErrorCode.VALIDATION,
                        f"Память референсов заполнена: максимум {max_items} изображений.",
                        details={"max_items": max_items},
                    )
                if used_bytes + size_bytes > max_bytes:
                    raise SubmissionError(
                        ErrorCode.VALIDATION,
                        "Недостаточно места в памяти референсов. Удалите несколько изображений.",
                        details={"max_bytes": max_bytes, "used_bytes": used_bytes},
                    )

                asset = ReferenceAsset(
                    id=asset_id,
                    user_id=user_id,
                    storage_key=storage_key,
                    content_type=content_type,
                    size_bytes=size_bytes,
                    checksum_sha256=checksum_sha256,
                    status="uploading",
                )
                session.add(asset)
                await session.flush()
                return _snapshot(asset), True

    async def activate(self, asset_id: UUID) -> ReferenceAssetSnapshot:
        async with self._database.session() as session:
            async with session.begin():
                asset = await session.scalar(
                    update(ReferenceAsset)
                    .where(
                        ReferenceAsset.id == asset_id,
                        ReferenceAsset.status == "uploading",
                    )
                    .values(status="active", activated_at=func.now(), updated_at=func.now())
                    .returning(ReferenceAsset)
                )
                if asset is None:
                    asset = await session.get(ReferenceAsset, asset_id)
                if asset is None or asset.status != "active":
                    raise SubmissionError(
                        ErrorCode.INPUT_STORAGE_FAILED,
                        "Не удалось активировать сохранённый референс.",
                        retryable=True,
                    )
                return _snapshot(asset)

    async def mark_failed(self, asset_id: UUID) -> None:
        async with self._database.session() as session:
            async with session.begin():
                await session.execute(
                    update(ReferenceAsset)
                    .where(
                        ReferenceAsset.id == asset_id,
                        ReferenceAsset.status == "uploading",
                    )
                    .values(status="failed", updated_at=func.now())
                )

    async def list_active(
        self,
        *,
        user_id: int,
        offset: int,
        limit: int,
    ) -> tuple[tuple[ReferenceAssetSnapshot, ...], int, int]:
        async with self._database.session() as session:
            assets = (
                (
                    await session.scalars(
                        select(ReferenceAsset)
                        .where(
                            ReferenceAsset.user_id == user_id,
                            ReferenceAsset.status == "active",
                        )
                        .order_by(ReferenceAsset.created_at.desc(), ReferenceAsset.id.desc())
                        .offset(offset)
                        .limit(limit)
                    )
                )
                .all()
            )
            usage_row = (
                await session.execute(
                    select(
                        func.count(ReferenceAsset.id),
                        func.coalesce(func.sum(ReferenceAsset.size_bytes), 0),
                    ).where(
                        ReferenceAsset.user_id == user_id,
                        ReferenceAsset.status == "active",
                    )
                )
            ).one()
            return (
                tuple(_snapshot(asset) for asset in assets),
                int(usage_row[0] or 0),
                int(usage_row[1] or 0),
            )

    async def get_active_many(
        self,
        *,
        user_id: int,
        asset_ids: tuple[UUID, ...],
    ) -> tuple[ReferenceAssetSnapshot, ...]:
        if not asset_ids:
            return ()
        async with self._database.session() as session:
            assets = (
                (
                    await session.scalars(
                        select(ReferenceAsset).where(
                            ReferenceAsset.user_id == user_id,
                            ReferenceAsset.id.in_(asset_ids),
                            ReferenceAsset.status == "active",
                        )
                    )
                )
                .all()
            )
            return tuple(_snapshot(asset) for asset in assets)

    async def schedule_delete(
        self,
        *,
        user_id: int,
        asset_id: UUID,
    ) -> ReferenceAssetSnapshot:
        async with self._database.session() as session:
            async with session.begin():
                asset = await session.scalar(
                    select(ReferenceAsset)
                    .where(
                        ReferenceAsset.id == asset_id,
                        ReferenceAsset.user_id == user_id,
                    )
                    .with_for_update()
                )
                if asset is None or asset.status in {"deleted", "failed"}:
                    raise SubmissionError(
                        ErrorCode.TASK_NOT_FOUND,
                        "Сохранённый референс не найден.",
                    )
                if asset.status == "uploading":
                    raise SubmissionError(
                        ErrorCode.INPUT_STORAGE_FAILED,
                        "Референс ещё сохраняется. Повторите удаление чуть позже.",
                        retryable=True,
                    )
                if asset.status == "active":
                    asset.status = "delete_pending"
                    asset.updated_at = func.now()
                    await session.flush()
                await session.execute(
                    pg_insert(OutboxEvent)
                    .values(
                        event_type="reference.delete",
                        aggregate_id=asset.id,
                        deduplication_key=f"reference.delete:{asset.id}",
                        payload={"reference_id": str(asset.id)},
                    )
                    .on_conflict_do_nothing(index_elements=[OutboxEvent.deduplication_key])
                )
                return _snapshot(asset)

    async def get_delete_pending(self, asset_id: UUID) -> ReferenceAssetSnapshot | None:
        async with self._database.session() as session:
            asset = await session.get(ReferenceAsset, asset_id)
            if asset is None or asset.status != "delete_pending":
                return None
            return _snapshot(asset)

    async def mark_deleted(self, asset_id: UUID) -> None:
        async with self._database.session() as session:
            async with session.begin():
                await session.execute(
                    update(ReferenceAsset)
                    .where(
                        ReferenceAsset.id == asset_id,
                        ReferenceAsset.status == "delete_pending",
                    )
                    .values(status="deleted", deleted_at=func.now(), updated_at=func.now())
                )
