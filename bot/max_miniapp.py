"""MAX-native Mini App authentication and core API helpers.

This module deliberately never touches Telegram users, FSM state, balances or
transactions.  The web UI is shared, but identity and mutable state remain
native to MAX.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl

from bot.max_admin_store import is_max_admin
from bot.max_catalog import MAX_VIDEO_TYPES, MaxPresetManager, max_preset_manager
from bot.max_generation import (
    MaxGenerationJob,
    enqueue_max_generation,
    get_max_generation_job,
)
from bot.max_store import (
    MaxInsufficientBalanceError,
    MaxUser,
    ensure_max_user,
    get_max_balance,
    list_max_history,
)
from bot.max_ui import IMAGE_LABELS, VIDEO_LABELS

logger = logging.getLogger(__name__)

MAX_INIT_DATA_MAX_AGE_SECONDS = 24 * 60 * 60

_IMAGE_RATIOS: dict[str, list[str]] = {
    "nano-banana-2-lite": ["1:1", "16:9", "9:16", "4:3", "3:4", "4:5", "5:4", "3:2", "2:3", "21:9"],
    "seedream_5_pro": ["1:1", "9:16", "16:9", "3:4", "4:3", "2:3", "3:2", "21:9"],
    "banana_pro": ["1:1", "16:9", "9:16", "4:3", "3:4", "4:5", "5:4", "3:2", "2:3", "21:9"],
    "banana_2": ["1:1", "16:9", "9:16", "4:3", "3:4", "4:5", "5:4", "3:2", "2:3", "21:9"],
    "flux_pro": ["auto", "1:1", "9:16", "16:9", "3:4", "4:3", "2:3"],
    "seedream_edit": ["1:1", "9:16", "16:9", "3:4", "4:3", "2:3", "3:2", "21:9"],
    "grok_imagine_i2i": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"],
    "wan_27": ["1:1", "16:9", "9:16", "4:3", "3:4", "21:9"],
}
_IMAGE_REQUIRES_REFERENCE = frozenset({"seedream_edit", "grok_imagine_i2i"})
_IMAGE_MAX_REFERENCES = {
    "nano-banana-2-lite": 8,
    "seedream_5_pro": 5,
    "banana_pro": 8,
    "banana_2": 8,
    "flux_pro": 9,
    "seedream_edit": 5,
    "grok_imagine_i2i": 9,
    "wan_27": 9,
}
_IMAGE_QUALITIES = {
    "nano-banana-2-lite": ["1K", "2K", "4K"],
    "banana_pro": ["1K", "2K", "4K"],
    "banana_2": ["1K", "2K", "4K"],
    "seedream_edit": ["basic", "high"],
    "seedream_5_pro": ["basic", "high"],
}
_VIDEO_RATIOS = {
    "v3_std": ["16:9", "9:16", "1:1"],
    "v3_pro": ["16:9", "9:16", "1:1"],
    "v26_pro": ["16:9", "9:16", "1:1"],
    "grok_imagine": ["16:9", "9:16", "1:1", "3:2", "2:3"],
    "grok_imagine_v15": ["auto", "16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3"],
    "seedance_2_5": ["16:9", "9:16", "1:1"],
    "seedance_2": ["16:9", "9:16", "1:1"],
    "glow": ["16:9", "9:16", "1:1"],
    "veo3": ["16:9", "9:16", "Auto"],
    "veo3_fast": ["16:9", "9:16", "Auto"],
    "veo3_lite": ["16:9", "9:16", "Auto"],
    "gemini_omni": ["16:9", "9:16"],
}
_DEFAULT_VIDEO_DURATION = {
    "grok_imagine": 6,
    "grok_imagine_v15": 8,
    "gemini_omni": 6,
    "veo3": 6,
    "veo3_fast": 6,
    "veo3_lite": 6,
}


@dataclass(frozen=True)
class MaxMiniAppIdentity:
    user_id: int
    user: dict[str, Any]
    payload: dict[str, Any]
    persisted: MaxUser


def is_max_miniapp_request(payload: dict[str, Any] | None) -> bool:
    return str((payload or {}).get("platform") or "").strip().lower() == "max"


def validate_max_init_data(
    init_data: str,
    bot_token: str,
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Validate official MAX WebAppData without accepting duplicate keys."""
    raw = str(init_data or "").strip()
    if not raw:
        raise ValueError("Missing MAX init_data")
    if not bot_token:
        raise RuntimeError("MAX_ACCESS_TOKEN is not configured")

    pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=False)
    if not pairs:
        raise ValueError("Invalid MAX init_data")

    seen: set[str] = set()
    parsed: dict[str, str] = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError("Duplicate MAX init_data key")
        seen.add(key)
        parsed[key] = value

    their_hash = parsed.pop("hash", "")
    if not their_hash:
        raise ValueError("Missing MAX hash")

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_hash, their_hash):
        raise ValueError("Invalid MAX signature")

    try:
        auth_date = int(parsed.get("auth_date", "0") or 0)
    except ValueError as exc:
        raise ValueError("Invalid MAX auth_date") from exc
    current = float(time.time() if now is None else now)
    if not auth_date or abs(current - auth_date) > MAX_INIT_DATA_MAX_AGE_SECONDS:
        raise ValueError("Expired MAX session")

    try:
        user = json.loads(parsed.get("user", "{}") or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid MAX user") from exc
    if not isinstance(user, dict) or not user.get("id"):
        raise ValueError("Missing MAX user")

    result: dict[str, Any] = dict(parsed)
    result["user"] = user
    return result


async def authenticate_max_miniapp(
    init_data: str,
    *,
    bot_token: str | None = None,
) -> MaxMiniAppIdentity:
    payload = validate_max_init_data(
        init_data,
        bot_token if bot_token is not None else str(os.getenv("MAX_ACCESS_TOKEN", "")).strip(),
    )
    raw_user = payload["user"]
    user_id = int(raw_user["id"])
    persisted = await ensure_max_user(
        user_id,
        username=str(raw_user.get("username") or ""),
        first_name=str(raw_user.get("first_name") or ""),
        last_name=str(raw_user.get("last_name") or ""),
    )
    return MaxMiniAppIdentity(
        user_id=user_id,
        user=raw_user,
        payload=payload,
        persisted=persisted,
    )


def _history_status(value: str) -> str:
    status = str(value or "").lower()
    if status in {"succeeded", "success", "completed", "delivered", "done"}:
        return "completed"
    if status in {"failed", "error", "cancelled", "canceled"}:
        return "failed"
    return "pending"


def _history_task(item: dict[str, Any]) -> dict[str, Any]:
    kind = str(item.get("kind") or "image")
    model = str(item.get("model") or "")
    created = item.get("created_at")
    created_at = created.isoformat() if hasattr(created, "isoformat") else str(created or "")
    result_url = str(item.get("result_url") or "").strip() or None
    prompt = str(item.get("prompt") or "")
    return {
        "task_id": str(item.get("generation_key") or ""),
        "type": "video" if kind == "video" else "image",
        "model": model,
        "model_label": VIDEO_LABELS.get(model, IMAGE_LABELS.get(model, model)),
        "aspect_ratio": "",
        "status": _history_status(str(item.get("status") or "")),
        "result_url": result_url,
        "result_urls": [result_url] if result_url else [],
        "created_at": created_at,
        "prompt_preview": prompt[:100] + ("..." if len(prompt) > 100 else ""),
        "cost": float(item.get("cost") or 0),
        "prompt_hidden": False,
        "prompt_actions_allowed": True,
    }


def _duration_values(catalog: MaxPresetManager, model: str) -> list[int]:
    pricing_key = "gemini_omni_video" if model == "gemini_omni" else model
    raw = (
        catalog.get_price_config()
        .get("costs_reference", {})
        .get("video_models", {})
        .get(pricing_key, {})
    )
    durations: list[int] = []
    if isinstance(raw, dict):
        for value in (raw.get("duration_costs") or {}):
            try:
                durations.append(int(value))
            except (TypeError, ValueError):
                continue
    return sorted(set(durations)) or [_DEFAULT_VIDEO_DURATION.get(model, 5)]


def image_models_payload(catalog: MaxPresetManager = max_preset_manager) -> list[dict[str, Any]]:
    return [
        {
            "id": model,
            "label": IMAGE_LABELS.get(model, model),
            "description": "MAX · HappyFox",
            "cost": float(cost),
            "ratios": _IMAGE_RATIOS.get(model, ["1:1", "16:9", "9:16"]),
            "requires_reference": model in _IMAGE_REQUIRES_REFERENCE,
            "max_references": int(_IMAGE_MAX_REFERENCES.get(model, 9)),
            **(
                {"qualities": list(_IMAGE_QUALITIES[model])}
                if model in _IMAGE_QUALITIES
                else {}
            ),
        }
        for model, cost in catalog.image_models().items()
    ]


def video_models_payload(catalog: MaxPresetManager = max_preset_manager) -> list[dict[str, Any]]:
    models = catalog.video_models()
    result: list[dict[str, Any]] = []
    for model in models:
        supports = [kind for kind, values in MAX_VIDEO_TYPES.items() if model in values]
        durations = _duration_values(catalog, model)
        costs: dict[str, float] = {}
        for duration in durations:
            quality = "720p" if model.startswith("veo3") or model == "gemini_omni" else None
            try:
                costs[str(duration)] = catalog.video_cost(
                    model,
                    duration=duration,
                    quality=quality,
                )
            except (KeyError, TypeError, ValueError):
                continue
        result.append(
            {
                "id": model,
                "label": VIDEO_LABELS.get(model, model),
                "description": "MAX · HappyFox",
                "durations": durations,
                "ratios": _VIDEO_RATIOS.get(model, ["16:9", "9:16", "1:1"]),
                "supports": supports,
                "costs": costs,
                "max_image_references": 9,
                "max_video_references": 5,
            }
        )
    return result


async def bootstrap_payload(
    identity: MaxMiniAppIdentity,
    *,
    bot_name: str = "",
    mini_app_url: str = "",
    catalog: MaxPresetManager = max_preset_manager,
) -> dict[str, Any]:
    history = await list_max_history(identity.user_id, limit=24)
    balance = await get_max_balance(identity.user_id)
    normalized_bot_name = str(bot_name or "").strip().lstrip("@")
    referral_link = (
        f"https://max.ru/{normalized_bot_name}?start=ref_{identity.user_id}"
        if normalized_bot_name
        else ""
    )
    return {
        "ok": True,
        "platform": "max",
        "max_user_id": identity.user_id,
        "credits": balance,
        "first_name": str(identity.user.get("first_name") or ""),
        "last_name": str(identity.user.get("last_name") or ""),
        "telegram_username": str(identity.user.get("username") or ""),
        "photo_url": str(identity.user.get("photo_url") or ""),
        "referral_code": str(identity.user_id),
        "profile_link": "",
        "referral_link": referral_link,
        "channel_url": "",
        "prompt_repeat_balance_rub": 0,
        "prompt_repeat_total_rub": 0,
        "bot_username": normalized_bot_name,
        "username": normalized_bot_name,
        "mini_app_url": mini_app_url,
        "is_admin": await is_max_admin(identity.user_id),
        "actions": ["generate_image", "generate_video", "task_detail", "upload", "create_payment"],
        "payment_packages": [dict(package) for package in catalog.get_packages()],
        "image_models": image_models_payload(catalog),
        "video_models": video_models_payload(catalog),
        "recent_tasks": [_history_task(item) for item in history],
        "saved_references": [],
        "notifications": [],
    }


async def enqueue_image(
    identity: MaxMiniAppIdentity,
    body: dict[str, Any],
) -> tuple[MaxGenerationJob, float]:
    model = str(body.get("img_service") or "banana_pro").strip()
    prompt = str(body.get("prompt") or "").strip()
    references = [
        str(item).strip()
        for item in list(body.get("reference_images") or [])
        if str(item).strip()
    ]
    max_refs = int(_IMAGE_MAX_REFERENCES.get(model, 9))
    if model in _IMAGE_REQUIRES_REFERENCE and not references:
        raise ValueError("Для этой модели нужен хотя бы один исходник")
    if len(references) > max_refs:
        raise ValueError(f"Слишком много референсов. Максимум: {max_refs}")

    options = {
        "aspect_ratio": str(body.get("img_ratio") or "1:1"),
        "quality": str(body.get("img_quality") or "2K"),
        "nsfw_checker": bool(body.get("img_nsfw_checker", False)),
        "nsfw_enabled": bool(body.get("nsfw_enabled", False)),
    }
    job = await enqueue_max_generation(
        identity.user_id,
        kind="image",
        generation_type="image",
        model=model,
        prompt=prompt,
        input_data={"image_urls": references, "video_urls": []},
        options=options,
    )
    return job, await get_max_balance(identity.user_id)


async def enqueue_video(
    identity: MaxMiniAppIdentity,
    body: dict[str, Any],
) -> tuple[MaxGenerationJob, float]:
    model = str(body.get("v_model") or "v3_pro").strip()
    generation_type = str(body.get("v_type") or "text").strip()
    if generation_type not in MAX_VIDEO_TYPES:
        raise ValueError("Этот сценарий видео пока недоступен в MAX Mini App")

    start_image = str(body.get("v_image_url") or "").strip()
    image_urls = [
        str(item).strip()
        for item in list(body.get("reference_images") or [])
        if str(item).strip()
    ]
    if start_image and start_image not in image_urls:
        image_urls.insert(0, start_image)
    video_urls = [
        str(item).strip()
        for item in list(body.get("v_reference_videos") or [])
        if str(item).strip()
    ]

    options = {
        "duration": int(body.get("v_duration") or _DEFAULT_VIDEO_DURATION.get(model, 5)),
        "aspect_ratio": str(body.get("v_ratio") or "16:9"),
        "resolution": str(
            body.get("veo_resolution")
            or body.get("grok_resolution")
            or body.get("omni_resolution")
            or "720p"
        ),
        "grok_mode": str(body.get("grok_mode") or "normal"),
        "generate_audio": bool(body.get("generate_audio", True)),
        "negative_prompt": str(body.get("kling_negative_prompt") or ""),
        "cfg_scale": body.get("kling_cfg_scale"),
    }
    job = await enqueue_max_generation(
        identity.user_id,
        kind="video",
        generation_type=generation_type,
        model=model,
        prompt=str(body.get("prompt") or "").strip(),
        input_data={
            "image_urls": image_urls,
            "video_urls": video_urls,
            "audio_url": str(body.get("audio_url") or "").strip() or None,
        },
        options=options,
    )
    return job, await get_max_balance(identity.user_id)


def task_payload(job: MaxGenerationJob) -> dict[str, Any]:
    result_url = str(job.result_url or "").strip() or None
    status = _history_status(job.status)
    return {
        "task_id": job.id,
        "type": "video" if job.kind == "video" else "image",
        "model": job.model,
        "model_label": VIDEO_LABELS.get(job.model, IMAGE_LABELS.get(job.model, job.model)),
        "aspect_ratio": str(job.options.get("aspect_ratio") or ""),
        "status": status,
        "result_url": result_url,
        "result_urls": [result_url] if result_url else [],
        "created_at": "",
        "prompt_preview": job.prompt[:100] + ("..." if len(job.prompt) > 100 else ""),
        "prompt": job.prompt,
        "cost": float(job.cost),
        "duration": job.options.get("duration"),
        "prompt_hidden": False,
        "prompt_actions_allowed": True,
        "request_data": {
            "reference_images": list(job.input_data.get("image_urls") or []),
            "v_reference_videos": list(job.input_data.get("video_urls") or []),
            "audio_reference": job.input_data.get("audio_url"),
        },
    }


async def owned_task(identity: MaxMiniAppIdentity, task_id: str) -> MaxGenerationJob | None:
    job = await get_max_generation_job(task_id)
    if job is None or int(job.max_user_id) != int(identity.user_id):
        return None
    return job


__all__ = [
    "MaxInsufficientBalanceError",
    "MaxMiniAppIdentity",
    "authenticate_max_miniapp",
    "bootstrap_payload",
    "enqueue_image",
    "enqueue_video",
    "is_max_miniapp_request",
    "owned_task",
    "task_payload",
    "validate_max_init_data",
]

# --- aiohttp integration ----------------------------------------------------

from aiohttp import web


def _json_error(message: str, *, status: int = 400) -> web.Response:
    return web.json_response({"ok": False, "error": str(message)}, status=status)


async def _identity_from_body(body: dict[str, Any]) -> MaxMiniAppIdentity:
    return await authenticate_max_miniapp(str(body.get("init_data") or ""))


async def _handle_bootstrap(request: web.Request, body: dict[str, Any]) -> web.Response:
    started = time.perf_counter()
    identity = await _identity_from_body(body)
    channel = request.app.get("max_channel")
    bot_name = str(getattr(channel, "bot_name", "") or os.getenv("MAX_BOT_NAME", "")).strip()
    mini_app_url = str(
        getattr(getattr(channel, "settings", None), "mini_app_url", "")
        or os.getenv("MAX_MINI_APP_URL", "")
    ).strip()
    data = await bootstrap_payload(
        identity,
        bot_name=bot_name,
        mini_app_url=mini_app_url,
    )
    logger.info(
        "Mini App bootstrap platform=max user_id=%s duration_ms=%.1f outcome=success",
        identity.user_id,
        (time.perf_counter() - started) * 1000,
    )
    return web.json_response(data)


async def _handle_generate_image(
    request: web.Request,
    body: dict[str, Any],
) -> web.Response:
    identity = await _identity_from_body(body)
    try:
        job, balance = await enqueue_image(identity, body)
    except MaxInsufficientBalanceError:
        return _json_error(
            "Недостаточно бананов для этой генерации",
            status=400,
        )
    return web.json_response(
        {
            "ok": True,
            "status": "queued",
            "task_id": job.id,
            "saved_url": job.result_url,
            "task_type": "image",
            "credits": balance,
            "cost": job.cost,
            "model_label": IMAGE_LABELS.get(job.model, job.model),
            "prompt_hidden": False,
            "prompt_actions_allowed": True,
            "prompt_id": None,
            "source_feed_gen_id": None,
        }
    )


async def _handle_generate_video(
    request: web.Request,
    body: dict[str, Any],
) -> web.Response:
    identity = await _identity_from_body(body)
    try:
        job, balance = await enqueue_video(identity, body)
    except MaxInsufficientBalanceError:
        return _json_error(
            "Недостаточно бананов для этой генерации",
            status=400,
        )
    return web.json_response(
        {
            "ok": True,
            "status": "queued",
            "task_id": job.id,
            "saved_url": job.result_url,
            "task_type": "video",
            "credits": balance,
            "cost": job.cost,
            "model_label": VIDEO_LABELS.get(job.model, job.model),
            "prompt_hidden": False,
            "prompt_actions_allowed": True,
            "source_feed_gen_id": None,
        }
    )


async def _handle_task_detail(
    request: web.Request,
    body: dict[str, Any],
) -> web.Response:
    identity = await _identity_from_body(body)
    task_id = str(body.get("task_id") or "").strip()
    if not task_id:
        return _json_error("task_id is required")
    job = await owned_task(identity, task_id)
    if job is None:
        return _json_error("Задача не найдена", status=404)
    return web.json_response({"ok": True, "task": task_payload(job)})


async def _handle_create_payment(
    request: web.Request,
    body: dict[str, Any],
) -> web.Response:
    identity = await _identity_from_body(body)
    provider = str(body.get("provider") or "yookassa").strip().lower()
    if provider != "yookassa":
        return _json_error(
            "В MAX Mini App сейчас доступна оплата через ЮKassa",
            status=400,
        )
    package_id = str(body.get("package_id") or "").strip()
    if not package_id:
        return _json_error("package_id is required")

    channel = request.app.get("max_channel")
    payments = getattr(channel, "payments", None)
    if payments is None or not payments.enabled:
        return _json_error("ЮKassa для MAX временно недоступна", status=503)

    order = await payments.create_checkout(identity.user_id, package_id)
    return web.json_response(
        {
            "ok": True,
            "provider": "yookassa",
            "order_id": order.order_id,
            "payment_id": order.provider_payment_id or order.order_id,
            "payment_url": order.checkout_url,
            "credits": order.credits,
            "promo_bonus_credits": 0,
            "promo_code": "",
        }
    )


async def _handle_upload_post(
    request: web.Request,
    post_data: Any,
) -> web.Response:
    body = {
        "init_data": str(post_data.get("init_data") or ""),
        "platform": "max",
    }
    identity = await _identity_from_body(body)
    _ = identity

    upload = post_data.get("file")
    file_kind = str(post_data.get("file_kind") or "image_reference")
    if upload is None or not getattr(upload, "file", None):
        return _json_error("Файл не был передан")

    from bot.miniapp import (
        FILE_KIND_MAP,
        _guess_extension,
        _normalize_miniapp_upload_content_type,
        save_uploaded_file,
    )

    config_entry = FILE_KIND_MAP.get(file_kind)
    if config_entry is None:
        return _json_error(f"Unsupported file_kind: {file_kind}")

    raw = upload.file.read()
    if not raw:
        return _json_error("Не удалось прочитать файл")
    filename = str(getattr(upload, "filename", "") or "")
    declared_type = str(getattr(upload, "content_type", "") or "")
    content_type = _normalize_miniapp_upload_content_type(
        file_kind,
        filename,
        declared_type,
        bytes(raw),
    )
    if not content_type:
        return _json_error("Формат файла не распознан")

    max_bytes = int(config_entry.get("max_bytes") or 220 * 1024 * 1024)
    if len(raw) > max_bytes:
        return _json_error("Файл слишком большой")

    extension = _guess_extension(
        filename,
        content_type,
        config_entry["fallback_ext"],
    )
    public_url = save_uploaded_file(bytes(raw), extension)
    if not public_url:
        return _json_error("Не удалось сохранить файл", status=500)

    return web.json_response(
        {
            "ok": True,
            "url": public_url,
            "kind": config_entry["group"],
            "filename": filename or public_url.rsplit("/", 1)[-1],
            "content_type": content_type,
            "reference": None,
        }
    )


async def _handle_upload_json(
    request: web.Request,
    body: dict[str, Any],
) -> web.Response:
    import base64

    identity = await _identity_from_body(body)
    _ = identity
    file_kind = str(body.get("file_kind") or "image_reference")
    encoded = str(body.get("data_base64") or "")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (TypeError, ValueError):
        return _json_error("Файл не был передан")

    from bot.miniapp import (
        FILE_KIND_MAP,
        _guess_extension,
        _normalize_miniapp_upload_content_type,
        save_uploaded_file,
    )

    config_entry = FILE_KIND_MAP.get(file_kind)
    if config_entry is None:
        return _json_error(f"Unsupported file_kind: {file_kind}")
    filename = str(body.get("filename") or "")
    declared_type = str(body.get("content_type") or "")
    content_type = _normalize_miniapp_upload_content_type(
        file_kind,
        filename,
        declared_type,
        bytes(raw),
    )
    if not content_type:
        return _json_error("Формат файла не распознан")
    max_bytes = int(config_entry.get("max_bytes") or 220 * 1024 * 1024)
    if len(raw) > max_bytes:
        return _json_error("Файл слишком большой")

    extension = _guess_extension(filename, content_type, config_entry["fallback_ext"])
    public_url = save_uploaded_file(bytes(raw), extension)
    if not public_url:
        return _json_error("Не удалось сохранить файл", status=500)

    return web.json_response(
        {
            "ok": True,
            "url": public_url,
            "kind": config_entry["group"],
            "filename": filename or public_url.rsplit("/", 1)[-1],
            "content_type": content_type,
            "reference": None,
        }
    )


async def _handle_ai_assistant(
    request: web.Request,
    body: dict[str, Any],
) -> web.Response:
    identity = await _identity_from_body(body)
    message = str(body.get("message") or "").strip()
    if not message:
        return _json_error("Сообщение не может быть пустым")

    from bot.services.ai_assistant_service import ai_assistant_service

    reply = await ai_assistant_service.get_assistant_response(
        user_message=message,
        context={
            "user_credits": await get_max_balance(identity.user_id),
            "menu_location": "max_mini_app_assistant",
        },
    )
    if reply is None:
        return _json_error(
            "AI-ассистент временно недоступен. Попробуйте позже.",
            status=503,
        )
    return web.json_response({"ok": True, "reply": reply})


_MAX_JSON_HANDLERS = {
    "/mini-app/api/bootstrap": _handle_bootstrap,
    "/mini-app/api/generate-image": _handle_generate_image,
    "/mini-app/api/generate-video": _handle_generate_video,
    "/mini-app/api/task-detail": _handle_task_detail,
    "/mini-app/api/create-payment": _handle_create_payment,
    "/mini-app/api/ai-assistant": _handle_ai_assistant,
}


@web.middleware
async def max_miniapp_middleware(
    request: web.Request,
    handler: Any,
) -> web.StreamResponse:
    if request.method != "POST" or not request.path.startswith("/mini-app/api/"):
        return await handler(request)

    try:
        if request.path == "/mini-app/api/upload":
            if request.content_type == "application/json":
                body = await request.json()
                if not is_max_miniapp_request(body):
                    return await handler(request)
                return await _handle_upload_json(request, body)

            post_data = await request.post()
            if str(post_data.get("platform") or "").strip().lower() != "max":
                return await handler(request)
            return await _handle_upload_post(request, post_data)

        if request.content_type != "application/json":
            return await handler(request)
        body = await request.json()
        if not is_max_miniapp_request(body):
            return await handler(request)

        max_handler = _MAX_JSON_HANDLERS.get(request.path)
        if max_handler is None:
            logger.info(
                "Mini App MAX unsupported route: method=%s path=%s",
                request.method,
                request.path,
            )
            return _json_error(
                "Этот раздел пока недоступен в MAX Mini App",
                status=501,
            )
        return await max_handler(request, body)
    except ValueError as exc:
        logger.info(
            "Mini App MAX request rejected: path=%s error=%s",
            request.path,
            type(exc).__name__,
        )
        return _json_error(str(exc), status=400)
    except RuntimeError as exc:
        logger.warning(
            "Mini App MAX runtime error: path=%s error=%s",
            request.path,
            exc,
        )
        return _json_error(str(exc), status=503)
    except Exception:
        logger.exception("Mini App MAX request failed: path=%s", request.path)
        return _json_error("Ошибка MAX Mini App. Попробуйте ещё раз.", status=500)


def install_max_miniapp_middleware(app: web.Application) -> None:
    if max_miniapp_middleware not in app.middlewares:
        app.middlewares.append(max_miniapp_middleware)
