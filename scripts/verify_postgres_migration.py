#!/usr/bin/env python3
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    project_dir = Path(__file__).resolve().parents[1]
    load_env_file(project_dir / '.env.postgres')
    dsn = os.getenv('DATABASE_URL', '')
    if not dsn.startswith(('postgresql://', 'postgres://')):
        raise SystemExit('DATABASE_URL must point to Postgres')
    sqlite_path = project_dir / 'bot.db'
    sconn = sqlite3.connect(sqlite_path)
    tables = [r[0] for r in sconn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()]
    mismatches = 0
    with psycopg.connect(dsn, row_factory=dict_row) as pg:
        with pg.cursor() as cur:
            for table in tables:
                scount = sconn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                cur.execute(f'SELECT COUNT(*) AS count FROM "{table}"')
                pcount = cur.fetchone()['count']
                status = 'OK' if scount == pcount else 'MISMATCH'
                print(f'{table}: sqlite={scount} postgres={pcount} {status}')
                if scount != pcount:
                    mismatches += 1
    sconn.close()
    return 1 if mismatches else 0


if __name__ == '__main__':
    raise SystemExit(main())
