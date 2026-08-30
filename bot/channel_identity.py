from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bot import db as db_backend


@dataclass(frozen=True)
class ChannelIdentity:
    id: int
    user_id: int | None
    channel: str
    account_id: str
    external_user_id: str
    username: str = ""
    display_name: str = ""


def _required(value: Any, name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized


async def ensure_channel_identity_schema() -> None:
    """Create the additive identity bridge without changing legacy Telegram users."""
    async with db_backend.connect() as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS channel_identities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                channel TEXT NOT NULL,
                account_id TEXT NOT NULL,
                external_user_id TEXT NOT NULL,
                username TEXT,
                display_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(channel, account_id, external_user_id),
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_channel_identities_user ON channel_identities(user_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_channel_identities_lookup "
            "ON channel_identities(channel, account_id, external_user_id)"
        )
        await db.commit()


def _row_to_identity(row: db_backend.Row | None) -> ChannelIdentity | None:
    if row is None:
        return None
    return ChannelIdentity(
        id=int(row["id"]),
        user_id=int(row["user_id"]) if row["user_id"] is not None else None,
        channel=str(row["channel"]),
        account_id=str(row["account_id"]),
        external_user_id=str(row["external_user_id"]),
        username=str(row["username"] or ""),
        display_name=str(row["display_name"] or ""),
    )


async def get_channel_identity(
    *,
    channel: str,
    account_id: str,
    external_user_id: str,
) -> ChannelIdentity | None:
    await ensure_channel_identity_schema()
    channel_name = _required(channel, "channel").lower()
    account = _required(account_id, "account_id")
    external_id = _required(external_user_id, "external_user_id")
    async with db_backend.connect() as db:
        cursor = await db.execute(
            """
            SELECT id, user_id, channel, account_id, external_user_id, username, display_name
            FROM channel_identities
            WHERE channel = ? AND account_id = ? AND external_user_id = ?
            """,
            (channel_name, account, external_id),
        )
        return _row_to_identity(await cursor.fetchone())


async def ensure_channel_identity(
    *,
    channel: str,
    account_id: str,
    external_user_id: str,
    username: str = "",
    display_name: str = "",
) -> ChannelIdentity:
    """Upsert an external identity; user_id deliberately stays nullable until linking."""
    await ensure_channel_identity_schema()
    channel_name = _required(channel, "channel").lower()
    account = _required(account_id, "account_id")
    external_id = _required(external_user_id, "external_user_id")
    normalized_username = str(username or "").strip()
    normalized_display_name = str(display_name or "").strip()

    async with db_backend.connect() as db:
        await db.execute(
            """
            INSERT INTO channel_identities (
                channel, account_id, external_user_id, username, display_name,
                created_at, updated_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(channel, account_id, external_user_id) DO UPDATE SET
                username = CASE
                    WHEN excluded.username <> '' THEN excluded.username
                    ELSE channel_identities.username
                END,
                display_name = CASE
                    WHEN excluded.display_name <> '' THEN excluded.display_name
                    ELSE channel_identities.display_name
                END,
                updated_at = CURRENT_TIMESTAMP,
                last_seen_at = CURRENT_TIMESTAMP
            """,
            (
                channel_name,
                account,
                external_id,
                normalized_username,
                normalized_display_name,
            ),
        )
        await db.commit()
        cursor = await db.execute(
            """
            SELECT id, user_id, channel, account_id, external_user_id, username, display_name
            FROM channel_identities
            WHERE channel = ? AND account_id = ? AND external_user_id = ?
            """,
            (channel_name, account, external_id),
        )
        identity = _row_to_identity(await cursor.fetchone())

    if identity is None:
        raise RuntimeError("Failed to persist channel identity")
    return identity


async def link_channel_identity_to_user(
    *,
    identity_id: int,
    user_id: int,
) -> ChannelIdentity:
    """Attach an already verified external identity to an existing HappyFox user."""
    await ensure_channel_identity_schema()
    if identity_id <= 0 or user_id <= 0:
        raise ValueError("identity_id and user_id must be positive")

    async with db_backend.connect() as db:
        user_cursor = await db.execute("SELECT id FROM users WHERE id = ?", (user_id,))
        if await user_cursor.fetchone() is None:
            raise ValueError("HappyFox user does not exist")
        await db.execute(
            """
            UPDATE channel_identities
            SET user_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (user_id, identity_id),
        )
        await db.commit()
        cursor = await db.execute(
            """
            SELECT id, user_id, channel, account_id, external_user_id, username, display_name
            FROM channel_identities
            WHERE id = ?
            """,
            (identity_id,),
        )
        identity = _row_to_identity(await cursor.fetchone())

    if identity is None:
        raise ValueError("Channel identity does not exist")
    return identity
