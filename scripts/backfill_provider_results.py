from __future__ import annotations

import argparse
import asyncio
import json
import logging
from typing import Any

from bot import db as db_backend
from bot.config import config
from bot.main import _persist_result_url_if_needed

logger = logging.getLogger(__name__)


def _decode_result_urls(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(value).strip() for value in raw if str(value or "").strip()]
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return [text]
    if isinstance(parsed, list):
        return [str(value).strip() for value in parsed if str(value or "").strip()]
    if isinstance(parsed, str) and parsed.strip():
        return [parsed.strip()]
    return []


def _encode_result_urls(urls: list[str]) -> str | None:
    cleaned = [str(value).strip() for value in urls if str(value or "").strip()]
    return json.dumps(cleaned, ensure_ascii=False) if cleaned else None


def _looks_external(url: str | None) -> bool:
    value = str(url or "").strip()
    if not value.startswith(("http://", "https://")):
        return False
    base = str(getattr(config, "STATIC_BASE_URL", "") or "").strip().rstrip("/")
    return not (base and value.startswith(base + "/static/uploads/"))


async def _persist_many(urls: list[str], *, task_type: str) -> list[str]:
    persisted: list[str] = []
    for url in urls:
        saved = await _persist_result_url_if_needed(url, task_type=task_type)
        persisted.append(str(saved or url))
    return persisted


async def backfill(*, apply: bool, limit: int) -> dict[str, int]:
    if not getattr(config, "PERSIST_PROVIDER_RESULTS", False):
        raise RuntimeError(
            "PERSIST_PROVIDER_RESULTS must be enabled before provider result backfill"
        )
    if not str(getattr(config, "STATIC_BASE_URL", "") or "").strip().startswith("https://"):
        raise RuntimeError("STATIC_BASE_URL must be a public HTTPS URL")

    stats = {
        "checked": 0,
        "candidates": 0,
        "updated": 0,
        "failed_to_persist": 0,
    }
    async with db_backend.connect() as connection:
        connection.row_factory = db_backend.Row
        rows = await (
            await connection.execute(
                """
                SELECT id, type, result_url, result_urls
                FROM generation_tasks
                WHERE status = 'completed'
                ORDER BY id ASC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            )
        ).fetchall()

        for row in rows:
            stats["checked"] += 1
            primary = str(row["result_url"] or "").strip()
            many = _decode_result_urls(row["result_urls"])
            source_urls = many or ([primary] if primary else [])
            if not any(_looks_external(url) for url in source_urls):
                continue

            stats["candidates"] += 1
            if not apply:
                continue

            task_type = str(row["type"] or "image").strip().lower() or "image"
            persisted_urls = await _persist_many(source_urls, task_type=task_type)
            if any(_looks_external(url) for url in persisted_urls):
                stats["failed_to_persist"] += 1
                logger.warning(
                    "Provider result backfill kept external URL for generation id=%s",
                    row["id"],
                )
                continue

            new_primary = persisted_urls[0] if persisted_urls else primary
            new_many = _encode_result_urls(persisted_urls) if many else row["result_urls"]
            await connection.execute(
                """
                UPDATE generation_tasks
                SET result_url = ?, result_urls = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (new_primary, new_many, int(row["id"])),
            )
            await connection.commit()
            stats["updated"] += 1

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Move completed provider result URLs into HappyFox durable storage"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="persist media and update generation_tasks; default is dry-run",
    )
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    stats = asyncio.run(backfill(apply=bool(args.apply), limit=max(1, args.limit)))
    print(json.dumps(stats, ensure_ascii=False, sort_keys=True))
    return 0 if not stats["failed_to_persist"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
