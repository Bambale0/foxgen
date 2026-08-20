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


async def ensure_internal_admin_notification_schema() -> None:
    """Create notification campaign tables once per process.

    DDL uses psycopg directly because the compatibility DB adapter deliberately
    skips generic CREATE TABLE statements. Internal routes call this only after
    private-network and HMAC verification; the background worker calls it at
    controlled bot startup.
    """

    global _SCHEMA_READY
    if _SCHEMA_READY:
        return

    async with _schema_lock():
        if _SCHEMA_READY:
            return

        database_url = os.getenv("DATABASE_URL", "").strip()
        if not database_url.startswith(("postgresql://", "postgres://")):
            raise RuntimeError("Notification campaigns require PostgreSQL DATABASE_URL")

        connection = await psycopg.AsyncConnection.connect(database_url)
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS notification_campaigns (
                        id BIGSERIAL PRIMARY KEY,
                        name TEXT NOT NULL,
                        channel TEXT NOT NULL DEFAULT 'telegram',
                        status TEXT NOT NULL DEFAULT 'draft',
                        segment JSONB NOT NULL,
                        message JSONB NOT NULL,
                        audience_count INTEGER NOT NULL DEFAULT 0,
                        queued_count INTEGER NOT NULL DEFAULT 0,
                        sent_count INTEGER NOT NULL DEFAULT 0,
                        failed_count INTEGER NOT NULL DEFAULT 0,
                        blocked_count INTEGER NOT NULL DEFAULT 0,
                        cancelled_count INTEGER NOT NULL DEFAULT 0,
                        created_by TEXT,
                        reason TEXT NOT NULL,
                        request_id TEXT,
                        idempotency_key TEXT UNIQUE,
                        scheduled_at TIMESTAMP,
                        started_at TIMESTAMP,
                        completed_at TIMESTAMP,
                        cancelled_at TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        CHECK (status IN (
                            'draft', 'scheduled', 'running', 'completed',
                            'cancelled', 'failed'
                        ))
                    )
                    """
                )
                await cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_notification_campaigns_status_created
                    ON notification_campaigns(status, created_at DESC, id DESC)
                    """
                )
                await cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS notification_deliveries (
                        id BIGSERIAL PRIMARY KEY,
                        campaign_id BIGINT NOT NULL
                            REFERENCES notification_campaigns(id) ON DELETE CASCADE,
                        user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
                        telegram_id BIGINT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'queued',
                        attempts INTEGER NOT NULL DEFAULT 0,
                        lease_until TIMESTAMP,
                        next_attempt_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_error TEXT,
                        telegram_message_id BIGINT,
                        sent_at TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(campaign_id, telegram_id),
                        CHECK (status IN (
                            'queued', 'sending', 'sent', 'failed',
                            'blocked', 'cancelled'
                        ))
                    )
                    """
                )
                await cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_notification_deliveries_claim
                    ON notification_deliveries(status, next_attempt_at, lease_until, id)
                    """
                )
                await cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_notification_deliveries_campaign_status
                    ON notification_deliveries(campaign_id, status)
                    """
                )
                await cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS notification_test_sends (
                        id BIGSERIAL PRIMARY KEY,
                        campaign_id BIGINT NOT NULL
                            REFERENCES notification_campaigns(id) ON DELETE CASCADE,
                        telegram_id BIGINT NOT NULL,
                        status TEXT NOT NULL,
                        telegram_message_id BIGINT,
                        error TEXT,
                        requested_by TEXT,
                        request_id TEXT,
                        idempotency_key TEXT UNIQUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            await connection.commit()
        except Exception:
            await connection.rollback()
            logger.exception("Failed to initialize notification campaign schema")
            raise
        finally:
            await connection.close()

        _SCHEMA_READY = True
