"""Keep Mini App video repeat and share flows on the server-side source contract.

Feed/profile cards intentionally hide prompts/references from clients. A repeat therefore
must restore the original generation payload on the server instead of trusting an empty
browser preset. This layer also makes copied video links open the Mini App remix flow
rather than the text-bot post link.
"""

from __future__ import annotations

import json
from functools import wraps
from typing import Any, Iterable

from aiohttp import web

from bot.database import get_generation_task_payload


_REPEAT_LIST_ALIASES: dict[str, tuple[str, ...]] = {
    "reference_images": ("reference_images", "reference_image_urls"),
    "v_reference_videos": (
        "v_reference_videos",
        "reference_videos",
        "reference_video_urls",
    ),
    "seedance25_reference_audio_urls": (
        "seedance25_reference_audio_urls",
        "reference_audios",
        "reference_audio_urls",
        "audio_references",
    ),
}

_REPEAT_SCALAR_ALIASES: dict[str, tuple[str, ...]] = {
    "v_image_url": (
        "v_image_url",
        "seedance25_first_frame_url",
        "first_frame_url",
        "start_image",
        "image_url",
    ),
    "seedance25_first_frame_url": (
        "seedance25_first_frame_url",
        "first_frame_url",
        "v_image_url",
        "start_image",
        "image_url",
    ),
    "seedance25_last_frame_url": (
        "seedance25_last_frame_url",
        "last_frame_url",
        "end_image_url",
    ),
    "audio_url": ("audio_url", "audio_reference"),
    "seedance25_scenario": ("seedance25_scenario", "scenario"),
    "seedance25_resolution": ("seedance25_resolution", "resolution"),
    "seedance25_output_format": ("seedance25_output_format", "output_format"),
    "seedance25_generate_audio": ("seedance25_generate_audio", "generate_audio"),
    "seedance25_return_last_frame": (
        "seedance25_return_last_frame",
        "return_last_frame",
    ),
    "seedance25_web_search": ("seedance25_web_search", "web_search"),
    "seedance25_nsfw_checker": ("seedance25_nsfw_checker", "nsfw_checker"),
}

_ADVANCED_VIDEO_KEYS = (
    "grok_mode",
    "grok_resolution",
    "veo_generation_type",
    "veo_translation",
    "veo_resolution",
    "veo_seed",
    "veo_watermark",
    "kling_negative_prompt",
    "kling_cfg_scale",
    "omni_resolution",
    "omni_seed",
    "omni_audio_ids",
    "omni_character_ids",
    "omni_base_voice",
    "omni_voice_name",
    "omni_voice_description",
    "omni_example_dialogue",
    "omni_character_name",
    "omni_character_audio_ids",
)


def _clean_list(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw or "").strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _first_value(source: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        value = source.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, tuple, set)) and not value:
            continue
        return value
    return None


def _first_list(source: dict[str, Any], keys: Iterable[str]) -> list[str]:
    for key in keys:
        values = _clean_list(source.get(key))
        if values:
            return values
    return []


def _missing(value: Any) -> bool:
    return value is None or value == "" or value == []


def _source_id(body: dict[str, Any]) -> int | None:
    raw = body.get("source_feed_gen_id") or body.get("sourceFeedGenId")
    return int(raw) if str(raw or "").isdigit() else None


def _source_request_data(task: dict[str, Any]) -> dict[str, Any]:
    request_data = task.get("request_data") or {}
    return request_data if isinstance(request_data, dict) else {}


def _infer_scenario(request_data: dict[str, Any]) -> str:
    scenario = str(
        request_data.get("seedance25_scenario")
        or request_data.get("scenario")
        or request_data.get("v_type")
        or ""
    ).strip().lower()
    if scenario:
        return scenario
    if _first_list(request_data, _REPEAT_LIST_ALIASES["v_reference_videos"]):
        return "video"
    if _first_value(request_data, _REPEAT_SCALAR_ALIASES["v_image_url"]):
        return "imgtxt"
    return "text"


