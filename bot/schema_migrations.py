from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from bot import db as db_backend

logger = logging.getLogger(__name__)

MigrationApply = Callable[[db_backend.Connection], Awaitable[None]]


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: MigrationApply


async def _execute_schema_ddl(connection: db_backend.Connection, statement: str) -> None:
    if not db_backend.is_postgres():
        await connection.execute(statement)
        return

    raw = getattr(connection, "_conn", None)
    if raw is None:
        raise RuntimeError("PostgreSQL connection does not expose migration handle")
    async with raw.cursor() as cursor:
        await cursor.execute(statement)


async def _ensure_migration_ledger(connection: db_backend.Connection) -> None:
    await _execute_schema_ddl(
        connection,
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
    )
    await connection.commit()


async def _payment_identity_unique_index(connection: db_backend.Connection) -> None:
    connection.row_factory = db_backend.Row
    duplicate = await (
        await connection.execute(
            """
            SELECT provider, payment_id, COUNT(*) AS duplicate_count
            FROM transactions
            WHERE payment_id IS NOT NULL AND payment_id <> ''
            GROUP BY provider, payment_id
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).fetchone()
    if duplicate:
        raise RuntimeError(
            "Cannot create unique payment identity index: duplicate provider/payment_id "
            f"provider={duplicate['provider']!r} payment_id={duplicate['payment_id']!r} "
            f"count={duplicate['duplicate_count']}"
        )

    await _execute_schema_ddl(
        connection,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_transactions_provider_payment_id
        ON transactions(provider, payment_id)
        WHERE payment_id IS NOT NULL AND payment_id <> ''
        """,
    )


_PROMPT_FEED_COMPATIBILITY_DDL: tuple[str, ...] = (
    "ALTER TABLE user_prompts ADD COLUMN IF NOT EXISTS source_generation_id BIGINT",
    "ALTER TABLE user_prompts ADD COLUMN IF NOT EXISTS generation_settings TEXT DEFAULT '{}'",
    "ALTER TABLE generation_tasks ADD COLUMN IF NOT EXISTS result_urls TEXT",
    "ALTER TABLE generation_tasks ADD COLUMN IF NOT EXISTS is_public_feed BOOLEAN DEFAULT FALSE",
    "ALTER TABLE generation_tasks ADD COLUMN IF NOT EXISTS is_profile_visible BOOLEAN DEFAULT FALSE",
    "ALTER TABLE generation_tasks ADD COLUMN IF NOT EXISTS is_adult_content BOOLEAN DEFAULT FALSE",
    "ALTER TABLE generation_tasks ADD COLUMN IF NOT EXISTS is_prompt_library BOOLEAN DEFAULT FALSE",
    "ALTER TABLE generation_tasks ADD COLUMN IF NOT EXISTS source_feed_gen_id BIGINT",
    "ALTER TABLE generation_tasks ADD COLUMN IF NOT EXISTS parent_generation_id BIGINT",
    "ALTER TABLE generation_tasks ADD COLUMN IF NOT EXISTS action_type TEXT",
    "ALTER TABLE generation_tasks ADD COLUMN IF NOT EXISTS likes_count INTEGER DEFAULT 0",
    "ALTER TABLE generation_tasks ADD COLUMN IF NOT EXISTS shares_count INTEGER DEFAULT 0",
    "ALTER TABLE generation_tasks ADD COLUMN IF NOT EXISTS feed_prompt_visible BOOLEAN DEFAULT FALSE",
    "ALTER TABLE generation_tasks ADD COLUMN IF NOT EXISTS feed_references_visible BOOLEAN DEFAULT FALSE",
    "ALTER TABLE generation_tasks ADD COLUMN IF NOT EXISTS feed_blurred BOOLEAN DEFAULT FALSE",
    "ALTER TABLE generation_tasks ADD COLUMN IF NOT EXISTS feed_published_at TIMESTAMP",
)


async def _prompt_feed_compatibility_columns(
    connection: db_backend.Connection,
) -> None:
    for statement in _PROMPT_FEED_COMPATIBILITY_DDL:
        await _execute_schema_ddl(connection, statement)


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        name="unique payment provider identity",
        apply=_payment_identity_unique_index,
    ),
    Migration(
        version=2,
        name="prompt feed compatibility columns",
        apply=_prompt_feed_compatibility_columns,
    ),
)


def _validate_registry() -> None:
    versions = [migration.version for migration in MIGRATIONS]
    if versions != sorted(versions) or len(versions) != len(set(versions)):
        raise RuntimeError("Schema migration versions must be unique and ordered")
    if versions and versions[0] != 1:
        raise RuntimeError("Schema migration registry must start at version 1")


async def run_schema_migrations() -> list[int]:
    """Apply pending HappyFox PostgreSQL migrations exactly once.

    SQLite remains a development/test compatibility backend. Production schema
    evolution is authoritative here so new changes no longer depend on request-
    time ``CREATE TABLE IF NOT EXISTS`` side effects.
    """

    if not db_backend.is_postgres():
        return []

    _validate_registry()
    applied_versions: list[int] = []

    async with db_backend.connect() as connection:
        await _ensure_migration_ledger(connection)
        connection.row_factory = db_backend.Row
        rows = await (
            await connection.execute(
                "SELECT version, name FROM schema_migrations ORDER BY version"
            )
        ).fetchall()
        applied = {int(row["version"]): str(row["name"]) for row in rows}

        known_versions = {migration.version for migration in MIGRATIONS}
        unknown = sorted(set(applied) - known_versions)
        if unknown:
            raise RuntimeError(
                "Database contains schema migrations unknown to this release: "
                + ", ".join(str(version) for version in unknown)
            )

        for migration in MIGRATIONS:
            previous_name = applied.get(migration.version)
            if previous_name is not None:
                if previous_name != migration.name:
                    raise RuntimeError(
                        "Schema migration identity changed for version "
                        f"{migration.version}: database={previous_name!r} code={migration.name!r}"
                    )
                continue

            logger.info(
                "Applying schema migration %s: %s",
                migration.version,
                migration.name,
            )
            try:
                await migration.apply(connection)
                await connection.execute(
                    "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
                    (migration.version, migration.name),
                )
                await connection.commit()
            except Exception:
                try:
                    await connection.rollback()
                except Exception:
                    logger.exception(
                        "Failed to roll back schema migration %s",
                        migration.version,
                    )
                raise
            applied_versions.append(migration.version)

    return applied_versions
