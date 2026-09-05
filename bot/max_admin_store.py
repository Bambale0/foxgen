from __future__ import annotations

import asyncio
import hashlib
import secrets
from typing import Any

from bot import database
from bot import db as db_backend
from bot.max_store import ensure_max_schema, ensure_max_user

_SCHEMA_LOCK: asyncio.Lock | None = None
_SCHEMA_READY: set[str] = set()


def _invite_hash(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def _schema_lock() -> asyncio.Lock:
    global _SCHEMA_LOCK
    if _SCHEMA_LOCK is None:
        _SCHEMA_LOCK = asyncio.Lock()
    return _SCHEMA_LOCK


def _schema_key() -> str:
    if db_backend.is_postgres():
        return f"postgres:{db_backend.DATABASE_URL}:max-admin"
    return f"sqlite:{database.DATABASE_PATH}:max-admin"


def _schema_statements() -> tuple[str, ...]:
    return (
        """
        CREATE TABLE IF NOT EXISTS max_admins (
            max_user_id BIGINT PRIMARY KEY,
            display_name TEXT NOT NULL DEFAULT '',
            granted_by TEXT NOT NULL DEFAULT 'manual',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (max_user_id) REFERENCES max_users(max_user_id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS max_admin_invites (
            token_hash TEXT PRIMARY KEY,
            display_name TEXT NOT NULL DEFAULT '',
            used_by_max_user_id BIGINT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            used_at TIMESTAMP,
            FOREIGN KEY (used_by_max_user_id) REFERENCES max_users(max_user_id) ON DELETE SET NULL
        )
        """,
    )


async def _create_postgres_schema(db: db_backend.Connection) -> None:
    raw = getattr(db, "_conn", None)
    if raw is None:
        raise RuntimeError("PostgreSQL connection does not expose migration handle")
    async with raw.cursor() as cursor:
        for statement in _schema_statements():
            await cursor.execute(statement)
    await raw.commit()


async def ensure_max_admin_schema() -> None:
    """Create isolated MAX admin role and one-time invite tables."""
    await ensure_max_schema()
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
                for statement in _schema_statements():
                    await db.execute(statement)
                await db.commit()
        _SCHEMA_READY.add(key)


async def grant_max_admin(
    max_user_id: int,
    *,
    display_name: str = "",
    granted_by: str = "manual",
) -> None:
    """Persist one MAX user as an administrator by stable MAX user ID."""
    user = await ensure_max_user(max_user_id)
    name = str(display_name or user.first_name or user.username or max_user_id).strip()
    await ensure_max_admin_schema()
    async with db_backend.connect() as db:
        await db.execute(
            """
            INSERT INTO max_admins (max_user_id, display_name, granted_by)
            VALUES (?, ?, ?)
            ON CONFLICT(max_user_id) DO UPDATE SET
                display_name = CASE
                    WHEN excluded.display_name <> '' THEN excluded.display_name
                    ELSE max_admins.display_name
                END,
                granted_by = excluded.granted_by
            """,
            (int(max_user_id), name, str(granted_by or "manual")),
        )
        await db.commit()


async def is_max_admin(max_user_id: int) -> bool:
    await ensure_max_admin_schema()
    async with db_backend.connect() as db:
        cursor = await db.execute(
            "SELECT 1 FROM max_admins WHERE max_user_id = ? LIMIT 1",
            (int(max_user_id),),
        )
        return await cursor.fetchone() is not None


async def list_max_admins() -> list[dict[str, Any]]:
    await ensure_max_admin_schema()
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT a.max_user_id, a.display_name, a.granted_by, a.created_at,
                   u.username, u.first_name, u.last_name
            FROM max_admins a
            LEFT JOIN max_users u ON u.max_user_id = a.max_user_id
            ORDER BY a.created_at, a.max_user_id
            """
        )
        return [dict(row) for row in await cursor.fetchall()]


async def create_max_admin_invite(display_name: str) -> str:
    """Create a one-use capability token; only its SHA-256 hash is stored."""
    await ensure_max_admin_schema()
    token = secrets.token_urlsafe(24)
    async with db_backend.connect() as db:
        await db.execute(
            """
            INSERT INTO max_admin_invites (token_hash, display_name)
            VALUES (?, ?)
            """,
            (_invite_hash(token), str(display_name or "").strip()),
        )
        await db.commit()
    return token


async def claim_max_admin_invite(max_user_id: int, token: str) -> bool:
    """Bind a one-time invite to the stable MAX user ID that redeems it."""
    token = str(token or "").strip()
    if not token:
        return False
    user = await ensure_max_user(max_user_id)
    await ensure_max_admin_schema()
    token_hash = _invite_hash(token)
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            "SELECT display_name, used_by_max_user_id FROM max_admin_invites WHERE token_hash = ?",
            (token_hash,),
        )
        row = await cursor.fetchone()
        if row is None:
            return False

        used_by = row["used_by_max_user_id"]
        if used_by is not None:
            if int(used_by) != int(max_user_id):
                return False
            admin_cursor = await db.execute(
                "SELECT 1 FROM max_admins WHERE max_user_id = ? LIMIT 1",
                (int(max_user_id),),
            )
            return await admin_cursor.fetchone() is not None

        update = await db.execute(
            """
            UPDATE max_admin_invites
            SET used_by_max_user_id = ?, used_at = CURRENT_TIMESTAMP
            WHERE token_hash = ? AND used_by_max_user_id IS NULL
            """,
            (int(max_user_id), token_hash),
        )
        if int(getattr(update, "rowcount", 0) or 0) != 1:
            await db.rollback()
            return False

        display_name = str(row["display_name"] or user.first_name or user.username).strip()
        await db.execute(
            """
            INSERT INTO max_admins (max_user_id, display_name, granted_by)
            VALUES (?, ?, 'invite')
            ON CONFLICT(max_user_id) DO UPDATE SET
                display_name = CASE
                    WHEN excluded.display_name <> '' THEN excluded.display_name
                    ELSE max_admins.display_name
                END,
                granted_by = 'invite'
            """,
            (int(max_user_id), display_name),
        )
        await db.commit()
        return True
