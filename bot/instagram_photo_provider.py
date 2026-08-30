from __future__ import annotations

import asyncio
from typing import Any

from bot.instagram_model_contract import INSTAGRAM_PHOTO_MODEL
from bot.services.seedream_service import seedream_service

_PROVIDER_POLL_SECONDS = 5.0
_PROVIDER_POLL_ATTEMPTS = 120
_SUCCESS_STATES = {"success", "succeeded", "completed", "done"}
_FAILURE_STATES = {"fail", "failed", "error", "cancelled", "canceled"}


def _result_url(status: dict[str, Any]) -> str:
    data = status.get("data") if isinstance(status.get("data"), dict) else {}
    output = data.get("output")
    if isinstance(output, str):
        return output.strip()
    if isinstance(output, list):
        for value in output:
            candidate = str(value or "").strip()
            if candidate:
                return candidate
    raw = status.get("raw") if isinstance(status.get("raw"), dict) else {}
    task_data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    extracted = seedream_service._extract_output(task_data)
    if isinstance(extracted, str):
        return extracted.strip()
    if isinstance(extracted, list):
        for value in extracted:
            candidate = str(value or "").strip()
            if candidate:
                return candidate
    return ""


async def generate_instagram_photo(prompt: str, image_url: str) -> str:
    """Generate one Instagram photo with Seedream 5 Pro High."""
    response = await seedream_service.generate_image(
        prompt=str(prompt or "").strip(),
        image_urls=[str(image_url or "").strip()],
        aspect_ratio=INSTAGRAM_PHOTO_MODEL.aspect_ratio,
        quality=INSTAGRAM_PHOTO_MODEL.quality,
        nsfw_checker=False,
        callBackUrl=None,
        model=INSTAGRAM_PHOTO_MODEL.provider_model,
    )
    if not isinstance(response, dict):
        raise RuntimeError("Seedream 5 Pro did not accept the generation")
    task_id = str(response.get("task_id") or "").strip()
    if not task_id:
        raise RuntimeError(
            str(response.get("message") or response.get("error") or "Seedream 5 Pro returned no task")
        )

    consecutive_errors = 0
    for _ in range(_PROVIDER_POLL_ATTEMPTS):
        status = await seedream_service.get_task_status(task_id)
        if not isinstance(status, dict):
            consecutive_errors += 1
            if consecutive_errors >= 5:
                raise RuntimeError("Seedream 5 Pro status is temporarily unavailable")
            await asyncio.sleep(_PROVIDER_POLL_SECONDS)
            continue

        consecutive_errors = 0
        data = status.get("data") if isinstance(status.get("data"), dict) else {}
        state = str(data.get("status") or "").strip().lower()
        if state in _SUCCESS_STATES:
            url = _result_url(status)
            if not url:
                raise RuntimeError("Seedream 5 Pro completed without a result URL")
            return url
        if state in _FAILURE_STATES:
            raise RuntimeError("Seedream 5 Pro generation failed")
        await asyncio.sleep(_PROVIDER_POLL_SECONDS)

    raise RuntimeError("Seedream 5 Pro generation timed out")
