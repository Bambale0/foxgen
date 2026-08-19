from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from aiohttp import web

from bot.config import config
from bot.database import (
    add_credits,
    check_can_afford,
    deduct_credits,
    get_or_create_user,
    get_prompt_by_id,
    touch_saved_references,
    use_prompt,
)
from bot.services.media_input_utils import missing_local_upload_sources
from bot.services.preset_manager import preset_manager
from bot.video_reference_policy import apply_video_reference_cost

logger = logging.getLogger(__name__)

MAX_TREND_REFERENCES = 12


class TrendRunValidationError(ValueError):
    """Raised when a curated trend cannot be run safely."""


@dataclass(frozen=True)
class TrendRunRequest:
    trend_id: int
    reference_urls: tuple[str, ...]


@dataclass(frozen=True)
class TrustedTrendRun:
    trend_id: int
    kind: str
    prompt: str
    model: str
    ratio: str
    reference_urls: tuple[str, ...]
    settings: dict[str, Any]


def _fallback_trend_settings(trend: Mapping[str, Any]) -> dict[str, Any]:
    tags = {
        str(tag or "").strip().lower()
        for tag in list(trend.get("tags") or [])
        if str(tag or "").strip()
    }
    model = str(trend.get("model") or "").strip()
    is_video = (
        str(trend.get("category") or "").strip().lower() == "video"
        or "trend-video" in tags
    )
    if not is_video:
        return {
            "kind": "image",
            "user_input": "photo",
            "model": model or "banana_pro",
            "ratio": "1:1",
            "quality": "2K" if model in {"banana_pro", "banana_2"} else "basic",
            "count": 1,
            "nsfw_checker": False,
            "nsfw_enabled": False,
        }

    return {
        "kind": "video",
        "user_input": "photo",
        "model": model or "v3_pro",
        "scenario": "imgtxt",
        "ratio": "16:9",
        "duration": 5,
        "grok_mode": "normal",
        "grok_resolution": "480p",
        "veo_generation_type": "IMAGE_2_VIDEO",
        "veo_translation": True,
        "veo_resolution": "720p",
        "veo_seed": None,
        "veo_watermark": "",
        "kling_negative_prompt": "",
        "kling_cfg_scale": 0.5,
        "omni_resolution": "720p",
        "omni_seed": None,
        "omni_audio_ids": [],
        "omni_character_ids": [],
        "omni_base_voice": "achernar",
        "omni_voice_name": "",
        "omni_voice_description": "",
        "omni_example_dialogue": "",
        "omni_character_name": "",
        "omni_character_audio_ids": [],
    }


def _clean_reference_urls(raw_urls: Any) -> tuple[str, ...]:
    if not isinstance(raw_urls, list):
        raise TrendRunValidationError("Передайте список фото-референсов")

    cleaned: list[str] = []
    for raw_url in raw_urls:
        url = str(raw_url or "").strip()
        if not url or url in cleaned:
            continue
        if url.startswith(("blob:", "data:", "file:")):
            raise TrendRunValidationError(
                "Дождитесь окончания загрузки референсов и попробуйте снова"
            )
        if not url.startswith(("https://", "http://", "/uploads/")):
            raise TrendRunValidationError("Некорректная ссылка на референс")
        cleaned.append(url)
        if len(cleaned) > MAX_TREND_REFERENCES:
            raise TrendRunValidationError(
                f"Слишком много референсов. Максимум: {MAX_TREND_REFERENCES}"
            )

    if not cleaned:
        raise TrendRunValidationError("Загрузите хотя бы одно фото")
    return tuple(cleaned)


def parse_trend_run_request(body: Any) -> TrendRunRequest:
    """Accept only a trend ID and uploaded references from the client.

    Any client-supplied model, prompt, ratio, quality, duration or provider
    options are deliberately ignored. Those values are loaded from the trend
    record created by an administrator.
    """

    if not isinstance(body, Mapping):
        raise TrendRunValidationError("Некорректный запрос")

    raw_trend_id = body.get("trend_id")
    if not str(raw_trend_id or "").isdigit():
        raise TrendRunValidationError("Тренд не найден")

    return TrendRunRequest(
        trend_id=int(raw_trend_id),
        reference_urls=_clean_reference_urls(body.get("reference_urls")),
    )


