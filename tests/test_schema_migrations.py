import aiosqlite
import pytest

from bot import schema_migrations


def test_migration_registry_is_ordered_and_unique() -> None:
    versions = [migration.version for migration in schema_migrations.MIGRATIONS]

    assert versions == sorted(versions)
    assert len(versions) == len(set(versions))
    assert versions[0] == 1


@pytest.mark.asyncio
async def test_non_postgres_runtime_skips_production_migrations(monkeypatch) -> None:
    monkeypatch.setattr(schema_migrations.db_backend, "is_postgres", lambda: False)

    assert await schema_migrations.run_schema_migrations() == []


@pytest.mark.asyncio
async def test_payment_identity_migration_rejects_existing_duplicates() -> None:
    async with aiosqlite.connect(":memory:") as connection:
        await connection.execute(
            "CREATE TABLE transactions(provider TEXT, payment_id TEXT)"
        )
        await connection.executemany(
            "INSERT INTO transactions(provider, payment_id) VALUES (?, ?)",
            [("yookassa", "pay-1"), ("yookassa", "pay-1")],
        )
        await connection.commit()

        with pytest.raises(RuntimeError, match="duplicate provider/payment_id"):
            await schema_migrations._payment_identity_unique_index(connection)


@pytest.mark.asyncio
async def test_payment_identity_migration_enforces_provider_scoped_uniqueness() -> None:
    async with aiosqlite.connect(":memory:") as connection:
        await connection.execute(
            "CREATE TABLE transactions(provider TEXT, payment_id TEXT)"
        )
        await schema_migrations._payment_identity_unique_index(connection)
        await connection.execute(
            "INSERT INTO transactions(provider, payment_id) VALUES (?, ?)",
            ("yookassa", "pay-1"),
        )
        await connection.execute(
            "INSERT INTO transactions(provider, payment_id) VALUES (?, ?)",
            ("lava", "pay-1"),
        )
        await connection.commit()

        with pytest.raises(aiosqlite.IntegrityError):
            await connection.execute(
                "INSERT INTO transactions(provider, payment_id) VALUES (?, ?)",
                ("yookassa", "pay-1"),
            )


class _NoRowsCursor:
    async def fetchone(self):
        return None


class _RawCursor:
    def __init__(self, statements: list[str]):
        self._statements = statements

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, sql: str, parameters=None) -> None:
        self._statements.append(" ".join(sql.split()))


class _RawPostgresConnection:
    def __init__(self):
        self.statements: list[str] = []
        self.commits = 0

    def cursor(self) -> _RawCursor:
        return _RawCursor(self.statements)

    async def commit(self) -> None:
        self.commits += 1


class _CompatibilityPostgresConnection:
    def __init__(self):
        self._conn = _RawPostgresConnection()
        self.row_factory = None

    async def execute(self, sql: str, parameters=None):
        normalized = sql.lstrip().upper()
        if normalized.startswith(("CREATE TABLE ", "CREATE INDEX ", "CREATE UNIQUE INDEX ", "ALTER TABLE ")):
            raise AssertionError("production schema DDL must bypass compatibility execute()")
        if "FROM TRANSACTIONS" in normalized and "HAVING COUNT(*) > 1" in normalized:
            return _NoRowsCursor()
        raise AssertionError(f"unexpected compatibility SQL: {sql}")

    async def commit(self) -> None:
        await self._conn.commit()


@pytest.mark.asyncio
async def test_postgres_schema_ddl_uses_raw_connection(monkeypatch) -> None:
    monkeypatch.setattr(schema_migrations.db_backend, "is_postgres", lambda: True)
    connection = _CompatibilityPostgresConnection()

    await schema_migrations._ensure_migration_ledger(connection)
    await schema_migrations._payment_identity_unique_index(connection)

    executed = "\n".join(connection._conn.statements)
    assert "CREATE TABLE IF NOT EXISTS schema_migrations" in executed
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_transactions_provider_payment_id" in executed
