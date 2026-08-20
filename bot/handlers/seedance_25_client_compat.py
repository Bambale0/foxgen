"""Backward-compatible Mini App request normalization for Seedance 2.5.

The dedicated Seedance UI sends ``seedance25_*`` fields, while older/stale
Mini App bundles use the generic video contract (``v_type`` + ``v_image_url``).
Because Telegram WebView can keep an older static bundle for a while, normalize
both shapes before the public Seedance handler validates the scenario.
"""

from __future__ import annotations

from functools import wraps
from typing import Any

from aiohttp import web

from . import generation as generation_module
from . import seedance_25_fullstack as fullstack

MODEL_KEY = "seedance_2_5"


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        candidate = str(value or "").strip()
        if candidate:
            return candidate
    return None


def normalize_seedance25_client_body(body: dict[str, Any]) -> dict[str, Any]:
    """Normalize current and legacy Mini App payloads to the Seedance contract."""
    normalized = dict(body)
    if str(normalized.get("v_model") or "").strip() != MODEL_KEY:
        return normalized

    first_frame = _first_non_empty(
        normalized.get("seedance25_first_frame_url"),
        normalized.get("first_frame_url"),
        normalized.get("v_image_url"),
        normalized.get("start_image"),
        normalized.get("image_url"),
    )
    last_frame = _first_non_empty(
        normalized.get("seedance25_last_frame_url"),
        normalized.get("last_frame_url"),
        normalized.get("end_image_url"),
    )

    raw_scenario = str(normalized.get("seedance25_scenario") or "").strip().lower()
    v_type = str(normalized.get("v_type") or "").strip().lower()

    if raw_scenario in {"imgtxt", "image", "image_to_video", "first"}:
        raw_scenario = "first_frame"
    elif raw_scenario in {"video", "reference", "references"}:
        raw_scenario = "multimodal"
    elif raw_scenario in {"first_last_frame", "first_and_last"}:
        raw_scenario = "first_last"

    if raw_scenario not in {"text", "first_frame", "first_last", "multimodal"}:
        has_multimodal_refs = bool(
            normalized.get("reference_images")
            or normalized.get("v_reference_videos")
            or normalized.get("seedance25_reference_audio_urls")
            or normalized.get("audio_references")
        )
        if last_frame and first_frame:
            raw_scenario = "first_last"
        elif first_frame and v_type in {"imgtxt", "image", "image_to_video"}:
            raw_scenario = "first_frame"
        elif v_type == "video" or has_multimodal_refs:
            raw_scenario = "multimodal"
        elif first_frame:
            raw_scenario = "first_frame"
        else:
            raw_scenario = "text"

    normalized["seedance25_scenario"] = raw_scenario
    normalized["seedance25_first_frame_url"] = first_frame
    normalized["seedance25_last_frame_url"] = last_frame

    # Legacy generic Mini App payload names.
    if not normalized.get("seedance25_reference_audio_urls") and normalized.get("audio_references"):
        normalized["seedance25_reference_audio_urls"] = normalized.get("audio_references")

    return normalized


def install_seedance_25_client_compat() -> None:
    """Install request normalization after the public Seedance handler."""
    if getattr(generation_module, "_seedance_25_client_compat_installed", False):
        return

    current_generate = fullstack._miniapp_seedance25_generate

    @wraps(current_generate)
    async def compatible_generate(request: web.Request, body: dict[str, Any]) -> web.Response:
        return await current_generate(request, normalize_seedance25_client_body(body))

    fullstack._miniapp_seedance25_generate = compatible_generate
    generation_module._seedance_25_client_compat_installed = True
