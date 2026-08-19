from __future__ import annotations

import asyncio
import logging
import os

import psycopg

logger = logging.getLogger(__name__)

_SCHEMA_READY = False
_SCHEMA_LOCK: asyncio.Lock | None = None


def _schema_lock() -> asyncio.Lock:
    global _SCHEMA_LOCK
    if _SCHEMA_LOCK is None:
        _SCHEMA_LOCK = asyncio.Lock()
    return _SCHEMA_LOCK


async def ensure_internal_admin_command_schema() -> None:
    """Create the bot-owned idempotency ledger once per process.

    The compatibility database adapter intentionally skips generic DDL, so
    this narrowly scoped PostgreSQL initializer uses psycopg directly. It is
    called only after the request passed the internal HMAC and network checks.
    """

    global _SCHEMA_READY
    if _SCHEMA_READY:
        return

    async with _schema_lock():
        if _SCHEMA_READY:
            return

        database_url = os.getenv("DATABASE_URL", "").strip()
        if not database_url.startswith(("postgresql://", "postgres://")):
            raise RuntimeError("Internal admin write API requires PostgreSQL DATABASE_URL")

        connection = await psycopg.AsyncConnection.connect(database_url)
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS internal_admin_commands (
                        id BIGSERIAL PRIMARY KEY,
                        idempotency_key TEXT UNIQUE NOT NULL,
                        action TEXT NOT NULL,
                        target_user_id BIGINT NOT NULL,
                        admin_user_id TEXT NOT NULL,
                        request_id TEXT NOT NULL,
                        request_payload JSONB NOT NULL,
                        response_payload JSONB,
                        status TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        completed_at TIMESTAMP
                    )
                    """
                )
                await cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_internal_admin_commands_request_id
                    ON internal_admin_commands(request_id)
                    """
                )
                await cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_internal_admin_commands_target
                    ON internal_admin_commands(target_user_id, created_at DESC)
                    """
                )
            await connection.commit()
        except Exception:
            await connection.rollback()
            logger.exception("Failed to initialize internal admin command ledger")
            raise
        finally:
            await connection.close()

        _SCHEMA_READY = True
