#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from bot import db as db_backend
from bot.env import load_project_env


REQUIRED_TABLES = (
    "users",
    "transactions",
    "generation_tasks",
    "saved_references",
    "user_prompts",
    "promo_codes",
    "referrals",
)


async def main() -> int:
    load_project_env()
    if db_backend.backend_name() != "postgres":
        print("[error] DATABASE_URL does not select Postgres")
        return 1

    async with db_backend.connect() as db:
        cursor = await db.execute("SELECT current_database() AS database_name, current_user AS user_name")
        row = await cursor.fetchone()
        print(f"[ok] connected database={row['database_name']} user={row['user_name']}")

        missing: list[str] = []
        counts: dict[str, Any] = {}
        for table in REQUIRED_TABLES:
            exists_cursor = await db.execute("SELECT to_regclass(%s) AS regclass", (f"public.{table}",))
            exists = await exists_cursor.fetchone()
            if not exists or not exists["regclass"]:
                missing.append(table)
                continue
            count_cursor = await db.execute(f'SELECT COUNT(*) AS count FROM "{table}"')
            count_row = await count_cursor.fetchone()
            counts[table] = count_row["count"]

    if missing:
        print("[error] missing tables:", ", ".join(missing))
        return 1

    for table, count in counts.items():
        print(f"[ok] {table}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
