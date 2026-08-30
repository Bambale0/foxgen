from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from bot import database
from bot import db as db_backend
from bot.channel_identity import ensure_channel_identity_schema

INSTAGRAM_FIRST_IMAGE_PROMOTION = "instagram_first_image"
_DEFAULT_RESERVATION_TTL_SECONDS = 30 * 60
_SCHEMA_LOCK: asyncio.Lock | None = None
_SCHEMA_READY: set[str] = set()


@dataclass(frozen=True)
class ChannelPromotionStatus:
    promotion_code: str
    status: str
    reservation_key: str | None


def _schema_lock() -> asyncio.Lock:
    global _SCHEMA_LOCK
    if _SCHEMA_LOCK is None:
        _SCHEMA_LOCK = asyncio.Lock()
    return _SCHEMA_LOCK


def _schema_key() -> str:
    if db_backend.is_postgres():
        return f"postgres:{db_backend.DATABASE_URL}"
    return f"sqlite:{database.DATABASE_PATH}"


def _use_mapping_rows(db: db_backend.Connection) -> None:
    db.row_factory = db_backend.Row


def _sqlite_schema_statements() -> tuple[str, ...]:
    return (
        """
        CREATE TABLE IF NOT EXISTS channel_promotions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL,
            external_user_id TEXT NOT NULL,
            promotion_code TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'available',
            reservation_key TEXT,
            reservation_expires_at_epoch INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            consumed_at TIMESTAMP,
            UNIQUE(channel, external_user_id, promotion_code)
        )
        """,
        (
            "CREATE INDEX IF NOT EXISTS idx_channel_promotions_lookup "
            "ON channel_promotions(channel, external_user_id, promotion_code)"
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_channel_promotions_reservation "
            "ON channel_promotions(reservation_key)"
        ),
    )


def _postgres_schema_statements() -> tuple[str, ...]:
    return (
        """
        CREATE TABLE IF NOT EXISTS channel_promotions (
            id BIGSERIAL PRIMARY KEY,
            channel TEXT NOT NULL,
            external_user_id TEXT NOT NULL,
            promotion_code TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'available',
            reservation_key TEXT,
            reservation_expires_at_epoch BIGINT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            consumed_at TIMESTAMP,
            UNIQUE(channel, external_user_id, promotion_code)
        )
        """,
        (
            "CREATE INDEX IF NOT EXISTS idx_channel_promotions_lookup "
            "ON channel_promotions(channel, external_user_id, promotion_code)"
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_channel_promotions_reservation "
            "ON channel_promotions(reservation_key)"
        ),
    )


async def _create_postgres_schema(db: db_backend.Connection) -> None:
    raw_connection = getattr(db, "_conn", None)
    if raw_connection is None:
        raise RuntimeError("PostgreSQL connection does not expose its migration handle")
    async with raw_connection.cursor() as cursor:
        for statement in _postgres_schema_statements():
            await cursor.execute(statement)
    await raw_connection.commit()


async def ensure_channel_promotion_schema() -> None:
    await ensure_channel_identity_schema()
    key = _schema_key()
    if key in _SCHEMA_READY:
        return

    async with _schema_lock():
        if key in _SCHEMA_READY:
            return
        async with db_backend.connect() as db:
            if db_backend.is_postgres():
                await _create_postgres_schema(db)
            else:
                for statement in _sqlite_schema_statements():
                    await db.execute(statement)
                await db.commit()
        _SCHEMA_READY.add(key)


async def _identity_key(identity_id: int) -> tuple[str, str]:
    if identity_id <= 0:
        raise ValueError("identity_id must be positive")
    await ensure_channel_promotion_schema()
    async with db_backend.connect() as db:
        _use_mapping_rows(db)
        cursor = await db.execute(
            "SELECT channel, external_user_id FROM channel_identities WHERE id = ?",
            (identity_id,),
        )
        row = await cursor.fetchone()
    if row is None:
        raise ValueError("Channel identity does not exist")
    return str(row["channel"]), str(row["external_user_id"])


async def ensure_instagram_first_image_promotion(identity_id: int) -> ChannelPromotionStatus:
    """Create the durable one-time free-image entitlement for an Instagram identity."""
    channel, external_user_id = await _identity_key(identity_id)
    if channel != "instagram":
        raise ValueError("First-image promotion is only available for Instagram")

    async with db_backend.connect() as db:
        _use_mapping_rows(db)
        await db.execute(
            """
            INSERT INTO channel_promotions (
                channel, external_user_id, promotion_code, status, created_at, updated_at
            ) VALUES (?, ?, ?, 'available', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(channel, external_user_id, promotion_code) DO NOTHING
            """,
            (channel, external_user_id, INSTAGRAM_FIRST_IMAGE_PROMOTION),
        )
        await db.commit()
        cursor = await db.execute(
            """
            SELECT promotion_code, status, reservation_key
            FROM channel_promotions
            WHERE channel = ? AND external_user_id = ? AND promotion_code = ?
            """,
            (channel, external_user_id, INSTAGRAM_FIRST_IMAGE_PROMOTION),
        )
        row = await cursor.fetchone()
    if row is None:
        raise RuntimeError("Failed to persist channel promotion")
    return ChannelPromotionStatus(
        promotion_code=str(row["promotion_code"]),
        status=str(row["status"]),
        reservation_key=(
            str(row["reservation_key"]) if row["reservation_key"] is not None else None
        ),
    )


