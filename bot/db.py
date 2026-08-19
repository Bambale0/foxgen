from __future__ import annotations

import os
import sys
from typing import Any

import aiosqlite


DATABASE_PATH = os.getenv("DATABASE_PATH", "bot.db")
DATABASE_URL = os.getenv("DATABASE_URL", "")
SQLITE_BUSY_TIMEOUT_MS = int(os.getenv("SQLITE_BUSY_TIMEOUT_MS", "30000"))

Row = aiosqlite.Row
Connection = Any
OperationalError = aiosqlite.OperationalError
IntegrityError = aiosqlite.IntegrityError


class _ConfiguredSqliteConnection:
    def __init__(self, connector):
        self._connector = connector
        self._conn = None
        self._configured = False

    async def _ensure(self):
        if self._conn is None:
            self._conn = await self._connector
        if not self._configured:
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.execute("PRAGMA synchronous=NORMAL")
            await self._conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
            await self._conn.execute("PRAGMA foreign_keys=ON")
            await self._conn.execute("PRAGMA temp_store=MEMORY")
            self._configured = True
        return self._conn

    def __await__(self):
        return self._ensure().__await__()

    async def __aenter__(self):
        return await self._ensure()

    async def __aexit__(self, exc_type, exc, tb):
        conn = await self._ensure()
        return await conn.__aexit__(exc_type, exc, tb)


def is_postgres() -> bool:
    database_url = os.getenv("DATABASE_URL", DATABASE_URL).strip().lower()
    return database_url.startswith(
        ("postgresql://", "postgres://", "postgresql+asyncpg://")
    )


def backend_name() -> str:
    return "postgres" if is_postgres() else "sqlite"


def connect(database_path: str | None = None, *args, **kwargs):
    if is_postgres():
        from bot.postgres_aiosqlite import connect as postgres_connect

        return postgres_connect(*args, **kwargs)

    kwargs.setdefault("timeout", max(SQLITE_BUSY_TIMEOUT_MS / 1000, 5))
    if database_path is None:
        database_module = sys.modules.get("bot.database")
        database_path = str(
            getattr(database_module, "DATABASE_PATH", None)
            or os.getenv("DATABASE_PATH", DATABASE_PATH)
        )
    return _ConfiguredSqliteConnection(
        aiosqlite.connect(database_path, *args, **kwargs)
    )
