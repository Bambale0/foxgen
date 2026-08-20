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


async def ensure_internal_admin_support_schema() -> None:
    """Create support/CMS tables once per process.

    The compatibility DB adapter intentionally skips generic DDL. The initializer
    therefore uses psycopg directly and must only run after internal HMAC auth or
    during trusted bot startup.
    """

    global _SCHEMA_READY
    if _SCHEMA_READY:
        return

    async with _schema_lock():
        if _SCHEMA_READY:
            return

        database_url = os.getenv("DATABASE_URL", "").strip()
        if not database_url.startswith(("postgresql://", "postgres://")):
            raise RuntimeError("Support administration requires PostgreSQL DATABASE_URL")

        connection = await psycopg.AsyncConnection.connect(database_url)
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS support_tickets (
                        id BIGSERIAL PRIMARY KEY,
                        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        subject TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'new'
                            CHECK (status IN ('new', 'in_progress', 'waiting_user', 'resolved', 'closed')),
                        priority TEXT NOT NULL DEFAULT 'normal'
                            CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
                        assigned_admin_id TEXT,
                        linked_payment_id BIGINT REFERENCES transactions(id) ON DELETE SET NULL,
                        linked_operation_id BIGINT REFERENCES generation_tasks(id) ON DELETE SET NULL,
                        source TEXT NOT NULL DEFAULT 'telegram',
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        last_user_message_at TIMESTAMP,
                        last_admin_message_at TIMESTAMP,
                        closed_at TIMESTAMP
                    )
                    """
                )
                await cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_support_tickets_status_updated
                    ON support_tickets(status, updated_at DESC, id DESC)
                    """
                )
                await cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_support_tickets_assignee
                    ON support_tickets(assigned_admin_id, status, updated_at DESC)
                    """
                )
                await cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_support_tickets_user
                    ON support_tickets(user_id, created_at DESC)
                    """
                )

                await cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS support_messages (
                        id BIGSERIAL PRIMARY KEY,
                        ticket_id BIGINT NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
                        sender_type TEXT NOT NULL
                            CHECK (sender_type IN ('user', 'admin', 'system')),
                        sender_id TEXT,
                        body TEXT NOT NULL DEFAULT '',
                        telegram_message_id BIGINT,
                        delivery_status TEXT NOT NULL DEFAULT 'stored'
                            CHECK (delivery_status IN ('stored', 'queued', 'sent', 'failed')),
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                await cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_support_messages_ticket_created
                    ON support_messages(ticket_id, created_at, id)
                    """
                )

                await cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS support_attachments (
                        id BIGSERIAL PRIMARY KEY,
                        message_id BIGINT NOT NULL REFERENCES support_messages(id) ON DELETE CASCADE,
                        kind TEXT NOT NULL CHECK (kind IN ('photo', 'document', 'video', 'audio', 'other')),
                        telegram_file_id TEXT NOT NULL,
                        file_name TEXT,
                        mime_type TEXT,
                        size_bytes BIGINT,
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                await cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_support_attachments_message
                    ON support_attachments(message_id)
                    """
                )

                await cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS support_outbox (
                        id BIGSERIAL PRIMARY KEY,
                        ticket_id BIGINT NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
                        message_id BIGINT NOT NULL UNIQUE REFERENCES support_messages(id) ON DELETE CASCADE,
                        telegram_id BIGINT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'queued'
                            CHECK (status IN ('queued', 'sending', 'sent', 'failed', 'cancelled')),
                        attempts INTEGER NOT NULL DEFAULT 0,
                        next_attempt_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        last_error TEXT,
                        telegram_message_id BIGINT,
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        sent_at TIMESTAMP
                    )
                    """
                )
                await cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_support_outbox_delivery
                    ON support_outbox(status, next_attempt_at, id)
                    """
                )

                await cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cms_documents (
                        id BIGSERIAL PRIMARY KEY,
                        document_key TEXT UNIQUE NOT NULL,
                        title TEXT NOT NULL,
                        kind TEXT NOT NULL CHECK (kind IN ('announcement', 'help', 'faq', 'banner', 'legal')),
                        status TEXT NOT NULL DEFAULT 'draft'
                            CHECK (status IN ('draft', 'published', 'archived')),
                        published_version_id BIGINT,
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                await cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cms_document_versions (
                        id BIGSERIAL PRIMARY KEY,
                        document_id BIGINT NOT NULL REFERENCES cms_documents(id) ON DELETE CASCADE,
                        version_number INTEGER NOT NULL,
                        content JSONB NOT NULL,
                        reason TEXT NOT NULL,
                        created_by TEXT,
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(document_id, version_number)
                    )
                    """
                )
                await cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_cms_versions_document
                    ON cms_document_versions(document_id, version_number DESC)
                    """
                )
                await cursor.execute(
                    """
                    ALTER TABLE cms_documents
                    DROP CONSTRAINT IF EXISTS cms_documents_published_version_fk
                    """
                )
                await cursor.execute(
                    """
                    ALTER TABLE cms_documents
                    ADD CONSTRAINT cms_documents_published_version_fk
                    FOREIGN KEY (published_version_id)
                    REFERENCES cms_document_versions(id)
                    ON DELETE SET NULL
                    """
                )

                await cursor.execute(
                    """
                    CREATE OR REPLACE FUNCTION support_touch_ticket()
                    RETURNS trigger AS $$
                    BEGIN
                        UPDATE support_tickets
                        SET updated_at = CURRENT_TIMESTAMP,
                            last_user_message_at = CASE
                                WHEN NEW.sender_type = 'user' THEN CURRENT_TIMESTAMP
                                ELSE last_user_message_at
                            END,
                            last_admin_message_at = CASE
                                WHEN NEW.sender_type = 'admin' THEN CURRENT_TIMESTAMP
                                ELSE last_admin_message_at
                            END,
                            status = CASE
                                WHEN NEW.sender_type = 'user' AND status IN ('waiting_user', 'resolved')
                                    THEN 'in_progress'
                                WHEN NEW.sender_type = 'admin' AND status = 'new'
                                    THEN 'in_progress'
                                ELSE status
                            END
                        WHERE id = NEW.ticket_id;
                        RETURN NEW;
                    END;
                    $$ LANGUAGE plpgsql
                    """
                )
                await cursor.execute(
                    "DROP TRIGGER IF EXISTS support_messages_touch_ticket ON support_messages"
                )
                await cursor.execute(
                    """
                    CREATE TRIGGER support_messages_touch_ticket
                    AFTER INSERT ON support_messages
                    FOR EACH ROW EXECUTE FUNCTION support_touch_ticket()
                    """
                )

                await cursor.execute(
                    """
                    CREATE OR REPLACE FUNCTION internal_admin_prevent_cms_version_mutation()
                    RETURNS trigger AS $$
                    BEGIN
                        RAISE EXCEPTION 'cms versions are append-only';
                    END;
                    $$ LANGUAGE plpgsql
                    """
                )
                await cursor.execute(
                    "DROP TRIGGER IF EXISTS cms_versions_append_only ON cms_document_versions"
                )
                await cursor.execute(
                    """
                    CREATE TRIGGER cms_versions_append_only
                    BEFORE UPDATE OR DELETE ON cms_document_versions
                    FOR EACH ROW EXECUTE FUNCTION internal_admin_prevent_cms_version_mutation()
                    """
                )
            await connection.commit()
        except Exception:
            await connection.rollback()
            logger.exception("Failed to initialize CMS/support schema")
            raise
        finally:
            await connection.close()

        _SCHEMA_READY = True
