from __future__ import annotations

import asyncio
import time

from bot import database
from bot import db as db_backend
from bot.channel_identity import ensure_channel_identity_schema
from bot.instagram_model_contract import normalize_instagram_creation_kind

_SCHEMA_LOCK: asyncio.Lock | None = None
_SCHEMA_READY: set[str] = set()


def _schema_lock() -> asyncio.Lock:
    global _SCHEMA_LOCK
    if _SCHEMA_LOCK is None:
        _SCHEMA_LOCK = asyncio.Lock()
    return _SCHEMA_LOCK


def _schema_key() -> str:
    if db_backend.is_postgres():
        return f"postgres:{db_backend.DATABASE_URL}"
    return f"sqlite:{database.DATABASE_PATH}"


def _statement() -> str:
    identity_type = "BIGINT" if db_backend.is_postgres() else "INTEGER"
    return f"""
        CREATE TABLE IF NOT EXISTS instagram_creation_modes (
            identity_id {identity_type} PRIMARY KEY,
            creation_kind TEXT NOT NULL,
            updated_at_epoch BIGINT NOT NULL,
            FOREIGN KEY (identity_id) REFERENCES channel_identities (id) ON DELETE CASCADE
        )
    """


async def ensure_instagram_creation_mode_schema() -> None:
    await ensure_channel_identity_schema()
    key = _schema_key()
    if key in _SCHEMA_READY:
        return
    async with _schema_lock():
        if key in _SCHEMA_READY:
            return
        async with db_backend.connect() as db:
            if db_backend.is_postgres():
                raw = getattr(db, "_conn", None)
                if raw is None:
                    raise RuntimeError("PostgreSQL migration handle is unavailable")
                async with raw.cursor() as cursor:
                    await cursor.execute(_statement())
                await raw.commit()
            else:
                await db.execute(_statement())
                await db.commit()
        _SCHEMA_READY.add(key)


async def get_instagram_creation_kind(identity_id: int) -> str:
    await ensure_instagram_creation_mode_schema()
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            "SELECT creation_kind FROM instagram_creation_modes WHERE identity_id = ?",
            (identity_id,),
        )
        row = await cursor.fetchone()
    if row is None:
        return ""
    return normalize_instagram_creation_kind(str(row["creation_kind"] or ""))


async def set_instagram_creation_kind(identity_id: int, creation_kind: str) -> str:
    await ensure_instagram_creation_mode_schema()
    normalized = normalize_instagram_creation_kind(creation_kind)
    if not normalized:
        raise ValueError("creation_kind must be photo or video")
    now = int(time.time())
    async with db_backend.connect() as db:
        await db.execute(
            """
            INSERT INTO instagram_creation_modes (identity_id, creation_kind, updated_at_epoch)
            VALUES (?, ?, ?)
            ON CONFLICT(identity_id) DO UPDATE SET
                creation_kind = excluded.creation_kind,
                updated_at_epoch = excluded.updated_at_epoch
            """,
            (identity_id, normalized, now),
        )
        await db.commit()
    return normalized
