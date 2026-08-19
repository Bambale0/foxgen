#!/usr/bin/env python3
"""Localize already-published feed videos into durable backend storage.

The public feed must not depend on provider URLs that can expire, reject byte
ranges, or behave differently inside Telegram WebView. New publications are
localized by ``persist_feed_result_urls``; this script repairs historical rows.

Per-row provider failures are non-fatal so one expired video cannot block a
production deployment. Fatal database/runtime errors still return a non-zero
exit code.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from bot import db as db_backend
from bot.database import DATABASE_PATH
from bot.services.feed_persist import FEED_MEDIA_MAX_BYTES, persist_feed_result_urls

logger = logging.getLogger("feed-video-backfill")

BACKFILL_LIMIT = max(1, int(os.getenv("FEED_VIDEO_BACKFILL_LIMIT", "50")))
MIN_VALID_VIDEO_BYTES = max(1, int(os.getenv("FEED_VIDEO_MIN_VALID_BYTES", "1024")))
UPLOAD_ROOT = Path("static/uploads")


def _parse_result_urls(value: Any, fallback: str | None = None) -> list[str]:
    parsed: Any = value
    if isinstance(value, str):
        raw = value.strip()
        if raw:
            try:
                parsed = json.loads(raw)
            except (TypeError, ValueError):
                parsed = [raw]
        else:
            parsed = []

    if not isinstance(parsed, (list, tuple)):
        parsed = []

    urls: list[str] = []
    for item in parsed:
        url = str(item or "").strip()
        if url and url not in urls:
            urls.append(url)

    fallback_url = str(fallback or "").strip()
    if fallback_url and fallback_url not in urls:
        urls.insert(0, fallback_url)
    return urls


def _durable_feed_path(url: str) -> Path | None:
    try:
        parsed = urlparse(str(url or ""))
    except ValueError:
        return None
    path = unquote(parsed.path if parsed.scheme else str(url or ""))
    prefix = "/uploads/feed/"
    if not path.startswith(prefix) or "/thumbs/" in path:
        return None

    relative = path[len("/uploads/") :].lstrip("/")
    candidate = UPLOAD_ROOT / relative
    try:
        candidate.resolve().relative_to(UPLOAD_ROOT.resolve())
    except ValueError:
        return None
    return candidate


def _is_durable_feed_url(url: str) -> bool:
    return _durable_feed_path(url) is not None


def _durable_feed_file_exists(url: str) -> bool:
    path = _durable_feed_path(url)
    if not path:
        return False
    try:
        return path.is_file() and path.stat().st_size >= MIN_VALID_VIDEO_BYTES
    except OSError:
        return False


async def backfill_feed_video_media(limit: int = BACKFILL_LIMIT) -> dict[str, int]:
    counters = {
        "scanned": 0,
        "already_local": 0,
        "missing_local": 0,
        "repaired": 0,
        "failed": 0,
    }

    async with db_backend.connect(DATABASE_PATH, timeout=30) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT id, task_id, result_url, result_urls
            FROM generation_tasks
            WHERE type = 'video'
              AND status = 'completed'
              AND is_public_feed = 1
              AND COALESCE(is_adult_content, 0) = 0
              AND result_url IS NOT NULL
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        )
        rows = await cursor.fetchall()

        for row in rows:
            counters["scanned"] += 1
            row_id = int(row["id"])
            task_id = str(row["task_id"] or "")
            urls = _parse_result_urls(row["result_urls"], row["result_url"])

            if not urls:
                counters["failed"] += 1
                logger.warning("row=%s task=%s has no usable result URLs", row_id, task_id)
                continue

            local_urls = [url for url in urls if _is_durable_feed_url(url)]
            missing_local = [url for url in local_urls if not _durable_feed_file_exists(url)]
            if local_urls and not missing_local and len(local_urls) == len(urls):
                counters["already_local"] += 1
                continue
            if missing_local:
                counters["missing_local"] += 1
                logger.warning(
                    "row=%s task=%s has %d durable URL(s) with missing/empty files",
                    row_id,
                    task_id,
                    len(missing_local),
                )

            try:
                persisted = await persist_feed_result_urls(
                    urls,
                    require_local=True,
                    max_size_bytes=FEED_MEDIA_MAX_BYTES,
                )
            except Exception:
                counters["failed"] += 1
                logger.exception("row=%s task=%s localization crashed", row_id, task_id)
                continue

            if (
                not persisted
                or len(persisted) != len(urls)
                or not all(_durable_feed_file_exists(url) for url in persisted)
            ):
                counters["failed"] += 1
                logger.warning(
                    "row=%s task=%s could not produce valid local video files (%d/%d)",
                    row_id,
                    task_id,
                    len(persisted),
                    len(urls),
                )
                continue

            await db.execute(
                """
                UPDATE generation_tasks
                SET result_url = ?, result_urls = ?
                WHERE id = ?
                """,
                (
                    persisted[0],
                    json.dumps(persisted, ensure_ascii=False),
                    row_id,
                ),
            )
            await db.commit()
            counters["repaired"] += 1
            logger.info(
                "row=%s task=%s localized %d public video URL(s)",
                row_id,
                task_id,
                len(persisted),
            )

    return counters


async def _main() -> int:
    counters = await backfill_feed_video_media()
    print(
        "[feed-video-backfill] "
        + " ".join(f"{key}={value}" for key, value in counters.items())
    )
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    raise SystemExit(asyncio.run(_main()))
