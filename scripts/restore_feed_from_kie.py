"""Restore missing public feed files from Kie.ai task results.

The script does not delete or unpublish anything. It finds public feed rows whose
local /uploads/feed file is missing, asks Kie.ai for the original task result,
downloads the result into static/uploads/feed, and updates result_url/result_urls.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

logger = logging.getLogger("restore_feed_from_kie")


def _load_env_file(path: Path, *, override: bool = True) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if override or key not in os.environ:
            os.environ[key] = value


def _load_runtime_env() -> None:
    _load_env_file(PROJECT_DIR / ".env", override=False)
    _load_env_file(PROJECT_DIR / ".env.postgres", override=True)


def _parse_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except Exception:
        return None


def _collect_urls(value: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(value, dict):
        for item in value.values():
            urls.extend(_collect_urls(item))
    elif isinstance(value, list):
        for item in value:
            urls.extend(_collect_urls(item))
    elif isinstance(value, str):
        text = value.strip()
        if text.startswith("http://") or text.startswith("https://"):
            urls.append(text)
        else:
            parsed = _parse_json(text)
            if parsed is not None:
                urls.extend(_collect_urls(parsed))
            else:
                urls.extend(re.findall(r"https?://[^\s,\]\"']+", text))
    return urls


def _unique_urls(urls: list[str]) -> list[str]:
    unique: list[str] = []
    for url in urls:
        normalized = str(url or "").strip()
        if normalized and normalized not in unique:
            unique.append(normalized)
    return unique


def _task_id_candidates(row: Any) -> list[str]:
    candidates: list[str] = []
    if row["task_id"]:
        candidates.append(str(row["task_id"]))
    request_data = _parse_json(row["request_data"]) or {}
    aliases = request_data.get("task_id_aliases") if isinstance(request_data, dict) else None
    if isinstance(aliases, list):
        candidates.extend(str(item) for item in aliases if item)
    return list(dict.fromkeys(item.strip() for item in candidates if item and item.strip()))


async def _fetch_kie_record(
    session: aiohttp.ClientSession,
    headers: dict[str, str],
    task_id: str,
    *,
    include_veo: bool,
) -> dict[str, Any] | None:
    endpoints = ["/api/v1/jobs/recordInfo"]
    if include_veo:
        endpoints.append("/api/v1/veo/record-info")

    for endpoint in endpoints:
        try:
            async with session.get(
                f"https://api.kie.ai{endpoint}",
                params={"taskId": task_id},
                headers=headers,
            ) as resp:
                if resp.status == 404:
                    continue
                data = await resp.json(content_type=None)
                if resp.status < 400 and isinstance(data, dict) and data.get("code") == 200:
                    return data
                logger.warning(
                    "KIE lookup failed: task_id=%s endpoint=%s http=%s code=%s",
                    task_id,
                    endpoint,
                    resp.status,
                    data.get("code") if isinstance(data, dict) else None,
                )
        except Exception as exc:
            logger.warning("KIE lookup error: task_id=%s endpoint=%s error=%s", task_id, endpoint, exc)
    return None


def _extract_result_urls(record: dict[str, Any]) -> list[str]:
    data = record.get("data") if isinstance(record, dict) else None
    if not isinstance(data, dict):
        return []

    result_payloads: list[Any] = []
    for key in (
        "resultJson",
        "result_json",
        "response",
        "info",
        "resultUrls",
        "fullResultUrls",
        "originUrls",
        "resultUrl",
        "videoUrl",
        "imageUrl",
        "output",
    ):
        if key in data:
            result_payloads.append(data.get(key))

    parsed: list[Any] = []
    for payload in result_payloads:
        parsed_payload = _parse_json(payload)
        parsed.append(parsed_payload if parsed_payload is not None else payload)

    return _unique_urls(_collect_urls(parsed))


async def _select_rows(db: Any, *, limit: int) -> list[Any]:
    from bot.database import _generation_result_urls
    from bot.services.media_input_utils import is_local_upload_source, resolve_local_upload_path

    cur = await db.execute(
        """
        SELECT id, task_id, type, preset_id, model, result_url, result_urls, request_data, created_at
        FROM generation_tasks
        WHERE is_public_feed = 1
          AND status = 'completed'
          AND type IN ('image', 'video')
          AND result_url IS NOT NULL
        ORDER BY created_at DESC
        """
    )
    rows = await cur.fetchall()
    missing = [
        row
        for row in rows
        if any(
            is_local_upload_source(url) and not resolve_local_upload_path(url)
            for url in _generation_result_urls(row)
        )
    ]
    if limit > 0:
        return missing[:limit]
    return missing


def _backup_rows(rows: list[Any]) -> Path | None:
    if not rows:
        return None
    backup_dir = PROJECT_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    path = backup_dir / f"feed-kie-restore-before-{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    payload = [{key: row[key] for key in row.keys()} for row in rows]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return path


async def main() -> None:
    parser = argparse.ArgumentParser(description="Restore missing feed uploads from Kie.ai task results")
    parser.add_argument("--limit", type=int, default=0, help="Maximum rows to process; 0 means all")
    parser.add_argument("--dry-run", action="store_true", help="Only check KIE result availability")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    _load_runtime_env()

    api_key = os.environ.get("KIE_AI_API_KEY")
    if not api_key:
        raise SystemExit("KIE_AI_API_KEY is not configured")

    import bot.db as db_backend
    from bot.config import config
    from bot.database import DATABASE_PATH
    from bot.services.feed_persist import download_to_local

    db_backend.DATABASE_URL = os.environ.get("DATABASE_URL", "")
    db_backend.DATABASE_PATH = os.environ.get("DATABASE_URL", DATABASE_PATH)

    headers = {"Authorization": f"Bearer {api_key}"}
    restored = 0
    no_kie_result = 0
    download_failed = 0
    skipped = 0

    async with db_backend.connect(db_backend.DATABASE_PATH, timeout=30) as db:
        db.row_factory = db_backend.Row
        rows = await _select_rows(db, limit=args.limit)
        logger.info("Rows with missing local feed files: %s", len(rows))
        backup_path = _backup_rows(rows)
        if backup_path:
            logger.info("Saved pre-update backup: %s", backup_path)

        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
            for index, row in enumerate(rows, start=1):
                task_ids = _task_id_candidates(row)
                if not task_ids:
                    skipped += 1
                    logger.info("[%s/%s] id=%s skipped: no task_id", index, len(rows), row["id"])
                    continue

                result_urls: list[str] = []
                for task_id in task_ids:
                    record = await _fetch_kie_record(
                        session,
                        headers,
                        task_id,
                        include_veo=row["type"] == "video",
                    )
                    if not record:
                        continue
                    result_urls = _extract_result_urls(record)
                    if result_urls:
                        break

                if not result_urls:
                    no_kie_result += 1
                    logger.info("[%s/%s] id=%s no KIE result URLs", index, len(rows), row["id"])
                    continue

                if args.dry_run:
                    restored += 1
                    logger.info("[%s/%s] id=%s dry-run: found %s KIE URLs", index, len(rows), row["id"], len(result_urls))
                    continue

                local_urls: list[str] = []
                for url in result_urls:
                    local_url = await download_to_local(url, max_size_bytes=700 * 1024 * 1024)
                    if local_url:
                        local_urls.append(local_url)

                if not local_urls:
                    download_failed += 1
                    logger.info("[%s/%s] id=%s download failed", index, len(rows), row["id"])
                    continue

                await db.execute(
                    """
                    UPDATE generation_tasks
                    SET result_url = ?,
                        result_urls = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        local_urls[0],
                        json.dumps(local_urls, ensure_ascii=False),
                        row["id"],
                    ),
                )
                await db.commit()
                restored += 1
                logger.info(
                    "[%s/%s] id=%s restored %s file(s) via %s",
                    index,
                    len(rows),
                    row["id"],
                    len(local_urls),
                    config.static_base_url.rstrip("/"),
                )

    logger.info(
        "Done. restored=%s no_kie_result=%s download_failed=%s skipped=%s dry_run=%s",
        restored,
        no_kie_result,
        download_failed,
        skipped,
        args.dry_run,
    )


if __name__ == "__main__":
    asyncio.run(main())
