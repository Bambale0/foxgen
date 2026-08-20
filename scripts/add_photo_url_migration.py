#!/usr/bin/env python3
"""Add photo_url column to users table in PostgreSQL."""
import asyncio
import os
import sys
from pathlib import Path

# Load .env.postgres
env_path = Path(__file__).resolve().parents[1] / '.env.postgres'
for line in env_path.read_text().splitlines():
    line = line.strip()
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ[k.strip()] = v.strip()

dsn = os.environ.get('DATABASE_URL', '')
if not dsn.startswith(('postgresql://', 'postgres://')):
    print('❌ DATABASE_URL must point to PostgreSQL')
    sys.exit(1)

import psycopg

async def main():
    conn = await psycopg.AsyncConnection.connect(dsn)
    try:
        # Check if column exists
        cur = await conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'users' AND column_name = 'photo_url'"
        )
        row = await cur.fetchone()
        if row:
            print('✅ Column photo_url already exists')
        else:
            await conn.execute('ALTER TABLE users ADD COLUMN photo_url TEXT')
            await conn.commit()
            print('✅ Column photo_url added successfully')
        
        # Verify
        cur = await conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'users' AND column_name = 'photo_url'"
        )
        row = await cur.fetchone()
        if row:
            print('✅ Verified: photo_url column exists')
        else:
            print('❌ Verification failed')
    finally:
        await conn.close()

asyncio.run(main())
