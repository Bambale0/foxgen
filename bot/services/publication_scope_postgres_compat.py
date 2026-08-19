from __future__ import annotations

import logging

from bot import db as db_backend

logger = logging.getLogger(__name__)
_INSTALLED = False
_HELPERS_EXTENDED = False


def install_publication_scope_postgres_compat() -> None:
    """Teach the SQLite-compatible Postgres adapter about profile visibility."""
    global _INSTALLED
    if _INSTALLED or not db_backend.is_postgres():
        return

    from bot import postgres_aiosqlite as postgres_backend

    if "is_profile_visible" not in postgres_backend._BOOL_COLUMNS:
        postgres_backend._BOOL_COLUMNS = (
            *postgres_backend._BOOL_COLUMNS,
            "is_profile_visible",
        )
        for helper_name in (
            "_bool_column_names",
            "_bool_assignment_param_indexes",
            "_bool_insert_param_indexes",
        ):
            cache_clear = getattr(
                getattr(postgres_backend, helper_name),
                "cache_clear",
                None,
            )
            if cache_clear is not None:
                cache_clear()

    original_helpers = postgres_backend._ensure_postgres_helpers

    async def ensure_helpers_with_publication_scope(conn) -> None:
        global _HELPERS_EXTENDED
        await original_helpers(conn)
        if _HELPERS_EXTENDED:
            return

        async with conn.cursor() as cursor:
            await cursor.execute(
                'ALTER TABLE "generation_tasks" '
                'ADD COLUMN IF NOT EXISTS "is_profile_visible" BOOLEAN DEFAULT FALSE'
            )
            await cursor.execute(
                'ALTER TABLE "generation_tasks" '
                'ADD COLUMN IF NOT EXISTS "profile_published_at" TIMESTAMP'
            )
            await cursor.execute(
                'UPDATE "generation_tasks" '
                'SET "is_profile_visible" = TRUE, '
                '"profile_published_at" = COALESCE('
                '"profile_published_at", "feed_published_at", "created_at") '
                'WHERE "is_public_feed" IS TRUE '
                'AND COALESCE("is_profile_visible", FALSE) IS FALSE'
            )
            await cursor.execute(
                'CREATE INDEX IF NOT EXISTS "idx_generation_tasks_profile" '
                'ON "generation_tasks"('
                '"is_profile_visible", "user_id", '
                '"profile_published_at" DESC, "created_at" DESC)'
            )
        await conn.commit()
        _HELPERS_EXTENDED = True
        logger.info("Postgres publication scope schema is ready")

    postgres_backend._ensure_postgres_helpers = ensure_helpers_with_publication_scope
    _INSTALLED = True