def trusted_trend_run(
    trend: Mapping[str, Any] | None,
    reference_urls: tuple[str, ...],
) -> TrustedTrendRun:
    if not trend:
        raise TrendRunValidationError("Тренд не найден")
    if trend.get("status") != "approved" or not bool(trend.get("is_public")):
        raise TrendRunValidationError("Тренд недоступен")

    tags = {
        str(tag or "").strip().lower()
        for tag in list(trend.get("tags") or [])
        if str(tag or "").strip()
    }
    if "trend" not in tags:
        raise TrendRunValidationError("Выбранный шаблон не является трендом")

    stored_settings = trend.get("generation_settings")
    settings = (
        dict(stored_settings)
        if isinstance(stored_settings, Mapping) and stored_settings
        else _fallback_trend_settings(trend)
    )
    if not settings:
        raise TrendRunValidationError(
            "Настройки тренда не сохранены. Администратору нужно пересоздать тренд"
        )
    kind = str(settings.get("kind") or "").strip().lower()
    if kind not in {"image", "video"}:
        raise TrendRunValidationError("Неизвестный тип тренда")
    if str(settings.get("user_input") or "photo") != "photo":
        raise TrendRunValidationError("Этот тренд не поддерживает фото-референсы")

    prompt = str(trend.get("prompt_text") or "").strip()
    model = str(settings.get("model") or trend.get("model") or "").strip()
    ratio = str(settings.get("ratio") or "").strip()
    if not prompt or not model or not ratio:
        raise TrendRunValidationError(
            "Настройки тренда заполнены не полностью. "
            "Администратору нужно пересохранить тренд"
        )

    return TrustedTrendRun(
        trend_id=int(trend["id"]),
        kind=kind,
        prompt=prompt,
        model=model,
        ratio=ratio,
        reference_urls=reference_urls,
        settings=settings,
    )


def _int_setting(settings: Mapping[str, Any], key: str, default: int) -> int:
    try:
        return int(settings.get(key, default) or default)
    except (TypeError, ValueError):
        return default


def _optional_int(settings: Mapping[str, Any], key: str) -> int | None:
    value = settings.get(key)
    if value in (None, "", False):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(
    settings: Mapping[str, Any],
    key: str,
    default: float | None = None,
) -> float | None:
    value = settings.get(key)
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _string_list(settings: Mapping[str, Any], key: str) -> list[str]:
    raw = settings.get(key)
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


async def _record_trend_use(
    trend_id: int,
    user_id: int,
    *,
    credits_spent: float,
) -> None:
    try:
        await use_prompt(trend_id, user_id, credits_spent=credits_spent)
    except Exception:
        logger.exception("Failed to record trend use: trend_id=%s", trend_id)


async def _debit_for_generation(
    telegram_id: int,
    user: Any,
    amount: float,
) -> tuple[bool, web.Response | None]:
    if config.is_admin(telegram_id):
        return False, None
    if not await check_can_afford(telegram_id, amount):
        return False, web.json_response(
            {
                "ok": False,
                "error": f"Недостаточно бананов. Нужно {amount}🍌",
                "credits": user.credits,
            },
            status=400,
        )
    if not await deduct_credits(telegram_id, amount):
        return False, web.json_response(
            {"ok": False, "error": "Не удалось списать бананы. Обновите баланс"},
            status=409,
        )
    return True, None


def _validate_uploaded_references(
    references: list[str],
    miniapp_module: Any,
) -> None:
    if miniapp_module._browser_local_reference_urls(references):
        raise TrendRunValidationError(
            "Дождитесь окончания загрузки референсов и попробуйте снова"
        )
    if missing_local_upload_sources(references):
        raise TrendRunValidationError(
            "Один или несколько референсов уже удалены. Загрузите их заново"
        )


