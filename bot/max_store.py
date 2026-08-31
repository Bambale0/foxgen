from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from bot import db as db_backend

_SCHEMA_LOCK: asyncio.Lock | None = None
_SCHEMA_READY: set[str] = set()


class MaxInsufficientBalanceError(ValueError):
    """Raised when an isolated MAX balance cannot cover a debit."""


@dataclass(frozen=True)
class MaxUser:
    max_user_id: int
    username: str
    first_name: str
    last_name: str
    balance_credits: float


@dataclass(frozen=True)
class MaxSession:
    max_user_id: int
    state: str
    data: dict[str, Any]


def _schema_lock() -> asyncio.Lock:
    global _SCHEMA_LOCK
    if _SCHEMA_LOCK is None:
        _SCHEMA_LOCK = asyncio.Lock()
    return _SCHEMA_LOCK


def _schema_key() -> str:
    if db_backend.is_postgres():
        return f"postgres:{db_backend.DATABASE_URL}:max"
    return f"sqlite:{db_backend.DATABASE_PATH}:max"


def _schema_statements(*, postgres: bool) -> tuple[str, ...]:
    tx_id = "BIGSERIAL PRIMARY KEY" if postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
    history_id = "BIGSERIAL PRIMARY KEY" if postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
    return (
        """
        CREATE TABLE IF NOT EXISTS max_users (
            max_user_id BIGINT PRIMARY KEY,
            username TEXT NOT NULL DEFAULT '',
            first_name TEXT NOT NULL DEFAULT '',
            last_name TEXT NOT NULL DEFAULT '',
            balance_credits REAL NOT NULL DEFAULT 0 CHECK(balance_credits >= 0),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS max_transactions (
            id {tx_id},
            max_user_id BIGINT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            type TEXT NOT NULL,
            amount_credits REAL NOT NULL,
            amount_rub REAL,
            payment_provider TEXT,
            provider_order_id TEXT,
            status TEXT NOT NULL DEFAULT 'completed',
            metadata_json TEXT NOT NULL DEFAULT '{{}}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (max_user_id) REFERENCES max_users(max_user_id) ON DELETE CASCADE
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_max_transactions_user ON max_transactions(max_user_id, created_at)",
        f"""
        CREATE TABLE IF NOT EXISTS max_generation_history (
            id {history_id},
            max_user_id BIGINT NOT NULL,
            generation_key TEXT NOT NULL UNIQUE,
            provider_task_id TEXT,
            kind TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            cost REAL NOT NULL DEFAULT 0,
            result_url TEXT,
            request_json TEXT NOT NULL DEFAULT '{{}}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (max_user_id) REFERENCES max_users(max_user_id) ON DELETE CASCADE
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_max_history_user ON max_generation_history(max_user_id, created_at)",
        """
        CREATE TABLE IF NOT EXISTS max_sessions (
            max_user_id BIGINT PRIMARY KEY,
            state TEXT NOT NULL DEFAULT '',
            data_json TEXT NOT NULL DEFAULT '{}',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (max_user_id) REFERENCES max_users(max_user_id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS max_event_receipts (
            event_key TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'processing',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
    )


async def _create_postgres_schema(db: db_backend.Connection) -> None:
    raw = getattr(db, "_conn", None)
    if raw is None:
        raise RuntimeError("PostgreSQL connection does not expose migration handle")
    async with raw.cursor() as cursor:
        for statement in _schema_statements(postgres=True):
            await cursor.execute(statement)
    await raw.commit()


async def ensure_max_schema() -> None:
    key = _schema_key()
    if key in _SCHEMA_READY:
        return
    async with _schema_lock():
        if key in _SCHEMA_READY:
            return
        async with db_backend.connect() as db:
            if db_backend.is_postgres():
                await _create_postgres_schema(db)
            else:
                for statement in _schema_statements(postgres=False):
                    await db.execute(statement)
                await db.commit()
        _SCHEMA_READY.add(key)


def _mapping_rows(db: db_backend.Connection) -> None:
    db.row_factory = db_backend.Row


def _to_user(row: Any | None) -> MaxUser | None:
    if row is None:
        return None
    return MaxUser(
        max_user_id=int(row["max_user_id"]),
        username=str(row["username"] or ""),
        first_name=str(row["first_name"] or ""),
        last_name=str(row["last_name"] or ""),
        balance_credits=float(row["balance_credits"] or 0),
    )


async def ensure_max_user(
    max_user_id: int,
    *,
    username: str = "",
    first_name: str = "",
    last_name: str = "",
) -> MaxUser:
    if int(max_user_id) <= 0:
        raise ValueError("max_user_id must be positive")
    await ensure_max_schema()
    async with db_backend.connect() as db:
        _mapping_rows(db)
        await db.execute(
            """
            INSERT INTO max_users (max_user_id, username, first_name, last_name)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(max_user_id) DO UPDATE SET
                username = CASE WHEN excluded.username <> '' THEN excluded.username ELSE max_users.username END,
                first_name = CASE WHEN excluded.first_name <> '' THEN excluded.first_name ELSE max_users.first_name END,
                last_name = CASE WHEN excluded.last_name <> '' THEN excluded.last_name ELSE max_users.last_name END,
                updated_at = CURRENT_TIMESTAMP,
                last_seen_at = CURRENT_TIMESTAMP
            """,
            (int(max_user_id), str(username or ""), str(first_name or ""), str(last_name or "")),
        )
        await db.commit()
        cursor = await db.execute(
            "SELECT max_user_id, username, first_name, last_name, balance_credits FROM max_users WHERE max_user_id = ?",
            (int(max_user_id),),
        )
        user = _to_user(await cursor.fetchone())
    if user is None:
        raise RuntimeError("Failed to persist MAX user")
    return user


async def get_max_user(max_user_id: int) -> MaxUser | None:
    await ensure_max_schema()
    async with db_backend.connect() as db:
        _mapping_rows(db)
        cursor = await db.execute(
            "SELECT max_user_id, username, first_name, last_name, balance_credits FROM max_users WHERE max_user_id = ?",
            (int(max_user_id),),
        )
        return _to_user(await cursor.fetchone())


async def get_max_balance(max_user_id: int) -> float:
    user = await get_max_user(max_user_id)
    return float(user.balance_credits if user is not None else 0)


async def apply_max_balance_delta(
    max_user_id: int,
    amount_credits: float,
    *,
    tx_type: str,
    idempotency_key: str,
    amount_rub: float | None = None,
    payment_provider: str | None = None,
    provider_order_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> float:
    """Apply one isolated MAX ledger mutation exactly once."""
    if not idempotency_key.strip():
        raise ValueError("idempotency_key is required")
    await ensure_max_user(max_user_id)
    amount = float(amount_credits)
    async with db_backend.connect() as db:
        _mapping_rows(db)
        existing = await db.execute(
            "SELECT id FROM max_transactions WHERE idempotency_key = ?",
            (idempotency_key,),
        )
        if await existing.fetchone() is not None:
            cursor = await db.execute(
                "SELECT balance_credits FROM max_users WHERE max_user_id = ?",
                (int(max_user_id),),
            )
            row = await cursor.fetchone()
            return float(row["balance_credits"] if row is not None else 0)

        update = await db.execute(
            """
            UPDATE max_users
            SET balance_credits = balance_credits + ?, updated_at = CURRENT_TIMESTAMP
            WHERE max_user_id = ? AND balance_credits + ? >= 0
            """,
            (amount, int(max_user_id), amount),
        )
        if int(getattr(update, "rowcount", 0) or 0) != 1:
            await db.rollback()
            raise MaxInsufficientBalanceError("MAX balance is insufficient")

        await db.execute(
            """
            INSERT INTO max_transactions (
                max_user_id, idempotency_key, type, amount_credits, amount_rub,
                payment_provider, provider_order_id, status, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'completed', ?)
            """,
            (
                int(max_user_id),
                idempotency_key,
                tx_type,
                amount,
                amount_rub,
                payment_provider,
                provider_order_id,
                json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
            ),
        )
        await db.commit()
        cursor = await db.execute(
            "SELECT balance_credits FROM max_users WHERE max_user_id = ?",
            (int(max_user_id),),
        )
        row = await cursor.fetchone()
        return float(row["balance_credits"] if row is not None else 0)


async def get_max_session(max_user_id: int) -> MaxSession:
    await ensure_max_user(max_user_id)
    async with db_backend.connect() as db:
        _mapping_rows(db)
        cursor = await db.execute(
            "SELECT state, data_json FROM max_sessions WHERE max_user_id = ?",
            (int(max_user_id),),
        )
        row = await cursor.fetchone()
    if row is None:
        return MaxSession(max_user_id=int(max_user_id), state="", data={})
    try:
        data = json.loads(str(row["data_json"] or "{}"))
    except (TypeError, ValueError):
        data = {}
    return MaxSession(max_user_id=int(max_user_id), state=str(row["state"] or ""), data=data)


async def save_max_session(max_user_id: int, state: str, data: dict[str, Any] | None = None) -> None:
    await ensure_max_user(max_user_id)
    encoded = json.dumps(data or {}, ensure_ascii=False, sort_keys=True)
    async with db_backend.connect() as db:
        await db.execute(
            """
            INSERT INTO max_sessions (max_user_id, state, data_json, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(max_user_id) DO UPDATE SET
                state = excluded.state,
                data_json = excluded.data_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (int(max_user_id), str(state or ""), encoded),
        )
        await db.commit()


async def clear_max_session(max_user_id: int) -> None:
    await save_max_session(max_user_id, "", {})


async def record_max_generation(
    max_user_id: int,
    *,
    generation_key: str,
    kind: str,
    model: str,
    prompt: str,
    status: str,
    cost: float,
    provider_task_id: str | None = None,
    result_url: str | None = None,
    request_data: dict[str, Any] | None = None,
) -> None:
    await ensure_max_user(max_user_id)
    async with db_backend.connect() as db:
        await db.execute(
            """
            INSERT INTO max_generation_history (
                max_user_id, generation_key, provider_task_id, kind, model, prompt,
                status, cost, result_url, request_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(generation_key) DO UPDATE SET
                provider_task_id = COALESCE(excluded.provider_task_id, max_generation_history.provider_task_id),
                status = excluded.status,
                result_url = COALESCE(excluded.result_url, max_generation_history.result_url),
                request_json = excluded.request_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                int(max_user_id),
                generation_key,
                provider_task_id,
                kind,
                model,
                prompt,
                status,
                float(cost),
                result_url,
                json.dumps(request_data or {}, ensure_ascii=False, sort_keys=True),
            ),
        )
        await db.commit()


async def list_max_history(max_user_id: int, limit: int = 10) -> list[dict[str, Any]]:
    await ensure_max_schema()
    safe_limit = min(max(int(limit), 1), 100)
    async with db_backend.connect() as db:
        _mapping_rows(db)
        cursor = await db.execute(
            """
            SELECT generation_key, provider_task_id, kind, model, prompt, status, cost,
                   result_url, created_at, updated_at
            FROM max_generation_history
            WHERE max_user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(max_user_id), safe_limit),
        )
        rows = await cursor.fetchall()
    return [dict(row) for row in rows]


def max_event_key(update: dict[str, Any]) -> str:
    encoded = json.dumps(update, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def claim_max_event(event_key: str) -> bool:
    await ensure_max_schema()
    async with db_backend.connect() as db:
        cursor = await db.execute(
            """
            INSERT INTO max_event_receipts (event_key, status)
            VALUES (?, 'processing')
            ON CONFLICT(event_key) DO NOTHING
            """,
            (event_key,),
        )
        await db.commit()
        return int(getattr(cursor, "rowcount", 0) or 0) == 1


async def mark_max_event_processed(event_key: str) -> None:
    await ensure_max_schema()
    async with db_backend.connect() as db:
        await db.execute(
            "UPDATE max_event_receipts SET status = 'processed', updated_at = CURRENT_TIMESTAMP WHERE event_key = ?",
            (event_key,),
        )
        await db.commit()


async def release_max_event(event_key: str) -> None:
    """Allow MAX to retry an update after a failed handler execution."""
    await ensure_max_schema()
    async with db_backend.connect() as db:
        await db.execute("DELETE FROM max_event_receipts WHERE event_key = ?", (event_key,))
        await db.commit()
