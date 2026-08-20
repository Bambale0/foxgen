from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Mapping
from datetime import date, datetime
from functools import lru_cache
from typing import Any

import aiosqlite
import psycopg


_HELPERS_READY = False
_HELPERS_LOCK: asyncio.Lock | None = None
_LASTROWID_TABLES = {
    "batch_jobs",
    "feed_comments",
    "feed_generation_likes",
    "feed_remix_events",
    "generation_history",
    "generation_tasks",
    "miniapp_notifications",
    "partner_commissions",
    "partner_withdrawals",
    "promo_codes",
    "promo_redemptions",
    "prompt_likes",
    "prompt_repeat_events",
    "referral_events",
    "referrals",
    "saved_references",
    "transactions",
    "user_prompts",
    "user_settings",
    "users",
}
_BOOL_COLUMNS = (
    "attached",
    "has_paid",
    "is_active",
    "is_adult_content",
    "is_public",
    "is_public_feed",
    "is_profile_visible",
    "is_prompt_library",
    "is_repeat_click",
    "is_self_click",
    "feed_prompt_visible",
    "feed_references_visible",
    "feed_blurred",
    "referral_purchase_notifications_enabled",
)



def _get_helpers_lock() -> asyncio.Lock:
    global _HELPERS_LOCK
    if _HELPERS_LOCK is None:
        _HELPERS_LOCK = asyncio.Lock()
    return _HELPERS_LOCK


