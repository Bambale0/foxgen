from __future__ import annotations

import os
from urllib.parse import urlsplit

import psycopg
from psycopg import sql


PROMPT_FEED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("user_prompts", "source_generation_id", "BIGINT"),
    ("user_prompts", "generation_settings", "TEXT DEFAULT '{}'"),
    ("generation_tasks", "result_urls", "TEXT"),
    ("generation_tasks", "is_public_feed", "BOOLEAN DEFAULT FALSE"),
    ("generation_tasks", "is_profile_visible", "BOOLEAN DEFAULT FALSE"),
    ("generation_tasks", "is_adult_content", "BOOLEAN DEFAULT FALSE"),
    ("generation_tasks", "is_prompt_library", "BOOLEAN DEFAULT FALSE"),
    ("generation_tasks", "source_feed_gen_id", "BIGINT"),
    ("generation_tasks", "parent_generation_id", "BIGINT"),
    ("generation_tasks", "action_type", "TEXT"),
    ("generation_tasks", "likes_count", "INTEGER DEFAULT 0"),
    ("generation_tasks", "shares_count", "INTEGER DEFAULT 0"),
    ("generation_tasks", "feed_prompt_visible", "BOOLEAN DEFAULT FALSE"),
    ("generation_tasks", "feed_references_visible", "BOOLEAN DEFAULT FALSE"),
    ("generation_tasks", "feed_blurred", "BOOLEAN DEFAULT FALSE"),
    ("generation_tasks", "feed_published_at", "TIMESTAMP"),
)


def _postgres_dsn() -> str | None:
    value = str(os.getenv("DATABASE_URL", "") or "").strip()
    if not value:
        return None
    if value.lower().startswith("postgresql+asyncpg://"):
        value = "postgresql://" + value[len("postgresql+asyncpg://") :]
    parsed = urlsplit(value)
    if parsed.scheme not in {"postgres", "postgresql"}:
        return None
    return value


def ensure_schema() -> int:
    dsn = _postgres_dsn()
    if not dsn:
        print("[happyfox-schema] PostgreSQL not configured; schema guard skipped")
        return 0

    changed: list[str] = []
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cursor:
        for table, column, definition in PROMPT_FEED_COLUMNS:
            cursor.execute("SELECT to_regclass(%s)", (table,))
            row = cursor.fetchone()
            if not row or row[0] is None:
                continue

            cursor.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = %s AND column_name = %s",
                (table, column),
            )
            if cursor.fetchone():
                continue

            cursor.execute(
                sql.SQL("ALTER TABLE {} ADD COLUMN {} {}").format(
                    sql.Identifier(table),
                    sql.Identifier(column),
                    sql.SQL(definition),
                )
            )
            changed.append(f"{table}.{column}")

    if changed:
        print("[happyfox-schema] added=" + ",".join(changed))
    else:
        print("[happyfox-schema] schema current")
    return 0


if __name__ == "__main__":
    raise SystemExit(ensure_schema())
