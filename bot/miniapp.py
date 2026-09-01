import asyncio
import base64
import hashlib
import hmac
import html
import json
import logging
import mimetypes
import re
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qsl, urlparse

import aiohttp
from aiogram.types import BufferedInputFile, LabeledPrice
from aiohttp import web

from bot import db as db_backend
from bot.config import config

FILE_KIND_MAP: dict[str, dict[str, Any]] = {}

from bot.database import (
    DATABASE_PATH,
    MAX_ACTIVE_PROMPTS_PER_USER,
    SavedReference,
    add_credits,
    add_feed_comment,
    add_generation_task,
    approve_prompt,
    check_can_afford,
    complete_video_task,
    count_active_prompts_by_author,
    create_prompt,
    create_transaction,
    credit_feed_prompt_repeat,
    deactivate_prompt,
    deduct_credits,
    generation_adult_content,
    generation_profile_visible,
    generation_publication_scope,
    get_and_clear_miniapp_notifications,
    get_approved_prompts,
    get_author_prompts,
    get_feed_comments,
    get_feed_generation_card,
    get_feed_generations,
    get_generation_task_payload,
    get_or_create_user,
    get_partner_overview,
    get_popular_prompts,
    get_profile_generation_card,
    get_promo_bonus_for_credits,
    get_promo_code_by_code,
    get_prompt_by_id,
    get_prompts_by_tag,
    get_top_prompts,
    get_user_by_referral_code,
    get_user_feed_generations,
    get_user_feed_summary,
    get_user_stats,
    increment_feed_share,
    is_channel_subscription_required,
    like_feed_generation,
    like_prompt,
    list_saved_references,
    reject_prompt,
    remove_from_feed,
    remove_from_library,
    save_user_channel_url,
    set_feed_blurred,
    share_to_feed,
    share_to_library,
    touch_saved_references,
    update_transaction_status,
    update_user_profile,
    use_prompt,
)
from bot.handlers.common import (
    AI_ASSISTANT_AUDIO_FORMATS,
    AIAssistantStates,
    _build_balance_text,
    _build_main_menu_text,
    _notify_partner_about_new_referral,
)
from bot.handlers.generation import (
    _init_default_video_state,
    _show_image_model_selection_screen,
    _show_video_model_selection_screen,
    _start_image_generation_task,
    save_uploaded_file,
)
from bot.handlers.image_analyzer import ImageAnalyzerStates
from bot.keyboards import (
    get_ai_assistant_keyboard,
    get_animate_hub_keyboard,
    get_balance_keyboard,
    get_create_hub_keyboard,
    get_edit_hub_keyboard,
    get_image_model_label,
    get_image_result_keyboard,
    get_main_menu_button_keyboard,
    get_main_menu_keyboard,
    get_more_menu_keyboard,
    get_partner_program_keyboard,
    get_payment_packages_keyboard,
    get_support_keyboard,
    get_video_model_label,
)
from bot.miniapp_links import (
    feed_bot_link as build_feed_bot_link,
)
from bot.miniapp_links import (
    feed_link as build_feed_link,
)
from bot.miniapp_links import (
    profile_link as build_profile_link,
)
from bot.miniapp_links import (
    prompt_link as build_prompt_link,
)
from bot.miniapp_links import (
    referral_bot_link as build_referral_bot_link,
)
from bot.miniapp_links import (
    referral_link as build_referral_link,
)
from bot.miniapp_links import (
    remix_bot_link as build_remix_bot_link,
)
from bot.miniapp_links import (
    remix_link as build_remix_link,
)
from bot.payment_utils import (
    TELEGRAM_STARS_CURRENCY,
    TELEGRAM_STARS_PROVIDER,
    build_stars_invoice_payload,
    package_stars_amount,
    total_package_credits,
)
from bot.quality_pricing import QUALITY_COSTS, SEEDREAM_5_PRO_QUALITY_COSTS
from bot.services.ai_assistant_service import ai_assistant_service
from bot.services.lava_service import lava_service
from bot.services.media_input_utils import (
    is_reference_contact_sheet_url,
    missing_local_upload_sources,
    resolve_local_upload_path,
)
from bot.services.photo_prompt_billing import (
    PhotoPromptInsufficientBalance,
    refund_photo_prompt_charge,
    reserve_photo_prompt_charge,
)
from bot.services.preset_manager import preset_manager
from bot.services.reference_storage_service import save_reference_file
from bot.services.subscription_service import (
    REQUIRED_CHANNEL_USERNAME,
    check_required_channel_subscription,
    should_block_for_subscription,
)
from bot.services.yookassa_service import yookassa_service
from bot.utils.user_facing_errors import make_user_friendly_generation_error
from bot.utils.validators import detect_explicit_prompt_policy_violation
from bot.video_reference_policy import (
    apply_video_reference_cost,
    get_max_video_image_references,
    get_max_video_references,
    normalize_reference_urls,
    video_model_supports_reference_videos,
)

MINIAPP_MEDIA_CACHE_DIR = Path("static/uploads/miniapp-media-cache")
MINIAPP_MEDIA_MAX_BYTES = 50 * 1024 * 1024
MINIAPP_UPLOAD_TIMEOUT_SECONDS = 900
MINIAPP_UPLOAD_DEFAULT_MAX_BYTES = 50 * 1024 * 1024
MINIAPP_TREND_VIDEO_MAX_BYTES = 200 * 1024 * 1024
_miniapp_media_locks: dict[str, asyncio.Lock] = {}

logger = logging.getLogger(__name__)

_MINIAPP_INIT_DATA_ERRORS = {
    "Missing init_data": "Откройте Mini App из Telegram и попробуйте снова.",
    "Missing Telegram hash": "Откройте Mini App из Telegram и попробуйте снова.",
    "Invalid Telegram signature": "Откройте Mini App заново из Telegram.",
    "Expired Telegram session": "Сессия Telegram истекла. Откройте Mini App заново из Telegram.",
    "Missing Telegram user": "Откройте Mini App заново из Telegram.",
}


def _miniapp_expected_error_response(error: Exception) -> web.Response | None:
    if isinstance(error, PermissionError):
        return web.json_response({"ok": False, "error": str(error)}, status=403)

    if isinstance(error, ValueError):
        message = str(error)
        if message in _MINIAPP_INIT_DATA_ERRORS:
            return web.json_response(
                {"ok": False, "error": _MINIAPP_INIT_DATA_ERRORS[message]},
                status=401,
            )
        if (
            "Could not find starting boundary" in message
            or "Invalid boundary" in message
            or "multipart" in message.lower()
        ):
            return web.json_response(
                {"ok": False, "error": "Загрузка была прервана. Повторите попытку."},
                status=400,
            )

    if isinstance(error, TimeoutError):
        return web.json_response(
            {"ok": False, "error": "Загрузка не завершилась за 60 секунд. Попробуйте ещё раз."},
            status=408,
        )

    if isinstance(error, ConnectionResetError):
        return web.json_response(
            {"ok": False, "error": "Загрузка была прервана. Попробуйте ещё раз."},
            status=499,
        )

    if isinstance(error, web.HTTPException):
        return web.json_response(
            {"ok": False, "error": error.reason or "Mini App request failed"},
            status=error.status,
        )

    return None


def _miniapp_error_response(
    error: Exception,
    *,
    log_message: str,
    default_error: str | None = None,
) -> web.Response:
    expected_response = _miniapp_expected_error_response(error)
    if expected_response is not None:
        logger.warning("%s: %s", log_message, error)
        return expected_response

    logger.exception(log_message)
    return web.json_response(
        {"ok": False, "error": default_error or str(error)},
        status=500,
    )


