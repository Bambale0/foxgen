import asyncio

from bot import max_admin_store


class _FakeCursor:
    def __init__(self, statements: list[str]) -> None:
        self.statements = statements

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, statement: str) -> None:
        self.statements.append(statement)


class _FakeRawConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.commits = 0

    def cursor(self):
        return _FakeCursor(self.statements)

    async def commit(self) -> None:
        self.commits += 1


class _FakeConnection:
    def __init__(self, raw: _FakeRawConnection) -> None:
        self._conn = raw

    async def execute(self, statement: str, params=()):
        raise AssertionError("PostgreSQL DDL must use the raw migration connection")


class _FakeConnectContext:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_max_admin_schema_uses_raw_postgres_migration_handle(monkeypatch) -> None:
    raw = _FakeRawConnection()
    connection = _FakeConnection(raw)

    async def fake_ensure_max_schema() -> None:
        return None

    monkeypatch.setattr(max_admin_store, "ensure_max_schema", fake_ensure_max_schema)
    monkeypatch.setattr(max_admin_store.db_backend, "is_postgres", lambda: True)
    monkeypatch.setattr(max_admin_store.db_backend, "DATABASE_URL", "postgresql://test/max")
    monkeypatch.setattr(
        max_admin_store.db_backend,
        "connect",
        lambda: _FakeConnectContext(connection),
    )
    max_admin_store._SCHEMA_READY.clear()

    asyncio.run(max_admin_store.ensure_max_admin_schema())

    assert len(raw.statements) == 2
    assert "CREATE TABLE IF NOT EXISTS max_admins" in raw.statements[0]
    assert "CREATE TABLE IF NOT EXISTS max_admin_invites" in raw.statements[1]
    assert raw.commits == 1

    asyncio.run(max_admin_store.ensure_max_admin_schema())
    assert len(raw.statements) == 2
    assert raw.commits == 1
