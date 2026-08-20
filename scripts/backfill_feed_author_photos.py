#!/usr/bin/env python3
"""Backfill photo_url for feed authors via Telegram Bot API."""
import asyncio
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Load .env.postgres FIRST (DATABASE_URL)
env_path = Path(__file__).resolve().parents[1] / ".env.postgres"
for line in env_path.read_text().splitlines():
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip()

# Load .env for BOT_TOKEN (skip DATABASE_URL to keep postgres)
env_path = Path(__file__).resolve().parents[1] / ".env"
for line in env_path.read_text().splitlines():
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        k = k.strip()
        if k in ("DATABASE_URL", "DATABASE_PATH"):
            continue
        os.environ[k] = v.strip()

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from bot import db as db_backend
from bot.postgres_aiosqlite import connect as pg_connect


async def main():
    token = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("BOT_TOKEN not found in .env")
        sys.exit(1)

    logger.info("Using bot token: %s...", token[:20])

    # Fetch all unique feed authors without photo_url
    async with pg_connect() as conn:
        conn.row_factory = db_backend.Row
        cur = await conn.execute(
            """
            SELECT DISTINCT u.id, u.telegram_id, u.username
            FROM generation_tasks gt
            JOIN users u ON u.id = gt.user_id
            WHERE gt.is_public_feed = 1
              AND gt.status = 'completed'
              AND gt.result_url IS NOT NULL
              AND (u.photo_url IS NULL OR u.photo_url = '')
            """
        )
        authors = await cur.fetchall()

    logger.info("Found %d feed authors without photo_url", len(authors))

    import httpx

    api_base = f"https://api.telegram.org/bot{token}"
    updated = 0
    errors = 0
    skipped = 0

    async with httpx.AsyncClient(timeout=30) as http:
        for row in authors:
            d = dict(row)
            uid = d["id"]
            tid = d["telegram_id"]
            username = d.get("username") or f"user_{tid}"

            try:
                # Step 1: get user profile photos
                resp = await http.post(
                    f"{api_base}/getUserProfilePhotos",
                    json={"user_id": tid, "limit": 1},
                )
                data = resp.json()
                if not data.get("ok") or not data.get("result", {}).get("photos"):
                    skipped += 1
                    logger.debug("No profile photo for tg_id=%s (%s)", tid, username)
                    continue

                # Step 2: get the largest photo
                photos = data["result"]["photos"][0]
                file_id = photos[-1]["file_id"]

                # Step 3: get file path
                resp = await http.post(
                    f"{api_base}/getFile",
                    json={"file_id": file_id},
                )
                data = resp.json()
                if not data.get("ok") or not data.get("result", {}).get("file_path"):
                    logger.warning("No file_path for tg_id=%s", tid)
                    continue

                file_path = data["result"]["file_path"]
                photo_url = f"https://api.telegram.org/file/bot{token}/{file_path}"

                # Step 4: save to DB
                async with pg_connect() as db:
                    await db.execute(
                        "UPDATE users SET photo_url = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (photo_url, uid),
                    )
                    await db.commit()

                updated += 1
                logger.info("Updated tg_id=%s (%s) -> %s", tid, username, photo_url[:80])

            except Exception as e:
                errors += 1
                logger.error("Failed for tg_id=%s (%s): %s", tid, username, e)

    logger.info(
        "Done: %d updated, %d skipped (no photo), %d errors out of %d authors",
        updated,
        skipped,
        errors,
        len(authors),
    )


if __name__ == "__main__":
    asyncio.run(main())
