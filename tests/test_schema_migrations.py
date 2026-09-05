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
