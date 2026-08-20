# PostgreSQL migration notes for banano_kling

## Current state

- Production runtime uses PostgreSQL via `DATABASE_URL` from `.env.postgres`.
- Redis is only used for FSM/cache, not as the primary business database.
- SQLite files such as `bot.db` are legacy/import sources and should not be treated as the live business database after cutover.

## Prepared assets

- `.env.postgres` — local Postgres connection settings (root-only, not committed)
- `scripts/migrate_sqlite_to_postgres.py` — schema + data migration from SQLite to Postgres
- `scripts/verify_postgres_migration.py` — row-count verification
- `scripts/check_postgres_runtime.py` — current Postgres runtime health/count check

## Recommended cutover path

1. Stop writes briefly or enable maintenance window.
2. Run final SQLite backup.
3. Run `scripts/migrate_sqlite_to_postgres.py --drop-existing`.
4. Verify one-time migration counts with `scripts/verify_postgres_migration.py` before live writes resume.
5. Ensure `.env.postgres` is present and readable by the service user.
6. Restart `banano-kling.service` and confirm runtime with `scripts/check_postgres_runtime.py`.

## Runtime notes

The app keeps an `aiosqlite`-compatible DB facade for legacy call sites, but production should resolve `bot.db.backend_name()` to `postgres`. Keep SQLite compatibility only for imports, tests, and emergency recovery paths.

After Postgres is live, `scripts/verify_postgres_migration.py` may report count mismatches against `bot.db` because SQLite is no longer the write target. Use `scripts/check_postgres_runtime.py` for normal production checks.
