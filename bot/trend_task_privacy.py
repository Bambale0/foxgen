from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from bot import db as db_backend
from bot.database import DATABASE_PATH, get_prompts_by_tag

logger = logging.getLogger(__name__)


async def _protected_task_ids(task_ids: list[str]) -> set[str]:
    normalized = [
        str(task_id or "").strip()
        for task_id in task_ids
        if str(task_id or "").strip()
    ]
    if not normalized:
        return set()

    trend_prompts = {
        str(item.get("prompt_text") or "").strip()
        for item in await get_prompts_by_tag("trend", limit=500)
        if str(item.get("prompt_text") or "").strip()
    }

    placeholders = ",".join("?" for _ in normalized)
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            f"""
            SELECT task_id, source_feed_gen_id, action_type, prompt
            FROM generation_tasks
            WHERE task_id IN ({placeholders})
            """,
            tuple(normalized),
        )
        rows = await cursor.fetchall()

    protected: set[str] = set()
    for row in rows:
        task_id = str(row["task_id"] or "").strip()
        action_type = str(row["action_type"] or "").strip().lower()
        prompt = str(row["prompt"] or "").strip()
        inherited_prompt = bool(row["source_feed_gen_id"])
        curated_trend = action_type == "trend"
        legacy_trend = bool(prompt and prompt in trend_prompts)
        if inherited_prompt or curated_trend or legacy_trend:
            protected.add(task_id)
    return protected


def _task_objects(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    task = payload.get("task")
    if isinstance(task, dict):
        tasks.append(task)
    recent = payload.get("recent_tasks")
    if isinstance(recent, list):
        tasks.extend(item for item in recent if isinstance(item, dict))
    return tasks


async def sanitize_task_api_payload(payload: Any) -> Any:
    """Remove curated trend recipes from Mini App task/history responses.

    This also covers tasks created before the dedicated trend runner existed by
    matching their stored prompt against approved curated trend prompts.
    """

    if not isinstance(payload, Mapping):
        return payload

    result = dict(payload)
    tasks = _task_objects(result)
    if not tasks:
        return result

    task_ids = [str(task.get("task_id") or "").strip() for task in tasks]
    try:
        protected = await _protected_task_ids(task_ids)
    except Exception:  # noqa: BLE001 - privacy must fail closed without breaking Mini App
        logger.exception("Unable to resolve protected trend task prompts")
        protected = {task_id for task_id in task_ids if task_id}

    if not protected:
        return result

    def redact(task: dict[str, Any]) -> dict[str, Any]:
        task_id = str(task.get("task_id") or "").strip()
        if task_id not in protected:
            return task
        clean = dict(task)
        clean["prompt"] = ""
        clean["prompt_preview"] = ""
        clean["prompt_hidden"] = True
        clean["prompt_actions_allowed"] = False
        clean["feed_prompt_visible"] = False
        return clean

    if isinstance(result.get("task"), dict):
        result["task"] = redact(result["task"])
    if isinstance(result.get("recent_tasks"), list):
        result["recent_tasks"] = [
            redact(item) if isinstance(item, dict) else item
            for item in result["recent_tasks"]
        ]
    return result