def _bounded_int(value: Any, *, default: int, minimum: int = 1, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if parsed <= 0:
        parsed = default
    return min(max(parsed, minimum), maximum)


def _saved_reference_payload(reference: SavedReference) -> dict[str, Any]:
    file_url = reference.file_url
    if reference.kind == "image":
        from bot.services.media_input_utils import image_source_to_provider_safe_png_url

        file_url = image_source_to_provider_safe_png_url(file_url)

    return {
        "id": str(reference.id),
        "kind": reference.kind,
        "url": file_url,
        "filename": reference.original_filename or Path(reference.file_url).name,
        "content_type": reference.content_type,
        "source": reference.source,
        "created_at": reference.created_at.isoformat() if reference.created_at else None,
        "last_used_at": reference.last_used_at.isoformat() if reference.last_used_at else None,
    }


def _payment_package_payload(package: dict[str, Any]) -> dict[str, Any]:
    payload = dict(package)
    payload["price_stars"] = package_stars_amount(package)
    offer_id, currency = _miniapp_package_lava_offer_config(package)
    if offer_id:
        payload["lava_offer_id"] = offer_id
        payload["lava_currency"] = currency
    return payload


def _miniapp_package_lava_offer_config(package: dict[str, Any]) -> tuple[str, str]:
    package_id = str(package.get("id") or "")
    offer_id = str(package.get("lava_offer_id") or "").strip()
    if offer_id:
        currency = str(package.get("lava_currency") or "RUB").strip().upper() or "RUB"
        return offer_id, currency
    return config.lava_offer_id_for_package(package_id), "RUB"


IMAGE_MODELS = (
    {
        "id": "nano-banana-2-lite",
        "label": "Nano Banana 2 Lite 🔥 НОВИНКА",
        "description": "Быстрая новинка для лёгких image-задач и быстрых итераций",
        "cost": preset_manager.get_generation_cost("nano-banana-2-lite"),
        "ratios": [
            "1:1",
            "16:9",
            "9:16",
            "4:3",
            "3:4",
            "4:5",
            "5:4",
            "3:2",
            "2:3",
            "21:9",
        ],
        "requires_reference": False,
        "max_references": 8,
    },
    {
        "id": "seedream_5_pro",
        "label": "Seedream 5 Pro 🔥 НОВИНКА",
        "description": "Фотореалистичная генерация с нуля и image-to-image в одной модели",
        "cost": 2,
        "ratios": ["1:1", "9:16", "16:9", "3:4", "4:3", "2:3", "3:2", "21:9"],
        "requires_reference": False,
        "max_references": 5,
        "qualities": ["basic", "high"],
        "quality_costs": {"basic": 2, "high": 2.5},
        "supports_nsfw_checker": False,
    },
    {
        "id": "banana_pro",
        "label": "Nano Banana Pro",
        "description": "Универсальная модель для качественных изображений",
        "cost": preset_manager.get_generation_cost("nano-banana-pro"),
        "ratios": [
            "1:1",
            "16:9",
            "9:16",
            "4:3",
            "3:4",
            "4:5",
            "5:4",
            "3:2",
            "2:3",
            "21:9",
        ],
        "requires_reference": False,
        "max_references": 8,
        "qualities": ["1K", "2K", "4K"],
        "quality_costs": {
            "1K": QUALITY_COSTS["1K"],
            "2K": QUALITY_COSTS["2K"],
            "4K": QUALITY_COSTS["4K"],
        },
    },
    {
        "id": "banana_2",
        "label": "Nano Banana 2",
        "description": "Новая версия Nano Banana с улучшенной детализацией и цветопередачей",
        "cost": preset_manager.get_generation_cost("banana_2"),
        "ratios": [
            "1:1",
            "16:9",
            "9:16",
            "4:3",
            "3:4",
            "4:5",
            "5:4",
            "3:2",
            "2:3",
            "21:9",
        ],
        "requires_reference": False,
        "max_references": 8,
        "qualities": ["1K", "2K", "4K"],
        "quality_costs": {
            "1K": QUALITY_COSTS["1K"],
            "2K": QUALITY_COSTS["2K"],
            "4K": QUALITY_COSTS["4K"],
        },
    },
    {
        "id": "seedream_edit",
        "label": "Seedream 4.5 Edit",
        "description": "Сильный edit по исходникам",
        "cost": preset_manager.get_generation_cost("seedream_edit"),
        "ratios": ["1:1", "9:16", "16:9", "3:4", "4:3", "2:3", "3:2", "21:9"],
        "requires_reference": True,
        "max_references": 9,
        "qualities": ["2K", "4K"],
        "supports_nsfw_checker": False,
    },
    {
        "id": "flux_pro",
        "label": "GPT Image 2",
        "description": "Детальная генерация и мягкий image-to-image",
        "cost": preset_manager.get_generation_cost("flux_pro"),
        "ratios": ["auto", "1:1", "9:16", "16:9", "3:4", "4:3", "2:3"],
        "requires_reference": False,
        "max_references": 9,
        "supports_nsfw_checker": True,
    },
    {
        "id": "wan_27",
        "label": "Wan 2.7 Pro",
        "description": "Генерация и редактирование через Wan 2.7",
        "cost": preset_manager.get_generation_cost("wan_27"),
        "ratios": ["1:1", "16:9", "9:16", "4:3", "3:4", "21:9"],
        "requires_reference": False,
        "max_references": 9,
        "supports_nsfw_checker": False,
        "supports_wan_options": True,
    },
    {
        "id": "grok_imagine_i2i",
        "label": "Grok Imagine",
        "description": "I2I-сценарий для ярких переработок",
        "cost": preset_manager.get_generation_cost("grok_imagine_i2i"),
        "ratios": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"],
        "requires_reference": True,
        "max_references": 9,
        "supports_nsfw_mode": True,
    },
)


def _resolve_image_unit_cost(img_service: str, img_quality: str) -> float:
    quality_value = str(img_quality or "").strip()
    if img_service in ("banana_pro", "banana_2"):
        return QUALITY_COSTS.get(
            quality_value,
            QUALITY_COSTS.get(quality_value.upper(), preset_manager.get_generation_cost(img_service)),
        )
    if img_service == "seedream_5_pro":
        return SEEDREAM_5_PRO_QUALITY_COSTS.get(
            quality_value,
            SEEDREAM_5_PRO_QUALITY_COSTS.get(
                quality_value.upper(),
                preset_manager.get_generation_cost(img_service),
            ),
        )
    return preset_manager.get_generation_cost(img_service)

VIDEO_MODELS = (
    {
        "id": "v3_pro",
        "label": "Kling 3.0",
        "description": "Флагманский видео-режим",
        "durations": [5, 10, 15],
        "ratios": ["16:9", "9:16", "1:1"],
        "supports": ["text", "imgtxt"],
        "max_image_references": 9,
    },
    {
        "id": "v3_std",
        "label": "Kling v3",
        "description": "Быстрее и дешевле для everyday-видео",
        "durations": [5, 10, 15],
        "ratios": ["16:9", "9:16", "1:1"],
        "supports": ["text", "imgtxt"],
        "max_image_references": 9,
    },
    {
        "id": "v26_pro",
        "label": "Kling 2.5 Turbo Pro",
        "description": "Хорош для image-to-video",
        "durations": [5, 10],
        "ratios": ["16:9", "9:16", "1:1"],
        "supports": ["text", "imgtxt"],
        "supports_negative_prompt": True,
        "supports_cfg_scale": True,
        "max_image_references": 9,
    },
    {
        "id": "grok_imagine",
        "label": "Grok Imagine",
        "description": "Видео из фото с режимами Normal/Fun/Spicy",
        "durations": [6, 10, 20, 30],
        "ratios": ["16:9", "9:16", "1:1", "3:2", "2:3"],
        "supports": ["imgtxt"],
        "grok_modes": ["normal", "fun", "spicy"],
        "max_image_references": 6,
    },
    {
        "id": "grok_imagine_v15",
        "label": "Grok Imagine 1.5 NEW🔥🔥🔥",
        "description": "Видео 1-15 секунд из одного стартового фото",
        "durations": list(range(1, 16)),
        "ratios": ["auto", "16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3"],
        "supports": ["imgtxt"],
        "grok_resolutions": ["480p", "720p"],
        "max_image_references": 0,
    },
    {
        "id": "seedance_2",
        "label": "Bytedance Seedance 2.0",
        "description": "Мультимодальная видео-модель с текстом, фото и видео-рефами",
        "durations": [5, 10, 15],
        "ratios": ["16:9", "9:16", "1:1"],
        "supports": ["text", "imgtxt", "video"],
        "max_image_references": 9,
        "max_video_references": 3,
    },
    {
        "id": "gemini_omni",
        "label": "Gemini Omni",
        "description": "Единое меню для Gemini Omni Video, Audio ID и Character ID",
        "durations": [4, 6, 8, 10],
        "ratios": ["16:9", "9:16"],
        "supports": ["text", "imgtxt", "video", "audio", "character"],
        "omni_modes": ["video", "audio", "character"],
        "omni_resolutions": ["720p", "1080p", "4k"],
        "supports_omni_seed": True,
        "supports_omni_audio_ids": True,
        "supports_omni_character_ids": True,
        "supports_omni_character_audio_ids": True,
        "omni_base_voices": [
            "achernar",
            "achird",
            "algenib",
            "algieba",
            "alnilam",
            "aoede",
            "autonoe",
            "callirrhoe",
            "charon",
            "despina",
            "enceladus",
            "erinome",
            "fenrir",
            "gacrux",
            "iapetus",
            "kore",
            "laomedeia",
            "leda",
            "orus",
            "puck",
            "pulcherrima",
            "rasalgethi",
            "sadachbia",
            "sadaltager",
            "schedar",
            "sulafat",
            "umbriel",
            "vindemiatrix",
            "zephyr",
            "zubenelgenubi",
        ],
        "max_image_references": 7,
        "max_video_references": 1,
        "max_audio_references": 1,
    },
    {
        "id": "veo3_fast",
        "label": "Veo 3.1 Fast",
        "description": "Быстрый кинематографичный рендер",
        "durations": [2, 4, 6, 8, 10],
        "ratios": ["16:9", "9:16", "Auto"],
        "supports": ["text", "imgtxt"],
        "veo_generation_types": [
            "TEXT_2_VIDEO",
            "FIRST_AND_LAST_FRAMES_2_VIDEO",
            "REFERENCE_2_VIDEO",
        ],
        "veo_resolutions": ["720p", "1080p", "4k"],
        "supports_translation": True,
        "supports_seed": True,
        "supports_watermark": True,
        "max_image_references": 9,
    },
    {
        "id": "motion_control_v26",
        "label": "Kling 2.6 Motion Control",
        "description": "Перенос движения по фото персонажа и видео движения",
        "durations": [5],
        "ratios": ["1:1"],
        "supports": ["motion"],
        "motion_versions": ["2.6"],
        "motion_modes": ["720p", "1080p"],
        "max_image_references": 9,
        "max_video_references": 1,
    },
    {
        "id": "motion_control_v30",
        "label": "Kling 3.0 Motion Control",
        "description": "Обновлённая версия Motion Control для фото и видео движения",
        "durations": [5],
        "ratios": ["motion"],
        "supports": ["motion"],
        "motion_versions": ["3.0"],
        "motion_modes": ["720p", "1080p"],
        "max_image_references": 9,
        "max_video_references": 1,
    },
    {
        "id": "avatar_std",
        "label": "Kling Avatar Standard",
        "description": "Говорящий аватар по фото и аудио",
        "durations": [5],
        "ratios": ["avatar"],
        "supports": ["avatar"],
        "requires_audio": True,
        "requires_image": True,
        "max_image_references": 9,
        "max_audio_references": 1,
    },
    {
        "id": "avatar_pro",
        "label": "Kling Avatar Pro",
        "description": "Качественный говорящий аватар по фото и аудио",
        "durations": [5],
        "ratios": ["avatar"],
        "supports": ["avatar"],
        "requires_audio": True,
        "requires_image": True,
        "max_image_references": 9,
        "max_audio_references": 1,
    },
)

GEMINI_OMNI_INTERNAL_MODELS = {
    "gemini_omni_video",
    "gemini_omni_audio",
    "gemini_omni_character",
}


def _find_video_model_meta(model: str) -> dict[str, Any] | None:
    meta = next((item for item in VIDEO_MODELS if item["id"] == model), None)
    if meta:
        return meta
    if model in GEMINI_OMNI_INTERNAL_MODELS:
        return next((item for item in VIDEO_MODELS if item["id"] == "gemini_omni"), None)
    return None


def _resolve_gemini_omni_model(model: str, generation_type: str) -> str:
    if model != "gemini_omni":
        return model
    if generation_type == "audio":
        return "gemini_omni_audio"
    if generation_type == "character":
        return "gemini_omni_character"
    return "gemini_omni_video"


def _video_pricing_quality(
    model: str,
    veo_resolution: str | None = None,
    omni_resolution: str | None = None,
) -> str | None:
    key = preset_manager.normalize_video_model_key(model)
    if key.startswith("veo3"):
        return veo_resolution or "720p"
    if key == "gemini_omni_video":
        return omni_resolution or "720p"
    return None


def _clean_unique_values(values: list[Any] | None) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


def _collect_gemini_omni_images(
    image_url: str | None,
    image_references: list[str] | None,
) -> list[str]:
    return _clean_unique_values([image_url, *list(image_references or [])])


def _collect_gemini_omni_video_urls(video_references: list[str] | None) -> list[str]:
    return _clean_unique_values(video_references)


def _build_gemini_omni_video_list(
    video_references: list[str],
    duration: int,
) -> list[dict[str, Any]]:
    try:
        ends = min(20, max(1, int(duration)))
    except (TypeError, ValueError):
        ends = 10
    return [{"url": url, "start": 0, "ends": ends} for url in video_references]


def _validate_gemini_omni_video_inputs(
    *,
    image_urls: list[str],
    video_urls: list[str],
    audio_ids: list[str],
    character_ids: list[str],
) -> str | None:
    if len(video_urls) > 1:
        return "Gemini Omni принимает только один видео-референс. Удалите текущий или замените его."
    if len(audio_ids) > 1:
        return "Gemini Omni Video принимает один Audio ID за запуск."
    if len(character_ids) > 3:
        return "Gemini Omni принимает максимум 3 Character ID."
    units = len(image_urls) + len(video_urls) * 2 + len(character_ids)
    if units > 7:
        return "Слишком много входов для Gemini Omni. Лимит: фото + видео*2 + Character ID <= 7."
    return None


FILE_KIND_MAP.update({
    "image_reference": {"prefix": "image/", "fallback_ext": "png", "group": "image"},
    "video_reference": {"prefix": "video/", "fallback_ext": "mp4", "group": "video"},
    "audio_reference": {"prefix": "audio/", "fallback_ext": "mp3", "group": "audio"},
    "assistant_audio": {"prefix": "audio/", "fallback_ext": "webm", "group": "audio"},
    "trend_video_preview": {
        "prefix": "video/",
        "fallback_ext": "mp4",
        "group": "video",
        "max_bytes": MINIAPP_TREND_VIDEO_MAX_BYTES,
        "durable_reference": True,
        "source": "miniapp_trend",
    },
})


def _normalize_miniapp_upload_content_type(
    file_kind: str,
    filename: str,
    content_type: str,
    raw: bytes,
) -> str:
    """Accept iOS WebView uploads with missing/octet-stream MIME after safe sniffing."""
    declared = (content_type or "").split(";", 1)[0].strip().lower()
    config_entry = FILE_KIND_MAP[file_kind]
    expected_prefix = config_entry["prefix"]
    if declared.startswith(expected_prefix):
        return declared

    if declared not in {"", "application/octet-stream", "binary/octet-stream"}:
        return ""

    filename_mime = (mimetypes.guess_type(filename or "")[0] or "").lower()
    if filename_mime.startswith(expected_prefix):
        return filename_mime

    extension = Path(filename or "").suffix.lstrip(".").lower()
    extension_mimes = {
        "heic": "image/heic",
        "heif": "image/heif",
        "avif": "image/avif",
        "mov": "video/quicktime",
        "m4v": "video/x-m4v",
        "m4a": "audio/mp4",
    }
    extension_mime = extension_mimes.get(extension, "")
    if extension_mime.startswith(expected_prefix):
        return extension_mime

    if config_entry["group"] != "image":
        return ""

    try:
        import io

        from PIL import Image, UnidentifiedImageError

        try:
            from pillow_heif import register_heif_opener
        except ImportError:
            register_heif_opener = None
        if register_heif_opener is not None:
            register_heif_opener()

        with Image.open(io.BytesIO(raw)) as image:
            image_format = str(image.format or "").upper()
        return {
            "JPEG": "image/jpeg",
            "JPG": "image/jpeg",
            "PNG": "image/png",
            "WEBP": "image/webp",
            "GIF": "image/gif",
            "TIFF": "image/tiff",
            "AVIF": "image/avif",
            "HEIF": "image/heif",
            "HEIC": "image/heic",
        }.get(image_format, "")
    except (OSError, UnidentifiedImageError):
        return ""

MINIAPP_ASSISTANT_AUDIO_EXT_FORMATS = {
    "mp3": "mp3",
    "wav": "wav",
    "aac": "aac",
    "aiff": "aiff",
    "aif": "aiff",
    "ogg": "ogg",
    "oga": "ogg",
    "flac": "flac",
    "webm": "webm",
    "m4a": "m4a",
    "mp4": "m4a",
}


def _miniapp_assistant_audio_format(
    audio_url: str,
    content_type: str = "",
) -> tuple[str, str]:
    mime_type = (content_type or "").split(";", 1)[0].strip().lower()
    if not mime_type:
        mime_type = (mimetypes.guess_type(audio_url)[0] or "").strip().lower()

    audio_format = AI_ASSISTANT_AUDIO_FORMATS.get(mime_type, "")
    if audio_format:
        return mime_type, audio_format

    ext = Path(urlparse(audio_url).path or audio_url).suffix.lstrip(".").lower()
    audio_format = MINIAPP_ASSISTANT_AUDIO_EXT_FORMATS.get(ext, "")
    return mime_type, audio_format


def _load_miniapp_assistant_audio(
    audio_url: str,
    content_type: str = "",
) -> tuple[bytes, str, str]:
    local_path = resolve_local_upload_path(audio_url)
    if not local_path:
        raise ValueError("Аудио не найдено. Запишите или загрузите его ещё раз.")

    path = Path(local_path)
    if path.stat().st_size > config.PHOTO_PROMPT_MAX_AUDIO_BYTES:
        max_mb = max(1, config.PHOTO_PROMPT_MAX_AUDIO_BYTES // (1024 * 1024))
        raise ValueError(f"Аудио слишком большое. Максимум {max_mb}MB.")

    audio_bytes = path.read_bytes()
    if len(audio_bytes) > config.PHOTO_PROMPT_MAX_AUDIO_BYTES:
        max_mb = max(1, config.PHOTO_PROMPT_MAX_AUDIO_BYTES // (1024 * 1024))
        raise ValueError(f"Аудио слишком большое. Максимум {max_mb}MB.")

    mime_type, audio_format = _miniapp_assistant_audio_format(
        audio_url,
        content_type=content_type,
    )
    if not audio_format:
        raise ValueError("Этот аудиоформат не поддерживается. Попробуйте ogg, mp3, wav или webm.")

    return audio_bytes, mime_type, audio_format


def _resolve_miniapp_static_root() -> Path:
    """Prefer a built Next.js export when available, fallback to bundled static app.

    Use repository-relative absolute paths (based on this file location) so
    resolution does not depend on the process working directory.
    """
    base = Path(__file__).resolve().parent.parent
    candidates = [
        base / "frontend" / "miniapp-v0" / "out",
        base / "frontend" / "miniapp-v0" / "dist",
        base / "static" / "miniapp",
    ]
    for candidate in candidates:
        index_file = candidate / "index.html"
        if index_file.exists():
            return candidate
    # Fallback to repo static path (absolute) even if index missing — callers
    # will handle missing file and return correct 404. This avoids relying on
    # the current working directory.
    return base / "static" / "miniapp"


class _MessageTarget:
    """Tiny adapter so existing helpers can send messages outside updates."""

    def __init__(self, bot, telegram_id: int):
        self._bot = bot
        self.from_user = SimpleNamespace(id=telegram_id)
        self._telegram_id = telegram_id

    async def answer(self, text: str, **kwargs):
        return await self._bot.send_message(self._telegram_id, text, **kwargs)


def _validate_init_data(init_data: str, bot_token: str) -> dict[str, Any]:
    if not init_data:
        raise ValueError("Missing init_data")

    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    their_hash = parsed.pop("hash", "")
    if not their_hash:
        raise ValueError("Missing Telegram hash")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_hash, their_hash):
        raise ValueError("Invalid Telegram signature")

    auth_date = int(parsed.get("auth_date", "0") or 0)
    if not auth_date or abs(time.time() - auth_date) > 86400:
        raise ValueError("Expired Telegram session")

    user = json.loads(parsed.get("user", "{}") or "{}")
    if not user or "id" not in user:
        raise ValueError("Missing Telegram user")

    parsed["user"] = user
    return parsed


from bot.services.referral_service import (
    process_referral_click,
    referral_code_from_start_param,
)

_referral_code_from_start_param = referral_code_from_start_param


async def _activate_start_param_referral(
    app: web.Application,
    *,
    telegram_id: int,
    telegram_user: dict[str, Any],
    start_param: Any,
) -> None:
    referral_code = referral_code_from_start_param(start_param)
    if not referral_code:
        if start_param:
            logger.info(
                "Mini App referral skipped: unsupported start_param user_id=%s start_param=%s",
                telegram_id,
                start_param,
            )
        return

    try:
        logger.info(
            "Mini App referral requested: user_id=%s username=%s start_param=%s code=%s",
            telegram_id,
            telegram_user.get("username"),
            start_param,
            referral_code,
        )
        ref_result = await process_referral_click(
            telegram_id,
            referral_code,
            source="miniapp",
            start_param=str(start_param or ""),
        )
        referrer = (
            await get_user_by_referral_code(ref_result.clicked_code or referral_code)
            if ref_result.attached
            else None
        )
    except Exception:
        logger.exception(
            "Failed to activate Mini App referral for user_id=%s start_param=%s",
            telegram_id,
            start_param,
        )
        return

    if not ref_result.attached:
        logger.info(
            "Mini App referral not applied: user_id=%s username=%s start_param=%s code=%s reason=%s",
            telegram_id,
            telegram_user.get("username"),
            start_param,
            referral_code,
            ref_result.reason,
        )
        return

    if ref_result.notify_partner and referrer:
        referred = SimpleNamespace(
            id=telegram_id,
            username=telegram_user.get("username"),
            first_name=telegram_user.get("first_name"),
            last_name=telegram_user.get("last_name"),
            full_name=" ".join(
                str(telegram_user.get(key) or "").strip()
                for key in ("first_name", "last_name")
                if str(telegram_user.get(key) or "").strip()
            ),
        )
        sent = await _notify_partner_about_new_referral(
            app["bot"],
            referrer_telegram_id=referrer.telegram_id,
            referred=referred,
        )
        logger.info(
            "Mini App referral %s: user_id=%s code=%s referrer=%s",
            "notified" if sent else "skipped",
            telegram_id,
            referral_code,
            referrer.telegram_id,
        )


async def _get_user_context(app: web.Application, init_data: str, start_param_fallback: Any = None) -> tuple[int, dict]:
    payload = _validate_init_data(init_data, config.BOT_TOKEN)
    telegram_user = payload["user"]
    telegram_id = int(telegram_user["id"])
    if await is_channel_subscription_required():
        result = await check_required_channel_subscription(app["bot"], telegram_id)
        if should_block_for_subscription(result):
            raise PermissionError(
                f"Подпишитесь на @{REQUIRED_CHANNEL_USERNAME}, чтобы пользоваться ботом."
            )

    resolved_start_param = payload.get("start_param") or start_param_fallback

    # Извлекаем реферальный код из start_param до создания пользователя
    # и передаём в get_or_create_user (как в /start), чтобы привязка была атомарной
    referral_code = referral_code_from_start_param(resolved_start_param) or None
    # Проверяем, был ли у пользователя уже реферал до Mini App сессии
    # чтобы не спамить партнёру уведомлениями при каждом открытии
    _is_new_referral_visit = True
    try:
        if referral_code:
            async with db_backend.connect(DATABASE_PATH) as _db:
                _db.row_factory = db_backend.Row
                _cursor = await _db.execute(
                    "SELECT referred_by FROM users WHERE telegram_id = ? AND referred_by IS NOT NULL",
                    (telegram_id,),
                )
                if await _cursor.fetchone():
                    _is_new_referral_visit = False
    except Exception:
        _is_new_referral_visit = True

    user = await get_or_create_user(telegram_id, referral_code=referral_code)

    try:
        await update_user_profile(
            telegram_id,
            username=telegram_user.get("username"),
            first_name=telegram_user.get("first_name"),
            last_name=telegram_user.get("last_name"),
            photo_url=telegram_user.get("photo_url"),
        )
    except Exception:
        logger.exception("Unable to sync Mini App profile for %s", telegram_id)

    if not payload.get("start_param") and not start_param_fallback:
        logger.info(
            "Mini App opened without start_param: user_id=%s username=%s payload_keys=%s",
            telegram_id,
            telegram_user.get("username"),
            list(payload.keys()),
        )
    if referral_code and user.referred_by and _is_new_referral_visit:
        logger.info(
            "Mini App referral notification (new): user_id=%s code=%s referrer_id=%s",
            telegram_id,
            referral_code,
            user.referred_by,
        )
        # Уведомляем реферрера, если привязка произошла через get_or_create_user
        try:
            referrer = await get_user_by_referral_code(referral_code)
            if referrer and referrer.telegram_id != telegram_id:
                from types import SimpleNamespace
                referred_sn = SimpleNamespace(
                    id=telegram_id,
                    username=telegram_user.get("username"),
                    first_name=telegram_user.get("first_name"),
                    last_name=telegram_user.get("last_name"),
                    full_name=" ".join(
                        str(telegram_user.get(key) or "").strip()
                        for key in ("first_name", "last_name")
                        if str(telegram_user.get(key) or "").strip()
                    ),
                )
                sent = await _notify_partner_about_new_referral(
                    app["bot"],
                    referrer_telegram_id=referrer.telegram_id,
                    referred=referred_sn,
                )
                if sent:
                    logger.info(
                        "Mini App get_or_create_user referral notify: user_id=%s code=%s",
                        telegram_id, referral_code,
                    )
        except Exception:
            logger.exception(
                "Failed to notify partner about miniapp referral: user_id=%s code=%s",
                telegram_id,
                referral_code,
            )
    elif referral_code:
        logger.info(
            "Mini App referral not applied (fallback): user_id=%s code=%s",
            telegram_id,
            referral_code,
        )
        # Fallback на старый путь для уведомления
        await _activate_start_param_referral(
            app,
            telegram_id=telegram_id,
            telegram_user=telegram_user,
            start_param=resolved_start_param,
        )
    elif start_param_fallback and not payload.get("start_param"):
        logger.info(
            "Mini App start_param fallback used (no ref code): user_id=%s fallback=%s",
            telegram_id,
            start_param_fallback,
        )
    return telegram_id, {"payload": payload, "user": user}


async def _get_state(app: web.Application, telegram_id: int):
    dp = app["dp"]
    bot = app["bot"]
    return dp.fsm.get_context(bot=bot, chat_id=telegram_id, user_id=telegram_id)


def _guess_extension(filename: str, content_type: str, fallback_ext: str) -> str:
    guessed = ""
    if filename:
        guessed = Path(filename).suffix.lstrip(".").lower()
    if guessed:
        return guessed
    guessed = mimetypes.guess_extension(content_type or "") or ""
    guessed = guessed.lstrip(".").lower()
    return guessed or fallback_ext


def _task_preview(prompt: str, limit: int = 90) -> str:
    if not prompt:
        return ""
    compact = " ".join(str(prompt).split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"


def _parse_request_data(raw_value: str | None) -> dict[str, Any]:
    if not raw_value:
        return {}
    try:
        parsed = json.loads(raw_value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _task_has_source_feed(row_or_payload: Any) -> bool:
    try:
        return bool(row_or_payload["source_feed_gen_id"])
    except Exception:
        return bool(getattr(row_or_payload, "source_feed_gen_id", None))


def _task_prompt_hidden(row_or_payload: Any) -> bool:
    return _task_has_source_feed(row_or_payload)


def _task_prompt_actions_allowed(row_or_payload: Any) -> bool:
    return not _task_has_source_feed(row_or_payload)


def _browser_local_reference_urls(urls: list[str]) -> list[str]:
    """Return references that only exist inside the current browser session."""
    return [url for url in urls if url.strip().lower().startswith(("blob:", "data:"))]


def _source_image_references_from_task_payload(task_payload: dict[str, Any]) -> list[str]:
    request_data = task_payload.get("request_data") or {}
    if not isinstance(request_data, dict):
        return []

    raw_refs = request_data.get("source_reference_images")
    if not isinstance(raw_refs, list):
        raw_refs = request_data.get("reference_images", [])
    if not isinstance(raw_refs, list):
        return []

    references: list[str] = []
    for item in raw_refs:
        url = str(item or "").strip()
        if (
            url
            and url not in references
            and not is_reference_contact_sheet_url(url)
        ):
            references.append(url)
    return references


def _reference_upload_owner_telegram_id(url: str) -> int | None:
    try:
        path = urlparse(str(url or "").strip()).path
    except Exception:
        return None
    match = re.search(r"/uploads/refs/(?:image|video|audio)/(\d+)/", path)
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _filter_foreign_feed_source_references(
    source_card: dict[str, Any],
    task_payload: dict[str, Any],
    references: list[str],
    *,
    viewer_telegram_id: int | None = None,
) -> list[str]:
    if not references or source_card.get("is_mine"):
        return references

    source_references = set(_source_image_references_from_task_payload(task_payload))
    filtered: list[str] = []
    for item in references:
        url = str(item or "").strip()
        if not url or url in filtered:
            continue
        owner_telegram_id = _reference_upload_owner_telegram_id(url)
        if url in source_references:
            continue
        if (
            owner_telegram_id is not None
            and viewer_telegram_id is not None
            and owner_telegram_id != int(viewer_telegram_id)
        ):
            continue
        if (
            owner_telegram_id is None
            and source_references
            and any(url == source_url for source_url in source_references)
        ):
            continue
        if url not in filtered:
            filtered.append(url)
    return filtered


def _can_restore_private_profile_references(source_card: dict[str, Any]) -> bool:
    return bool(
        source_card.get("is_mine")
        and source_card.get("publication_scope") == "profile"
        and source_card.get("references_hidden")
    )


async def _get_repeat_source_card(
    gen_id: int,
    *,
    viewer_user_id: int,
) -> dict[str, Any] | None:
    """Resolve repeat sources published either in the feed or on a profile."""
    return await get_profile_generation_card(
        gen_id,
        viewer_user_id=viewer_user_id,
    )


def _public_result_urls(payload: dict[str, Any]) -> list[str]:
    urls = payload.get("result_urls") or []
    if isinstance(urls, str):
        try:
            urls = json.loads(urls)
        except (TypeError, json.JSONDecodeError):
            urls = []
    normalized = [str(item) for item in urls if str(item).strip()]
    result_url = payload.get("result_url")
    if result_url and result_url not in normalized:
        normalized.insert(0, result_url)
    missing = set(missing_local_upload_sources(normalized))
    return [url for url in normalized if url not in missing]


def _payload_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on", "да"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", "нет"}:
            return False
    return default


async def _miniapp_payload(request: web.Request) -> dict[str, Any]:
    cached_payload = request.get("_miniapp_payload_cache")
    if isinstance(cached_payload, dict):
        return dict(cached_payload)

    payload: dict[str, Any] = {}
    if request.can_read_body:
        try:
            raw = await request.json()
            if isinstance(raw, dict):
                payload.update(raw)
        except Exception:
            pass
    payload.update(dict(request.query))
    for key, value in request.match_info.items():
        payload.setdefault(key, value)
    if "gen_id" not in payload and "generation_id" in payload:
        payload["gen_id"] = payload["generation_id"]
    if "gen_id" not in payload and "feed_id" in payload:
        payload["gen_id"] = payload["feed_id"]
    if "prompt_id" in payload and str(payload["prompt_id"]).isdigit():
        payload["prompt_id"] = int(payload["prompt_id"])
    init_data = request.headers.get("X-Telegram-Init-Data")
    if init_data and not payload.get("init_data"):
        payload["init_data"] = init_data
    request["_miniapp_payload_cache"] = dict(payload)
    return payload


def _normalize_video_ratio(ratio: str) -> str:
    if ratio == "Auto":
        return "auto"
    return ratio or "16:9"


async def _deliver_miniapp_direct_image_result(
    app: web.Application,
    telegram_id: int,
    launch_result: dict[str, Any],
    *,
    img_service: str,
    img_ratio: str,
    unit_cost: float,
    prompt_hidden: bool,
) -> None:
    """Send Mini App direct image results to Telegram chat.

    Async webhook results are delivered by the webhook handlers. Direct provider
    results otherwise only appear in Mini App history, which makes them hard to
    save from Telegram clients.
    """
    if launch_result.get("status") != "done" or not launch_result.get("saved_url"):
        return

    saved_url = str(launch_result.get("saved_url") or "")
    task_id = str(launch_result.get("task_id") or "")
    result_bytes = launch_result.get("result_bytes")
    model_label = get_image_model_label(img_service)
    caption = (
        "✅ <b>Изображение готово</b>\n"
        f"• Модель: <code>{html.escape(str(model_label))}</code>\n"
        f"• ID: <code>{html.escape(task_id)}</code>"
    )
    if unit_cost:
        caption += f"\n• Стоимость: <code>{html.escape(str(unit_cost))}🍌</code>"
    if img_ratio:
        caption += f"\n• Формат: <code>{html.escape(str(img_ratio).replace(':', '∶'))}</code>"
    caption += "\n\n🎯 Промпт скрыт" if prompt_hidden else "\n\nСоздано через Mini App"
    if saved_url:
        caption += f"\n\n🔗 <a href='{html.escape(saved_url, quote=True)}'>Открыть оригинал</a>"

    try:
        if isinstance(result_bytes, (bytes, bytearray)):
            document = BufferedInputFile(bytes(result_bytes), filename=f"{task_id or 'generated'}.png")
        else:
            document = saved_url
        await app["bot"].send_document(
            chat_id=telegram_id,
            document=document,
            caption=caption,
            parse_mode="HTML",
            reply_markup=get_image_result_keyboard(saved_url, task_id=task_id),
        )
        logger.info(
            "Mini App direct image result delivered to Telegram: telegram_id=%s task_id=%s saved_url=%s",
            telegram_id,
            task_id,
            saved_url,
        )
    except Exception:
        logger.exception(
            "Mini App direct image Telegram delivery failed: telegram_id=%s task_id=%s saved_url=%s",
            telegram_id,
            task_id,
            saved_url,
        )


async def _notify_miniapp_image_task_queued(
    app: web.Application,
    telegram_id: int,
    launch_result: dict[str, Any],
    *,
    img_service: str,
    img_ratio: str,
    unit_cost: float,
) -> None:
    """Notify Telegram chat when a Mini App image task enters provider queue."""
    if launch_result.get("status") != "queued" or not launch_result.get("task_id"):
        return

    task_id = str(launch_result.get("task_id") or "")
    local_task_id = str(launch_result.get("local_task_id") or "")
    public_task_id = local_task_id or task_id
    model_label = get_image_model_label(img_service)
    text = (
        "⏳ <b>Задача принята в очередь</b>\n"
        f"• Модель: <code>{html.escape(str(model_label))}</code>\n"
        f"• ID: <code>{html.escape(public_task_id)}</code>"
    )
    if task_id and task_id != public_task_id:
        text += f"\n• ID провайдера: <code>{html.escape(task_id)}</code>"
    if unit_cost:
        text += f"\n• Стоимость: <code>{html.escape(str(unit_cost))}🍌</code>"
    if img_ratio:
        text += f"\n• Формат: <code>{html.escape(str(img_ratio).replace(':', '∶'))}</code>"
    text += "\n\nКогда файл будет готов, я пришлю его сюда."

    try:
        await app["bot"].send_message(
            chat_id=telegram_id,
            text=text,
            parse_mode="HTML",
        )
        logger.info(
            "Mini App queued image task notified: telegram_id=%s task_id=%s local_task_id=%s",
            telegram_id,
            task_id,
            local_task_id,
        )
    except Exception:
        logger.exception(
            "Mini App queued image task notification failed: telegram_id=%s task_id=%s local_task_id=%s",
            telegram_id,
            task_id,
            local_task_id,
        )


async def _fetch_recent_tasks(telegram_id: int, limit: int = 8) -> list[dict[str, Any]]:
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT id, task_id, type, model, duration, aspect_ratio, prompt, cost, status,
                   result_url, result_urls, is_public_feed, is_prompt_library,
               source_feed_gen_id, feed_prompt_visible, feed_references_visible,
               feed_blurred, is_profile_visible, is_adult_content, created_at
            FROM generation_tasks
            WHERE telegram_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (telegram_id, limit),
        )
        rows = await cursor.fetchall()

    tasks: list[dict[str, Any]] = []
    for row in rows:
        task_type = row["type"] or "image"
        model = row["model"] or ""
        result_urls = _public_result_urls(dict(row))
        label = (
            get_image_model_label(model)
            if task_type == "image"
            else get_video_model_label(model)
        )
        tasks.append(
            {
                "task_id": row["task_id"],
                "type": task_type,
                "model": model,
                "model_label": label,
                "duration": row["duration"],
                "aspect_ratio": row["aspect_ratio"] or "",
                "status": row["status"] or "pending",
                "result_url": result_urls[0] if result_urls else None,
                "result_urls": result_urls,
                "created_at": row["created_at"],
                "prompt_preview": "" if _task_prompt_hidden(row) else _task_preview(row["prompt"]),
                "prompt_hidden": _task_prompt_hidden(row),
                "prompt_actions_allowed": _task_prompt_actions_allowed(row),
                "is_public_feed": bool(row["is_public_feed"]),
                "is_prompt_library": bool(row["is_prompt_library"]),
                "feed_prompt_visible": bool(row["feed_prompt_visible"]) if "feed_prompt_visible" in row.keys() else False,
                "feed_references_visible": bool(row["feed_references_visible"]) if "feed_references_visible" in row.keys() else False,
                "feed_blurred": bool(row["feed_blurred"]) if "feed_blurred" in row.keys() else False,
                "is_profile_visible": generation_profile_visible(row),
                "is_adult_content": generation_adult_content(row),
                "publication_scope": generation_publication_scope(row),
                "feed_interactions_enabled": generation_publication_scope(row) == "feed",
                "feed_id": row["id"],
                "cost": row["cost"] or 0,
            }
        )
    return tasks


async def _fetch_task_detail(telegram_id: int, task_id: str) -> dict[str, Any] | None:
    lookup_value = str(task_id or "").strip()
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT id, task_id, type, model, duration, aspect_ratio, prompt, cost, status,
                   result_url, result_urls, is_public_feed, is_prompt_library,
                   source_feed_gen_id, feed_prompt_visible, feed_references_visible,
                   feed_blurred, is_profile_visible, is_adult_content, created_at, request_data
            FROM generation_tasks
            WHERE telegram_id = ? AND task_id = ?
            LIMIT 1
            """,
            (telegram_id, lookup_value),
        )
        row = await cursor.fetchone()
        if not row and lookup_value.isdigit():
            cursor = await db.execute(
                """
                SELECT id, task_id, type, model, duration, aspect_ratio, prompt, cost, status,
                       result_url, result_urls, is_public_feed, is_prompt_library,
                       source_feed_gen_id, feed_prompt_visible, feed_references_visible,
                       feed_blurred, is_profile_visible, is_adult_content, created_at, request_data
                FROM generation_tasks
                WHERE telegram_id = ? AND id = ?
                LIMIT 1
                """,
                (telegram_id, int(lookup_value)),
            )
            row = await cursor.fetchone()
        if not row and lookup_value:
            cursor = await db.execute(
                """
                SELECT id, task_id, type, model, duration, aspect_ratio, prompt, cost, status,
                       result_url, result_urls, is_public_feed, is_prompt_library,
                       source_feed_gen_id, feed_prompt_visible, feed_references_visible,
                       feed_blurred, is_profile_visible, is_adult_content, created_at, request_data
                FROM generation_tasks
                WHERE telegram_id = ?
                  AND EXISTS (
                      SELECT 1
                      FROM json_each(
                          CASE
                              WHEN json_valid(generation_tasks.request_data)
                              THEN generation_tasks.request_data
                              ELSE '{}'
                          END,
                          '$.task_id_aliases'
                      )
                      WHERE CAST(value AS TEXT) = ?
                  )
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (telegram_id, lookup_value),
            )
            row = await cursor.fetchone()

    if not row:
        return None

    task_type = row["type"] or "image"
    model = row["model"] or ""
    request_data = _parse_request_data(row["request_data"])
    result_urls = _public_result_urls(dict(row))
    model_label = (
        get_image_model_label(model)
        if task_type == "image"
        else get_video_model_label(model)
    )
    return {
        "task_id": row["task_id"],
        "feed_id": row["id"],
        "type": task_type,
        "model": model,
        "model_label": model_label,
        "duration": row["duration"],
        "aspect_ratio": row["aspect_ratio"] or "",
        "prompt": "" if _task_prompt_hidden(row) else (row["prompt"] or ""),
        "prompt_hidden": _task_prompt_hidden(row),
        "prompt_actions_allowed": _task_prompt_actions_allowed(row),
        "cost": row["cost"] or 0,
        "status": row["status"] or "pending",
        "result_url": result_urls[0] if result_urls else None,
        "result_urls": result_urls,
        "is_public_feed": bool(row["is_public_feed"]),
        "is_prompt_library": bool(row["is_prompt_library"]),
        "feed_prompt_visible": bool(row["feed_prompt_visible"]) if "feed_prompt_visible" in row.keys() else False,
        "feed_references_visible": bool(row["feed_references_visible"]) if "feed_references_visible" in row.keys() else False,
        "feed_blurred": bool(row["feed_blurred"]) if "feed_blurred" in row.keys() else False,
        "is_profile_visible": generation_profile_visible(row),
        "is_adult_content": generation_adult_content(row),
        "publication_scope": generation_publication_scope(row),
        "feed_interactions_enabled": generation_publication_scope(row) == "feed",
        "created_at": row["created_at"],
        "request_data": request_data,
    }


def _classify_video_generation_result(result: Any) -> tuple[str, str | None]:
    if isinstance(result, dict):
        if result.get("status") == "done" and result.get("asset_id"):
            return "done", None
        if result.get("task_id"):
            return "queued", None
        return "failed", make_user_friendly_generation_error(
            result.get("message") or result.get("error") or str(result)
        )
    if isinstance(result, (bytes, bytearray)):
        return "done", None
    if result:
        return "failed", make_user_friendly_generation_error(
            f"Unexpected result type: {type(result).__name__}"
        )
    return "failed", None


def _derive_miniapp_asset_name(text: str, fallback: str) -> str:
    value = " ".join(str(text or "").strip().split())
    value = "".join(ch for ch in value if ch.isalnum() or ch in {" ", ".", "-", "_"})
    return (value[:20] or fallback)[:20]


async def _launch_video_generation_task(
    *,
    telegram_id: int,
    user,
    model: str,
    prompt: str,
    duration: int,
    aspect_ratio: str,
    generation_type: str,
    image_url: str | None,
    image_references: list[str],
    video_references: list[str],
    audio_url: str | None = None,
    grok_mode: str = "normal",
    grok_resolution: str = "480p",
    veo_generation_type: str = "TEXT_2_VIDEO",
    veo_translation: bool = True,
    veo_resolution: str = "720p",
    veo_seed: int | None = None,
    veo_watermark: str | None = None,
    kling_negative_prompt: str | None = None,
    kling_cfg_scale: float | None = None,
    omni_resolution: str = "720p",
    omni_seed: int | None = None,
    omni_audio_ids: list[str] | None = None,
    omni_character_ids: list[str] | None = None,
    omni_base_voice: str = "achernar",
    omni_voice_name: str | None = None,
    omni_voice_description: str | None = None,
    omni_example_dialogue: str | None = None,
    omni_character_name: str | None = None,
    omni_character_audio_ids: list[str] | None = None,
    source_feed_gen_id: int | None = None,
    parent_generation_id: int | None = None,
    action_type: str | None = None,
) -> dict[str, Any]:
    from bot.services.gemini_omni_service import gemini_omni_service
    from bot.services.grok_service import grok_service
    from bot.services.kling_service import kling_service
    from bot.services.seedance_service import seedance_service
    from bot.services.veo_service import veo_service

    normalized_ratio = _normalize_video_ratio(aspect_ratio)
    callback_url = config.kling_notification_url if config.WEBHOOK_HOST else None
    if model == "gemini_omni_video":
        image_references = _clean_unique_values(image_references)
        video_references = _clean_unique_values(video_references)
    else:
        image_references = normalize_reference_urls(
            image_references,
            max_count=get_max_video_image_references(model),
        )
        video_references = normalize_reference_urls(
            video_references,
            max_count=get_max_video_references(model),
        )

    if model == "gemini_omni_video":
        omni_images = _collect_gemini_omni_images(image_url, image_references)
        omni_video_list = _build_gemini_omni_video_list(video_references, duration)
        result = await gemini_omni_service.generate_video(
            prompt=prompt,
            duration=duration,
            aspect_ratio=normalized_ratio,
            resolution=omni_resolution,
            image_urls=omni_images or None,
            audio_ids=omni_audio_ids or None,
            video_list=omni_video_list or None,
            character_ids=omni_character_ids or None,
            seed=omni_seed,
            callBackUrl=(config.kie_notification_url if config.WEBHOOK_HOST else None),
        )
    elif model == "gemini_omni_audio":
        audio_name = omni_voice_name or _derive_miniapp_asset_name(prompt, "Omni Voice")
        result = await gemini_omni_service.create_audio(
            audio_id=omni_base_voice,
            name=audio_name,
            voice_description=omni_voice_description or prompt,
            example_dialogue=omni_example_dialogue or "",
        )
    elif model == "gemini_omni_character":
        character_name = omni_character_name or _derive_miniapp_asset_name(
            prompt,
            "Character",
        )
        character_images = [image_url] if image_url else []
        result = await gemini_omni_service.create_character(
            description=prompt,
            image_urls=character_images,
            character_name=character_name,
            audio_ids=omni_character_audio_ids or None,
        )
    elif model in {"avatar_std", "avatar_pro"}:
        result = await kling_service.generate_video(
            prompt=prompt,
            model=model,
            duration=duration,
            aspect_ratio=normalized_ratio,
            image_url=image_url,
            video_urls=[audio_url] if audio_url else [],
            webhook_url=callback_url,
        )
    elif model == "motion_control_v26":
        result = await kling_service.generate_video(
            prompt=prompt,
            model=model,
            duration=duration,
            aspect_ratio=normalized_ratio,
            image_url=image_url,
            video_urls=video_references[:1],
            webhook_url=callback_url,
        )
    elif model == "grok_imagine":
        result = await grok_service.generate_image_to_video(
            image_urls=([image_url] if image_url else []) + image_references[:6],
            prompt=prompt,
            mode=grok_mode,
            duration=duration,
            resolution="720p",
            aspect_ratio=normalized_ratio,
            callBackUrl=(config.kie_notification_url if config.WEBHOOK_HOST else None),
        )
    elif model == "grok_imagine_v15":
        result = await grok_service.generate_image_to_video_v15(
            image_urls=[image_url] if image_url else [],
            prompt=prompt,
            duration=duration,
            resolution=grok_resolution,
            aspect_ratio=normalized_ratio,
            callBackUrl=(config.kie_notification_url if config.WEBHOOK_HOST else None),
        )
    elif model == "seedance_2":
        seedance_reference_images: list[str] = []
        seedance_reference_videos = video_references
        if generation_type == "imgtxt" and image_url:
            if image_references or seedance_reference_videos:
                seedance_reference_images.append(image_url)
                for ref_url in image_references:
                    if ref_url and ref_url not in seedance_reference_images:
                        seedance_reference_images.append(ref_url)
            result = await seedance_service.generate_video(
                prompt=prompt,
                duration=duration,
                aspect_ratio=normalized_ratio,
                resolution="720p",
                generate_audio=True,
                first_frame_url=image_url
                if not (image_references or seedance_reference_videos)
                else None,
                reference_image_urls=seedance_reference_images
                if (image_references or seedance_reference_videos)
                else None,
                reference_video_urls=seedance_reference_videos or None,
                callBackUrl=(config.kie_notification_url if config.WEBHOOK_HOST else None),
            )
        else:
            if image_url:
                seedance_reference_images.append(image_url)
            for ref_url in image_references:
                if ref_url and ref_url not in seedance_reference_images:
                    seedance_reference_images.append(ref_url)
            result = await seedance_service.generate_video(
                prompt=prompt,
                duration=duration,
                aspect_ratio=normalized_ratio,
                resolution="720p",
                generate_audio=True,
                reference_image_urls=seedance_reference_images or None,
                reference_video_urls=seedance_reference_videos or None,
                callBackUrl=(config.kie_notification_url if config.WEBHOOK_HOST else None),
            )
    elif model.startswith("veo3"):
        veo_image_urls = []
        generation_mode = "TEXT_2_VIDEO"
        if generation_type == "imgtxt":
            generation_mode = "FIRST_AND_LAST_FRAMES_2_VIDEO"
            if image_url:
                veo_image_urls.append(image_url)
            for ref_url in image_references:
                if ref_url not in veo_image_urls:
                    veo_image_urls.append(ref_url)
                if len(veo_image_urls) >= 2:
                    break
        result = await veo_service.generate_video(
            prompt=prompt,
            model=model,
            duration=duration,
            generation_type=veo_generation_type or generation_mode,
            image_urls=veo_image_urls or None,
            aspect_ratio=normalized_ratio,
            enable_translation=veo_translation,
            watermark=veo_watermark,
            resolution=veo_resolution or "720p",
            seeds=veo_seed,
            callBackUrl=(config.kie_notification_url if config.WEBHOOK_HOST else None),
        )
    else:
        result = await kling_service.generate_video(
            prompt=prompt,
            model=model,
            duration=duration,
            aspect_ratio=normalized_ratio,
            image_url=image_url,
            video_urls=video_references if generation_type == "video" else None,
            image_input=(
                image_references
                if generation_type != "imgtxt" or len(image_references) < 2
                else None
            ),
            elements=(
                [
                    {
                        "description": "reference photos for video generation consistency and style",
                        "reference_image_urls": image_references[:12],
                    }
                ]
                if generation_type == "imgtxt" and len(image_references) >= 2
                else None
            ),
            negative_prompt=kling_negative_prompt,
            cfg_scale=kling_cfg_scale,
            webhook_url=callback_url,
        )

    result_status, error_message = _classify_video_generation_result(result)
    pricing_quality = _video_pricing_quality(model, veo_resolution, omni_resolution)
    cost = preset_manager.get_video_cost_with_quality(model, duration, pricing_quality)
    cost = apply_video_reference_cost(model, cost, video_references)
    task_type = (
        "audio"
        if model == "gemini_omni_audio"
        else "character" if model == "gemini_omni_character" else "video"
    )

    if result_status == "queued":
        await add_generation_task(
            user.id,
            telegram_id,
            result["task_id"],
            task_type,
            "miniapp_video",
            model=model,
            duration=duration,
            aspect_ratio=normalized_ratio,
            prompt=prompt,
            cost=cost,
            request_data={
                "source": "miniapp",
                "v_type": generation_type,
                "v_model": model,
                "v_image_url": image_url,
                "reference_images": image_references,
                "v_reference_videos": video_references,
                "audio_url": audio_url,
                "grok_mode": grok_mode,
                "grok_resolution": (
                    grok_resolution if model == "grok_imagine_v15" else ""
                ),
                "resolution": (
                    grok_resolution
                    if model == "grok_imagine_v15"
                    else "720p" if model == "grok_imagine" else ""
                ),
                "veo_generation_type": veo_generation_type,
                "veo_translation": veo_translation,
                "veo_resolution": veo_resolution,
                "veo_seed": veo_seed,
                "veo_watermark": veo_watermark,
                "kling_negative_prompt": kling_negative_prompt,
                "kling_cfg_scale": kling_cfg_scale,
                "omni_resolution": omni_resolution,
                "omni_seed": omni_seed,
                "omni_audio_ids": omni_audio_ids or [],
                "omni_character_ids": omni_character_ids or [],
                "omni_base_voice": omni_base_voice,
                "omni_voice_name": omni_voice_name,
                "omni_voice_description": omni_voice_description,
                "omni_example_dialogue": omni_example_dialogue,
                "omni_character_name": omni_character_name,
                "omni_character_audio_ids": omni_character_audio_ids or [],
                "source_feed_gen_id": source_feed_gen_id,
                "parent_generation_id": parent_generation_id,
                "action_type": action_type,
            },
            source_feed_gen_id=source_feed_gen_id,
            parent_generation_id=parent_generation_id,
            action_type=action_type,
        )
        return {
            "status": "queued",
            "task_id": result["task_id"],
            "cost": cost,
            "task_type": task_type,
        }

    if (
        result_status == "done"
        and isinstance(result, dict)
        and result.get("asset_id")
    ):
        asset_id = str(result["asset_id"])
        await add_generation_task(
            user.id,
            telegram_id,
            asset_id,
            task_type,
            "miniapp_video",
            model=model,
            duration=duration,
            aspect_ratio=normalized_ratio,
            prompt=prompt,
            cost=cost,
            request_data={
                "source": "miniapp",
                "v_type": generation_type,
                "v_model": model,
                "asset_kind": result.get("asset_kind"),
                "asset_id": asset_id,
                "v_image_url": image_url,
                "reference_images": image_references,
                "audio_url": audio_url,
                "omni_base_voice": omni_base_voice,
                "omni_voice_name": omni_voice_name,
                "omni_voice_description": omni_voice_description,
                "omni_example_dialogue": omni_example_dialogue,
                "omni_character_name": omni_character_name,
                "omni_character_audio_ids": omni_character_audio_ids or [],
                "source_feed_gen_id": source_feed_gen_id,
                "parent_generation_id": parent_generation_id,
                "action_type": action_type,
            },
            source_feed_gen_id=source_feed_gen_id,
            parent_generation_id=parent_generation_id,
            action_type=action_type,
        )
        await complete_video_task(asset_id, asset_id)
        return {
            "status": "done",
            "task_id": asset_id,
            "saved_url": asset_id,
            "cost": cost,
            "task_type": task_type,
        }

    local_task_id = f"miniapp_video_{int(time.time() * 1000)}_{telegram_id}"
    await add_generation_task(
        user.id,
        telegram_id,
        local_task_id,
        task_type,
        "miniapp_video",
        model=model,
        duration=duration,
        aspect_ratio=normalized_ratio,
        prompt=prompt,
        cost=cost,
        request_data={
            "source": "miniapp",
            "v_type": generation_type,
            "v_model": model,
            "v_image_url": image_url,
            "reference_images": image_references,
            "v_reference_videos": video_references,
            "audio_url": audio_url,
            "grok_mode": grok_mode,
            "grok_resolution": (
                grok_resolution if model == "grok_imagine_v15" else ""
            ),
            "resolution": (
                grok_resolution
                if model == "grok_imagine_v15"
                else "720p" if model == "grok_imagine" else ""
            ),
            "veo_generation_type": veo_generation_type,
            "veo_translation": veo_translation,
            "veo_resolution": veo_resolution,
            "veo_seed": veo_seed,
            "veo_watermark": veo_watermark,
            "kling_negative_prompt": kling_negative_prompt,
            "kling_cfg_scale": kling_cfg_scale,
            "omni_resolution": omni_resolution,
            "omni_seed": omni_seed,
            "omni_audio_ids": omni_audio_ids or [],
            "omni_character_ids": omni_character_ids or [],
            "source_feed_gen_id": source_feed_gen_id,
            "parent_generation_id": parent_generation_id,
            "action_type": action_type,
        },
        source_feed_gen_id=source_feed_gen_id,
        parent_generation_id=parent_generation_id,
        action_type=action_type,
    )

    if result_status == "done":
        saved_url = save_uploaded_file(bytes(result), "mp4")
        await complete_video_task(local_task_id, saved_url)
        return {
            "status": "done",
            "task_id": local_task_id,
            "saved_url": saved_url,
            "cost": cost,
            "task_type": task_type,
        }

    await complete_video_task(local_task_id, None)
    return {
        "status": "failed",
        "task_id": local_task_id,
        "error": error_message or "Не удалось создать видео задачу",
        "cost": cost,
        "task_type": task_type,
    }


async def _send_main_menu(app: web.Application, telegram_id: int):
    user = await get_or_create_user(telegram_id)
    text = _build_main_menu_text(user.credits)
    await app["bot"].send_message(
        telegram_id,
        text,
        reply_markup=get_main_menu_keyboard(user.credits, telegram_id),
        parse_mode="HTML",
    )


async def _send_create_hub(app: web.Application, telegram_id: int):
    user = await get_or_create_user(telegram_id)
    text = (
        "✨ <b>Создать</b>\n"
        f"🍌 Баланс: <code>{user.credits}</code> бананов\n\n"
        "Выберите, что хотите получить. Можно использовать готовый сценарий "
        "или открыть пошаговый режим."
    )
    await app["bot"].send_message(
        telegram_id,
        text,
        reply_markup=get_create_hub_keyboard(),
        parse_mode="HTML",
    )


async def _send_edit_hub(app: web.Application, telegram_id: int):
    user = await get_or_create_user(telegram_id)
    text = (
        "✏️ <b>Изменить фото</b>\n"
        f"🍌 Баланс: <code>{user.credits}</code> бананов\n\n"
        "Здесь можно поменять стиль, фон, одежду, детали или настроение кадра.\n"
        "Сначала выберите сценарий ниже."
    )
    await app["bot"].send_message(
        telegram_id,
        text,
        reply_markup=get_edit_hub_keyboard(),
        parse_mode="HTML",
    )


async def _send_animate_hub(app: web.Application, telegram_id: int):
    user = await get_or_create_user(telegram_id)
    text = (
        "🎬 <b>Оживить</b>\n"
        f"🍌 Баланс: <code>{user.credits}</code> бананов\n\n"
        "Выберите, как хотите сделать видео:\n"
        "• оживить фото\n"
        "• перенести движение\n"
        "• использовать видео-референсы"
    )
    await app["bot"].send_message(
        telegram_id,
        text,
        reply_markup=get_animate_hub_keyboard(),
        parse_mode="HTML",
    )


async def _send_more_menu(app: web.Application, telegram_id: int):
    user = await get_or_create_user(telegram_id)
    text = (
        "⋯ <b>Ещё</b>\n"
        f"🍌 Баланс: <code>{user.credits}</code> бананов\n\n"
        "Здесь находятся баланс, история, помощь, поддержка и партнёрская программа."
    )
    await app["bot"].send_message(
        telegram_id,
        text,
        reply_markup=get_more_menu_keyboard(),
        parse_mode="HTML",
    )


async def _send_create_image(app: web.Application, telegram_id: int):
    state = await _get_state(app, telegram_id)
    await state.clear()
    await state.update_data(
        generation_type="image",
        img_service="banana_pro",
        img_ratio="1:1",
        img_count=1,
        img_quality="2K",
        img_nsfw_checker=False,
        reference_images=[],
        img_flow_step="select_model",
        preset_id="new",
    )
    await _show_image_model_selection_screen(
        _MessageTarget(app["bot"], telegram_id), state, edit=False
    )


async def _send_create_video(app: web.Application, telegram_id: int):
    state = await _get_state(app, telegram_id)
    await state.clear()
    await _init_default_video_state(
        state, v_model="v3_pro", v_duration=5, v_ratio="16:9"
    )
    await state.update_data(video_flow_step="select_model")
    await _show_video_model_selection_screen(
        _MessageTarget(app["bot"], telegram_id), state, edit=False
    )


async def _send_photo_prompt(app: web.Application, telegram_id: int):
    state = await _get_state(app, telegram_id)
    await state.clear()
    await state.set_state(ImageAnalyzerStates.waiting_for_photo)
    user = await get_or_create_user(telegram_id)
    text = (
        "📸 <b>Анализ фото -> Промпт</b>\n"
        f"🍌 Баланс: <code>{user.credits}</code> бананов\n\n"
        "<b>Что делает этот режим</b>\n"
        "Отправьте фото, и бот соберёт по нему аккуратный промпт для дальнейшей генерации.\n\n"
        "Обычно хорошо распознаются:\n"
        "• персонажи, лица и одежда\n"
        "• поза, композиция и ракурс\n"
        "• свет, фон и общее настроение\n\n"
        "<i>Анализ бесплатный.</i>"
    )
    await app["bot"].send_message(
        telegram_id,
        text,
        reply_markup=get_main_menu_button_keyboard(),
        parse_mode="HTML",
    )


async def _send_balance(app: web.Application, telegram_id: int):
    user = await get_or_create_user(telegram_id)
    stats = await get_user_stats(telegram_id)
    await app["bot"].send_message(
        telegram_id,
        _build_balance_text(stats),
        reply_markup=get_balance_keyboard(user.credits),
        parse_mode="HTML",
    )


async def _send_topup(app: web.Application, telegram_id: int):
    packages = preset_manager.get_packages()
    text = (
        "🍌 <b>Пополнение баланса</b>\n\n"
        "Оплата выполняется через CryptoBot.\n"
        "Выберите пакет бананов ниже.\n\n"
        "<i>Чем больше пакет, тем выгоднее цена за банан.</i>"
    )
    await app["bot"].send_message(
        telegram_id,
        text,
        reply_markup=get_payment_packages_keyboard(packages),
        parse_mode="HTML",
    )


async def _send_support(app: web.Application, telegram_id: int):
    text = (
        "🆘 <b>Поддержка</b>\n\n"
        "Можно написать прямо сюда — AI-ассистент поможет с:\n"
        "• генерацией изображений и видео\n"
        "• выбором модели и настроек\n"
        "• оплатой и балансом\n"
        "• любыми непонятными шагами в боте\n\n"
        "<b>Если нужен человек:</b>\n"
        "@only_tany"
    )
    await app["bot"].send_message(
        telegram_id,
        text,
        reply_markup=get_support_keyboard(),
        parse_mode="HTML",
    )


async def _send_ai_assistant(app: web.Application, telegram_id: int):
    state = await _get_state(app, telegram_id)
    await state.clear()
    await state.set_state(AIAssistantStates.waiting_for_message)
    await state.update_data(ai_mode="main_menu")
    text = """🍌 <b>AI-ассистент</b>

Я помогу с моделями, промптами, настройками и сценариями генерации.

<b>Например, можно спросить:</b>
• какая модель лучше для фотореализма
• что выбрать для видео из фото
• как использовать референсы
• как собрать промпт под fashion / anime / product
• чем отличается Veo от Kling
• как работает Motion Control

<i>Просто напишите вопрос — отвечу по делу и подскажу следующий шаг в боте.</i>"""
    await app["bot"].send_message(
        telegram_id,
        text,
        reply_markup=get_ai_assistant_keyboard(),
        parse_mode="HTML",
    )


async def _send_history(app: web.Application, telegram_id: int):
    user = await get_or_create_user(telegram_id)
    stats = await get_user_stats(telegram_id)
    text = (
        "📋 <b>История</b>\n\n"
        f"• Всего генераций: <code>{stats['generations']}</code>\n"
        f"• Потрачено бананов: <code>{stats['total_spent']}</code>\n"
        f"• Текущий баланс: <code>{user.credits}</code>🍌\n"
        f"• Дата регистрации: <code>{stats['member_since']}</code>\n\n"
        "<i>Подробная история запусков появится здесь чуть позже.</i>"
    )
    await app["bot"].send_message(
        telegram_id,
        text,
        reply_markup=get_main_menu_keyboard(user.credits, telegram_id),
        parse_mode="HTML",
    )


async def _send_batch_edit(app: web.Application, telegram_id: int):
    from bot.handlers.batch_generation import get_batch_upload_keyboard

    state = await _get_state(app, telegram_id)
    await state.clear()
    await state.update_data(
        batch_mode="reference_edit",
        main_image=None,
        reference_images=[],
    )
    from bot.states import GenerationStates

    await state.set_state(GenerationStates.waiting_for_batch_image)
    user_credits = (await get_or_create_user(telegram_id)).credits
    text = (
        "🎨 <b>Редактирование по референсам</b>\n"
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов\n\n"
        "1. Загрузите <b>главное фото</b> для редактирования\n"
        "2. Добавьте до <b>14 референсов</b>\n"
        "3. Введите промпт\n"
        "4. Получите результат с учётом исходников\n\n"
        "💰 Стоимость: <b>4🍌</b>\n"
        "<i>📸 Отправьте главное фото для редактирования.</i>"
    )
    await app["bot"].send_message(
        telegram_id,
        text,
        reply_markup=get_batch_upload_keyboard(),
        parse_mode="HTML",
    )


async def _send_partner(app: web.Application, telegram_id: int):
    stats = await get_partner_overview(telegram_id)
    user = await get_or_create_user(telegram_id)
    me = await app["bot"].get_me()
    referral_link = (
        build_referral_link(me.username, user.referral_code)
        if user.referral_code
        else ""
    )
    text = (
        "🤝 <b>Партнёрская программа</b>\n\n"
        f"• Рефералов: <code>{stats.get('referrals_count', 0)}</code>\n"
        f"• Повторы prompt: <code>{stats.get('prompt_repeat_balance_rub', 0)}</code> ₽\n"
        f"• Баланс партнёра: <code>{stats.get('balance_rub', 0)}</code> ₽\n"
        f"• Статус: <code>{'partner' if stats.get('is_partner') else 'basic'}</code>\n\n"
        "<i>Ниже доступны оферта, статистика, вывод и ваша ссылка.</i>"
    )
    await app["bot"].send_message(
        telegram_id,
        text,
        reply_markup=get_partner_program_keyboard(
            referral_link, is_partner=stats.get("is_partner", False)
        ),
        parse_mode="HTML",
    )


async def _send_admin(app: web.Application, telegram_id: int):
    from bot.database import get_admin_stats
    from bot.keyboards import get_admin_keyboard

    if not config.is_admin(telegram_id):
        await app["bot"].send_message(
            telegram_id,
            "⛔ У вас нет доступа к админ-панели.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return

    stats = await get_admin_stats()
    text = f"""
🔧 <b>Админ-панель</b>

📊 <b>Статистика:</b>
• Пользователей: <code>{stats['total_users']}</code>
• Генераций: <code>{stats['total_generations']}</code>
• Транзакций: <code>{stats['total_transactions']}</code>
• Выручка: <code>{stats['total_revenue']:.0f}</code> ₽

Выберите действие:
"""
    await app["bot"].send_message(
        telegram_id,
        text,
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML",
    )


ACTIONS = {
    "open_main_menu": _send_main_menu,
    "open_create_hub": _send_create_hub,
    "open_edit_hub": _send_edit_hub,
    "open_animate_hub": _send_animate_hub,
    "open_more_menu": _send_more_menu,
    "create_image": _send_create_image,
    "create_video": _send_create_video,
    "photo_prompt": _send_photo_prompt,
    "show_balance": _send_balance,
    "show_topup": _send_topup,
    "show_support": _send_support,
    "show_ai_assistant": _send_ai_assistant,
    "show_history": _send_history,
    "open_batch_edit": _send_batch_edit,
    "show_partner": _send_partner,
    "show_admin": _send_admin,
}


async def miniapp_index(request: web.Request) -> web.Response:
    root = _resolve_miniapp_static_root()
    index_path = root / "index.html"
    logger.info(
        "Miniapp index requested, query_string=%s resolved static root=%s index_exists=%s",
        str(request.query_string),
        str(root),
        str(index_path.exists()),
    )
    response: web.StreamResponse
    try:
        me = await request.app["bot"].get_me()
        runtime_config = {
            "botUsername": str(me.username or ""),
            "miniAppUrl": config.mini_app_url,
        }
        snapshot_script = (
            '<script id="miniapp-snapshot">'
            '(function(){'
            '  var h=location.href,s=location.search,ha=location.hash;'
            '  window.__BANANO_INITIAL_LAUNCH__={href:h,search:s,hash:ha};'
            '  try{'
            '    window.sessionStorage.setItem("__banano_initial_href",h);'
            '    window.sessionStorage.setItem("__banano_initial_search",s);'
            '    window.sessionStorage.setItem("__banano_initial_hash",ha);'
            '  }catch(e){}'
            '})();'
            '</script>'
        )
        debug_script = (
            '<script id="miniapp-debug-log">'
            'console.log("MINIAPP_DEBUG_URL:", window.location.href);'
            'console.log("MINIAPP_DEBUG_REFERRER:", document.referrer);'
            'console.log("MINIAPP_DEBUG_HASH:", window.location.hash);'
            'console.log("MINIAPP_DEBUG_SEARCH:", window.location.search);'
            'console.log("MINIAPP_DEBUG_TG:", typeof window.Telegram !== "undefined" ? !!window.Telegram.WebApp : "no TG");'
            'if (window.Telegram?.WebApp?.initDataUnsafe) {'
            '  console.log("MINIAPP_DEBUG_INITDATA_UNSAFE:", JSON.stringify(window.Telegram.WebApp.initDataUnsafe));'
            '}'
            'try{sessionStorage.setItem("miniapp_debug_url",window.location.href)}catch(e){}'
            '</script>'
        )
        watchdog_script = (
            '<script id="miniapp-bootstrap-watchdog">'
            '(function(){'
            '  function clientLog(event, extra){'
            '    try{'
            '      var tg=window.Telegram;'
            '      var wa=tg&&tg.WebApp;'
            '      var payload=Object.assign({'
            '        event:event,'
            '        href:String((window.location.pathname||"")+(window.location.search||"")),'
            '        search:String(window.location.search||""),'
            '        hash_len:String(window.location.hash||"").length,'
            '        has_tg:!!tg,'
            '        has_webapp:!!wa,'
            '        init_data_len:wa&&wa.initData?String(wa.initData).length:0'
            '      },extra||{});'
            '      var body=JSON.stringify(payload);'
            '      if(navigator.sendBeacon){'
            '        var blob=new Blob([body],{type:"application/json"});'
            '        if(navigator.sendBeacon("/mini-app/api/client-log",blob)){return;}'
            '      }'
            '      if(window.fetch){fetch("/mini-app/api/client-log",{method:"POST",headers:{"Content-Type":"application/json"},body:body,keepalive:true}).catch(function(){});}'
            '    }catch(e){}'
            '  }'
            '  clientLog("index-loaded");'
            '  window.addEventListener("error",function(e){clientLog("window-error",{message:String(e.message||""),source:String(e.filename||""),lineno:e.lineno||0,colno:e.colno||0});});'
            '  window.addEventListener("unhandledrejection",function(e){clientLog("unhandledrejection",{message:String((e.reason&&e.reason.message)||e.reason||"")});});'
            '  var started=false;'
            '  var rawFetch=window.fetch;'
            '  if(typeof rawFetch==="function"){'
            '    window.fetch=function(input,init){'
            '      try{'
            '        var url=typeof input==="string"?input:(input&&input.url)||"";'
            '        if(String(url).indexOf("/mini-app/api/bootstrap")!==-1){started=true;}'
            '      }catch(e){}'
            '      return rawFetch.apply(this,arguments);'
            '    };'
            '  }'
            '  window.__BANANO_MARK_BOOTSTRAP_STARTED__=function(){started=true;};'
            '  window.setTimeout(function(){'
            '    if(started){return;}'
            '    try{'
            '      if(window.performance&&performance.getEntriesByType){'
            '        var entries=performance.getEntriesByType("resource")||[];'
            '        for(var i=0;i<entries.length;i++){'
            '          if(String(entries[i].name||"").indexOf("/mini-app/api/bootstrap")!==-1){return;}'
            '        }'
            '      }'
            '      clientLog("bootstrap-timeout");'
            '      if(sessionStorage.getItem("__banano_bootstrap_reload_once")==="1"){return;}'
            '      sessionStorage.setItem("__banano_bootstrap_reload_once","1");'
            '      var url=new URL(window.location.href);'
            '      url.searchParams.set("_miniapp_reload",String(Date.now()));'
            '      window.location.replace(url.toString());'
            '    }catch(e){}'
            '  },9000);'
            '})();'
            '</script>'
        )
        script = (
            '<script id="miniapp-runtime-config">'
            "window.__BANANO_MINIAPP_CONFIG__="
            f"{json.dumps(runtime_config, ensure_ascii=False).replace('</', '<\\/')};"
            "</script>"
        )
        html_text = index_path.read_text(encoding="utf-8")
        asset_version = str(int(index_path.stat().st_mtime))

        def version_miniapp_asset(match: re.Match[str]) -> str:
            attr = match.group(1)
            url = match.group(2)
            separator = "&" if "?" in url else "?"
            return f'{attr}{url}{separator}v={asset_version}"'

        html_text = re.sub(
            r'((?:src|href)=")(/mini-app/(?:_next/static/[^"]+|telegram-web-app\.js))"',
            version_miniapp_asset,
            html_text,
        )
        all_scripts = f"{snapshot_script}{watchdog_script}{script}"
        if "</head>" in html_text:
            html_text = html_text.replace("</head>", f"{all_scripts}</head>", 1)
        else:
            html_text = f"{all_scripts}{html_text}"
        response = web.Response(text=html_text, content_type="text/html")
    except Exception:
        logger.exception("Miniapp runtime config injection failed")
        response = web.FileResponse(index_path)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


async def miniapp_asset(request: web.Request) -> web.Response:
    static_root = _resolve_miniapp_static_root().resolve()
    tail = request.match_info.get("tail", "").lstrip("/")
    asset_path = (static_root / tail).resolve()
    logger.info(
        "Miniapp asset request: tail=%s static_root=%s asset_path=%s exists=%s",
        tail,
        str(static_root),
        str(asset_path),
        str(asset_path.exists()),
    )

    try:
        asset_path.relative_to(static_root)
    except ValueError:
        raise web.HTTPNotFound()

    if not asset_path.exists() or not asset_path.is_file():
        requested = Path(tail)
        if not requested.suffix:
            return await miniapp_index(request)
        raise web.HTTPNotFound()

    response = web.FileResponse(asset_path)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

async def miniapp_client_log(request: web.Request) -> web.Response:
    try:
        try:
            payload = await request.json()
        except Exception:
            text = await request.text()
            payload = {"raw": text[:2000]}
        if not isinstance(payload, dict):
            payload = {"payload": str(payload)[:2000]}
        compact = {
            "event": str(payload.get("event") or "")[:80],
            "href": str(payload.get("href") or "")[:500],
            "search": str(payload.get("search") or "")[:500],
            "hash_len": int(payload.get("hash_len") or len(str(payload.get("hash") or ""))),
            "has_tg": bool(payload.get("has_tg")),
            "has_webapp": bool(payload.get("has_webapp")),
            "init_data_len": int(payload.get("init_data_len") or 0),
            "message": str(payload.get("message") or "")[:500],
            "source": str(payload.get("source") or "")[:200],
            "file_kind": str(payload.get("file_kind") or "")[:80],
            "file_name": str(payload.get("file_name") or "")[:200],
            "file_type": str(payload.get("file_type") or "")[:120],
            "file_size": int(payload.get("file_size") or 0),
            "duration_ms": int(payload.get("duration_ms") or 0),
            "status": int(payload.get("status") or 0),
            "lineno": payload.get("lineno"),
            "colno": payload.get("colno"),
            "user_agent": request.headers.get("User-Agent", "")[:300],
            "ip": request.headers.get("X-Forwarded-For", request.remote or "")[:80],
        }
        logger.warning("Mini App client log: %s", compact)
    except Exception:
        logger.exception("Mini App client log failed")
    return web.json_response({"ok": True})


async def miniapp_bootstrap(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        user = ctx["user"]
        telegram_user = ctx["payload"]["user"]
        me = await request.app["bot"].get_me()
        profile_link = (
            build_profile_link(me.username, user.referral_code)
            if me.username and user.referral_code
            else config.mini_app_url
        )
        referral_link = (
            build_referral_link(me.username, user.referral_code)
            if me.username and user.referral_code
            else config.mini_app_url
        )
        recent_tasks = await _fetch_recent_tasks(telegram_id)
        partner_stats = await get_partner_overview(telegram_id)
        data = {
            "ok": True,
            "telegram_id": telegram_id,
            "credits": user.credits,
            "first_name": telegram_user.get("first_name", ""),
            "last_name": telegram_user.get("last_name", ""),
            "telegram_username": telegram_user.get("username", ""),
            "photo_url": telegram_user.get("photo_url", ""),
            "referral_code": user.referral_code or "",
            "profile_link": profile_link,
            "referral_link": referral_link,
            "channel_url": user.channel_url or "",
            "prompt_repeat_balance_rub": float(
                partner_stats.get("prompt_repeat_balance_rub", 0) or 0
            ),
            "prompt_repeat_total_rub": float(
                partner_stats.get("prompt_repeat_total_rub", 0) or 0
            ),
            "bot_username": me.username,
            "username": me.username,
            "mini_app_url": config.mini_app_url,
            "is_admin": config.is_admin(telegram_id),
            "actions": sorted(ACTIONS.keys()),
            "payment_packages": [
                _payment_package_payload(package)
                for package in preset_manager.get_packages()
            ],
            "image_models": [
                {
                    **item,
                    "cost": (
                        _resolve_image_unit_cost(item["id"], "basic")
                        if item.get("id") == "seedream_5_pro"
                        else _resolve_image_unit_cost(item["id"], "")
                    ),
                }
                for item in IMAGE_MODELS
            ],
            "video_models": [
                {
                    **item,
                    "costs": {
                        str(duration): preset_manager.get_video_cost(
                            item["id"], duration
                        )
                        for duration in item["durations"]
                    },
                    "quality_costs": preset_manager.get_video_quality_costs(
                        item["id"]
                    ),
                    **(
                        {
                            "omni_audio_cost": preset_manager.get_video_cost(
                                "gemini_omni_audio", 6
                            ),
                            "omni_character_cost": preset_manager.get_video_cost(
                                "gemini_omni_character", 6
                            ),
                        }
                        if item["id"] == "gemini_omni"
                        else {}
                    ),
                }
                for item in VIDEO_MODELS
            ],
            "recent_tasks": recent_tasks,
            "saved_references": [
                _saved_reference_payload(item)
                for item in await list_saved_references(telegram_id, limit=24)
            ],
            "notifications": await get_and_clear_miniapp_notifications(telegram_id),
        }
        return web.json_response(data)
    except Exception as e:
        return _miniapp_error_response(
            e,
            log_message="Mini App bootstrap failed",
        )


async def miniapp_action(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        init_data = body.get("init_data", "")
        action = body.get("action", "")
        telegram_id, _ctx = await _get_user_context(
            request.app, init_data, body.get("start_param_fallback")
        )

        handler = ACTIONS.get(action)
        if not handler:
            return web.json_response(
                {"ok": False, "error": f"Unknown action: {action}"}, status=400
            )

        await handler(request.app, telegram_id)
        return web.json_response({"ok": True})
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App action failed")


async def miniapp_upload(request: web.Request) -> web.Response:
    try:
        upload = None
        raw: bytes | None = None
        filename = ""
        declared_content_type = ""
        if request.content_type == "application/json":
            body = await request.json()
            init_data = str(body.get("init_data", ""))
            file_kind = str(body.get("file_kind", "image_reference"))
            filename = str(body.get("filename", "") or "")
            declared_content_type = str(body.get("content_type", "") or "")
            encoded_data = str(body.get("data_base64", "") or "")
            try:
                raw = base64.b64decode(encoded_data, validate=True)
            except (TypeError, ValueError):
                raw = None
        else:
            data = await asyncio.wait_for(request.post(), timeout=MINIAPP_UPLOAD_TIMEOUT_SECONDS)
            init_data = str(data.get("init_data", ""))
            file_kind = str(data.get("file_kind", "image_reference"))
            upload = data.get("file")
            filename = getattr(upload, "filename", "") or ""
            declared_content_type = getattr(upload, "content_type", "") or ""

        telegram_id, _ctx = await _get_user_context(request.app, init_data)
        _ = telegram_id

        if file_kind not in FILE_KIND_MAP:
            return web.json_response(
                {"ok": False, "error": f"Unsupported file_kind: {file_kind}"},
                status=400,
            )
        if raw is None and (upload is None or not getattr(upload, "file", None)):
            return web.json_response(
                {"ok": False, "error": "Файл не был передан"}, status=400
            )

        config_entry = FILE_KIND_MAP[file_kind]
        if raw is None:
            raw = upload.file.read()
        if not isinstance(raw, (bytes, bytearray)) or not raw:
            return web.json_response(
                {"ok": False, "error": "Не удалось прочитать файл"}, status=400
            )

        content_type = _normalize_miniapp_upload_content_type(
            file_kind,
            filename,
            declared_content_type,
            bytes(raw),
        )
        if not content_type:
            declared_type = getattr(upload, "content_type", "") or "unknown"
            return web.json_response(
                {
                    "ok": False,
                    "error": (
                        f"Формат файла не распознан: {declared_type}. "
                        "Используйте JPG, PNG, WEBP, HEIC, MP4 или MOV."
                    ),
                },
                status=400,
            )

        max_bytes = int(config_entry.get("max_bytes") or MINIAPP_UPLOAD_DEFAULT_MAX_BYTES)
        if len(raw) > max_bytes:
            max_mb = max(1, max_bytes // (1024 * 1024))
            return web.json_response(
                {"ok": False, "error": f"Файл слишком большой, максимум {max_mb}MB"},
                status=400,
            )

        extension = _guess_extension(
            getattr(upload, "filename", ""),
            content_type,
            config_entry["fallback_ext"],
        )
        public_url = None
        saved_reference = None
        if file_kind.endswith("_reference") or config_entry.get("durable_reference"):
            public_url, saved_reference = await save_reference_file(
                telegram_id,
                bytes(raw),
                file_ext=extension,
                kind=config_entry["group"],
                original_filename=filename or None,
                content_type=content_type or None,
                source=str(config_entry.get("source") or "miniapp"),
            )
        if not public_url:
            public_url = save_uploaded_file(bytes(raw), extension)
        if not public_url:
            return web.json_response(
                {"ok": False, "error": "Не удалось сохранить файл"}, status=500
            )

        return web.json_response(
            {
                "ok": True,
                "url": public_url,
                "kind": config_entry["group"],
                "filename": filename or Path(public_url).name,
                "content_type": content_type,
                "reference": (
                    _saved_reference_payload(saved_reference) if saved_reference else None
                ),
            }
        )
    except Exception as e:
        return _miniapp_error_response(
            e,
            log_message="Mini App upload failed",
            default_error="Не удалось загрузить файл",
        )


async def miniapp_create_payment(request: web.Request) -> web.Response:
    """Create a payment for a selected package from the mini-app."""
    try:
        body = await request.json()
        init_data = body.get("init_data", "")
        package_id = body.get("package_id")
        promo_code = body.get("promo_code")
        raw_provider = str(body.get("provider") or TELEGRAM_STARS_PROVIDER).lower()
        provider = {
            "stars": TELEGRAM_STARS_PROVIDER,
            "telegram_stars": TELEGRAM_STARS_PROVIDER,
            "xtr": TELEGRAM_STARS_PROVIDER,
            "yookassa": "yookassa",
            "lava": "lava",
        }.get(raw_provider)

        if not provider:
            return web.json_response(
                {"ok": False, "error": "Unsupported payment provider"}, status=400
            )

        if not package_id:
            return web.json_response(
                {"ok": False, "error": "package_id is required"}, status=400
            )

        telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        user = ctx["user"]

        package = preset_manager.get_package(package_id)
        if not package:
            return web.json_response(
                {"ok": False, "error": "Package not found"}, status=404
            )

        order_id = f"{telegram_id}_{int(time.time() * 1000)}_{package_id}"
        promo = (
            await get_promo_code_by_code(promo_code, active_only=True)
            if promo_code
            else None
        )
        promo_bonus = (
            get_promo_bonus_for_credits(package["credits"]) if promo else 0
        )
        total_credits = total_package_credits(package, promo_bonus)
        description = f"Покупка {total_credits} бананов ({package['name']})"

        if provider == TELEGRAM_STARS_PROVIDER:
            if not config.TELEGRAM_STARS_ENABLED:
                return web.json_response(
                    {"ok": False, "error": "Telegram Stars disabled"}, status=500
                )

            stars_amount = package_stars_amount(package)
            invoice_payload = build_stars_invoice_payload(order_id, stars_amount)
            created = await create_transaction(
                order_id=order_id,
                user_id=user.id,
                payment_id=f"pending:{stars_amount}",
                provider=TELEGRAM_STARS_PROVIDER,
                credits=total_credits,
                amount_rub=float(package["price_rub"]),
                status="pending",
                promo_code_id=promo.id if promo and promo_bonus > 0 else None,
                promo_code=promo.code if promo and promo_bonus > 0 else None,
                promo_bonus_credits=promo_bonus,
            )
            if not created:
                return web.json_response(
                    {"ok": False, "error": "Payment already exists"}, status=409
                )

            try:
                payment_url = await request.app["bot"].create_invoice_link(
                    title=f"{package['name']} · {total_credits}🍌",
                    description=description,
                    payload=invoice_payload,
                    currency=TELEGRAM_STARS_CURRENCY,
                    prices=[
                        LabeledPrice(
                            label=f"{total_credits} бананов",
                            amount=stars_amount,
                        )
                    ],
                    provider_token="",
                )
            except Exception as exc:
                await update_transaction_status(order_id, "failed")
                logger.exception("Mini App Stars invoice link failed order=%s", order_id)
                return web.json_response(
                    {"ok": False, "error": str(exc)}, status=500
                )

            return web.json_response(
                {
                    "ok": True,
                    "provider": TELEGRAM_STARS_PROVIDER,
                    "order_id": order_id,
                    "payment_id": f"pending:{stars_amount}",
                    "payment_url": payment_url,
                    "invoice_url": payment_url,
                    "stars_amount": stars_amount,
                    "credits": total_credits,
                    "promo_bonus_credits": promo_bonus,
                    "promo_code": promo.code if promo and promo_bonus > 0 else "",
                }
            )

        if provider == "lava":
            if not lava_service.enabled:
                return web.json_response(
                    {"ok": False, "error": "Lava not configured"}, status=500
                )

            offer_id, lava_currency = _miniapp_package_lava_offer_config(package)
            if not offer_id:
                return web.json_response(
                    {"ok": False, "error": "Lava offer is not configured for package"},
                    status=500,
                )

            result = await lava_service.create_invoice(
                email=config.LAVA_DEFAULT_EMAIL,
                offer_id=offer_id,
                currency=lava_currency,
                buyer_language="RU",
                client_utm={
                    "telegram_id": str(telegram_id),
                    "order_id": order_id,
                    "package_id": str(package_id),
                },
            )

            if not result or not result.get("ok"):
                return web.json_response(
                    {"ok": False, "error": result or "Failed to create payment"},
                    status=500,
                )

            payment_id = lava_service.extract_invoice_id(result)
            payment_url = lava_service.extract_payment_url(result)
            if not payment_id or not payment_url:
                return web.json_response(
                    {"ok": False, "error": "Failed to get Lava payment link"},
                    status=500,
                )

            await create_transaction(
                order_id=order_id,
                user_id=user.id,
                payment_id=payment_id,
                provider="lava",
                credits=total_credits,
                amount_rub=float(package["price_rub"]),
                status="pending",
                promo_code_id=promo.id if promo and promo_bonus > 0 else None,
                promo_code=promo.code if promo and promo_bonus > 0 else None,
                promo_bonus_credits=promo_bonus,
            )

            return web.json_response(
                {
                    "ok": True,
                    "provider": "lava",
                    "order_id": order_id,
                    "payment_id": payment_id,
                    "payment_url": payment_url,
                    "credits": total_credits,
                    "promo_bonus_credits": promo_bonus,
                    "promo_code": promo.code if promo and promo_bonus > 0 else "",
                }
            )

        if provider != "yookassa":
            return web.json_response(
                {"ok": False, "error": "Unsupported payment provider"}, status=400
            )

        if not yookassa_service.enabled:
            return web.json_response(
                {"ok": False, "error": "YooKassa not configured"}, status=500
            )

        result = await yookassa_service.create_payment(
            amount_rub=float(package["price_rub"]),
            order_id=order_id,
            description=description,
            return_url=config.YOOKASSA_RETURN_URL or config.mini_app_url,
            notification_url=config.yookassa_notification_url,
        )

        if not result or not (result.get("Success") or result.get("PaymentId")):
            return web.json_response(
                {"ok": False, "error": result or "Failed to create payment"}, status=500
            )

        payment_id = result.get("PaymentId")
        payment_url = result.get("PaymentURL")

        # Persist transaction
        await create_transaction(
            order_id=order_id,
            user_id=user.id,
            payment_id=payment_id,
            provider="yookassa",
            credits=total_credits,
            amount_rub=float(package["price_rub"]),
            status="pending",
            promo_code_id=promo.id if promo and promo_bonus > 0 else None,
            promo_code=promo.code if promo and promo_bonus > 0 else None,
            promo_bonus_credits=promo_bonus,
        )

        return web.json_response(
            {
                "ok": True,
                "provider": "yookassa",
                "order_id": order_id,
                "payment_id": payment_id,
                "payment_url": payment_url,
                "credits": total_credits,
                "promo_bonus_credits": promo_bonus,
                "promo_code": promo.code if promo and promo_bonus > 0 else "",
            }
        )

    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App create-payment failed")


async def miniapp_photo_to_prompt(request: web.Request) -> web.Response:
    """Analyze a photo for 1 RUB (0.1 credit) without changing generation prices."""
    charge = None
    try:
        body = await request.json()
        init_data = body.get("init_data", "")
        image_url = str(body.get("image_url", "") or "").strip()
        preserve = str(body.get("preserve", "") or "").strip()
        goal = str(body.get("goal", "") or "").strip()

        telegram_id, _ctx = await _get_user_context(
            request.app,
            init_data,
            body.get("start_param_fallback"),
        )

        if not image_url:
            return web.json_response(
                {"ok": False, "error": "Загрузите фото для анализа"},
                status=400,
            )

        try:
            charge = await reserve_photo_prompt_charge(telegram_id)
        except PhotoPromptInsufficientBalance as exc:
            return web.json_response(
                {
                    "ok": False,
                    "error": str(exc),
                    "credits": exc.balance,
                    "cost_credits": exc.cost_credits,
                    "price_rub": exc.price_rub,
                },
                status=402,
            )

        from bot.services.photo_prompt_service import photo_prompt_service

        try:
            result = await photo_prompt_service.analyze_photo(
                image_url=image_url,
                preserve=preserve,
                goal=goal,
            )
        except Exception:
            await refund_photo_prompt_charge(charge)
            raise

        return web.json_response(
            {
                "ok": True,
                "prompt_en": result["prompt_en"],
                "prompt_ru": result["prompt_ru"],
                "negative_prompt": result["negative_prompt"],
                "model_hint": result["model_hint"],
                "gemini_omni_prompt": result.get("gemini_omni_prompt", ""),
                "voice_transcript": result.get("voice_transcript", ""),
                "voice_prompt_summary_ru": result.get("voice_prompt_summary_ru", ""),
                "voice_description_ru": result.get("voice_description_ru", ""),
                "key_details": result.get("key_details", []),
                "credits": charge.balance_after,
                "cost_credits": charge.cost_credits,
                "price_rub": charge.price_rub,
            }
        )
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App photo-to-prompt failed")


async def miniapp_prompts(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        source = (
            "my"
            if request.path.endswith("/prompts/my")
            else str(body.get("source", "catalog") or "catalog")
        )
        tag = str(body.get("tag", "") or "").strip()
        category = str(body.get("category", "") or "").strip() or None
        page = max(int(body.get("page", 1) or 1), 1)
        limit = min(max(int(body.get("limit", 40) or 40), 1), 120)

        _telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        user = ctx["user"]

        if source == "my":
            prompts = await get_author_prompts(user.id)
        elif source == "top":
            prompts = await get_top_prompts(limit)
        elif source in {"popular", "trending", "best"}:
            prompts = await get_popular_prompts(limit)
        elif source == "tag" and tag:
            prompts = await get_prompts_by_tag(tag, limit)
        else:
            prompts = await get_approved_prompts(
                category=category,
                offset=(page - 1) * limit,
                limit=limit,
            )

        return web.json_response({"ok": True, "prompts": prompts})
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App prompts list failed")


async def miniapp_prompt_detail(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        prompt_id = int(body.get("prompt_id") or 0)
        _telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        user = ctx["user"]

        prompt = await get_prompt_by_id(prompt_id)
        if not prompt:
            return web.json_response({"ok": False, "error": "Промпт не найден"}, status=404)
        if not (prompt["status"] == "approved" and prompt["is_public"]) and prompt["author_id"] != user.id:
            return web.json_response({"ok": False, "error": "Промпт недоступен"}, status=403)
        return web.json_response({"ok": True, "prompt": prompt})
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App prompt detail failed")


async def miniapp_prompt_like(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        prompt_id = int(body.get("prompt_id") or 0)
        _telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        prompt = await like_prompt(prompt_id, ctx["user"].id)
        if not prompt:
            return web.json_response(
                {"ok": False, "error": "Можно лайкать только опубликованные промпты"},
                status=404,
            )
        return web.json_response({"ok": True, "prompt": prompt})
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App prompt like failed")


async def miniapp_prompt_use(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        prompt_id = int(body.get("prompt_id") or 0)
        _telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        prompt = await use_prompt(prompt_id, ctx["user"].id)
        if not prompt:
            return web.json_response(
                {"ok": False, "error": "Промпт не найден или ещё не опубликован"},
                status=404,
            )
        return web.json_response({"ok": True, "prompt": prompt})
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App prompt use failed")


async def miniapp_prompt_link(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        prompt_id = int(body.get("prompt_id") or 0)
        _telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        user = ctx["user"]
        prompt = await get_prompt_by_id(prompt_id)
        if not prompt:
            return web.json_response({"ok": False, "error": "Промпт не найден"}, status=404)
        if not (prompt["status"] == "approved" and prompt["is_public"]) and prompt["author_id"] != user.id:
            return web.json_response({"ok": False, "error": "Промпт недоступен"}, status=403)
        me = await request.app["bot"].get_me()
        link = build_prompt_link(me.username, prompt_id) if me.username else config.mini_app_url
        return web.json_response({"ok": True, "prompt": prompt, "link": link})
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App prompt link failed")


async def miniapp_prompt_submit(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        user = ctx["user"]
        prompt_text = str(body.get("prompt_text", "") or body.get("prompt", "") or "").strip()
        if not prompt_text:
            return web.json_response({"ok": False, "error": "Введите текст промпта"}, status=400)

        policy_error = detect_explicit_prompt_policy_violation(prompt_text)
        if policy_error:
            return web.json_response({"ok": False, "error": policy_error}, status=400)

        raw_generation_settings = body.get("generation_settings")
        generation_settings = (
            dict(raw_generation_settings)
            if isinstance(raw_generation_settings, dict)
            else {}
        )
        if not config.is_admin(telegram_id):
            generation_settings = {}
        if len(json.dumps(generation_settings, ensure_ascii=False)) > 12_000:
            return web.json_response(
                {"ok": False, "error": "Слишком много настроек тренда"},
                status=400,
            )

        active_count = await count_active_prompts_by_author(user.id)
        if active_count >= MAX_ACTIVE_PROMPTS_PER_USER and not config.is_admin(telegram_id):
            return web.json_response(
                {"ok": False, "error": f"Лимит активных промптов: {MAX_ACTIVE_PROMPTS_PER_USER}"},
                status=400,
            )

        prompt = await create_prompt(
            author_id=user.id,
            prompt_text=prompt_text,
            title=str(body.get("title", "") or "").strip() or None,
            description=str(body.get("description", "") or "").strip() or None,
            category=str(body.get("category", "") or "").strip() or None,
            preview_url=str(body.get("preview_url", "") or "").strip() or None,
            model=str(body.get("model", "") or "").strip() or None,
            tags=[str(item) for item in list(body.get("tags", []) or [])],
            generation_settings=generation_settings,
            is_public=True,
        )
        if prompt:
            prompt = await approve_prompt(prompt["id"])
        return web.json_response({"ok": True, "prompt": prompt})
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App prompt submit failed")


async def miniapp_prompt_deactivate(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        prompt_id = int(body.get("prompt_id") or 0)
        _telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        prompt = await deactivate_prompt(prompt_id, author_id=ctx["user"].id)
        return web.json_response({"ok": True, "prompt": prompt})
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App prompt deactivate failed")


async def miniapp_prompt_moderate(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        prompt_id = int(body.get("prompt_id") or 0)
        action = str(body.get("action", "") or "")
        telegram_id, _ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        if not config.is_admin(telegram_id):
            return web.json_response({"ok": False, "error": "Нет доступа"}, status=403)
        if action == "approve":
            prompt = await approve_prompt(prompt_id)
        elif action == "reject":
            prompt = await reject_prompt(prompt_id, str(body.get("reason", "") or ""))
        elif action == "deactivate":
            prompt = await deactivate_prompt(prompt_id)
        else:
            return web.json_response({"ok": False, "error": "Неизвестное действие"}, status=400)
        return web.json_response({"ok": True, "prompt": prompt})
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App prompt moderate failed")


async def miniapp_feed(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        source = str(body.get("source", "recent") or "recent")
        limit = _bounded_int(body.get("limit"), default=24, maximum=48)
        offset = _bounded_int(body.get("offset"), default=0, maximum=999999)
        telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        feed = await get_feed_generations(
            limit=limit,
            offset=offset,
            source=source,
            viewer_user_id=ctx["user"].id,
            include_unavailable=True,
        )
        is_admin = config.is_admin(telegram_id)
        for item in feed:
            is_mine = bool(item.get("is_mine"))
            if is_admin:
                item["can_remove"] = True
            if is_admin or is_mine:
                item["can_blur"] = True
        return web.json_response({"ok": True, "feed": feed})
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App feed list failed")


async def miniapp_feed_item(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        gen_id = body.get("gen_id") or body.get("task_id") or body.get("feed_id")
        if not gen_id:
            return web.json_response({"ok": False, "error": "gen_id is required"}, status=400)

        telegram_id, ctx = await _get_user_context(
            request.app,
            init_data,
            body.get("start_param_fallback"),
        )
        card = await get_profile_generation_card(
            gen_id,
            viewer_user_id=ctx["user"].id,
            include_unavailable=True,
        )
        if not card:
            return web.json_response({"ok": False, "error": "Пост ленты не найден"}, status=404)
        is_admin = config.is_admin(telegram_id)
        is_mine = bool(card.get("is_mine"))
        if is_admin:
            card["can_remove"] = True
        if is_admin or is_mine:
            card["can_blur"] = True
        return web.json_response({"ok": True, "feed_item": card})
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App feed item failed")


async def miniapp_my_feed(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        limit = _bounded_int(body.get("limit"), default=24, maximum=48)
        offset = _bounded_int(body.get("offset"), default=0, maximum=999999)
        telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        feed = await get_user_feed_generations(
            ctx["user"].id,
            limit=limit,
            offset=offset,
            profile_visible_only=True,
            include_unavailable=True,
        )
        is_admin = config.is_admin(telegram_id)
        for item in feed:
            item["can_blur"] = True
            if is_admin:
                item["can_remove"] = True
        return web.json_response({"ok": True, "feed": feed})
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App my feed failed")


def _miniapp_profile_payload(
    author,
    bot_username: str,
    *,
    viewer_user_id: int | None = None,
    feed_summary: dict[str, int] | None = None,
) -> dict[str, Any]:
    referral_code = str(getattr(author, "referral_code", "") or "").strip().upper()
    username = str(getattr(author, "username", "") or "").strip().lstrip("@")
    first_name = str(getattr(author, "first_name", "") or "").strip()
    last_name = str(getattr(author, "last_name", "") or "").strip()
    display_name = " ".join(part for part in (first_name, last_name) if part)
    if not display_name:
        display_name = username or f"user_{getattr(author, 'telegram_id', '') or getattr(author, 'id', '')}"

    profile_link = (
        build_profile_link(bot_username, referral_code)
        if bot_username and referral_code
        else config.mini_app_url
    )
    referral_link = (
        build_referral_link(bot_username, referral_code)
        if bot_username and referral_code
        else config.mini_app_url
    )
    summary = feed_summary or {}
    return {
        "referral_code": referral_code,
        "first_name": first_name,
        "last_name": last_name,
        "username": username,
        "display_name": display_name,
        "photo_url": getattr(author, "photo_url", None) or "",
        "profile_link": profile_link,
        "referral_link": referral_link,
        "channel_url": getattr(author, "channel_url", None) or "",
        "posts_count": int(summary.get("posts_count") or 0),
        "likes_count": int(summary.get("likes_count") or 0),
        "shares_count": int(summary.get("shares_count") or 0),
        "remixes_count": int(summary.get("remixes_count") or 0),
        "is_me": bool(viewer_user_id and getattr(author, "id", None) == viewer_user_id),
    }


async def miniapp_profile_feed(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        referral_code = str(body.get("referral_code", "") or "").strip().upper()
        limit = _bounded_int(body.get("limit"), default=24, maximum=48)
        offset = _bounded_int(body.get("offset"), default=0, maximum=999999)
        if not referral_code:
            return web.json_response({"ok": False, "error": "Не указан профиль"}, status=400)

        telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        author = await get_user_by_referral_code(referral_code)
        if not author:
            return web.json_response({"ok": False, "error": "Профиль не найден"}, status=404)

        feed = await get_user_feed_generations(
            author.id,
            limit=limit,
            offset=offset,
            profile_visible_only=True,
            include_unavailable=True,
        )
        feed_summary = await get_user_feed_summary(author.id)
        is_mine = bool(author.id == ctx["user"].id)
        is_admin = config.is_admin(telegram_id)
        for item in feed:
            item["is_mine"] = is_mine
            if is_admin:
                item["can_remove"] = True
            if is_admin or is_mine:
                item["can_blur"] = True

        me = await request.app["bot"].get_me()
        profile = _miniapp_profile_payload(
            author,
            me.username or "",
            viewer_user_id=ctx["user"].id,
            feed_summary=feed_summary,
        )
        return web.json_response({"ok": True, "profile": profile, "feed": feed})
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App profile feed failed")


async def miniapp_profile_channel_save(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        channel_url = str(body.get("channel_url", "") or "")
        telegram_id, _ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        normalized = await save_user_channel_url(telegram_id, channel_url)
        return web.json_response({"ok": True, "channel_url": normalized})
    except ValueError as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App profile channel save failed")


async def miniapp_generation_share(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        gen_id = body.get("gen_id") or body.get("task_id") or body.get("feed_id")
        prompt_visible = _payload_bool(
            body.get("prompt_visible", body.get("feed_prompt_visible")),
            False,
        )
        references_visible = _payload_bool(
            body.get("references_visible", body.get("feed_references_visible")),
            False,
        )
        blurred = None
        if "blurred" in body or "feed_blurred" in body:
            blurred = _payload_bool(
                body.get("blurred", body.get("feed_blurred")),
                False,
            )
        publication_scope = str(
            body.get("publication_scope", body.get("scope", "feed")) or "feed"
        ).strip().lower()
        adult_content = _payload_bool(
            body.get("adult_content", body.get("is_adult_content")),
            False,
        )
        telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        card = await share_to_feed(
            gen_id,
            ctx["user"].id,
            prompt_visible=prompt_visible,
            references_visible=references_visible,
            blurred=blurred,
            publication_scope=publication_scope,
            adult_content=adult_content,
        )
        if not card:
            logger.warning(
                "Mini App share rejected: telegram_id=%s user_id=%s gen_id=%r body_keys=%s",
                telegram_id,
                ctx["user"].id,
                gen_id,
                sorted(body.keys()),
            )
            return web.json_response(
                {"ok": False, "error": "Нельзя опубликовать эту генерацию"},
                status=403,
            )
        try:
            from bot.handlers.common import _invalidate_feed_and_profile_caches

            _invalidate_feed_and_profile_caches()
        except Exception:
            logger.exception("Failed to invalidate feed caches after Mini App publish")
        me = await request.app["bot"].get_me()
        author_referral_code = str(card.get("author_referral_code") or "").strip().upper()
        publication_link = (
            build_feed_link(me.username, card["id"], author_referral_code)
            if me.username
            else config.mini_app_url
        )
        card["publication_link"] = publication_link
        return web.json_response({"ok": True, "feed_item": card})
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App share generation failed")


async def miniapp_feed_blur(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        gen_id = body.get("gen_id") or body.get("task_id") or body.get("feed_id")
        blurred = _payload_bool(body.get("blurred", body.get("feed_blurred")), False)
        telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        is_admin = config.is_admin(telegram_id)
        card = await set_feed_blurred(
            gen_id,
            ctx["user"].id,
            blurred,
            allow_any_user=is_admin,
        )
        if not card:
            return web.json_response({"ok": False, "error": "Пост ленты не найден или нет доступа"}, status=404)
        if is_admin:
            card["can_remove"] = True
        card["can_blur"] = True
        try:
            from bot.handlers.common import _invalidate_feed_and_profile_caches

            _invalidate_feed_and_profile_caches()
        except Exception:
            logger.exception("Failed to invalidate feed caches after Mini App blur toggle")
        logger.info(
            "Admin toggled Mini App feed blur: admin_telegram_id=%s gen_id=%r blurred=%s",
            telegram_id,
            gen_id,
            blurred,
        )
        return web.json_response({"ok": True, "feed_item": card})
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App feed blur failed")


async def miniapp_feed_remove(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        gen_id = body.get("gen_id") or body.get("task_id") or body.get("feed_id")
        telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        is_admin = config.is_admin(telegram_id)
        removed = await remove_from_feed(gen_id, ctx["user"].id, allow_any_user=is_admin)
        if removed:
            if is_admin:
                logger.info(
                    "Admin removed Mini App feed item: admin_telegram_id=%s gen_id=%r",
                    telegram_id,
                    gen_id,
                )
            try:
                from bot.handlers.common import _invalidate_feed_and_profile_caches

                _invalidate_feed_and_profile_caches()
            except Exception:
                logger.exception("Failed to invalidate feed caches after Mini App remove")
        return web.json_response({"ok": True, "removed": removed})
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App remove feed failed")


async def miniapp_feed_like(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        gen_id = body.get("gen_id") or body.get("task_id")
        allow_profile = str(body.get("surface", "feed") or "feed").strip().lower() == "profile"
        _telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        card = await like_feed_generation(
            gen_id,
            ctx["user"].id,
            allow_profile=allow_profile,
        )
        if not card:
            return web.json_response({"ok": False, "error": "Публикация не найдена"}, status=404)
        return web.json_response({"ok": True, "feed_item": card})
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App feed like failed")


async def miniapp_feed_share(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        gen_id = body.get("gen_id") or body.get("task_id")
        allow_profile = str(body.get("surface", "feed") or "feed").strip().lower() == "profile"
        telegram_id, _ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        card = await increment_feed_share(gen_id, allow_profile=allow_profile)
        if not card:
            return web.json_response({"ok": False, "error": "Публикация не найдена"}, status=404)
        me = await request.app["bot"].get_me()
        author_referral_code = str(card.get("author_referral_code") or "").strip().upper()
        is_image_feed_item = str(card.get("gen_type") or "").strip().lower() == "image"
        post_link = (
            build_feed_bot_link(me.username, card["id"], author_referral_code)
            if me.username
            else config.mini_app_url
        )
        repeat_link = (
            build_remix_bot_link(me.username, card["id"], author_referral_code)
            if me.username and is_image_feed_item
            else post_link
        )
        miniapp_post_link = (
            build_feed_link(me.username, card["id"], author_referral_code)
            if me.username
            else config.mini_app_url
        )
        miniapp_repeat_link = (
            build_remix_link(me.username, card["id"], author_referral_code)
            if me.username and is_image_feed_item
            else miniapp_post_link
        )
        logger.info("Feed share link issued by %s for feed %s", telegram_id, card["id"])
        preferred_link = repeat_link if is_image_feed_item else post_link
        return web.json_response(
            {
                "ok": True,
                "feed_item": card,
                "link": preferred_link,
                "bot_link": post_link,
                "post_link": post_link,
                "repeat_link": repeat_link,
                "miniapp_link": miniapp_post_link,
                "miniapp_post_link": miniapp_post_link,
                "miniapp_repeat_link": miniapp_repeat_link,
            }
        )
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App feed share failed")


async def miniapp_feed_comments(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        gen_id = body.get("gen_id") or body.get("task_id")
        limit = min(max(int(body.get("limit", 80) or 80), 1), 150)
        allow_profile = str(body.get("surface", "feed") or "feed").strip().lower() == "profile"
        _telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        getter = get_profile_generation_card if allow_profile else get_feed_generation_card
        card = await getter(
            gen_id,
            viewer_user_id=ctx["user"].id,
            include_unavailable=True,
        )
        if not card:
            return web.json_response({"ok": False, "error": "Публикация не найдена"}, status=404)
        comments = await get_feed_comments(
            gen_id,
            limit=limit,
            viewer_user_id=ctx["user"].id,
        )
        return web.json_response({"ok": True, "comments": comments})
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App feed comments failed")


async def miniapp_feed_comment_add(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        gen_id = body.get("gen_id") or body.get("task_id")
        text = str(body.get("text", "") or "")
        allow_profile = str(body.get("surface", "feed") or "feed").strip().lower() == "profile"
        _telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        comment = await add_feed_comment(
            gen_id,
            ctx["user"].id,
            text,
            allow_profile=allow_profile,
        )
        if not comment:
            return web.json_response(
                {"ok": False, "error": "Комментарий не удалось добавить"},
                status=400,
            )
        getter = get_profile_generation_card if allow_profile else get_feed_generation_card
        card = await getter(
            gen_id,
            viewer_user_id=ctx["user"].id,
            include_unavailable=True,
        )
        return web.json_response(
            {
                "ok": True,
                "comment": comment,
                "comments_count": int((card or {}).get("comments_count") or 0),
            }
        )
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App feed comment add failed")


async def miniapp_generation_share_library(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        gen_id = body.get("gen_id") or body.get("task_id")
        _telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        task = await share_to_library(gen_id, ctx["user"].id)
        if not task:
            return web.json_response(
                {"ok": False, "error": "Нельзя сохранить prompt этой генерации"},
                status=403,
            )
        return web.json_response({"ok": True, "generation": task})
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App share library failed")


async def miniapp_generation_remove_library(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        gen_id = body.get("gen_id") or body.get("task_id")
        _telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        removed = await remove_from_library(gen_id, ctx["user"].id)
        return web.json_response({"ok": True, "removed": removed})
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App remove library failed")


async def _get_feed_remix_source_card(
    gen_id: Any,
    *,
    viewer_user_id: int,
    allow_profile: bool = False,
) -> dict[str, Any] | None:
    if allow_profile:
        return await get_profile_generation_card(
            gen_id,
            viewer_user_id=viewer_user_id,
        )

    source = await get_feed_generation_card(
        gen_id,
        viewer_user_id=viewer_user_id,
    )
    if source:
        return source

    return await get_profile_generation_card(
        gen_id,
        viewer_user_id=viewer_user_id,
    )


async def miniapp_feed_remix(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        gen_id = body.get("gen_id") or body.get("task_id")
        telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        user = ctx["user"]
        allow_profile = str(body.get("surface", "feed") or "feed").strip().lower() == "profile"

        source = await _get_feed_remix_source_card(
            gen_id,
            viewer_user_id=user.id,
            allow_profile=allow_profile,
        )
        if not source or source.get("gen_type") != "image":
            return web.json_response({"ok": False, "error": "Публикация не найдена"}, status=404)

        source_task = await get_generation_task_payload(source["id"])
        if not source_task:
            return web.json_response({"ok": False, "error": "Пост ленты не найден"}, status=404)
        source_prompt = str(source_task.get("prompt") or "").strip()
        if not source_prompt:
            return web.json_response({"ok": False, "error": "У исходной генерации нет prompt"}, status=400)
        prompt = str(body.get("prompt", "") or "").strip() or source_prompt

        img_service = str(body.get("img_service") or body.get("model") or source.get("model") or "banana_pro")
        img_ratio = str(body.get("img_ratio") or source.get("aspect_ratio") or "1:1")
        references = [str(item) for item in list(body.get("reference_images", []) or []) if str(item).strip()]
        if not references and _can_restore_private_profile_references(source):
            references = _source_image_references_from_task_payload(source_task)
        references = _filter_foreign_feed_source_references(
            source,
            source_task,
            references,
            viewer_telegram_id=telegram_id,
        )
        img_quality = str(body.get("img_quality", "2K"))
        img_nsfw_checker = bool(body.get("img_nsfw_checker", False))
        nsfw_enabled = bool(body.get("nsfw_enabled", False))

        model_meta = next((item for item in IMAGE_MODELS if item["id"] == img_service), None)
        if not model_meta:
            return web.json_response({"ok": False, "error": f"Неизвестная модель: {img_service}"}, status=400)
        if model_meta["requires_reference"] and not references:
            return web.json_response({"ok": False, "error": "Для этой модели нужен референс"}, status=400)
        if len(references) > model_meta["max_references"]:
            return web.json_response(
                {"ok": False, "error": f"Слишком много референсов. Максимум: {model_meta['max_references']}"},
                status=400,
            )
        if _browser_local_reference_urls(references):
            return web.json_response(
                {
                    "ok": False,
                    "error": "Дождитесь окончания загрузки референса и попробуйте снова.",
                },
                status=400,
            )
        if missing_local_upload_sources(references):
            return web.json_response(
                {
                    "ok": False,
                    "error": "Один или несколько старых референсов уже удалены. Загрузите фото заново.",
                },
                status=400,
            )

        user_references = [url for url in references if url != source.get("result_url")]
        if user_references:
            await touch_saved_references(telegram_id, user_references, kind="image")

        unit_cost = _resolve_image_unit_cost(img_service, img_quality)
        is_admin = config.is_admin(telegram_id)
        if not is_admin and not await check_can_afford(telegram_id, unit_cost):
            return web.json_response(
                {"ok": False, "error": f"Недостаточно бананов. Нужно {unit_cost}🍌", "credits": user.credits},
                status=400,
            )
        if not is_admin:
            await deduct_credits(telegram_id, unit_cost)

        launch_result = await _start_image_generation_task(
            user=user,
            telegram_id=telegram_id,
            img_service=img_service,
            prompt=prompt,
            img_ratio=img_ratio,
            reference_images=references,
            unit_cost=unit_cost,
            img_quality=img_quality,
            img_nsfw_checker=img_nsfw_checker,
            nsfw_enabled=nsfw_enabled,
            callback_url=(config.kie_notification_url if config.WEBHOOK_HOST else None),
            source_feed_gen_id=int(source.get("source_feed_gen_id") or source["id"]),
            parent_generation_id=int(source["id"]),
            action_type="remix",
        )

        if launch_result["status"] == "failed":
            if not is_admin:
                await add_credits(telegram_id, unit_cost)
            return web.json_response(
                {"ok": False, "error": "Не удалось запустить remix. Бананы уже возвращены."},
                status=500,
            )

        await _notify_miniapp_image_task_queued(
            request.app,
            telegram_id,
            launch_result,
            img_service=img_service,
            img_ratio=img_ratio,
            unit_cost=unit_cost,
        )

        await _deliver_miniapp_direct_image_result(
            request.app,
            telegram_id,
            launch_result,
            img_service=img_service,
            img_ratio=img_ratio,
            unit_cost=unit_cost,
            prompt_hidden=True,
        )

        await credit_feed_prompt_repeat(
            int(source["id"]),
            user.id,
            repeat_task_id=str(launch_result.get("task_id") or ""),
            credits_spent=unit_cost,
        )

        fresh_user = await get_or_create_user(telegram_id)
        return web.json_response(
            {
                "ok": True,
                "status": launch_result["status"],
                "task_id": launch_result["task_id"],
                "saved_url": launch_result.get("saved_url"),
                "task_type": "image",
                "credits": fresh_user.credits,
                "cost": unit_cost,
                "model_label": get_image_model_label(img_service),
                "prompt_hidden": True,
                "prompt_actions_allowed": False,
                "source_feed_gen_id": int(source["id"]),
            }
        )
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App feed remix failed")


async def miniapp_generate_image(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        init_data = body.get("init_data", "")
        telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        user = ctx["user"]

        prompt = str(body.get("prompt", "")).strip()
        prompt_id_raw = body.get("prompt_id")
        prompt_id = int(prompt_id_raw) if str(prompt_id_raw or "").isdigit() else None
        references = [
            str(item).strip()
            for item in list(body.get("reference_images", []) or [])
            if str(item).strip()
        ]
        source_feed_gen_id_raw = body.get("source_feed_gen_id") or body.get("sourceFeedGenId")
        source_feed_gen_id = (
            int(source_feed_gen_id_raw)
            if str(source_feed_gen_id_raw or "").isdigit()
            else None
        )
        source_feed_task = None
        if source_feed_gen_id:
            source_feed_task = await _get_repeat_source_card(
                source_feed_gen_id,
                viewer_user_id=user.id,
            )
            if not source_feed_task or source_feed_task.get("gen_type") != "image":
                return web.json_response(
                    {"ok": False, "error": "Пост ленты не найден"},
                    status=404,
                )
            source_feed_payload = await get_generation_task_payload(source_feed_gen_id)
            if not source_feed_payload:
                return web.json_response(
                    {"ok": False, "error": "Пост ленты не найден"},
                    status=404,
                )
            source_prompt = str(source_feed_payload.get("prompt") or "").strip()
            if not source_prompt:
                return web.json_response(
                    {"ok": False, "error": "У исходной генерации нет prompt"},
                    status=400,
                )
            if not prompt:
                prompt = source_prompt
            references = _filter_foreign_feed_source_references(
                source_feed_task,
                source_feed_payload,
                references,
                viewer_telegram_id=telegram_id,
            )
            if not references:
                return web.json_response(
                    {"ok": False, "error": "Добавьте своё фото или референс для remix"},
                    status=400,
                )
            # P2-03: propagate original source_feed_gen_id for multi-hop remix lineage
            immediate_parent_id = source_feed_gen_id
            source_feed_gen_id = int(source_feed_task.get("source_feed_gen_id") or source_feed_gen_id)

        img_service = str(
            body.get("img_service")
            or (source_feed_task or {}).get("model")
            or "banana_pro"
        )
        img_ratio = str(
            body.get("img_ratio")
            or (source_feed_task or {}).get("aspect_ratio")
            or "1:1"
        )
        img_quality = str(body.get("img_quality", "2K"))
        img_nsfw_checker = bool(body.get("img_nsfw_checker", False))
        nsfw_enabled = bool(body.get("nsfw_enabled", False))

        prompt_source = None
        if prompt_id and not source_feed_gen_id:
            prompt_source = await get_prompt_by_id(prompt_id, approved_public_only=True)
            if not prompt_source:
                return web.json_response(
                    {"ok": False, "error": "Промпт не найден или ещё не опубликован"},
                    status=404,
                )
            prompt = str(prompt_source["prompt_text"]).strip()

        if not prompt:
            return web.json_response(
                {"ok": False, "error": "Введите промпт для генерации фото"},
                status=400,
            )

        model_meta = next(
            (item for item in IMAGE_MODELS if item["id"] == img_service), None
        )
        if not model_meta:
            return web.json_response(
                {"ok": False, "error": f"Неизвестная модель: {img_service}"},
                status=400,
            )

        if model_meta["requires_reference"] and not references:
            return web.json_response(
                {"ok": False, "error": "Для этой модели нужен хотя бы один исходник"},
                status=400,
            )
        if len(references) > model_meta["max_references"]:
            return web.json_response(
                {
                    "ok": False,
                    "error": f"Слишком много референсов. Максимум: {model_meta['max_references']}",
                },
                status=400,
            )
        if _browser_local_reference_urls(references):
            return web.json_response(
                {
                    "ok": False,
                    "error": "Дождитесь окончания загрузки референса и попробуйте снова.",
                },
                status=400,
            )
        if missing_local_upload_sources(references):
            return web.json_response(
                {
                    "ok": False,
                    "error": "Один или несколько старых референсов уже удалены. Загрузите фото заново.",
                },
                status=400,
            )

        if references:
            await touch_saved_references(telegram_id, references, kind="image")

        unit_cost = _resolve_image_unit_cost(img_service, img_quality)
        is_admin = config.is_admin(telegram_id)
        if not is_admin and not await check_can_afford(telegram_id, unit_cost):
            return web.json_response(
                {
                    "ok": False,
                    "error": f"Недостаточно бананов. Нужно {unit_cost}🍌",
                    "credits": user.credits,
                },
                status=400,
            )

        if not is_admin:
            await deduct_credits(telegram_id, unit_cost)

        launch_result = await _start_image_generation_task(
            user=user,
            telegram_id=telegram_id,
            img_service=img_service,
            prompt=prompt,
            img_ratio=img_ratio,
            reference_images=references,
            unit_cost=unit_cost,
            img_quality=img_quality,
            img_nsfw_checker=img_nsfw_checker,
            nsfw_enabled=nsfw_enabled,
            callback_url=(config.kie_notification_url if config.WEBHOOK_HOST else None),
            prompt_source_id=(None if source_feed_gen_id else prompt_id),
            source_feed_gen_id=source_feed_gen_id,
            parent_generation_id=(immediate_parent_id if source_feed_gen_id else None),
            action_type=("remix" if source_feed_gen_id else None),
        )

        if launch_result["status"] == "failed":
            if not is_admin:
                await add_credits(telegram_id, unit_cost)
            return web.json_response(
                {
                    "ok": False,
                    "error": "Не удалось запустить генерацию. Бананы уже возвращены.",
                },
                status=500,
            )

        prompt_hidden = bool(source_feed_gen_id)
        await _notify_miniapp_image_task_queued(
            request.app,
            telegram_id,
            launch_result,
            img_service=img_service,
            img_ratio=img_ratio,
            unit_cost=unit_cost,
        )
        await _deliver_miniapp_direct_image_result(
            request.app,
            telegram_id,
            launch_result,
            img_service=img_service,
            img_ratio=img_ratio,
            unit_cost=unit_cost,
            prompt_hidden=prompt_hidden,
        )

        if source_feed_gen_id:
            await credit_feed_prompt_repeat(
                immediate_parent_id,
                user.id,
                repeat_task_id=str(launch_result.get("task_id") or ""),
                credits_spent=unit_cost,
            )
        elif prompt_id:
            await use_prompt(prompt_id, user.id, credits_spent=unit_cost)

        fresh_user = await get_or_create_user(telegram_id)
        return web.json_response(
            {
                "ok": True,
                "status": launch_result["status"],
                "task_id": launch_result["task_id"],
                "saved_url": launch_result.get("saved_url"),
                "task_type": launch_result.get("task_type", "image"),
                "credits": fresh_user.credits,
                "cost": unit_cost,
                "model_label": get_image_model_label(img_service),
                "prompt_hidden": prompt_hidden,
                "prompt_actions_allowed": not bool(source_feed_gen_id),
                "prompt_id": (None if source_feed_gen_id else prompt_id),
                "source_feed_gen_id": source_feed_gen_id,
            }
        )
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App image generation failed")


async def miniapp_generate_video(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        init_data = body.get("init_data", "")
        telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        user = ctx["user"]

        prompt = str(body.get("prompt", "")).strip()
        source_feed_gen_id_raw = body.get("source_feed_gen_id") or body.get("sourceFeedGenId")
        source_feed_gen_id = (
            int(source_feed_gen_id_raw)
            if str(source_feed_gen_id_raw or "").isdigit()
            else None
        )
        source_feed_task = None
        source_request_data: dict[str, Any] = {}
        if source_feed_gen_id:
            source_feed_card = await _get_repeat_source_card(
                source_feed_gen_id,
                viewer_user_id=user.id,
            )
            if not source_feed_card or source_feed_card.get("gen_type") != "video":
                return web.json_response(
                    {"ok": False, "error": "Видео из ленты не найдено"},
                    status=404,
                )
            source_feed_task = await get_generation_task_payload(source_feed_gen_id)
            if not source_feed_task:
                return web.json_response(
                    {"ok": False, "error": "Видео из ленты не найдено"},
                    status=404,
                )
            source_feed_task["result_url"] = source_feed_card.get("result_url")
            source_feed_task["result_urls"] = source_feed_card.get("result_urls") or []
            source_prompt = str(source_feed_task.get("prompt") or "").strip()
            if not source_prompt:
                return web.json_response(
                    {"ok": False, "error": "У исходного видео нет prompt"},
                    status=400,
                )
            if not prompt:
                prompt = source_prompt
            source_request_data = source_feed_task.get("request_data") or {}
            if not isinstance(source_request_data, dict):
                source_request_data = {}
            # P2-03: propagate original source_feed_gen_id for multi-hop remix lineage
            immediate_parent_id = source_feed_gen_id
            source_feed_gen_id = int(source_feed_card.get("source_feed_gen_id") or source_feed_gen_id)

        model = str(
            body.get("v_model")
            or (source_feed_task or {}).get("model")
            or "v3_pro"
        )
        generation_type = str(
            body.get("v_type")
            or source_request_data.get("v_type")
            or "text"
        )
        duration = int(
            body.get("v_duration")
            or (source_feed_task or {}).get("duration")
            or 5
        )
        aspect_ratio = str(
            body.get("v_ratio")
            or (source_feed_task or {}).get("aspect_ratio")
            or "16:9"
        )
        image_url = str(body.get("v_image_url", "") or "") or None
        image_references = list(body.get("reference_images", []) or [])
        video_references = list(body.get("v_reference_videos", []) or [])
        audio_url = str(body.get("audio_url", "") or "") or None
        if not audio_url:
            audio_url = str(body.get("audio_reference", "") or "") or None
        audio_references = list(body.get("audio_references", []) or [])
        if not audio_url and audio_references:
            audio_url = str(audio_references[0] or "") or None
        grok_mode = str(body.get("grok_mode", "normal") or "normal")
        grok_resolution = str(body.get("grok_resolution", "480p") or "480p")
        veo_generation_type = str(
            body.get("veo_generation_type", "TEXT_2_VIDEO") or "TEXT_2_VIDEO"
        )
        veo_translation = bool(body.get("veo_translation", True))
        veo_resolution = str(body.get("veo_resolution", "720p") or "720p")
        veo_seed_raw = body.get("veo_seed")
        veo_seed = int(veo_seed_raw) if veo_seed_raw not in (None, "", False) else None
        veo_watermark = str(body.get("veo_watermark", "") or "") or None
        kling_negative_prompt = str(body.get("kling_negative_prompt", "") or "") or None
        kling_cfg_scale_raw = body.get("kling_cfg_scale", 0.5)
        kling_cfg_scale = (
            float(kling_cfg_scale_raw)
            if kling_cfg_scale_raw not in (None, "")
            else None
        )
        omni_resolution = str(body.get("omni_resolution", "720p") or "720p")
        omni_seed_raw = body.get("omni_seed")
        try:
            omni_seed = (
                int(omni_seed_raw)
                if omni_seed_raw not in (None, "", False)
                else None
            )
        except (TypeError, ValueError):
            return web.json_response(
                {"ok": False, "error": "Seed должен быть числом"},
                status=400,
            )
        omni_audio_ids = [
            str(item).strip()
            for item in list(body.get("omni_audio_ids", []) or [])
            if str(item).strip()
        ]
        omni_character_ids = [
            str(item).strip()
            for item in list(body.get("omni_character_ids", []) or [])
            if str(item).strip()
        ]
        omni_base_voice = str(body.get("omni_base_voice", "achernar") or "achernar")
        omni_voice_name = str(body.get("omni_voice_name", "") or "")[:20] or None
        omni_voice_description = (
            str(body.get("omni_voice_description", "") or "")[:2000] or None
        )
        omni_example_dialogue = (
            str(body.get("omni_example_dialogue", "") or "")[:2000] or None
        )
        omni_character_name = (
            str(body.get("omni_character_name", "") or "")[:20] or None
        )
        omni_character_audio_ids = [
            str(item).strip()
            for item in list(body.get("omni_character_audio_ids", []) or [])
            if str(item).strip()
        ][:1]

        if not prompt:
            return web.json_response(
                {"ok": False, "error": "Введите промпт для генерации видео"},
                status=400,
            )
        model_meta = _find_video_model_meta(model)
        if not model_meta:
            return web.json_response(
                {"ok": False, "error": f"Неизвестная видео модель: {model}"},
                status=400,
            )
        if generation_type not in model_meta["supports"]:
            return web.json_response(
                {
                    "ok": False,
                    "error": f"{model_meta['label']} не поддерживает режим {generation_type}",
                },
                status=400,
            )
        effective_model = _resolve_gemini_omni_model(model, generation_type)
        if effective_model in {"gemini_omni_audio", "gemini_omni_character"}:
            duration = 6

        if effective_model == "grok_imagine_v15":
            normalized_grok_ratio = _normalize_video_ratio(aspect_ratio)
            if normalized_grok_ratio not in model_meta["ratios"]:
                return web.json_response(
                    {"ok": False, "error": "Недопустимый формат для Grok Imagine 1.5"},
                    status=400,
                )
            if grok_resolution not in model_meta.get("grok_resolutions", []):
                return web.json_response(
                    {"ok": False, "error": "Недопустимое качество для Grok Imagine 1.5"},
                    status=400,
                )
            if image_references:
                return web.json_response(
                    {
                        "ok": False,
                        "error": "Grok Imagine 1.5 принимает только одно стартовое фото без дополнительных референсов",
                    },
                    status=400,
                )

        if generation_type == "video" and not video_model_supports_reference_videos(effective_model):
            return web.json_response(
                {
                    "ok": False,
                    "error": "Для нескольких видео-референсов выберите Seedance 2.0",
                },
                status=400,
            )
        if duration not in model_meta["durations"]:
            return web.json_response(
                {
                    "ok": False,
                    "error": "Недопустимая длительность для выбранной модели",
                },
                status=400,
            )
        if (
            generation_type == "imgtxt"
            and not image_url
            and effective_model != "gemini_omni_video"
        ):
            return web.json_response(
                {
                    "ok": False,
                    "error": "Для режима Фото + Текст загрузите стартовое фото",
                },
                status=400,
            )
        if generation_type == "character" and not image_url:
            return web.json_response(
                {
                    "ok": False,
                    "error": "Для Gemini Omni Character загрузите изображение персонажа",
                },
                status=400,
            )
        if (
            generation_type == "video"
            and not video_references
            and effective_model != "gemini_omni_video"
        ):
            return web.json_response(
                {
                    "ok": False,
                    "error": "Для режима Видео + Текст нужен хотя бы один видео-референс",
                },
                status=400,
            )
        if generation_type == "motion" and (not image_url or not video_references):
            return web.json_response(
                {
                    "ok": False,
                    "error": "Для Motion Control загрузите фото персонажа и видео движения",
                },
                status=400,
            )
        if generation_type == "avatar" and (not image_url or not audio_url):
            return web.json_response(
                {
                    "ok": False,
                    "error": "Для Kling Avatar загрузите фото персонажа и аудиофайл",
                },
                status=400,
            )

        max_image_references = int(model_meta.get("max_image_references", 0) or 0)
        if max_image_references and len(image_references) > max_image_references:
            return web.json_response(
                {
                    "ok": False,
                    "error": f"Слишком много фото-референсов. Максимум: {max_image_references}",
                },
                status=400,
            )

        max_video_references = int(model_meta.get("max_video_references", 0) or 0)
        if max_video_references and len(video_references) > max_video_references:
            return web.json_response(
                {
                    "ok": False,
                    "error": f"Слишком много видео-референсов. Максимум: {max_video_references}",
                },
                status=400,
            )
        if effective_model == "gemini_omni_video":
            omni_images = _collect_gemini_omni_images(image_url, image_references)
            omni_video_urls = _collect_gemini_omni_video_urls(video_references)
            validation_error = _validate_gemini_omni_video_inputs(
                image_urls=omni_images,
                video_urls=omni_video_urls,
                audio_ids=omni_audio_ids,
                character_ids=omni_character_ids,
            )
            if validation_error:
                return web.json_response(
                    {"ok": False, "error": validation_error},
                    status=400,
                )
        if generation_type == "motion" and (not image_url or not video_references):
            return web.json_response(
                {
                    "ok": False,
                    "error": "Для Motion Control загрузите фото персонажа и видео движения",
                },
                status=400,
            )
        if generation_type == "avatar" and (not image_url or not audio_url):
            return web.json_response(
                {
                    "ok": False,
                    "error": "Для Kling Avatar загрузите фото персонажа и аудиофайл",
                },
                status=400,
            )

        missing_video_images = missing_local_upload_sources(
            _clean_unique_values([image_url, *image_references])
        )
        if missing_video_images:
            return web.json_response(
                {
                    "ok": False,
                    "error": "Один или несколько старых фото-референсов уже удалены. Загрузите фото заново.",
                },
                status=400,
            )

        if image_url:
            await touch_saved_references(telegram_id, [image_url], kind="image")
        if image_references:
            await touch_saved_references(telegram_id, image_references, kind="image")
        if video_references:
            await touch_saved_references(telegram_id, video_references, kind="video")
        if audio_url:
            await touch_saved_references(telegram_id, [audio_url], kind="audio")

        pricing_quality = _video_pricing_quality(
            effective_model, veo_resolution, omni_resolution
        )
        cost = preset_manager.get_video_cost_with_quality(
            effective_model, duration, pricing_quality
        )
        cost = apply_video_reference_cost(
            effective_model,
            cost,
            video_references,
        )
        is_admin = config.is_admin(telegram_id)
        if not is_admin and not await check_can_afford(telegram_id, cost):
            return web.json_response(
                {
                    "ok": False,
                    "error": f"Недостаточно бананов. Нужно {cost}🍌",
                    "credits": user.credits,
                },
                status=400,
            )
        if not is_admin:
            await deduct_credits(telegram_id, cost)

        launch_result = await _launch_video_generation_task(
            telegram_id=telegram_id,
            user=user,
            model=effective_model,
            prompt=prompt,
            duration=duration,
            aspect_ratio=aspect_ratio,
            generation_type=generation_type,
            image_url=image_url,
            image_references=image_references,
            video_references=video_references,
            audio_url=audio_url,
            grok_mode=grok_mode,
            grok_resolution=grok_resolution,
            veo_generation_type=veo_generation_type,
            veo_translation=veo_translation,
            veo_resolution=veo_resolution,
            veo_seed=veo_seed,
            veo_watermark=veo_watermark,
            kling_negative_prompt=kling_negative_prompt,
            kling_cfg_scale=kling_cfg_scale,
            omni_resolution=omni_resolution,
            omni_seed=omni_seed,
            omni_audio_ids=omni_audio_ids,
            omni_character_ids=omni_character_ids,
            omni_base_voice=omni_base_voice,
            omni_voice_name=omni_voice_name,
            omni_voice_description=omni_voice_description,
            omni_example_dialogue=omni_example_dialogue,
            omni_character_name=omni_character_name,
            omni_character_audio_ids=omni_character_audio_ids,
            source_feed_gen_id=source_feed_gen_id,
            parent_generation_id=(immediate_parent_id if source_feed_gen_id else None),
            action_type=("repeat" if source_feed_gen_id else None),
        )

        if launch_result["status"] == "failed":
            if not is_admin:
                await add_credits(telegram_id, cost)
            return web.json_response(
                {
                    "ok": False,
                    "error": launch_result.get("error") or "Не удалось запустить видео",
                },
                status=500,
            )

        if source_feed_gen_id:
            await credit_feed_prompt_repeat(
                immediate_parent_id,
                user.id,
                repeat_task_id=str(launch_result.get("task_id") or ""),
                credits_spent=cost,
            )

        fresh_user = await get_or_create_user(telegram_id)
        return web.json_response(
            {
                "ok": True,
                "status": launch_result["status"],
                "task_id": launch_result["task_id"],
                "saved_url": launch_result.get("saved_url"),
                "task_type": launch_result.get("task_type"),
                "credits": fresh_user.credits,
                "cost": cost,
                "model_label": get_video_model_label(effective_model),
                "prompt_hidden": bool(source_feed_gen_id),
                "prompt_actions_allowed": not bool(source_feed_gen_id),
                "source_feed_gen_id": source_feed_gen_id,
            }
        )
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App video generation failed")


async def miniapp_generate_motion(request: web.Request) -> web.Response:
    """Mini App endpoint for Motion Control."""
    try:
        body = await request.json()
        init_data = body.get("init_data", "")
        telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        user = ctx["user"]

        prompt = str(body.get("prompt", "") or "").strip()
        model = str(
            body.get("motion_model", "motion_control_v26") or "motion_control_v26"
        )
        image_url = str(body.get("motion_image_url", "") or "").strip()
        video_url = str(body.get("motion_video_url", "") or "").strip()
        mode = str(body.get("motion_mode", "720p") or "720p")
        motion_direction = str(body.get("motion_direction", "video") or "video")

        if not image_url:
            return web.json_response(
                {"ok": False, "error": "Загрузите фото персонажа"},
                status=400,
            )
        if not video_url:
            return web.json_response(
                {"ok": False, "error": "Загрузите видео движения"},
                status=400,
            )
        if mode not in {"720p", "1080p"}:
            return web.json_response(
                {"ok": False, "error": "Недопустимое качество Motion Control"},
                status=400,
            )
        if motion_direction not in {"video", "image"}:
            motion_direction = "video"
        if model not in {"motion_control_v26", "motion_control_v30"}:
            model = "motion_control_v26"

        from bot.services.kling_service import kling_service

        raw_duration = body.get("motion_duration")
        if raw_duration in (None, ""):
            duration = 5
        else:
            try:
                duration = int(raw_duration)
            except (TypeError, ValueError):
                return web.json_response(
                    {"ok": False, "error": "Длительность Motion Control должна быть целым числом от 3 до 30 секунд"},
                    status=400,
                )
            if duration < 3 or duration > 30:
                return web.json_response(
                    {"ok": False, "error": "Длительность Motion Control должна быть от 3 до 30 секунд"},
                    status=400,
                )

        await touch_saved_references(telegram_id, [image_url], kind="image")
        await touch_saved_references(telegram_id, [video_url], kind="video")

        cost = preset_manager.get_video_cost_with_quality(model, duration, mode)

        is_admin = config.is_admin(telegram_id)
        if not is_admin and not await check_can_afford(telegram_id, cost):
            return web.json_response(
                {
                    "ok": False,
                    "error": f"Недостаточно бананов. Нужно {cost}🍌",
                    "credits": user.credits,
                },
                status=400,
            )

        if not is_admin:
            await deduct_credits(telegram_id, cost)

        callback_url = config.kie_notification_url if config.WEBHOOK_HOST else None
        api_motion_model = (
            "kling-3.0/motion-control"
            if model == "motion_control_v30"
            else "kling-2.6/motion-control"
        )
        model_label = (
            "Kling 3.0 Motion Control"
            if model == "motion_control_v30"
            else "Kling 2.6 Motion Control"
        )
        result = await kling_service.generate_motion_control(
            image_url=image_url,
            video_urls=[video_url],
            prompt=prompt,
            mode=mode,
            motion_direction=motion_direction,
            motion_model=api_motion_model,
            webhook_url=callback_url,
        )

        result_status, error_message = _classify_video_generation_result(result)

        if result_status == "queued":
            task_id = result["task_id"]
            await add_generation_task(
                user.id,
                telegram_id,
                task_id,
                "video",
                "miniapp_motion_control",
                model=model,
                duration=duration,
                aspect_ratio="1:1",
                prompt=prompt,
                cost=cost,
                request_data={
                    "source": "miniapp",
                    "v_type": "motion_control",
                    "motion_image_url": image_url,
                    "motion_video_url": video_url,
                    "motion_mode": mode,
                    "motion_direction": motion_direction,
                },
            )
            fresh_user = await get_or_create_user(telegram_id)
            return web.json_response(
                {
                    "ok": True,
                    "status": "queued",
                    "task_id": task_id,
                    "credits": fresh_user.credits,
                    "cost": cost,
                    "model_label": model_label,
                }
            )

        local_task_id = f"miniapp_motion_{int(time.time() * 1000)}_{telegram_id}"
        await add_generation_task(
            user.id,
            telegram_id,
            local_task_id,
            "video",
            "miniapp_motion_control",
            model=model,
            duration=duration,
            aspect_ratio="1:1",
            prompt=prompt,
            cost=cost,
            request_data={
                "source": "miniapp",
                "v_type": "motion_control",
                "motion_image_url": image_url,
                "motion_video_url": video_url,
                "motion_mode": mode,
                "motion_direction": motion_direction,
            },
        )

        if result_status == "done":
            saved_url = save_uploaded_file(bytes(result), "mp4")
            await complete_video_task(local_task_id, saved_url)
            fresh_user = await get_or_create_user(telegram_id)
            return web.json_response(
                {
                    "ok": True,
                    "status": "done",
                    "task_id": local_task_id,
                    "saved_url": saved_url,
                    "credits": fresh_user.credits,
                    "cost": cost,
                    "model_label": model_label,
                }
            )

        await complete_video_task(local_task_id, None)
        if not is_admin:
            await add_credits(telegram_id, cost)

        return web.json_response(
            {
                "ok": False,
                "error": error_message or "Не удалось запустить Motion Control",
            },
            status=500,
        )

    except Exception as e:
        logger.exception(f"Mini App Motion Control failed: {e}")
        if 'telegram_id' in locals() and 'cost' in locals():
            try:
                await add_credits(telegram_id, cost)
            except Exception:
                pass
        return _miniapp_error_response(e, log_message="Mini App Motion Control generation failed")


async def miniapp_partner_overview(request: web.Request) -> web.Response:
    """Return real partner program data for Mini App."""
    try:
        body = await request.json()
        init_data = body.get("init_data", "")

        telegram_id, _ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        stats = await get_partner_overview(telegram_id)
        user = await get_or_create_user(telegram_id)
        me = await request.app["bot"].get_me()

        referral_link = (
            build_referral_link(me.username, user.referral_code)
            if user.referral_code
            else ""
        )
        referral_bot_link_str = (
            build_referral_bot_link(me.username, user.referral_code)
            if user.referral_code
            else ""
        )

        return web.json_response(
            {
                "ok": True,
                "is_partner": bool(stats.get("is_partner")),
                "referrals_count": int(stats.get("referrals_count", 0) or 0),
                "balance_rub": float(stats.get("balance_rub", 0) or 0),
                "prompt_repeat_balance_rub": float(
                    stats.get("prompt_repeat_balance_rub", 0) or 0
                ),
                "prompt_repeat_total_rub": float(
                    stats.get("prompt_repeat_total_rub", 0) or 0
                ),
                "channel_url": user.channel_url or "",
                "referral_link": referral_link,
                "referral_bot_link": referral_bot_link_str,
                "status": "partner" if stats.get("is_partner") else "basic",
            }
        )
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App partner overview failed")


def _miniapp_media_extension(content_type: str, url: str) -> str:
    mime = str(content_type or "").split(";", 1)[0].strip().lower()
    extensions = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "video/quicktime": ".mov",
    }
    if mime in extensions:
        return extensions[mime]
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix if suffix in set(extensions.values()) else ".bin"


async def miniapp_media(request: web.Request) -> web.StreamResponse:
    task_id = str(request.match_info.get("task_id") or "").strip()
    try:
        index = max(0, int(request.match_info.get("index") or 0))
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(text="Invalid media index")
    if not task_id or len(task_id) > 200:
        raise web.HTTPBadRequest(text="Invalid task id")

    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            "SELECT result_url, result_urls FROM generation_tasks WHERE task_id = ? LIMIT 1",
            (task_id,),
        )
        row = await cursor.fetchone()
    if not row:
        raise web.HTTPNotFound(text="Media not found")

    urls = _public_result_urls(dict(row))
    if index >= len(urls):
        raise web.HTTPNotFound(text="Media not found")
    source_url = urls[index]

    from bot.services.media_input_utils import resolve_local_upload_path

    local_path = resolve_local_upload_path(source_url)
    if local_path:
        response = web.FileResponse(local_path)
        response.headers["Cache-Control"] = "public, max-age=86400"
        return response

    from bot.database import FEED_EPHEMERAL_RESULT_HOSTS, _feed_result_host

    host = _feed_result_host(source_url)
    if not any(host == allowed or host.endswith(f".{allowed}") for allowed in FEED_EPHEMERAL_RESULT_HOSTS):
        raise web.HTTPForbidden(text="Media host is not allowed")

    cache_key = hashlib.sha256(source_url.encode("utf-8")).hexdigest()
    MINIAPP_MEDIA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = next(MINIAPP_MEDIA_CACHE_DIR.glob(f"{cache_key}.*"), None)
    if cached and cached.is_file():
        response = web.FileResponse(cached)
        response.headers["Cache-Control"] = "public, max-age=86400"
        return response

    lock = _miniapp_media_locks.setdefault(cache_key, asyncio.Lock())
    async with lock:
        cached = next(MINIAPP_MEDIA_CACHE_DIR.glob(f"{cache_key}.*"), None)
        if not cached:
            timeout = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(source_url, allow_redirects=True) as upstream:
                    if upstream.status != 200:
                        raise web.HTTPBadGateway(text="Media source is unavailable")
                    content_length = int(upstream.headers.get("Content-Length") or 0)
                    if content_length > MINIAPP_MEDIA_MAX_BYTES:
                        raise web.HTTPRequestEntityTooLarge(
                            max_size=MINIAPP_MEDIA_MAX_BYTES,
                            actual_size=content_length,
                        )
                    content = await upstream.read()
                    if len(content) > MINIAPP_MEDIA_MAX_BYTES:
                        raise web.HTTPRequestEntityTooLarge(
                            max_size=MINIAPP_MEDIA_MAX_BYTES,
                            actual_size=len(content),
                        )
                    extension = _miniapp_media_extension(
                        upstream.headers.get("Content-Type", ""), source_url
                    )
            cached = MINIAPP_MEDIA_CACHE_DIR / f"{cache_key}{extension}"
            temporary = cached.with_suffix(f"{cached.suffix}.tmp")
            await asyncio.to_thread(temporary.write_bytes, content)
            await asyncio.to_thread(temporary.replace, cached)
    _miniapp_media_locks.pop(cache_key, None)
    response = web.FileResponse(cached)
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response


async def miniapp_task_detail(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        init_data = body.get("init_data", "")
        task_id = str(body.get("task_id", "")).strip()
        if not task_id:
            return web.json_response(
                {"ok": False, "error": "task_id is required"}, status=400
            )

        telegram_id, _ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        detail = await _fetch_task_detail(telegram_id, task_id)
        if not detail:
            return web.json_response(
                {"ok": False, "error": "Задача не найдена"}, status=404
            )

        return web.json_response({"ok": True, "task": detail})
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App task detail failed")


async def miniapp_ai_assistant(request: web.Request) -> web.Response:
    """AI-ассистент через настоящий LLM backend."""
    try:
        body = await request.json()
        init_data = body.get("init_data", "")
        user_message = str(body.get("message", "")).strip()
        audio_url = str(body.get("audio_url", "") or "").strip()
        audio_content_type = str(body.get("audio_content_type", "") or "").strip()
        history = list(body.get("history", []) or [])

        if not user_message and not audio_url:
            return web.json_response(
                {"ok": False, "error": "Сообщение не может быть пустым"}, status=400
            )

        telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        user = ctx["user"]
        audio_bytes = None
        audio_format = ""

        if audio_url:
            try:
                audio_bytes, _mime_type, audio_format = _load_miniapp_assistant_audio(
                    audio_url,
                    content_type=audio_content_type,
                )
            except ValueError as e:
                return web.json_response(
                    {"ok": False, "error": str(e)},
                    status=400,
                )

        context = {
            "user_credits": user.credits,
            "menu_location": "mini_app_assistant",
        }

        if audio_bytes:
            response_text = await ai_assistant_service.get_assistant_response_with_audio(
                user_message=user_message,
                context=context,
                audio_bytes=audio_bytes,
                audio_format=audio_format,
            )
        else:
            response_text = await ai_assistant_service.get_assistant_response(
                user_message=user_message,
                context=context,
            )

        if response_text is None:
            return web.json_response(
                {
                    "ok": False,
                    "error": "AI-ассистент временно недоступен. Попробуйте позже.",
                },
                status=503,
            )

        return web.json_response({"ok": True, "reply": response_text})
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App AI assistant failed")


async def miniapp_api_not_found(request: web.Request) -> web.Response:
    logger.warning(
        "Mini App API route not found: method=%s path=%s",
        request.method,
        request.path,
    )
    return web.json_response(
        {"ok": False, "error": "API endpoint not found"},
        status=404,
    )


def setup_miniapp_routes(app: web.Application):
    miniapp_path = config.MINI_APP_PATH or "/mini-app"
    if not miniapp_path.startswith("/"):
        miniapp_path = f"/{miniapp_path}"
    miniapp_root = miniapp_path.rstrip("/")
    miniapp_frontend_host = urlparse(config.mini_app_url or "").netloc.lower()

    def _should_redirect_to_frontend(request: web.Request) -> bool:
        if not miniapp_frontend_host:
            return False
        request_host = request.host.split(":", 1)[0].lower()
        return request_host != miniapp_frontend_host

    def _frontend_miniapp_url(suffix: str = "") -> str:
        base = (config.mini_app_url or "").rstrip("/")
        suffix = suffix.lstrip("/")
        return f"{base}/{suffix}" if suffix else f"{base}/"

    @web.middleware
    async def _miniapp_cors_middleware(
        request: web.Request,
        handler,
    ) -> web.StreamResponse:
        """Add CORS headers to Mini App API responses.

        Telegram Mini Apps run inside an iframe. Some VPNs/proxies inspect or
        strip CORS headers, causing fetch() requests from the mini-app to fail
        if the response lacks explicit Access-Control-Allow-Origin.

        We echo the request Origin back (not '*') because credentialed requests
        (with X-Telegram-Init-Data) require a concrete origin, not a wildcard.
        """
        if request.method == "OPTIONS":
            response = web.Response(status=204)
            origin = request.headers.get("Origin", "")
            if origin:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = (
                "Content-Type, Authorization, X-Telegram-Init-Data, X-Requested-With"
            )
            response.headers["Access-Control-Max-Age"] = "86400"
            return response

        response = await handler(request)
        origin = request.headers.get("Origin", "")
        if origin:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
        if request.path.startswith(f"{miniapp_root}/_next/static/") or request.path == f"{miniapp_root}/telegram-web-app.js":
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    @web.middleware
    async def _miniapp_api_json_errors(
        request: web.Request,
        handler,
    ) -> web.StreamResponse:
        try:
            return await handler(request)
        except web.HTTPException as exc:
            if request.path.startswith(f"{miniapp_root}/api/") or request.path.startswith(
                "/api/v1/"
            ):
                return web.json_response(
                    {"ok": False, "error": exc.reason or "API request failed"},
                    status=exc.status,
                )
            raise

    # CORS middleware must be FIRST so it wraps all other middlewares and
    # applies to every Mini App / API response.
    app.middlewares.insert(0, _miniapp_cors_middleware)
    app.middlewares.append(_miniapp_api_json_errors)

    # miniapp_static_mount_v1
    from pathlib import Path as _MiniAppPath

    miniapp_out_dir = (
        _MiniAppPath(__file__).resolve().parent.parent
        / "frontend"
        / "miniapp-v0"
        / "out"
    )
    miniapp_next_static_dir = miniapp_out_dir / "_next" / "static"
    if miniapp_next_static_dir.exists():
        app.router.add_static(
            "/mini-app/_next/static/",
            path=str(miniapp_next_static_dir),
            name="miniapp_next_static",
        )

    async def _miniapp_root_file(request: web.Request) -> web.Response:
        asset_name = request.match_info.get("asset", "") or "icon-light-32x32.png"
        asset_path = miniapp_out_dir / asset_name
        if asset_path.exists() and asset_path.is_file():
            return web.FileResponse(asset_path)
        if asset_name == "favicon.ico":
            for fallback_name in ("icon.svg", "icon-light-32x32.png"):
                fallback_path = miniapp_out_dir / fallback_name
                if fallback_path.exists() and fallback_path.is_file():
                    return web.FileResponse(fallback_path)
        raise web.HTTPNotFound()

    async def _empty_vercel_insights(request: web.Request) -> web.Response:
        # The exported miniapp can request Vercel Insights from the site root.
        # We do not run Vercel here, so serve a no-op script instead of noisy 404s.
        return web.Response(
            text="/* Vercel Insights disabled on self-hosted deployment. */\n",
            content_type="application/javascript",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    async def _miniapp_frontend_redirect(request: web.Request) -> web.Response:
        if _should_redirect_to_frontend(request):
            return web.HTTPFound(_frontend_miniapp_url())
        return await miniapp_index(request)

    async def _miniapp_asset_or_redirect(request: web.Request) -> web.Response:
        if _should_redirect_to_frontend(request):
            tail = request.match_info.get("tail", "")
            return web.HTTPFound(_frontend_miniapp_url(tail))
        return await miniapp_asset(request)

    # Do not mount the full `out/` directory as a static resource here.
    # Serving of `index.html` and other files is handled explicitly by
    # `miniapp_index` and `miniapp_asset` so we avoid conflicts where the
    # static resource would match `/mini-app/` and return 403 for directory
    # requests when `show_index` is disabled. Keep only `_next/static`
    # mounted above for Next.js runtime assets.
    app.router.add_get("/icon-light-32x32.png", _miniapp_root_file)
    app.router.add_get("/icon.svg", _miniapp_root_file)
    app.router.add_get("/icon-dark-32x32.png", _miniapp_root_file)
    app.router.add_get("/favicon.ico", _miniapp_root_file)
    app.router.add_get("/apple-icon.png", _miniapp_root_file)
    app.router.add_get("/_vercel/insights/script.js", _empty_vercel_insights)
    app.router.add_get("/telegram-web-app.js", _miniapp_root_file)
    app.router.add_get(miniapp_root, _miniapp_frontend_redirect)
    app.router.add_get(f"{miniapp_root}/", _miniapp_frontend_redirect)
    app.router.add_post(miniapp_root + "/api/bootstrap", miniapp_bootstrap)
    app.router.add_post(miniapp_root + "/api/client-log", miniapp_client_log)
    app.router.add_post(miniapp_root + "/api/action", miniapp_action)
    app.router.add_post(miniapp_root + "/api/upload", miniapp_upload)
    app.router.add_post(miniapp_root + "/api/photo-to-prompt", miniapp_photo_to_prompt)
    app.router.add_post(miniapp_root + "/api/prompts", miniapp_prompts)
    app.router.add_post(miniapp_root + "/api/prompts/detail", miniapp_prompt_detail)
    app.router.add_post(miniapp_root + "/api/prompts/like", miniapp_prompt_like)
    app.router.add_post(miniapp_root + "/api/prompts/use", miniapp_prompt_use)
    app.router.add_post(miniapp_root + "/api/prompts/link", miniapp_prompt_link)
    app.router.add_post(miniapp_root + "/api/prompts/submit", miniapp_prompt_submit)
    app.router.add_post(miniapp_root + "/api/prompts/deactivate", miniapp_prompt_deactivate)
    app.router.add_post(miniapp_root + "/api/admin/prompts/moderate", miniapp_prompt_moderate)
    app.router.add_post(miniapp_root + "/api/feed", miniapp_feed)
    app.router.add_post(miniapp_root + "/api/feed/item", miniapp_feed_item)
    app.router.add_post(miniapp_root + "/api/feed/my", miniapp_my_feed)
    app.router.add_get(miniapp_root + "/api/feed/profile", miniapp_profile_feed)
    app.router.add_post(miniapp_root + "/api/feed/profile", miniapp_profile_feed)
    app.router.add_post(miniapp_root + "/api/profile/channel", miniapp_profile_channel_save)
    app.router.add_post(miniapp_root + "/api/feed/like", miniapp_feed_like)
    app.router.add_post(miniapp_root + "/api/feed/share", miniapp_feed_share)
    app.router.add_get(miniapp_root + "/api/feed/comments", miniapp_feed_comments)
    app.router.add_post(miniapp_root + "/api/feed/comments", miniapp_feed_comments)
    app.router.add_post(miniapp_root + "/api/feed/comment", miniapp_feed_comment_add)
    app.router.add_post(miniapp_root + "/api/feed/blur", miniapp_feed_blur)
    app.router.add_post(miniapp_root + "/api/feed/remove", miniapp_feed_remove)
    app.router.add_post(miniapp_root + "/api/feed/remix", miniapp_feed_remix)
    app.router.add_post(miniapp_root + "/api/generations/share", miniapp_generation_share)
    app.router.add_post(miniapp_root + "/api/generations/publish", miniapp_generation_share)
    app.router.add_post(
        miniapp_root + "/api/generations/share-library",
        miniapp_generation_share_library,
    )
    app.router.add_post(
        miniapp_root + "/api/generations/remove-library",
        miniapp_generation_remove_library,
    )
    app.router.add_post(miniapp_root + "/api/generate-image", miniapp_generate_image)
    app.router.add_post(miniapp_root + "/api/generate-video", miniapp_generate_video)
    app.router.add_post(miniapp_root + "/api/generate-motion", miniapp_generate_motion)
    app.router.add_post(
        miniapp_root + "/api/partner-overview", miniapp_partner_overview
    )
    app.router.add_post(miniapp_root + "/api/create-payment", miniapp_create_payment)
    app.router.add_post(miniapp_root + "/api/task-detail", miniapp_task_detail)
    app.router.add_post(miniapp_root + "/api/ai-assistant", miniapp_ai_assistant)
    app.router.add_get(
        miniapp_root + "/api/media/{task_id}/{index}", miniapp_media
    )
    app.router.add_route("*", miniapp_root + "/api/{tail:.*}", miniapp_api_not_found)

    api_v1_root = "/api/v1"
    app.router.add_get(api_v1_root + "/feed", miniapp_feed)
    app.router.add_get(api_v1_root + "/me/feed", miniapp_my_feed)
    app.router.add_get(api_v1_root + "/feed/profile", miniapp_profile_feed)
    app.router.add_post(api_v1_root + "/feed/profile", miniapp_profile_feed)
    app.router.add_get(api_v1_root + "/feed/{gen_id}", miniapp_feed_item)
    app.router.add_get(api_v1_root + "/profiles/{referral_code}/feed", miniapp_profile_feed)
    app.router.add_post(api_v1_root + "/profiles/{referral_code}/feed", miniapp_profile_feed)
    app.router.add_post(api_v1_root + "/me/channel", miniapp_profile_channel_save)
    app.router.add_get(api_v1_root + "/feed/{gen_id}/comments", miniapp_feed_comments)
    app.router.add_post(api_v1_root + "/feed/{gen_id}/comments", miniapp_feed_comment_add)
    app.router.add_post(api_v1_root + "/generations/{gen_id}/share", miniapp_generation_share)
    app.router.add_post(api_v1_root + "/generations/{gen_id}/publish", miniapp_generation_share)
    app.router.add_post(
        api_v1_root + "/generations/{gen_id}/share-library",
        miniapp_generation_share_library,
    )
    app.router.add_post(
        api_v1_root + "/generations/{gen_id}/remove-library",
        miniapp_generation_remove_library,
    )
    app.router.add_post(api_v1_root + "/feed/{gen_id}/remove", miniapp_feed_remove)
    app.router.add_post(api_v1_root + "/feed/{gen_id}/blur", miniapp_feed_blur)
    app.router.add_post(api_v1_root + "/feed/{gen_id}/like", miniapp_feed_like)
    app.router.add_post(api_v1_root + "/feed/{gen_id}/remix", miniapp_feed_remix)
    app.router.add_get(api_v1_root + "/feed/{gen_id}/link", miniapp_feed_share)
    app.router.add_get(api_v1_root + "/prompts", miniapp_prompts)
    app.router.add_post(api_v1_root + "/prompts", miniapp_prompt_submit)
    app.router.add_get(api_v1_root + "/prompts/my", miniapp_prompts)
    app.router.add_get(api_v1_root + "/prompts/{prompt_id}", miniapp_prompt_detail)
    app.router.add_get(api_v1_root + "/prompts/{prompt_id}/link", miniapp_prompt_link)
    app.router.add_post(api_v1_root + "/prompts/{prompt_id}/like", miniapp_prompt_like)
    app.router.add_post(api_v1_root + "/prompts/{prompt_id}/use", miniapp_prompt_use)
    app.router.add_post(
        api_v1_root + "/prompts/{prompt_id}/deactivate",
        miniapp_prompt_deactivate,
    )
    app.router.add_post(api_v1_root + "/generate/image", miniapp_generate_image)
    app.router.add_route("*", api_v1_root + "/{tail:.*}", miniapp_api_not_found)
    app.router.add_get(miniapp_root + "/{tail:.*}", _miniapp_asset_or_redirect)
