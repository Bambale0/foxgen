import asyncio

from bot import postgres_aiosqlite as pg


class _FakeRawConnection:
    def __init__(self):
        self.rollback_calls = 0
        self.close_calls = 0

    async def rollback(self):
        self.rollback_calls += 1

    async def close(self):
        self.close_calls += 1


class _FakePool:
    def __init__(self, raw=None):
        self.raw = raw or _FakeRawConnection()
        self.getconn_calls = 0
        self.putconn_calls = []
        self.close_calls = 0

    async def getconn(self):
        self.getconn_calls += 1
        return self.raw

    async def putconn(self, conn):
        self.putconn_calls.append(conn)

    async def close(self):
        self.close_calls += 1


def test_postgres_connect_returns_connection_to_pool(monkeypatch):
    async def scenario():
        raw = _FakeRawConnection()
        pool = _FakePool(raw)

        async def fake_get_pool():
            return pool

        async def fake_helpers(_conn):
            return None

        monkeypatch.setattr(pg, "_get_postgres_pool", fake_get_pool)
        monkeypatch.setattr(pg, "_ensure_postgres_helpers", fake_helpers)

        connector = pg.PostgresConnect()
        async with connector as conn:
            assert conn._conn is raw

        assert pool.getconn_calls == 1
        assert pool.putconn_calls == [raw]
        assert raw.rollback_calls == 1
        assert raw.close_calls == 0

    asyncio.run(scenario())


def test_standalone_connection_still_closes_physical_connection():
    async def scenario():
        raw = _FakeRawConnection()
        conn = pg.PostgresConnection(raw)
        await conn.close()
        await conn.close()

        assert raw.close_calls == 1
        assert raw.rollback_calls == 0

    asyncio.run(scenario())


def test_close_postgres_pool_resets_global(monkeypatch):
    async def scenario():
        pool = _FakePool()
        monkeypatch.setattr(pg, "_POSTGRES_POOL", pool)

        await pg.close_postgres_pool()

        assert pool.close_calls == 1
        assert pg._POSTGRES_POOL is None

    asyncio.run(scenario())