class PostgresRow(Mapping):
    def __init__(self, columns: list[str], values: tuple[Any, ...]):
        self._columns = columns
        self._values = tuple(self._normalize_value(value) for value in values)
        self._index = {column: index for index, column in enumerate(columns)}

    @staticmethod
    def _normalize_value(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat(sep=" ")
        if isinstance(value, date):
            return value.isoformat()
        return value

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return self._values[key]
        return self._values[self._index[key]]

    def __iter__(self):
        return iter(self._columns)

    def __len__(self) -> int:
        return len(self._columns)

    def keys(self):
        return self._columns


class PostgresCursor:
    def __init__(
        self,
        rows: list[tuple[Any, ...]] | None = None,
        columns: list[str] | None = None,
        *,
        rowcount: int = -1,
        lastrowid: int | None = None,
    ):
        self._rows = rows or []
        self._columns = columns or []
        self._pos = 0
        self.rowcount = rowcount
        self.lastrowid = lastrowid

    async def fetchone(self):
        if self._pos >= len(self._rows):
            return None
        row = self._rows[self._pos]
        self._pos += 1
        return PostgresRow(self._columns, row)

    async def fetchall(self):
        rows = self._rows[self._pos :]
        self._pos = len(self._rows)
        return [PostgresRow(self._columns, row) for row in rows]


def _normalize_postgres_dsn(value: str | None = None) -> str:
    url = str(value if value is not None else os.getenv("DATABASE_URL", "") or "").strip()
    if url.lower().startswith("postgresql+asyncpg://"):
        return "postgresql://" + url[len("postgresql+asyncpg://") :]
    return url


def _is_postgres_url(value: str | None = None) -> bool:
    url = _normalize_postgres_dsn(value).lower()
    return url.startswith(("postgresql://", "postgres://"))


def _translate_placeholders(sql: str) -> str:
    return sql.replace("?", "%s")


def _translate_insert_ignore(sql: str) -> str:
    if not re.search(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", sql, flags=re.IGNORECASE):
        return sql
    translated = re.sub(
        r"\bINSERT\s+OR\s+IGNORE\s+INTO\b",
        "INSERT INTO",
        sql,
        flags=re.IGNORECASE,
    )
    if re.search(r"\bON\s+CONFLICT\b", translated, flags=re.IGNORECASE):
        return translated
    return translated.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"


@lru_cache(maxsize=512)
def _update_set_bounds(sql: str) -> tuple[int, int] | None:
    set_match = re.search(r"\bSET\b", sql, flags=re.IGNORECASE)
    if not set_match:
        return None
    where_match = re.search(r"\bWHERE\b", sql[set_match.end() :], flags=re.IGNORECASE)
    end = set_match.end() + where_match.start() if where_match else len(sql)
    return set_match.end(), end


def _bool_column_names() -> str:
    return "|".join(_BOOL_COLUMNS)


def _split_csv(segment: str) -> list[tuple[str, int, int]]:
    items: list[tuple[str, int, int]] = []
    start = 0
    depth = 0
    quote: str | None = None
    index = 0
    while index < len(segment):
        char = segment[index]
        if quote:
            if char == quote:
                if index + 1 < len(segment) and segment[index + 1] == quote:
                    index += 1
                else:
                    quote = None
        elif char in {"'", '"'}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")" and depth > 0:
            depth -= 1
        elif char == "," and depth == 0:
            items.append((segment[start:index].strip(), start, index))
            start = index + 1
        index += 1
    items.append((segment[start:].strip(), start, len(segment)))
    return items


def _find_matching_paren(sql: str, open_index: int) -> int | None:
    depth = 0
    quote: str | None = None
    index = open_index
    while index < len(sql):
        char = sql[index]
        if quote:
            if char == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    index += 1
                else:
                    quote = None
        elif char in {"'", '"'}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _insert_columns_values(sql: str) -> tuple[list[str], str, int, int] | None:
    insert_match = re.search(r"\bINSERT\s+INTO\b", sql, flags=re.IGNORECASE)
    if not insert_match:
        return None
    columns_open = sql.find("(", insert_match.end())
    if columns_open < 0:
        return None
    columns_close = _find_matching_paren(sql, columns_open)
    if columns_close is None:
        return None
    values_match = re.search(r"\bVALUES\b", sql[columns_close:], flags=re.IGNORECASE)
    if not values_match:
        return None
    values_open = sql.find("(", columns_close + values_match.end())
    if values_open < 0:
        return None
    values_close = _find_matching_paren(sql, values_open)
    if values_close is None:
        return None
    columns = [
        item.strip().strip('"').lower()
        for item, _, _ in _split_csv(sql[columns_open + 1 : columns_close])
    ]
    values = sql[values_open + 1 : values_close]
    return columns, values, values_open + 1, values_close


def _translate_bool_set_literals(sql: str) -> str:
    bounds = _update_set_bounds(sql)
    if not bounds:
        return sql
    start, end = bounds
    set_clause = sql[start:end]
    names = _bool_column_names()

    def replace_assignment(match: re.Match) -> str:
        value = "TRUE" if match.group("value") == "1" else "FALSE"
        return f"{match.group('prefix')}{value}"

    translated_set = re.sub(
        rf"(?P<prefix>\b(?:{names})\b\s*=\s*)(?P<value>[01])\b",
        replace_assignment,
        set_clause,
        flags=re.IGNORECASE,
    )
    return sql[:start] + translated_set + sql[end:]


def _translate_bool_insert_literals(sql: str) -> str:
    parsed = _insert_columns_values(sql)
    if not parsed:
        return sql
    columns, values, values_start, _values_end = parsed
    value_items = _split_csv(values)
    if len(columns) != len(value_items):
        return sql
    replacements: list[tuple[int, int, str]] = []
    for column, (value, start, end) in zip(columns, value_items):
        if column not in _BOOL_COLUMNS:
            continue
        normalized = value.strip()
        if normalized in {"0", "1"}:
            replacements.append(
                (
                    values_start + start,
                    values_start + end,
                    "TRUE" if normalized == "1" else "FALSE",
                )
            )
    translated = sql
    for start, end, value in reversed(replacements):
        translated = translated[:start] + value + translated[end:]
    return translated


def _translate_bool_sql(sql: str) -> str:
    names = _bool_column_names()
    sql = _translate_bool_set_literals(sql)
    sql = _translate_bool_insert_literals(sql)
    sql = re.sub(
        rf"\bCOALESCE\(\s*((?:\w+\.)?(?:{names}))\s*,\s*0\s*\)",
        r"COALESCE(\1, FALSE)",
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(
        rf"\bCOALESCE\(\s*((?:\w+\.)?(?:{names}))\s*,\s*1\s*\)",
        r"COALESCE(\1, TRUE)",
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(
        rf"((?:\b\w+\.)?(?:{names}))\s*=\s*1\b",
        r"\1 IS TRUE",
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(
        rf"((?:\b\w+\.)?(?:{names}))\s*=\s*0\b",
        r"\1 IS FALSE",
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(
        r"COALESCE\(([^)]*),\s*FALSE\)\s*=\s*1\b",
        r"COALESCE(\1, FALSE) IS TRUE",
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(
        r"COALESCE\(([^)]*),\s*FALSE\)\s*=\s*0\b",
        r"COALESCE(\1, FALSE) IS FALSE",
        sql,
        flags=re.IGNORECASE,
    )
    return sql


def _placeholder_count(sql_fragment: str) -> int:
    return len(re.findall(r"(?<!%)%s", sql_fragment))


def _coerce_bool_param(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "t", "yes", "on"}:
        return True
    if normalized in {"0", "false", "f", "no", "off"}:
        return False
    return value


@lru_cache(maxsize=512)
def _bool_assignment_param_indexes(sql: str) -> frozenset[int]:
    bounds = _update_set_bounds(sql)
    if not bounds:
        return frozenset()
    start, end = bounds
    set_clause = sql[start:end]
    names = _bool_column_names()
    indexes: set[int] = set()
    for match in re.finditer(
        rf"\b(?:{names})\b\s*=\s*(?<!%)%s\b",
        set_clause,
        flags=re.IGNORECASE,
    ):
        indexes.add(_placeholder_count(sql[:start] + set_clause[: match.start()]))
    return frozenset(indexes)


@lru_cache(maxsize=512)
def _bool_insert_param_indexes(sql: str) -> frozenset[int]:
    parsed = _insert_columns_values(sql)
    if not parsed:
        return frozenset()
    columns, values, values_start, _values_end = parsed
    value_items = _split_csv(values)
    if len(columns) != len(value_items):
        return frozenset()
    indexes: set[int] = set()
    for column, (value, start, _end) in zip(columns, value_items):
        if column in _BOOL_COLUMNS and re.fullmatch(r"(?<!%)%s", value.strip()):
            indexes.add(_placeholder_count(sql[:values_start] + values[:start]))
    return frozenset(indexes)


def _normalize_bool_assignment_params(sql: str, params: Any) -> Any:
    indexes = _bool_assignment_param_indexes(sql) | _bool_insert_param_indexes(sql)
    if not indexes or not isinstance(params, tuple):
        return params
    values = list(params)
    for index in indexes:
        if 0 <= index < len(values):
            values[index] = _coerce_bool_param(values[index])
    return tuple(values)


def _translate_sqlite_scalars(sql: str) -> str:
    sql = re.sub(
        r"MIN\s*\(\s*COALESCE\(prompt_repeat_balance_rub,\s*0\)\s*,\s*MAX\s*\(\s*COALESCE\(partner_balance_rub,\s*0\)\s*-\s*%s\s*,\s*0\s*\)\s*\)",
        "LEAST(COALESCE(prompt_repeat_balance_rub, 0), GREATEST(COALESCE(partner_balance_rub, 0) - %s, 0))",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    sql = re.sub(
        r"\bLIMIT\s+-1\s+OFFSET\s+%s\b",
        "OFFSET %s",
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(
        r"date\('now',\s*'-([0-9]+)\s+day'\)",
        r"(CURRENT_DATE - INTERVAL '\1 day')::date",
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(r"date\('now'\)", "CURRENT_DATE", sql, flags=re.IGNORECASE)
    sql = re.sub(
        r"datetime\('now',\s*'-([0-9]+)\s+(hour|minute|second)s?'\)",
        r"(CURRENT_TIMESTAMP - INTERVAL '\1 \2')",
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(
        r"datetime\('now',\s*'\+([0-9]+)\s+(hour|minute|second)s?'\)",
        r"(CURRENT_TIMESTAMP + INTERVAL '\1 \2')",
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(r"datetime\('now'\)", "CURRENT_TIMESTAMP", sql, flags=re.IGNORECASE)
    return sql


def _escape_percent_literals(sql: str) -> str:
    # Escape % that are NOT psycopg placeholders (%s) or literal percents (%%).
    # SQL LIKE wildcards (% inside quotes) will also be escaped — this is fine
    # because LIKE params should use %s placeholders, not literal %.
    return re.sub(r"%(?![%s])", "%%", sql)


def _should_skip_statement(sql: str) -> bool:
    stripped = sql.strip()
    upper = stripped.upper()
    return upper.startswith(
        (
            "PRAGMA ",
            "CREATE TABLE ",
            "CREATE INDEX ",
            "CREATE UNIQUE INDEX ",
            "ALTER TABLE ",
        )
    )


def translate_sql(sql: str) -> str | None:
    if _should_skip_statement(sql):
        return None
    translated = _translate_insert_ignore(sql)
    translated = _translate_placeholders(translated)
    translated = _translate_bool_sql(translated)
    translated = _translate_sqlite_scalars(translated)
    translated = _escape_percent_literals(translated)
    if translated.strip().upper() == "BEGIN IMMEDIATE":
        return "BEGIN"
    return translated


def _normalize_params(params: Any) -> Any:
    if params is None:
        return None
    if isinstance(params, list):
        return tuple(params)
    return params


def _extract_insert_table(sql: str) -> str | None:
    match = re.search(r"\bINSERT\s+INTO\s+\"?([A-Za-z_][A-Za-z0-9_]*)\"?", sql, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).lower()


async def _ensure_postgres_helpers(conn: psycopg.AsyncConnection) -> None:
    global _HELPERS_READY
    if _HELPERS_READY:
        return
    async with _get_helpers_lock():
        if _HELPERS_READY:
            return
        async with conn.cursor() as cur:
            for table, column in (
                ("users", "credits"),
                ("users", "referral_earned"),
                ("generation_tasks", "cost"),
                ("generation_history", "cost"),
                ("batch_jobs", "total_cost"),
            ):
                await cur.execute(
                    f'ALTER TABLE "{table}" ALTER COLUMN "{column}" TYPE DOUBLE PRECISION USING "{column}"::DOUBLE PRECISION'
                )
            await cur.execute(
                'ALTER TABLE "generation_tasks" ADD COLUMN IF NOT EXISTS "feed_prompt_visible" BOOLEAN DEFAULT FALSE'
            )
            await cur.execute(
                'ALTER TABLE "generation_tasks" ADD COLUMN IF NOT EXISTS "feed_references_visible" BOOLEAN DEFAULT FALSE'
            )
            await cur.execute(
                'ALTER TABLE "generation_tasks" ADD COLUMN IF NOT EXISTS "feed_blurred" BOOLEAN DEFAULT FALSE'
            )
            await cur.execute(
                'ALTER TABLE "generation_tasks" ADD COLUMN IF NOT EXISTS "feed_published_at" TIMESTAMP'
            )
            await cur.execute(
                'ALTER TABLE "generation_tasks" ADD COLUMN IF NOT EXISTS "is_adult_content" BOOLEAN DEFAULT FALSE'
            )
            await cur.execute(
                'CREATE INDEX IF NOT EXISTS "idx_generation_tasks_feed_safe" '
                'ON "generation_tasks"("is_public_feed", "is_adult_content", "status", "created_at" DESC)'
            )
            # Новые таблицы: referral_events, partner_commissions
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS referral_events (
                    id BIGSERIAL PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    visitor_user_id BIGINT,
                    visitor_telegram_id BIGINT NOT NULL,
                    clicked_code TEXT,
                    clicked_referrer_id BIGINT,
                    existing_referrer_id BIGINT,
                    attached BOOLEAN DEFAULT FALSE,
                    reason TEXT NOT NULL,
                    source TEXT,
                    start_param TEXT,
                    is_self_click BOOLEAN DEFAULT FALSE,
                    is_repeat_click BOOLEAN DEFAULT FALSE,
                    metadata JSONB DEFAULT '{}'::jsonb
                )
            """)
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS partner_commissions (
                    id BIGSERIAL PRIMARY KEY,
                    transaction_id BIGINT NOT NULL,
                    order_id TEXT NOT NULL,
                    referrer_id BIGINT NOT NULL,
                    referred_id BIGINT NOT NULL,
                    level INT NOT NULL,
                    base_amount_rub NUMERIC(12,2) NOT NULL,
                    percent NUMERIC(5,2) NOT NULL,
                    amount_rub NUMERIC(12,2) NOT NULL,
                    tier TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(transaction_id, referrer_id, level)
                )
            """)
            for idx_stmt in [
                "CREATE INDEX IF NOT EXISTS idx_referral_events_created_at ON referral_events(created_at)",
                "CREATE INDEX IF NOT EXISTS idx_referral_events_visitor_telegram_id ON referral_events(visitor_telegram_id)",
                "CREATE INDEX IF NOT EXISTS idx_referral_events_clicked_referrer_id ON referral_events(clicked_referrer_id)",
                "CREATE INDEX IF NOT EXISTS idx_referral_events_reason ON referral_events(reason)",
                "CREATE INDEX IF NOT EXISTS idx_referral_events_attached ON referral_events(attached)",
                "CREATE INDEX IF NOT EXISTS idx_referral_events_clicked_code ON referral_events(clicked_code)",
                "CREATE INDEX IF NOT EXISTS idx_partner_commissions_referrer_id ON partner_commissions(referrer_id)",
                "CREATE INDEX IF NOT EXISTS idx_partner_commissions_referred_id ON partner_commissions(referred_id)",
                "CREATE INDEX IF NOT EXISTS idx_partner_commissions_transaction_id ON partner_commissions(transaction_id)",
                "CREATE INDEX IF NOT EXISTS idx_partner_commissions_created_at ON partner_commissions(created_at)",
            ]:
                await cur.execute(idx_stmt)
            await cur.execute(
                """
                CREATE OR REPLACE FUNCTION public.json_valid(payload text)
                RETURNS boolean
                LANGUAGE plpgsql
                IMMUTABLE
                AS $$
                BEGIN
                    IF payload IS NULL OR btrim(payload) = '' THEN
                        RETURN FALSE;
                    END IF;
                    PERFORM payload::jsonb;
                    RETURN TRUE;
                EXCEPTION WHEN others THEN
                    RETURN FALSE;
                END;
                $$;
                """
            )
            await cur.execute(
                """
                CREATE OR REPLACE FUNCTION public.json_each(payload text, path text DEFAULT NULL)
                RETURNS TABLE(value text)
                LANGUAGE plpgsql
                STABLE
                AS $$
                DECLARE
                    doc jsonb;
                    selected jsonb;
                BEGIN
                    IF payload IS NULL OR btrim(payload) = '' THEN
                        RETURN;
                    END IF;
                    doc := payload::jsonb;
                    IF path = '$.task_id_aliases' THEN
                        selected := doc -> 'task_id_aliases';
                    ELSE
                        selected := doc;
                    END IF;
                    IF jsonb_typeof(selected) = 'array' THEN
                        RETURN QUERY SELECT jsonb_array_elements_text(selected);
                    ELSIF jsonb_typeof(selected) = 'object' THEN
                        RETURN QUERY SELECT item.value::text FROM jsonb_each(selected) AS item(key, value);
                    END IF;
                    RETURN;
                EXCEPTION WHEN others THEN
                    RETURN;
                END;
                $$;
                """
            )
            await cur.execute(
                """
                CREATE OR REPLACE FUNCTION public.datetime(value timestamp without time zone)
                RETURNS timestamp without time zone
                LANGUAGE sql
                IMMUTABLE
                AS $$ SELECT value $$;
                """
            )
            await cur.execute(
                """
                CREATE OR REPLACE FUNCTION public.datetime(value text)
                RETURNS timestamp without time zone
                LANGUAGE plpgsql
                STABLE
                AS $$
                BEGIN
                    IF lower(value) = 'now' THEN
                        RETURN CURRENT_TIMESTAMP;
                    END IF;
                    RETURN value::timestamp;
                EXCEPTION WHEN others THEN
                    RETURN NULL;
                END;
                $$;
                """
            )
            await cur.execute(
                """
                CREATE OR REPLACE FUNCTION public.datetime(value text, modifier text)
                RETURNS timestamp without time zone
                LANGUAGE plpgsql
                STABLE
                AS $$
                DECLARE
                    base_value timestamp without time zone;
                BEGIN
                    base_value := public.datetime(value);
                    IF base_value IS NULL THEN
                        RETURN NULL;
                    END IF;
                    IF modifier IS NULL OR btrim(modifier) = '' THEN
                        RETURN base_value;
                    END IF;
                    RETURN base_value + modifier::interval;
                EXCEPTION WHEN others THEN
                    RETURN base_value;
                END;
                $$;
                """
            )
            await cur.execute(
                """
                CREATE OR REPLACE FUNCTION public.date(value text, modifier text)
                RETURNS date
                LANGUAGE plpgsql
                STABLE
                AS $$
                DECLARE
                    base_value timestamp without time zone;
                BEGIN
                    base_value := public.datetime(value);
                    IF base_value IS NULL THEN
                        RETURN NULL;
                    END IF;
                    IF modifier IS NOT NULL AND btrim(modifier) != '' THEN
                        base_value := base_value + modifier::interval;
                    END IF;
                    RETURN base_value::date;
                EXCEPTION WHEN others THEN
                    RETURN NULL;
                END;
                $$;
                """
            )
        await conn.commit()
        _HELPERS_READY = True


class PostgresConnection:
    def __init__(self, conn: psycopg.AsyncConnection):
        self._conn = conn
        self._closed = False
        self.row_factory = None
        self.total_changes = 0

    async def execute(self, sql: str, parameters: Any = None) -> PostgresCursor:
        translated = translate_sql(sql)
        if translated is None:
            return PostgresCursor(rowcount=0)

        params = _normalize_bool_assignment_params(
            translated,
            _normalize_params(parameters),
        )
        try:
            async with self._conn.cursor() as cur:
                await cur.execute(translated, params)
                columns = [desc.name for desc in cur.description] if cur.description else []
                rows = await cur.fetchall() if cur.description else []
                rowcount = cur.rowcount if cur.rowcount is not None else -1
                lastrowid = None
                if translated.lstrip().upper().startswith("INSERT") and rowcount and rowcount > 0:
                    table = _extract_insert_table(translated)
                    if table in _LASTROWID_TABLES and "ON CONFLICT" not in translated.upper():
                        try:
                            async with self._conn.cursor() as id_cur:
                                await id_cur.execute(
                                    "SELECT currval(pg_get_serial_sequence(%s, 'id'))",
                                    (table,),
                                )
                                id_row = await id_cur.fetchone()
                                lastrowid = id_row[0] if id_row else None
                        except Exception:
                            lastrowid = None
                if rowcount and rowcount > 0 and not cur.description:
                    self.total_changes += int(rowcount)
                return PostgresCursor(
                    rows=[tuple(row) for row in rows],
                    columns=columns,
                    rowcount=rowcount,
                    lastrowid=lastrowid,
                )
        except psycopg.IntegrityError as exc:
            await self._conn.rollback()
            raise aiosqlite.IntegrityError(str(exc)) from exc
        except psycopg.Error as exc:
            await self._conn.rollback()
            raise aiosqlite.OperationalError(str(exc)) from exc

    async def executemany(self, sql: str, seq_of_parameters) -> PostgresCursor:
        translated = translate_sql(sql)
        if translated is None:
            return PostgresCursor(rowcount=0)
        total = 0
        try:
            async with self._conn.cursor() as cur:
                await cur.executemany(
                    translated,
                    [
                        _normalize_bool_assignment_params(
                            translated,
                            _normalize_params(params),
                        )
                        for params in seq_of_parameters
                    ],
                )
                total = cur.rowcount if cur.rowcount is not None else -1
            if total and total > 0:
                self.total_changes += int(total)
            return PostgresCursor(rowcount=total)
        except psycopg.IntegrityError as exc:
            await self._conn.rollback()
            raise aiosqlite.IntegrityError(str(exc)) from exc
        except psycopg.Error as exc:
            await self._conn.rollback()
            raise aiosqlite.OperationalError(str(exc)) from exc

    async def commit(self) -> None:
        await self._conn.commit()

    async def rollback(self) -> None:
        await self._conn.rollback()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._conn.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type:
            try:
                await self.rollback()
            except Exception:
                pass
        await self.close()
        return False


class PostgresConnect:
    def __init__(self, *args, **kwargs):
        self._conn: PostgresConnection | None = None

    async def _ensure(self) -> PostgresConnection:
        if self._conn is None:
            raw_conn = await psycopg.AsyncConnection.connect(
                _normalize_postgres_dsn()
            )
            await _ensure_postgres_helpers(raw_conn)
            self._conn = PostgresConnection(raw_conn)
        return self._conn

    def __await__(self):
        return self._ensure().__await__()

    async def __aenter__(self):
        return await self._ensure()

    async def __aexit__(self, exc_type, exc, tb):
        conn = await self._ensure()
        return await conn.__aexit__(exc_type, exc, tb)


def connect(*args, **kwargs) -> PostgresConnect:
    return PostgresConnect(*args, **kwargs)