async def _run_image_trend(
    request: web.Request,
    *,
    telegram_id: int,
    user: Any,
    trend: TrustedTrendRun,
) -> web.Response:
    from bot import miniapp as miniapp_module

    model_meta = next(
        (item for item in miniapp_module.IMAGE_MODELS if item["id"] == trend.model),
        None,
    )
    if not model_meta:
        raise TrendRunValidationError("Модель фото-тренда больше недоступна")
    if trend.ratio not in model_meta.get("ratios", []):
        raise TrendRunValidationError("Формат фото-тренда больше не поддерживается")

    max_references = int(model_meta.get("max_references", 0) or 0)
    if max_references and len(trend.reference_urls) > max_references:
        raise TrendRunValidationError(
            f"Слишком много референсов. Максимум: {max_references}"
        )

    quality = str(trend.settings.get("quality") or "basic")
    allowed_qualities = list(model_meta.get("qualities") or [])
    if trend.model in {"banana_pro", "banana_2"}:
        allowed_qualities = ["1K", "2K", "4K"]
    if allowed_qualities and quality not in allowed_qualities:
        raise TrendRunValidationError("Качество фото-тренда больше не поддерживается")

    configured_count = _int_setting(trend.settings, "count", 1)
    if configured_count != 1:
        raise TrendRunValidationError(
            "Тренд нужно пересохранить с одной генерацией за запуск"
        )

    references = list(trend.reference_urls)
    _validate_uploaded_references(references, miniapp_module)
    await touch_saved_references(telegram_id, references, kind="image")

    cost = miniapp_module._resolve_image_unit_cost(trend.model, quality)
    debited, debit_error = await _debit_for_generation(telegram_id, user, cost)
    if debit_error is not None:
        return debit_error

    launched = False
    try:
        launch_result = await miniapp_module._start_image_generation_task(
            user=user,
            telegram_id=telegram_id,
            img_service=trend.model,
            prompt=trend.prompt,
            img_ratio=trend.ratio,
            reference_images=references,
            unit_cost=cost,
            img_quality=quality,
            img_nsfw_checker=bool(trend.settings.get("nsfw_checker", False)),
            nsfw_enabled=bool(trend.settings.get("nsfw_enabled", False)),
            callback_url=(
                config.kie_notification_url if config.WEBHOOK_HOST else None
            ),
            prompt_source_id=trend.trend_id,
            action_type="trend",
        )
        if launch_result["status"] == "failed":
            if debited:
                await add_credits(telegram_id, cost)
            return web.json_response(
                {
                    "ok": False,
                    "error": "Не удалось запустить тренд. Бананы уже возвращены.",
                },
                status=500,
            )
        launched = True

        await miniapp_module._notify_miniapp_image_task_queued(
            request.app,
            telegram_id,
            launch_result,
            img_service=trend.model,
            img_ratio=trend.ratio,
            unit_cost=cost,
        )
        await miniapp_module._deliver_miniapp_direct_image_result(
            request.app,
            telegram_id,
            launch_result,
            img_service=trend.model,
            img_ratio=trend.ratio,
            unit_cost=cost,
            prompt_hidden=True,
        )
        await _record_trend_use(
            trend.trend_id,
            user.id,
            credits_spent=float(cost),
        )

        fresh_user = await get_or_create_user(telegram_id)
        return web.json_response(
            {
                "ok": True,
                "status": launch_result["status"],
                "task_id": launch_result["task_id"],
                "saved_url": launch_result.get("saved_url"),
                "task_type": launch_result.get("task_type", "image"),
                "credits": fresh_user.credits,
                "cost": cost,
                "model": trend.model,
                "model_label": miniapp_module.get_image_model_label(trend.model),
                "aspect_ratio": trend.ratio,
                "duration": None,
                "prompt_hidden": True,
                "prompt_actions_allowed": False,
                "trend_id": trend.trend_id,
            }
        )
    except Exception:
        if debited and not launched:
            await add_credits(telegram_id, cost)
        raise


