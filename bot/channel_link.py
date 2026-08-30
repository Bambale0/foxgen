from __future__ import annotations

import asyncio
import hashlib
import secrets
import time
from dataclasses import dataclass

from bot import database
from bot import db as db_backend
from bot.channel_identity import ChannelIdentity, ensure_channel_identity_schema

_DEFAULT_TTL_SECONDS = 15 * 60
_SCHEMA_LOCK: asyncio.Lock | None = None
_SCHEMA_READY: set[str] = set()


class ChannelLinkError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ChannelLinkToken:
    token: str
    identity_id: int
    expires_at_epoch: int


def _schema_lock() -> asyncio.Lock:
    global _SCHEMA_LOCK
    if _SCHEMA_LOCK is None:
        _SCHEMA_LOCK = asyncio.Lock()
    return _SCHEMA_LOCK


def _schema_key() -> str:
    if db_backend.is_postgres():
        return f"postgres:{db_backend.DATABASE_URL}"
    return f"sqlite:{database.DATABASE_PATH}"


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _use_mapping_rows(db: db_backend.Connection) -> None:
    db.row_factory = db_backend.Row


def _sqlite_schema_statements() -> tuple[str, ...]:
    return (
        """
        CREATE TABLE IF NOT EXISTS channel_link_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            identity_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at_epoch INTEGER NOT NULL,
            consumed_at_epoch INTEGER,
            created_at_epoch INTEGER NOT NULL,
            FOREIGN KEY (identity_id) REFERENCES channel_identities (id) ON DELETE CASCADE
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_channel_link_tokens_identity "
        "ON channel_link_tokens(identity_id)",
        "CREATE INDEX IF NOT EXISTS idx_channel_link_tokens_expiry "
        "ON channel_link_tokens(expires_at_epoch)",
    )


def _postgres_schema_statements() -> tuple[str, ...]:
    return (
        """
        CREATE TABLE IF NOT EXISTS channel_link_tokens (
            id BIGSERIAL PRIMARY KEY,
            identity_id BIGINT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at_epoch BIGINT NOT NULL,
            consumed_at_epoch BIGINT,
            created_at_epoch BIGINT NOT NULL,
            FOREIGN KEY (identity_id) REFERENCES channel_identities (id) ON DELETE CASCADE
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_channel_link_tokens_identity "
        "ON channel_link_tokens(identity_id)",
        "CREATE INDEX IF NOT EXISTS idx_channel_link_tokens_expiry "
        "ON channel_link_tokens(expires_at_epoch)",
    )


async def _create_postgres_schema(db: db_backend.Connection) -> None:
    raw_connection = getattr(db, "_conn", None)
    if raw_connection is None:
        raise RuntimeError("PostgreSQL connection does not expose its migration handle")
    async with raw_connection.cursor() as cursor:
        for statement in _postgres_schema_statements():
            await cursor.execute(statement)
    await raw_connection.commit()


async def ensure_channel_link_schema() -> None:
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


async def create_channel_link_token(
    identity_id: int,
    *,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> str:
    """Create one active raw token while persisting only its SHA-256 digest."""
    if identity_id <= 0:
        raise ValueError("identity_id must be positive")
    ttl = max(60, min(int(ttl_seconds), 24 * 60 * 60))
    await ensure_channel_link_schema()

    raw_token = secrets.token_urlsafe(18)
    now = int(time.time())
    expires_at = now + ttl
    digest = _token_hash(raw_token)

    async with db_backend.connect() as db:
        _use_mapping_rows(db)
        identity_cursor = await db.execute(
            "SELECT id FROM channel_identities WHERE id = ?",
            (identity_id,),
        )
        if await identity_cursor.fetchone() is None:
            raise ChannelLinkError("identity_not_found", "Channel identity does not exist")

        await db.execute(
            """
            UPDATE channel_link_tokens
            SET consumed_at_epoch = ?
            WHERE identity_id = ? AND consumed_at_epoch IS NULL
            """,
            (now, identity_id),
        )
        await db.execute(
            """
            INSERT INTO channel_link_tokens (
                identity_id,
                token_hash,
                expires_at_epoch,
                consumed_at_epoch,
                created_at_epoch
            ) VALUES (?, ?, ?, NULL, ?)
            """,
            (identity_id, digest, expires_at, now),
        )
        await db.commit()
    return raw_token


async def consume_channel_link_token(token: str, user_id: int) -> ChannelIdentity:
    """Atomically consume a token and attach its identity to one existing user."""
    normalized = str(token or "").strip()
    if not normalized:
        raise ChannelLinkError("invalid", "Link token is missing")
    if user_id <= 0:
        raise ValueError("user_id must be positive")
    await ensure_channel_link_schema()

    now = int(time.time())
    digest = _token_hash(normalized)
    async with db_backend.connect() as db:
        _use_mapping_rows(db)
        user_cursor = await db.execute("SELECT id FROM users WHERE id = ?", (user_id,))
        if await user_cursor.fetchone() is None:
            raise ChannelLinkError("user_not_found", "HappyFox user does not exist")

        cursor = await db.execute(
            """
            SELECT
                t.id AS token_id,
                t.identity_id,
                t.expires_at_epoch,
                t.consumed_at_epoch,
                i.user_id,
                i.channel,
                i.account_id,
                i.external_user_id,
                i.username,
                i.display_name
            FROM channel_link_tokens AS t
            JOIN channel_identities AS i ON i.id = t.identity_id
            WHERE t.token_hash = ?
            """,
            (digest,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise ChannelLinkError("invalid", "Link token is invalid")
        if row["consumed_at_epoch"] is not None:
            raise ChannelLinkError("used", "Link token was already used")
        if int(row["expires_at_epoch"]) < now:
            raise ChannelLinkError("expired", "Link token has expired")
        existing_user_id = (
            int(row["user_id"]) if row["user_id"] is not None else None
        )
        if existing_user_id is not None and existing_user_id != user_id:
            raise ChannelLinkError(
                "conflict",
                "Instagram identity is already linked to another HappyFox user",
            )

        claim_cursor = await db.execute(
            """
            UPDATE channel_link_tokens
            SET consumed_at_epoch = ?
            WHERE id = ? AND consumed_at_epoch IS NULL AND expires_at_epoch >= ?
            """,
            (now, int(row["token_id"]), now),
        )
        if int(getattr(claim_cursor, "rowcount", 0) or 0) != 1:
            raise ChannelLinkError("used", "Link token was already used")

        await db.execute(
            """
            UPDATE channel_identities
            SET user_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND (user_id IS NULL OR user_id = ?)
            """,
            (user_id, int(row["identity_id"]), user_id),
        )
        await db.commit()

    return ChannelIdentity(
        id=int(row["identity_id"]),
        user_id=user_id,
        channel=str(row["channel"]),
        account_id=str(row["account_id"]),
        external_user_id=str(row["external_user_id"]),
        username=str(row["username"] or ""),
        display_name=str(row["display_name"] or ""),
    )