async def reserve_instagram_first_image(
    identity_id: int,
    reservation_key: str,
    *,
    ttl_seconds: int = _DEFAULT_RESERVATION_TTL_SECONDS,
) -> bool:
    """Atomically reserve the free image for one generation submission."""
    key = str(reservation_key or "").strip()
    if not key:
        raise ValueError("reservation_key is required")
    channel, external_user_id = await _identity_key(identity_id)
    if channel != "instagram":
        return False

    ttl = max(60, min(int(ttl_seconds), 24 * 60 * 60))
    now = int(time.time())
    expires_at = now + ttl

    async with db_backend.connect() as db:
        _use_mapping_rows(db)
        await db.execute(
            """
            INSERT INTO channel_promotions (
                channel, external_user_id, promotion_code, status, created_at, updated_at
            ) VALUES (?, ?, ?, 'available', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(channel, external_user_id, promotion_code) DO NOTHING
            """,
            (channel, external_user_id, INSTAGRAM_FIRST_IMAGE_PROMOTION),
        )
        claim = await db.execute(
            """
            UPDATE channel_promotions
            SET status = 'reserved',
                reservation_key = ?,
                reservation_expires_at_epoch = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE channel = ?
              AND external_user_id = ?
              AND promotion_code = ?
              AND (
                    status = 'available'
                    OR (
                        status = 'reserved'
                        AND reservation_expires_at_epoch IS NOT NULL
                        AND reservation_expires_at_epoch < ?
                    )
              )
            """,
            (
                key,
                expires_at,
                channel,
                external_user_id,
                INSTAGRAM_FIRST_IMAGE_PROMOTION,
                now,
            ),
        )
        claimed = int(getattr(claim, "rowcount", 0) or 0) == 1
        if not claimed:
            cursor = await db.execute(
                """
                SELECT status, reservation_key
                FROM channel_promotions
                WHERE channel = ? AND external_user_id = ? AND promotion_code = ?
                """,
                (channel, external_user_id, INSTAGRAM_FIRST_IMAGE_PROMOTION),
            )
            row = await cursor.fetchone()
            claimed = bool(
                row
                and row["status"] == "reserved"
                and str(row["reservation_key"] or "") == key
            )
        await db.commit()
    return claimed


async def consume_instagram_first_image(reservation_key: str) -> bool:
    """Consume the entitlement only after the image generation succeeds."""
    key = str(reservation_key or "").strip()
    if not key:
        return False
    await ensure_channel_promotion_schema()
    async with db_backend.connect() as db:
        cursor = await db.execute(
            """
            UPDATE channel_promotions
            SET status = 'consumed',
                reservation_expires_at_epoch = NULL,
                consumed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE promotion_code = ?
              AND status = 'reserved'
              AND reservation_key = ?
            """,
            (INSTAGRAM_FIRST_IMAGE_PROMOTION, key),
        )
        changed = int(getattr(cursor, "rowcount", 0) or 0) == 1
        if not changed:
            _use_mapping_rows(db)
            check = await db.execute(
                """
                SELECT status, reservation_key
                FROM channel_promotions
                WHERE promotion_code = ? AND reservation_key = ?
                """,
                (INSTAGRAM_FIRST_IMAGE_PROMOTION, key),
            )
            row = await check.fetchone()
            changed = bool(row and row["status"] == "consumed")
        await db.commit()
    return changed


async def release_instagram_first_image(reservation_key: str) -> bool:
    """Return a reserved free image when provider submission or generation fails."""
    key = str(reservation_key or "").strip()
    if not key:
        return False
    await ensure_channel_promotion_schema()
    async with db_backend.connect() as db:
        cursor = await db.execute(
            """
            UPDATE channel_promotions
            SET status = 'available',
                reservation_key = NULL,
                reservation_expires_at_epoch = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE promotion_code = ?
              AND status = 'reserved'
              AND reservation_key = ?
            """,
            (INSTAGRAM_FIRST_IMAGE_PROMOTION, key),
        )
        changed = int(getattr(cursor, "rowcount", 0) or 0) == 1
        await db.commit()
    return changed