async def _run_video_trend(
    *,
    telegram_id: int,
    user: Any,
    trend: TrustedTrendRun,
) -> web.Response:
    from bot import miniapp as miniapp_module

    scenario = str(trend.settings.get("scenario") or "imgtxt")
    if scenario != "imgtxt":
        raise TrendRunValidationError(
            "Видео-тренд должен быть сохранён в режиме «Фото + текст»"
        )

    model_meta = miniapp_module._find_video_model_meta(trend.model)
    if not model_meta:
        raise TrendRunValidationError("Модель видео-тренда больше недоступна")
    if scenario not in model_meta.get("supports", []):
        raise TrendRunValidationError("Модель тренда больше не поддерживает фото")
    if trend.ratio not in model_meta.get("ratios", []):
        raise TrendRunValidationError("Формат видео-тренда больше не поддерживается")

    duration = _int_setting(trend.settings, "duration", 5)
    if duration not in model_meta.get("durations", []):
        raise TrendRunValidationError(
            "Длительность видео-тренда больше не поддерживается"
        )

    max_extra_references = int(model_meta.get("max_image_references", 0) or 0)
    max_references = max(1, max_extra_references + 1)
    if len(trend.reference_urls) > max_references:
        raise TrendRunValidationError(
            f"Слишком много референсов. Максимум: {max_references}"
        )

    image_url = trend.reference_urls[0]
    image_references = list(trend.reference_urls[1:])
    all_references = [image_url, *image_references]
    _validate_uploaded_references(all_references, miniapp_module)
    await touch_saved_references(telegram_id, all_references, kind="image")

    effective_model = miniapp_module._resolve_gemini_omni_model(
        trend.model,
        scenario,
    )
    veo_resolution = str(trend.settings.get("veo_resolution") or "720p")
    omni_resolution = str(trend.settings.get("omni_resolution") or "720p")
    pricing_quality = miniapp_module._video_pricing_quality(
        effective_model,
        veo_resolution,
        omni_resolution,
    )
    cost = preset_manager.get_video_cost_with_quality(
        effective_model,
        duration,
        pricing_quality,
    )
    cost = apply_video_reference_cost(effective_model, cost, [])

    debited, debit_error = await _debit_for_generation(telegram_id, user, cost)
    if debit_error is not None:
        return debit_error

    launched = False
    try:
        launch_result = await miniapp_module._launch_video_generation_task(
            telegram_id=telegram_id,
            user=user,
            model=effective_model,
            prompt=trend.prompt,
            duration=duration,
            aspect_ratio=trend.ratio,
            generation_type=scenario,
            image_url=image_url,
            image_references=image_references,
            video_references=[],
            grok_mode=str(trend.settings.get("grok_mode") or "normal"),
            grok_resolution=str(
                trend.settings.get("grok_resolution") or "480p"
            ),
            veo_generation_type=str(
                trend.settings.get("veo_generation_type") or "IMAGE_2_VIDEO"
            ),
            veo_translation=bool(trend.settings.get("veo_translation", True)),
            veo_resolution=veo_resolution,
            veo_seed=_optional_int(trend.settings, "veo_seed"),
            veo_watermark=(
                str(trend.settings.get("veo_watermark") or "") or None
            ),
            kling_negative_prompt=(
                str(trend.settings.get("kling_negative_prompt") or "") or None
            ),
            kling_cfg_scale=_optional_float(
                trend.settings,
                "kling_cfg_scale",
                0.5,
            ),
            omni_resolution=omni_resolution,
            omni_seed=_optional_int(trend.settings, "omni_seed"),
            omni_audio_ids=_string_list(trend.settings, "omni_audio_ids"),
            omni_character_ids=_string_list(
                trend.settings,
                "omni_character_ids",
            ),
            omni_base_voice=str(
                trend.settings.get("omni_base_voice") or "achernar"
            ),
            omni_voice_name=(
                str(trend.settings.get("omni_voice_name") or "") or None
            ),
            omni_voice_description=(
                str(trend.settings.get("omni_voice_description") or "") or None
            ),
            omni_example_dialogue=(
                str(trend.settings.get("omni_example_dialogue") or "") or None
            ),
            omni_character_name=(
                str(trend.settings.get("omni_character_name") or "") or None
            ),
            omni_character_audio_ids=_string_list(
                trend.settings,
                "omni_character_audio_ids",
            )[:1],
            action_type="trend",
        )
        if launch_result["status"] == "failed":
            if debited:
                await add_credits(telegram_id, cost)
            return web.json_response(
                {
                    "ok": False,
                    "error": launch_result.get("error")
                    or "Не удалось запустить видео-тренд. Бананы уже возвращены.",
                },
                status=500,
            )
        launched = True

        await _record_trend_use(
            trend.trend_id,
            user.id,
            credits_spent=float(cost),
        )
        fresh_user = await get_or_create_user(telegram_id)
        return web.json_response(
            {
                "ok": True,
                "status": launch_result["status"],
                "task_id": launch_result["task_id"],
                "saved_url": launch_result.get("saved_url"),
                "task_type": launch_result.get("task_type", "video"),
                "credits": fresh_user.credits,
                "cost": cost,
                "model": effective_model,
                "model_label": miniapp_module.get_video_model_label(
                    effective_model
                ),
                "aspect_ratio": trend.ratio,
                "duration": duration,
                "prompt_hidden": True,
                "prompt_actions_allowed": False,
                "trend_id": trend.trend_id,
            }
        )
    except Exception:
        if debited and not launched:
            await add_credits(telegram_id, cost)
        raise


async def miniapp_run_trend(request: web.Request) -> web.Response:
    """Run a curated trend using only settings stored by an administrator."""

    try:
        body = await request.json()
        parsed = parse_trend_run_request(body)

        from bot import miniapp as miniapp_module

        telegram_id, context = await miniapp_module._get_user_context(
            request.app,
            str(body.get("init_data") or ""),
            body.get("start_param_fallback"),
        )
        prompt = await get_prompt_by_id(
            parsed.trend_id,
            approved_public_only=True,
        )
        trend = trusted_trend_run(prompt, parsed.reference_urls)

        if trend.kind == "video":
            return await _run_video_trend(
                telegram_id=telegram_id,
                user=context["user"],
                trend=trend,
            )
        return await _run_image_trend(
            request,
            telegram_id=telegram_id,
            user=context["user"],
            trend=trend,
        )
    except TrendRunValidationError as error:
        return web.json_response({"ok": False, "error": str(error)}, status=400)
    except Exception:
        logger.exception("Mini App trend generation failed")
        return web.json_response(
            {"ok": False, "error": "Не удалось запустить тренд. Попробуйте ещё раз."},
            status=500,
        )


def setup_trend_routes(app: web.Application, miniapp_root: str) -> None:
    """Register the exact route before Mini App's catch-all API handler."""

    app.router.add_post(miniapp_root + "/api/trends/run", miniapp_run_trend)