def enrich_video_repeat_body(
    body: dict[str, Any],
    source_task: dict[str, Any],
) -> dict[str, Any]:
    """Merge private source payload into a repeat request without exposing it to UI."""

    normalized = dict(body)
    request_data = _source_request_data(source_task)

    if not str(normalized.get("prompt") or "").strip():
        normalized["prompt"] = str(source_task.get("prompt") or "")
    if not str(normalized.get("v_model") or "").strip():
        normalized["v_model"] = str(
            source_task.get("model") or request_data.get("v_model") or ""
        )
    if not str(normalized.get("v_type") or "").strip():
        normalized["v_type"] = str(request_data.get("v_type") or _infer_scenario(request_data))
    if _missing(normalized.get("v_duration")):
        normalized["v_duration"] = source_task.get("duration") or request_data.get("v_duration") or 5
    if not str(normalized.get("v_ratio") or "").strip():
        normalized["v_ratio"] = str(
            source_task.get("aspect_ratio") or request_data.get("v_ratio") or "16:9"
        )

    for target, aliases in _REPEAT_LIST_ALIASES.items():
        if not _clean_list(normalized.get(target)):
            restored = _first_list(request_data, aliases)
            if restored:
                normalized[target] = restored

    for target, aliases in _REPEAT_SCALAR_ALIASES.items():
        if _missing(normalized.get(target)):
            restored = _first_value(request_data, aliases)
            if restored is not None:
                normalized[target] = restored

    if _missing(normalized.get("audio_url")):
        audio_urls = _clean_list(normalized.get("seedance25_reference_audio_urls"))
        if not audio_urls:
            audio_urls = _first_list(
                request_data,
                _REPEAT_LIST_ALIASES["seedance25_reference_audio_urls"],
            )
        if audio_urls:
            normalized["audio_url"] = audio_urls[0]
            normalized.setdefault("audio_references", audio_urls)

    for key in _ADVANCED_VIDEO_KEYS:
        if _missing(normalized.get(key)) and key in request_data:
            normalized[key] = request_data.get(key)

    # Dedicated Seedance 2.5 uses a richer scenario vocabulary than the generic
    # video form. Preserve that server-side value for hidden-reference repeats.
    if str(normalized.get("v_model") or "").strip() == "seedance_2_5":
        restored_scenario = _first_value(
            request_data,
            ("seedance25_scenario", "scenario"),
        )
        if restored_scenario:
            normalized["seedance25_scenario"] = restored_scenario

    return normalized


async def _restore_repeat_request(request: web.Request, body: dict[str, Any]) -> dict[str, Any]:
    source_id = _source_id(body)
    if not source_id:
        return body

    import bot.miniapp as miniapp_module

    try:
        _telegram_id, context = await miniapp_module._get_user_context(
            request.app,
            str(body.get("init_data") or ""),
            body.get("start_param_fallback"),
        )
        card = await miniapp_module._get_repeat_source_card(
            source_id,
            viewer_user_id=context["user"].id,
        )
        if not card or str(card.get("gen_type") or "").lower() != "video":
            return body
        source_task = await get_generation_task_payload(source_id)
        if not source_task:
            return body
        return enrich_video_repeat_body(body, source_task)
    except Exception:
        # The original handler owns user-facing auth/not-found semantics. If
        # enrichment cannot be performed, delegate unchanged instead of masking it.
        return body


def _replace_cached_json(request: web.Request, body: dict[str, Any]) -> None:
    # aiohttp Request.json() re-reads the cached byte body. Replacing this cache
    # lets established handlers validate the enriched request without duplicating
    # their billing/provider logic.
    request._read_bytes = json.dumps(  # type: ignore[attr-defined]
        body,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _video_remix_link(payload: dict[str, Any]) -> str:
    candidates = (
        payload.get("miniapp_repeat_link"),
        payload.get("miniapp_post_link"),
        payload.get("miniapp_link"),
    )
    for raw in candidates:
        link = str(raw or "").strip()
        if not link:
            continue
        if "startapp=remix_" in link:
            return link
        if "startapp=feed_" in link:
            return link.replace("startapp=feed_", "startapp=remix_", 1)
    return ""


def _response_payload(response: web.StreamResponse) -> dict[str, Any] | None:
    if not isinstance(response, web.Response) or not response.body:
        return None
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _json_response_like(response: web.Response, payload: dict[str, Any]) -> web.Response:
    headers = {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in {"content-length", "content-type"}
    }
    return web.json_response(payload, status=response.status, headers=headers)


def install_miniapp_video_continuity_compat() -> None:
    import bot.miniapp as miniapp_module

    if getattr(miniapp_module, "_video_continuity_compat_installed", False):
        return

    current_generate_video = miniapp_module.miniapp_generate_video
    current_feed_share = miniapp_module.miniapp_feed_share

    @wraps(current_generate_video)
    async def generate_video_with_repeat_context(request: web.Request) -> web.StreamResponse:
        try:
            body = await request.json()
        except Exception:
            return await current_generate_video(request)
        enriched = await _restore_repeat_request(request, body)
        if enriched != body:
            _replace_cached_json(request, enriched)
        return await current_generate_video(request)

    @wraps(current_feed_share)
    async def feed_share_with_miniapp_video_link(request: web.Request) -> web.StreamResponse:
        response = await current_feed_share(request)
        payload = _response_payload(response)
        if not payload or response.status >= 400:
            return response
        feed_item = payload.get("feed_item")
        if not isinstance(feed_item, dict) or str(feed_item.get("gen_type") or "").lower() != "video":
            return response

        remix_link = _video_remix_link(payload)
        if not remix_link:
            return response

        # Existing web bundle intentionally chooses post_link for videos. Point
        # that compatibility field at the Mini App remix route as well so stale
        # clients immediately receive a usable repeat link.
        payload["link"] = remix_link
        payload["post_link"] = remix_link
        payload["repeat_link"] = remix_link
        payload["miniapp_repeat_link"] = remix_link
        return _json_response_like(response, payload)

    miniapp_module.miniapp_generate_video = generate_video_with_repeat_context
    miniapp_module.miniapp_feed_share = feed_share_with_miniapp_video_link
    miniapp_module._video_continuity_compat_installed = True
