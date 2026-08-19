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


async def ensure_internal_admin_operation_schema() -> None:
    """Create the bot-owned operation timeline ledger once per process.

    The compatibility database adapter intentionally skips generic DDL. This
    initializer therefore uses psycopg directly and must only be called after
    the internal network allowlist and HMAC checks have succeeded.
    """

    global _SCHEMA_READY
    if _SCHEMA_READY:
        return

    async with _schema_lock():
        if _SCHEMA_READY:
            return

        database_url = os.getenv("DATABASE_URL", "").strip()
        if not database_url.startswith(("postgresql://", "postgres://")):
            raise RuntimeError("Internal admin operation API requires PostgreSQL DATABASE_URL")

        connection = await psycopg.AsyncConnection.connect(database_url)
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS internal_admin_operation_events (
                        id BIGSERIAL PRIMARY KEY,
                        operation_id BIGINT NOT NULL REFERENCES generation_tasks(id) ON DELETE CASCADE,
                        event_type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        actor_type TEXT NOT NULL DEFAULT 'admin',
                        actor_id TEXT,
                        request_id TEXT,
                        idempotency_key TEXT,
                        amount INTEGER,
                        related_operation_id BIGINT REFERENCES generation_tasks(id) ON DELETE SET NULL,
                        details JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                await cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_internal_admin_operation_events_operation
                    ON internal_admin_operation_events(operation_id, created_at, id)
                    """
                )
                await cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_internal_admin_operation_events_request
                    ON internal_admin_operation_events(request_id)
                    """
                )
                await cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_internal_admin_operation_events_related
                    ON internal_admin_operation_events(related_operation_id)
                    """
                )
            await connection.commit()
        except Exception:
            await connection.rollback()
            logger.exception("Failed to initialize internal admin operation ledger")
            raise
        finally:
            await connection.close()

        _SCHEMA_READY = True
