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


async def ensure_internal_admin_payment_schema() -> None:
    """Create append-only payment events and tariff versions once per process.

    The compatibility DB adapter intentionally skips generic DDL. This function
    uses psycopg directly and must be called only after private-network and HMAC
    authentication have succeeded.
    """

    global _SCHEMA_READY
    if _SCHEMA_READY:
        return

    async with _schema_lock():
        if _SCHEMA_READY:
            return

        database_url = os.getenv("DATABASE_URL", "").strip()
        if not database_url.startswith(("postgresql://", "postgres://")):
            raise RuntimeError("Internal payment administration requires PostgreSQL DATABASE_URL")

        connection = await psycopg.AsyncConnection.connect(database_url)
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS internal_admin_payment_events (
                        id BIGSERIAL PRIMARY KEY,
                        transaction_id BIGINT NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
                        event_type TEXT NOT NULL,
                        status TEXT,
                        provider_status TEXT,
                        source TEXT NOT NULL,
                        actor_type TEXT NOT NULL DEFAULT 'system',
                        actor_id TEXT,
                        request_id TEXT,
                        idempotency_key TEXT,
                        details JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                await cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_internal_admin_payment_events_transaction
                    ON internal_admin_payment_events(transaction_id, created_at, id)
                    """
                )
                await cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_internal_admin_payment_events_request
                    ON internal_admin_payment_events(request_id)
                    """
                )
                await cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS internal_admin_tariff_versions (
                        id BIGSERIAL PRIMARY KEY,
                        checksum TEXT NOT NULL,
                        snapshot JSONB NOT NULL,
                        reason TEXT NOT NULL,
                        published_by TEXT,
                        request_id TEXT,
                        idempotency_key TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                await cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_internal_admin_tariff_versions_created
                    ON internal_admin_tariff_versions(created_at DESC, id DESC)
                    """
                )
                await cursor.execute(
                    """
                    CREATE OR REPLACE FUNCTION internal_admin_prevent_ledger_mutation()
                    RETURNS trigger AS $$
                    BEGIN
                        RAISE EXCEPTION 'internal administrative ledgers are append-only';
                    END;
                    $$ LANGUAGE plpgsql
                    """
                )
                for table_name, trigger_name in (
                    (
                        "internal_admin_payment_events",
                        "internal_admin_payment_events_append_only",
                    ),
                    (
                        "internal_admin_tariff_versions",
                        "internal_admin_tariff_versions_append_only",
                    ),
                ):
                    await cursor.execute(
                        f"DROP TRIGGER IF EXISTS {trigger_name} ON {table_name}"
                    )
                    await cursor.execute(
                        f"""
                        CREATE TRIGGER {trigger_name}
                        BEFORE UPDATE OR DELETE ON {table_name}
                        FOR EACH ROW EXECUTE FUNCTION internal_admin_prevent_ledger_mutation()
                        """
                    )

                await cursor.execute(
                    """
                    CREATE OR REPLACE FUNCTION internal_admin_capture_transaction_event()
                    RETURNS trigger AS $$
                    BEGIN
                        IF TG_OP = 'INSERT' THEN
                            INSERT INTO internal_admin_payment_events (
                                transaction_id, event_type, status, source, details
                            ) VALUES (
                                NEW.id,
                                'transaction.created',
                                NEW.status,
                                'database_trigger',
                                jsonb_build_object(
                                    'provider', NEW.provider,
                                    'order_id', NEW.order_id,
                                    'payment_id', NEW.payment_id,
                                    'credits', NEW.credits,
                                    'amount_rub', NEW.amount_rub
                                )
                            );
                            RETURN NEW;
                        END IF;

                        IF OLD.status IS DISTINCT FROM NEW.status THEN
                            INSERT INTO internal_admin_payment_events (
                                transaction_id, event_type, status, source, details
                            ) VALUES (
                                NEW.id,
                                'transaction.status_changed',
                                NEW.status,
                                'database_trigger',
                                jsonb_build_object(
                                    'old_status', OLD.status,
                                    'new_status', NEW.status
                                )
                            );
                        END IF;

                        IF OLD.payment_id IS DISTINCT FROM NEW.payment_id THEN
                            INSERT INTO internal_admin_payment_events (
                                transaction_id, event_type, status, source, details
                            ) VALUES (
                                NEW.id,
                                'transaction.payment_id_changed',
                                NEW.status,
                                'database_trigger',
                                jsonb_build_object(
                                    'old_payment_id', OLD.payment_id,
                                    'new_payment_id', NEW.payment_id
                                )
                            );
                        END IF;
                        RETURN NEW;
                    END;
                    $$ LANGUAGE plpgsql
                    """
                )
                await cursor.execute(
                    "DROP TRIGGER IF EXISTS internal_admin_transactions_events ON transactions"
                )
                await cursor.execute(
                    """
                    CREATE TRIGGER internal_admin_transactions_events
                    AFTER INSERT OR UPDATE OF status, payment_id ON transactions
                    FOR EACH ROW EXECUTE FUNCTION internal_admin_capture_transaction_event()
                    """
                )
            await connection.commit()
        except Exception:
            await connection.rollback()
            logger.exception("Failed to initialize payment administration schema")
            raise
        finally:
            await connection.close()

        _SCHEMA_READY = True
