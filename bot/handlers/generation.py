import asyncio
import base64
import html
import io
import json
import logging
import os
import random
import re
import subprocess
import time
import uuid
from datetime import datetime
from typing import Any, Optional

from aiogram import Bot, F, Router, types
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from PIL import Image

from bot import db as db_backend
from bot.config import config
from bot.quality_pricing import QUALITY_COSTS, SEEDREAM_5_PRO_QUALITY_COSTS
from bot.database import (
    add_credits,
    add_generation_history,
    add_generation_task,
    _merge_task_id_aliases,
    check_can_afford,
    complete_video_task,
    credit_feed_prompt_repeat,
    deduct_credits,
    delete_saved_reference,
    get_feed_generation_card,
    get_or_create_user,
    get_task_by_id,
    get_user_credits,
    get_user_settings,
    list_saved_references,
    remove_from_feed,
    remove_from_library,
    share_to_feed,
    share_to_library,
)
from bot.keyboards import (
    get_back_keyboard,
    get_create_image_keyboard,
    get_create_video_keyboard,
    get_gemini_omni_result_keyboard,
    get_image_model_label,
    get_image_model_selection_keyboard,
    get_image_result_keyboard,
    get_main_menu_button_keyboard,
    get_main_menu_keyboard,
    get_motion_control_keyboard,
    get_preset_action_keyboard,
    get_reference_images_keyboard,
    get_reference_images_upload_keyboard,
    get_reference_videos_upload_keyboard,
    get_saved_reference_picker_keyboard,
    get_video_edit_input_type_keyboard,
    get_video_edit_keyboard,
    get_video_media_step_keyboard,
    get_video_model_label,
    get_video_model_selection_keyboard,
    get_video_options_no_preset_keyboard,
    get_video_result_keyboard,
    get_video_type_label,
)
from bot.miniapp_links import feed_bot_link, feed_link
from bot.services.gemini_service import gemini_service
from bot.services.gemini_omni_service import gemini_omni_service
from bot.services.gpt_image_service import gpt_image_service
from bot.services.grok_service import grok_service
from bot.services.media_input_utils import (
    filter_available_image_sources,
    is_reference_contact_sheet_url,
    missing_local_upload_sources,
)
from bot.services.nano_banana_2_service import nano_banana_2_service
from bot.services.nano_banana_pro_service import nano_banana_pro_service
from bot.services.preset_manager import preset_manager
from bot.services.seedream_service import seedream_service
from bot.services.reference_storage_service import save_reference_file
from bot.services.veo_service import veo_service
from bot.services.wan27_service import wan27_service
from bot.states import GenerationStates
from bot.utils.help_texts import (
    UserHints,
    format_generation_options,
    get_prompt_tips,
    get_reference_images_help,
)
from bot.utils.user_facing_errors import make_user_friendly_generation_error
from bot.utils.validators import detect_explicit_prompt_policy_violation
from bot.video_reference_policy import (
    apply_video_reference_cost,
    choose_video_reference_model,
    get_max_video_image_references,
    get_max_video_references,
    normalize_reference_urls,
    video_model_supports_reference_videos,
)

logger = logging.getLogger(__name__)
router = Router()
_reference_upload_locks: dict[int, asyncio.Lock] = {}
IMAGE_REFERENCE_DOCUMENT_MIME_TYPES = ("image/jpeg", "image/png", "image/webp")
IMAGE_REFERENCE_MIN_SIDE_PX = 300
AVATAR_AUDIO_MAX_SECONDS = 60
BANANA_IMAGE_ASPECT_RATIOS = (
    "1:1",
    "2:3",
    "3:2",
    "3:4",
    "4:3",
    "4:5",
    "5:4",
    "9:16",
    "16:9",
    "21:9",
)


def _default_image_flow_data(
    *,
    reference_images: list[str] | None = None,
    img_flow_step: str = "select_model",
) -> dict:
    return {
        "generation_type": "image",
        "img_service": "banana_pro",
        "img_ratio": "1:1",
        "img_count": 1,
        "img_quality": "2K",
        "img_nsfw_checker": False,
        "nsfw_enabled": False,
        "reference_images": list(reference_images or []),
        "img_flow_step": img_flow_step,
        "preset_id": "new",
    }


def _image_file_ext_from_mime(mime_type: str | None) -> str:
    return {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }.get(mime_type or "", "png")


def _parse_omni_ids(raw: str, *, max_count: int | None = None) -> list[str]:
    """Parse comma/space separated Gemini Omni reusable asset ids."""
    value = (raw or "").strip()
    if value.lower() in {"off", "none", "нет", "clear", "очистить", "-"}:
        return []
    tokens = re.split(r"[\s,;]+", value)
    parsed: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        item = token.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        parsed.append(item)
        if max_count is not None and len(parsed) >= max_count:
            break
    return parsed


def _derive_omni_name(text: str, fallback: str) -> str:
    value = re.sub(r"\s+", " ", (text or "").strip())
    value = re.sub(r"[^\w\s.-]", "", value, flags=re.UNICODE).strip()
    return (value[:20] or fallback)[:20]


def _clean_unique_urls(values) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        url = str(value or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        cleaned.append(url)
    return cleaned


def _seedance_media_inputs(
    generation_type: str,
    image_url: str | None,
    reference_images,
    reference_videos,
) -> tuple[str | None, list[str], list[str]]:
    """Build one Seedance scenario without changing prompt or user mode."""
    images = normalize_reference_urls(
        reference_images,
        max_count=get_max_video_image_references("seedance_2"),
    )
    videos = normalize_reference_urls(
        reference_videos,
        max_count=get_max_video_references("seedance_2"),
    )
    has_multimodal_refs = bool(images or videos)
    if generation_type == "imgtxt" and image_url and not has_multimodal_refs:
        return image_url, [], []
    return None, _clean_unique_urls([image_url, *images]), videos


def _collect_gemini_omni_image_urls(
    image_url: str | None,
    reference_images,
) -> list[str]:
    return _clean_unique_urls([image_url, *list(reference_images or [])])


def _collect_gemini_omni_video_urls(video_references) -> list[str]:
    return _clean_unique_urls(video_references)


def _build_gemini_omni_video_list(video_urls, duration: int) -> list[dict]:
    try:
        ends = min(20, max(1, int(duration)))
    except (TypeError, ValueError):
        ends = 10
    return [{"url": url, "start": 0, "ends": ends} for url in video_urls or []]


def _gemini_omni_input_units(
    image_urls,
    video_urls,
    character_ids,
) -> int:
    return len(image_urls or []) + len(video_urls or []) * 2 + len(character_ids or [])


def _validate_gemini_omni_video_inputs(
    *,
    image_urls,
    video_urls,
    character_ids,
    audio_ids=None,
) -> str | None:
    audio_count = len(audio_ids or [])
    character_count = len(character_ids or [])
    video_count = len(video_urls or [])
    units = _gemini_omni_input_units(image_urls, video_urls, character_ids)
    if video_count > gemini_omni_service.MAX_VIDEO_INPUTS:
        return "Gemini Omni принимает только один видео-референс. Удалите текущий или замените его."
    if audio_count > gemini_omni_service.MAX_AUDIO_IDS:
        return "Gemini Omni Video принимает один Audio ID за запуск."
    if character_count > gemini_omni_service.MAX_CHARACTER_IDS:
        return "Gemini Omni принимает максимум 3 Character ID."
    if units > gemini_omni_service.MAX_IMAGE_SLOTS:
        return (
            "Слишком много входов для Gemini Omni. "
            "Лимит: фото + видео*2 + Character ID <= 7."
        )
    return None


def _get_reference_upload_lock(user_id: int) -> asyncio.Lock:
    lock = _reference_upload_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _reference_upload_locks[user_id] = lock
    return lock


async def _persist_reusable_image_reference(
    telegram_id: int,
    image_data: bytes,
    file_ext: str,
    *,
    original_filename: str | None = None,
    content_type: str | None = None,
) -> Optional[str]:
    return await _persist_reusable_media_reference(
        telegram_id,
        image_data,
        file_ext,
        kind="image",
        original_filename=original_filename,
        content_type=content_type,
    )


async def _persist_reusable_media_reference(
    telegram_id: int,
    file_data: bytes,
    file_ext: str,
    *,
    kind: str,
    original_filename: str | None = None,
    content_type: str | None = None,
) -> Optional[str]:
    public_url, _saved_reference = await save_reference_file(
        telegram_id,
        file_data,
        file_ext=file_ext,
        kind=kind,
        original_filename=original_filename,
        content_type=content_type,
        source="telegram_bot",
    )
    if public_url:
        return public_url
    return save_uploaded_file(file_data, file_ext)


async def _save_reference_image_from_message(
    message: types.Message,
    *,
    original_filename_prefix: str = "reference",
) -> tuple[Optional[str], Optional[str]]:
    """Download, validate and persist a Telegram image as a reusable reference."""
    if message.photo:
        media = message.photo[-1]
        file_ext = "jpg"
    elif (
        message.document
        and message.document.mime_type in IMAGE_REFERENCE_DOCUMENT_MIME_TYPES
    ):
        media = message.document
        file_ext = _image_file_ext_from_mime(message.document.mime_type)
    else:
        return None, "Пожалуйста, отправьте фото JPEG, PNG или WEBP."

    try:
        file = await message.bot.get_file(media.file_id)
        image_bytes = await message.bot.download_file(file.file_path)
        image_data = image_bytes.read()
    except Exception:
        logger.exception(
            "Failed to download reference image for user_id=%s",
            getattr(message.from_user, "id", None),
        )
        return None, "❌ Не удалось скачать изображение. Попробуйте ещё раз."

    try:
        with Image.open(io.BytesIO(image_data)) as img:
            width, height = img.size
        if (
            width < IMAGE_REFERENCE_MIN_SIDE_PX
            or height < IMAGE_REFERENCE_MIN_SIDE_PX
        ):
            return (
                None,
                f"❌ Изображение слишком маленькое (мин {IMAGE_REFERENCE_MIN_SIDE_PX}px).",
            )
    except Exception:
        logger.exception(
            "Image validation failed for user_id=%s",
            getattr(message.from_user, "id", None),
        )
        return None, "❌ Не удалось обработать изображение. Попробуйте другое."

    content_type = "image/jpeg" if file_ext == "jpg" else f"image/{file_ext}"
    original_filename = getattr(media, "file_name", None) or (
        f"{original_filename_prefix}_{media.file_id}.{file_ext}"
    )
    image_url = await _persist_reusable_image_reference(
        message.from_user.id,
        image_data,
        file_ext,
        original_filename=original_filename,
        content_type=content_type,
    )

    if not image_url:
        return None, "❌ Не удалось сохранить фото. Попробуйте ещё раз."
    return image_url, None


@router.message(CommandStart(), StateFilter("*"))
async def cmd_start_interrupt(message: types.Message, state: FSMContext):
    """/start interrupts any active FSM state and redirects to main menu handler"""
    from bot.handlers.common import cmd_start as _cmd_start

    current_state = await state.get_state()
    if current_state is not None:
        await state.clear()
    await _cmd_start(message, state)


SENSITIVE_FASHION_KEYWORDS = {
    "белье",
    "нижнее белье",
    "нижнем белье",
    "бюстгальтер",
    "стринги",
    "лиф",
    "чулки",
    "подвяз",
    "корсет",
    "бикини",
    "купальник",
    "lingerie",
    "underwear",
    "bra",
    "thong",
    "stockings",
    "garter",
    "corset",
    "bikini",
    "swimsuit",
}

BANANA_IMAGE_SERVICES = {
    "banana_pro",
    "banana_2",
    "nanobanana",
    "nano-banana-2-lite",
}


def _get_image_provider_model(img_service: str, reference_images: list[str]) -> str:
    """Return provider-facing model identifier for routing logs."""
    if img_service == "nano-banana-2-lite":
        return "nano-banana-2-lite"
    if img_service == "banana_2":
        return "nano-banana-2"
    if img_service in {"banana_pro", "nanobanana"}:
        return "nano-banana-pro"
    if img_service == "seedream_edit":
        return "seedream/4.5-edit"
    if img_service == "seedream_5_pro":
        return (
            "seedream/5-pro-image-to-image"
            if reference_images
            else "seedream/5-pro-text-to-image"
        )
    if img_service == "flux_pro":
        return (
            "gpt-image-2-image-to-image"
            if reference_images
            else "gpt-image-2-text-to-image"
        )
    if img_service in {"seedream", "seedream_45"}:
        return "google/gemini-pro"
    if img_service == "grok_imagine_i2i":
        return "grok-imagine-image-to-image"
    if img_service == "wan_27":
        return "wan/2-7-image-pro"
    return img_service


def _infer_image_aspect_ratio_from_prompt(prompt: str) -> Optional[str]:
    """Infer a single explicit aspect ratio mentioned in the prompt."""
    normalized = (prompt or "").replace("∶", ":")
    if not normalized:
        return None

    found: list[str] = []
    seen: set[str] = set()
    for left, right in re.findall(r"(?<!\d)(\d{1,2})\s*:\s*(\d{1,2})(?!\d)", normalized):
        ratio = f"{left}:{right}"
        if ratio in BANANA_IMAGE_ASPECT_RATIOS and ratio not in seen:
            found.append(ratio)
            seen.add(ratio)

    return found[0] if len(found) == 1 else None


def _resolve_image_aspect_ratio(img_service: str, img_ratio: str, prompt: str) -> str:
    """Keep provider aspect_ratio aligned with a single explicit ratio in the prompt."""
    ratio = str(img_ratio or "1:1").replace("∶", ":").strip() or "1:1"
    if img_service not in BANANA_IMAGE_SERVICES:
        return ratio

    prompt_ratio = _infer_image_aspect_ratio_from_prompt(prompt)
    if prompt_ratio and ratio in {"1:1", "auto"} and prompt_ratio != ratio:
        logger.info(
            "Image aspect ratio inferred from prompt for %s: %s -> %s",
            img_service,
            ratio,
            prompt_ratio,
        )
        return prompt_ratio

    return ratio


def _get_max_image_references(img_service: str | None) -> int:
    normalized = str(img_service or "").strip()
    if normalized == "seedream_5_pro":
        return 5
    if normalized in {"seedream_edit", "flux_pro", "wan_27", "grok_imagine_i2i"}:
        return 9
    return 8


def _classify_image_generation_result(result) -> tuple[str, Optional[str]]:
    """Normalize provider responses into queued/done/failed states."""
    if isinstance(result, dict):
        if result.get("image_bytes"):
            return "done", None
        if result.get("task_id"):
            return "queued", None
        error_message = result.get("message") or result.get("error") or str(result)
        return "failed", make_user_friendly_generation_error(error_message)
    if isinstance(result, (bytes, bytearray)):
        return "done", None
    if result:
        return "failed", make_user_friendly_generation_error(
            f"Unexpected result type: {type(result).__name__}"
        )
    return "failed", None


def _enforce_generation_prompt_policy(prompt: str, *, medium: str) -> Optional[str]:
    """Local prompt moderation is disabled; let the upstream provider decide."""
    return None


def _enforce_image_prompt_policy(prompt: str) -> Optional[str]:
    return _enforce_generation_prompt_policy(prompt, medium="image")


def _enforce_video_prompt_policy(prompt: str) -> Optional[str]:
    return _enforce_generation_prompt_policy(prompt, medium="video")


NO_REFERENCE_CONFIRM_PREFIXES = (
    "без рефа:",
    "без референса:",
    "без фото:",
    "no ref:",
    "no reference:",
)


def _extract_no_reference_confirmation(prompt: str) -> tuple[str, bool]:
    value = (prompt or "").strip()
    lower = value.lower()
    for prefix in NO_REFERENCE_CONFIRM_PREFIXES:
        if lower.startswith(prefix):
            return value[len(prefix):].strip(), True
    return value, False


def _prompt_expects_reference_image(prompt: str) -> bool:
    text = f" {(prompt or '').lower()} "
    phrases = (
        "референс",
        "реф ",
        "рефа",
        "рефом",
        "рефу",
        "фото референс",
        "фото-референс",
        "как на фото",
        "как в фото",
        "по фото",
        " с фото ",
        " с фотографии ",
        "по моему фото",
        "по моей фотографии",
        "моё фото",
        "мое фото",
        "загруженное фото",
        "загруженному фото",
        "исходное фото",
        "исходник",
        "не меняя черты лица",
        "не меняй черты лица",
        "сохрани лицо",
        "сохранить лицо",
        "сохрани черты",
        "сохранить черты",
        "сохранить сходство",
        "сохрани сходство",
        "same face",
        "keep face",
        "preserve face",
        "reference photo",
        "reference image",
        "uploaded photo",
        "uploaded image",
    )
    return any(phrase in text for phrase in phrases)


def _apply_safe_prompt_framing(
    img_service: str, prompt: str, *, has_reference_images: bool = False
) -> str:
    """Reduce false positives for benign fashion/editorial prompts without bypassing policy."""
    prompt = (prompt or "").strip()
    if not prompt:
        return prompt
    if img_service not in {
        *BANANA_IMAGE_SERVICES,
        "seedream_edit",
        "seedream_5_pro",
        "grok_imagine_i2i",
        "wan_27",
    }:
        return prompt

    garment_patterns = {
        r"\blingerie\b",
        r"\bunderwear\b",
        r"\bbra\b",
        r"\bthong\b",
        r"\bstockings\b",
        r"\bgarter\b",
        r"\bнижн(?:ее|ем|его|ей|юю|им)\s+бель[еёя]\b",
        r"\bбелье\b",
        r"\bбельё\b",
        r"\bбелья\b",
        r"\bбюстгальтер\b",
        r"\bлиф(?:чик|а|ом|е)?\b",
        r"\bстринг\w*\b",
        r"\bчулк\w*\b",
        r"\bкорсет\w*\b",
        r"\bбоди\b",
    }
    nudity_patterns = {
        r"\bnude\b",
        r"\bnaked\b",
        r"\btopless\b",
        r"\bbreast?s?\b",
        r"\bnipple?s?\b",
        r"\bbutt(?:ocks)?\b",
        r"\bcrotch\b",
        r"\bcleavage\b",
        r"\bbust\b",
        r"\bvoluptuous\b",
        r"\bsensual\b",
        r"\bsultry\b",
        r"\bseductive\b",
        r"\bhourglass\b",
        r"\bобнаженн\w*\b",
        r"\bгол(?:ый|ая|ое|ые|ого|ой|ую|ым|ыми|ых|ому|ом)\b",
        r"\bголыш\w*\b",
        r"\bобнаж\w*\b",
        r"\bсоск\w*\b",
        r"\bгруд\w*\b",
        r"\bягодиц\w*\b",
        r"\bпромежност\w*\b",
        r"\bпышн\w*\s+груд\w*\b",
        r"\bпышн\w*\s+бюст\w*\b",
        r"\bбюст\w*\b",
        r"\bдекольт\w*\b",
        r"\bчувствен\w*\b",
        r"\bсоблазнительн\w*\b",
        r"\bэротичес\w*\b",
        r"\bманящ\w*\b",
    }
    preserve_garment_terms = img_service in {
        *BANANA_IMAGE_SERVICES,
        "seedream_edit",
        "seedream_5_pro",
        "wan_27",
    } and has_reference_images
    preserve_nudity_terms = img_service in {*BANANA_IMAGE_SERVICES, "wan_27"} and has_reference_images

    replacements = [
        (r"\blingerie\b", "fashion outfit"),
        (r"\bunderwear\b", "fashion outfit"),
        (r"\bbra\b", "top"),
        (r"\bthong\b", "swimwear bottom"),
        (r"\bstockings\b", "fashion stockings"),
        (r"\bgarter\b", "fashion accessory"),
        (r"\bnude\b", "editorial"),
        (r"\bnaked\b", "editorial"),
        (r"\btopless\b", "covered fashion top"),
        (r"\bbreast?s?\b", "silhouette"),
        (r"\bnipple?s?\b", "upper outfit details"),
        (r"\bbutt(?:ocks)?\b", "body line"),
        (r"\bcrotch\b", "lower silhouette"),
        (r"\bнижн(?:ее|ем|его|ей|юю|им)\s+бель[еёя]\b", "модный образ"),
        (r"\bбелье\b", "модный образ"),
        (r"\bбельё\b", "модный образ"),
        (r"\bбелья\b", "модный образ"),
        (r"\bбикини\b", "resort fashion outfit"),
        (r"\bбюстгальтер\b", "топ"),
        (r"\bлиф(?:чик|а|ом|е)?\b", "топ"),
        (r"\bстринг\w*\b", "низ от купального образа"),
        (r"\bчулк\w*\b", "fashion-чулки"),
        (r"\bкорсет\w*\b", "fashion-корсет"),
        (r"\bбоди\b", "fashion-образ"),
        (r"\bлеж(?:ит|ат|ащ\w*|а)\b", "отдыхает"),
        (r"\bвытянут\w*\s+ног\w*,\s*отдыхающ\w*", "курортных деталей"),
        (r"\bвытянут\w*\s+ног\w*\b", "деталей курортной композиции"),
        (r"\bног[аиу]\b", "детали нижнего кадра"),
        (r"\bглянцев\w*\s+естественн\w*\s+губ\w*\b", "естественные черты нижней части лица"),
        (r"\bгуб\w*\b", "черты нижней части лица"),
        (r"\bлини[яю]\s+челюст\w*\b", "нижняя линия лица"),
        (r"\bчелюст\w*\b", "нижняя линия лица"),
        (r"\bплечах\s+и\s+ключицах\b", "образе и деталях кадра"),
        (r"\bплеч\w*\b", "верхней части образа"),
        (r"\bключиц\w*\b", "деталях образа"),
        (r"\bглубок\w*\s+бронзов\w*\s+загар\w*\b", "теплая бронзовая палитра"),
        (r"\bзагорел\w*\s+кож\w*\b", "теплый бронзовый тон кожи"),
        (r"\bзагар\w*\b", "бронзовый тон"),
        (r"\bсолнцезащитн\w*\s+крем\w*\b", "курортного света"),
        (r"\bглянцев\w*\s+отражени\w*\b", "мягкие световые отражения"),
        (r"\bглянцев\w*\s+блик\w*\b", "мягкие световые блики"),
        (r"\bглянцев\w*\s+блеск\w*\b", "естественный световой блеск"),
        (r"\bглянцев\w*\b", "мягкий световой"),
        (r"\bбудуар\w*\b", "soft editorial"),
        (r"\bглубок\w*\s+вырез\w*\b", "аккуратный fashion-вырез"),
        (r"\bпрозрачн\w*\b", "текстурный"),
        (r"\bобнаженн\w*\b", "editorial"),
        (r"\bгол(?:ый|ая|ое|ые|ого|ой|ую|ым|ыми|ых|ому|ом)\b", "editorial"),
        (r"\bголыш\w*\b", "editorial"),
        (r"\bобнаж\w*\b", "editorial"),
        (r"\bсоск\w*\b", "детали верхней части образа"),
        (r"\bгруд\w*\b", "силуэт"),
        (r"\bягодиц\w*\b", "линии фигуры"),
        (r"\bпромежност\w*\b", "нижний силуэт"),
        (r"\bпирсинг\s+пупка\b", "аксессуар на талии"),
        (r"\bпупок\b", "талия"),
        (r"\bязык\b", "выражение лица"),
        (r"\bоблизывает?\s+пал(?:ец|ьцы)\b", "касается пальца губами"),
        (r"\bcleavage\b", "neckline"),
        (r"\bbust\b", "upper silhouette"),
        (r"\bhourglass\s+figure\b", "balanced proportions"),
        (r"\bcurvy\b", "balanced silhouette"),
        (r"\bvoluptuous\b", "editorial silhouette"),
        (r"\bsensual\b", "editorial"),
        (r"\bsultry\b", "editorial"),
        (r"\bseductive\b", "confident"),
        (r"\bhourglass\b", "balanced"),
        (r"\bпышн\w*\s+груд\w*\b", "выразительный верхний силуэт"),
        (r"\bпышн\w*\s+бюст\w*\b", "выразительный верхний силуэт"),
        (r"\bбюст\w*\b", "верхний силуэт"),
        (r"\bдекольт\w*\b", "линия выреза"),
        (r"\bпесочн\w*\s+час\w*\b", "сбалансированные пропорции"),
        (r"\bширок\w*\s+бед\w*\b", "выразительный силуэт"),
        (r"\bокругл\w*\s+бед\w*\b", "плавный силуэт"),
        (r"\bупруг\w*\s+ягодиц\w*\b", "подтянутый силуэт"),
        (r"\bузк\w*\s+тал\w*\b", "четкий силуэт талии"),
        (r"\bплоск\w*\s+живот\w*\b", "ровный силуэт живота"),
        (r"\b\d+\s+размер(?:а|ом|е|у)?\b", "editorial proportions"),
        (r"\bвлажн\w*\s+сияни\w*\s+кож\w*\b", "мягкое сияние кожи"),
        (r"\bмасло\/вода\b", "soft glow"),
        (r"\bчувствен\w*\b", "editorial"),
        (r"\bсоблазнительн\w*\b", "уверенный editorial-акцент"),
        (r"\bэротичес\w*\b", "editorial"),
        (r"\bманящ\w*\b", "игривый акцент"),
    ]
    normalized = prompt
    for pattern, replacement in replacements:
        if preserve_garment_terms and pattern in garment_patterns:
            continue
        if preserve_nudity_terms and pattern in nudity_patterns:
            continue
        normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)

    selfie_instruction = ""
    if _prompt_requests_selfie_without_visible_device(prompt):
        selfie_instruction = (
            "Selfie means front-camera style only; do not show a phone, mirror, "
            "visible camera, or hand holding a device unless explicitly requested. "
        )

    if img_service == "wan_27":
        # Wan 2.7 — отправляем промпт как есть, без safety-префикса.
        # Модель сама должна следовать описанию пользователя (включая undress/nudity),
        # а эвфемизмы "editorial" только мешают и заставляют её одевать персонажа.
        return f"{selfie_instruction}{normalized}"
    elif preserve_nudity_terms:
        safety_prefix = (
            "Follow the user's prompt exactly. "
            "Execute the requested scene, styling, composition, lighting, pose, and coverage level precisely as described. "
            "Preserve the content and intent of the user's description without adding or removing visual coverage. "
        )
    elif preserve_garment_terms:
        safety_prefix = (
            "Reference-first editorial styling. "
            "Treat referenced garments as clothing and design details. "
            "Treat the referenced outfit, garment cut, accessories, styling, and coverage level as intentional visual details. "
            "Preserve the clothing and how it is worn from the main reference unless the user explicitly asks to change outfit or coverage. "
            "Focus on matching the referenced look, materials, fit, pose intent, and composition. "
        )
    else:
        safety_prefix = (
            "Editorial fashion or product framing. "
            "Follow the user's requested styling, composition, lighting, and materials without inventing unnecessary wardrobe changes. "
        )
    normalized_lower = normalized.lower()
    framing_prefixes = (
        "safe, non-explicit editorial image",
        "editorial fashion or product framing.",
        "editorial fashion styling.",
    )
    if normalized_lower.startswith(framing_prefixes):
        return f"{selfie_instruction}{normalized}"
    if normalized.startswith("EDIT REQUEST (highest priority):"):
        safety_suffix = safety_prefix.strip()
        selfie_suffix = selfie_instruction.strip()
        suffix = " ".join(part for part in [safety_suffix, selfie_suffix] if part)
        return f"{normalized}\n\n{suffix}"
    return f"{safety_prefix}{selfie_instruction}{normalized}"


def _prompt_requests_selfie_without_visible_device(prompt: str) -> bool:
    text = f" {(prompt or '').lower()} "
    if "selfie" not in text and "селфи" not in text:
        return False
    explicit_device_terms = (
        "phone",
        "smartphone",
        "iphone",
        "camera",
        "mirror",
        "телефон",
        "смартфон",
        "айфон",
        "камера",
        "зеркал",
    )
    return not any(term in text for term in explicit_device_terms)


def _build_compact_reference_guidance(prompt: str, reference_images: list[str]) -> str:
    prompt = (prompt or "").strip()
    guidance_lines = [
        "Use the uploaded image as a visual reference, not as a locked pose.",
        "Keep the main subject recognizable from the first reference.",
        "Treat the first reference as the primary person identity: preserve the face shape, eyes, nose, lips, hairline, age impression, and distinctive facial features.",
        "Preserve the outfit, garment cut, accessories, styling, and coverage level from the main reference unless the user explicitly asks to change them.",
        "Follow the user's requested scene, pose, outfit, lighting, framing, and style.",
        "Keep visible text out of the image unless the user explicitly asks for typography.",
    ]
    if len(reference_images) > 1:
        guidance_lines.insert(
            2,
            "Use additional references for requested clothing, accessories, products, pose, style, colors, or scene cues; if another person appears there, use visual cues only unless the user asks for multiple people.",
        )
    guidance = " ".join(guidance_lines)
    if prompt:
        return f"EDIT REQUEST (highest priority): {prompt}\n\nReference guidance: {guidance}"
    return f"Reference guidance: {guidance}"


def _build_wan27_reference_guidance(prompt: str, reference_images: list[str]) -> str:
    """Wan 2.7-specific reference guidance: preserve identity, but do not force clothing/coverage from reference."""
    prompt = (prompt or "").strip()
    guidance_lines = [
        "Use the uploaded image as a visual reference for identity and composition, not as a locked pose.",
        "Keep the main subject recognizable from the first reference.",
        "Treat the first reference as the primary person identity: preserve the face shape, eyes, nose, lips, hairline, age impression, and distinctive facial features.",
        "Follow the user's requested scene, pose, outfit, lighting, framing, style, and coverage level exactly as described in the prompt.",
        "Do not force clothing or visual coverage from the reference unless the user's prompt explicitly requests it.",
        "Keep visible text out of the image unless the user explicitly asks for typography.",
    ]
    if len(reference_images) > 1:
        guidance_lines.insert(
            3,
            "Use additional references for requested clothing, accessories, products, pose, style, colors, or scene cues; if another person appears there, use visual cues only unless the user asks for multiple people.",
        )
    guidance = " ".join(guidance_lines)
    if prompt:
        return f"EDIT REQUEST (highest priority): {prompt}\n\nReference guidance: {guidance}"
    return f"Reference guidance: {guidance}"


def _build_banana_reference_guidance(prompt: str, reference_images: list[str]) -> str:
    """Banana-specific reference guidance: preserve only identity from the first reference."""
    prompt = (prompt or "").strip()
    guidance_lines = [
        "The requested edit is mandatory and must be clearly visible in the output. Returning the input image unchanged is an invalid result.",
        "Any attribute explicitly named in the edit request is excluded from preservation and must be replaced exactly as requested.",
        "For a hair edit, visibly replace the original hair length, hairstyle, texture, or color specified by the user while keeping the face and person identity unchanged.",
        "Preserve the same person while applying the mandatory edit: the output must depict the person from the first uploaded image, not a lookalike and not a newly invented face.",
        "This is an edit of the first uploaded image, not a request to invent a new composition: change only the details explicitly requested by the user and keep all other visible details unchanged.",
        "Use the first uploaded image only as the primary person identity reference.",
        "Preserve only the person's identity, but preserve facial identity exactly: face shape, facial geometry, eyes, eyebrows, nose, lips, cheekbones, jawline, hairline, age impression, skin tone, asymmetry, and distinctive facial features.",
        "Preserve hair color, hair length, and hairstyle from the first reference unless the user explicitly asks to change them.",
        "Follow the user's prompt for clothing, outfit, body styling, scene, pose, lighting, framing, and style, and apply those edits to that same person.",
        "Do not preserve or copy clothing, outfit, accessories, pose, body shape, background, lighting, camera angle, or visual coverage from the reference unless the user explicitly asks for those details.",
    ]
    if len(reference_images) > 1:
        guidance_lines.insert(
            3,
            "Use additional references only for identity if the user explicitly asks for multiple people; otherwise ignore non-identity details from additional references.",
        )
    guidance = " ".join(guidance_lines)
    if prompt:
        return f"EDIT REQUEST (highest priority): {prompt}\n\nReference guidance: {guidance}"
    return f"Reference guidance: {guidance}"


def _apply_reference_detail_preservation(
    img_service: str, prompt: str, reference_images: list[str]
) -> str:
    """For reference-based generation, preserve identity without suppressing edits."""
    prompt = (prompt or "").strip()
    if not reference_images or img_service not in BANANA_IMAGE_SERVICES:
        return prompt
    return _build_banana_reference_guidance(prompt, reference_images)


def _build_image_variant_prompt(
    prompt: str, variant_index: int, total_count: int
) -> str:
    """Add controlled variation for multi-image batches while keeping references."""
    prompt = (prompt or "").strip()
    if total_count <= 1:
        return prompt

    variants = [
        "Use a slightly different composition and camera crop only. Keep the referenced face exactly identical: same facial geometry, eyes, nose, lips, skin texture, asymmetry, age signs, hairline, and all distinctive facial details.",
        "Use a slightly different camera angle and framing only. Keep the referenced face exactly identical: same facial geometry, eyes, nose, lips, skin texture, asymmetry, age signs, hairline, and all distinctive facial details.",
        "Use a subtle lighting/framing variation only. Keep the referenced face exactly identical: same facial geometry, eyes, nose, lips, skin texture, asymmetry, age signs, hairline, and all distinctive facial details.",
        "Use a different crop and background depth only. Keep the referenced face exactly identical: same facial geometry, eyes, nose, lips, skin texture, asymmetry, age signs, hairline, and all distinctive facial details.",
    ]
    instruction = variants[variant_index % len(variants)]
    return (
        f"{prompt}\n\n"
        f"For this single output: {instruction} "
        "Do not render batch numbers, labels, prompt text, file names, URLs, or UI text in the image."
    )


def _format_prompt_caption_line(prompt: str | None, *, hidden: bool = False, limit: int = 700) -> str:
    if hidden:
        return "\n\n📝 <b>Промпт:</b> скрыт, это повтор из ленты"
    prompt_text = str(prompt or "").strip()
    if not prompt_text:
        return ""
    if len(prompt_text) > limit:
        prompt_text = prompt_text[: limit - 1].rstrip() + "…"
    return f"\n\n📝 <b>Промпт:</b>\n<pre>{html.escape(prompt_text)}</pre>"


def _format_public_task_id_lines(provider_task_id: str | None, local_task_id: str | None = None) -> tuple[str, str]:
    provider_id = str(provider_task_id or "").strip()
    local_id = str(local_task_id or "").strip()
    public_id = local_id or provider_id
    provider_line = ""
    if provider_id and provider_id != public_id:
        provider_line = f"• ID провайдера: <code>{html.escape(provider_id)}</code>\n"
    return html.escape(public_id), provider_line



async def _send_used_prompt_message_to_chat(
    send_message,
    prompt: str | None,
    *,
    task_id: str | None,
    model_label: str | None = None,
    hidden: bool = False,
) -> None:
    if hidden:
        return
    prompt_text = str(prompt or "").strip()
    if not prompt_text:
        return
    header = "📝 <b>Использованный промпт</b>\n"
    if task_id:
        header += f"ID: <code>{html.escape(str(task_id))}</code>\n"
    if model_label:
        header += f"Модель: <code>{html.escape(str(model_label))}</code>\n"
    header += "\n"

    def block(chunk: str) -> str:
        return f"<blockquote expandable><code>{html.escape(chunk)}</code></blockquote>"

    first_budget = max(500, 3900 - len(header) - 80)
    if len(prompt_text) <= first_budget:
        await send_message(header + block(prompt_text), parse_mode="HTML")
        return

    await send_message(header + block(prompt_text[:first_budget]), parse_mode="HTML")
    rest = prompt_text[first_budget:]
    chunk_size = 3200
    for idx, start in enumerate(range(0, len(rest), chunk_size), start=2):
        chunk = rest[start:start + chunk_size]
        await send_message(
            f"📝 <b>Промпт, продолжение {idx}</b>\n\n{block(chunk)}",
            parse_mode="HTML",
        )


def _snapshot_reference_images(reference_images: list[str] | None) -> list[str]:
    """Freeze the exact reference set for every launched image task."""
    if not reference_images:
        return []
    seen: set[str] = set()
    normalized: list[str] = []
    for image in reference_images:
        value = str(image).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _available_reference_images(
    reference_images: list[str] | None,
) -> tuple[list[str], list[str]]:
    normalized = _snapshot_reference_images(reference_images)
    missing = missing_local_upload_sources(normalized)
    if not missing:
        return normalized, []

    available = [
        str(source).strip()
        for source in filter_available_image_sources(normalized)
        if isinstance(source, str) and str(source).strip()
    ]
    return _snapshot_reference_images(available), missing


def _source_reference_images_from_request(request_data: dict) -> list[str]:
    """Return user-provided refs, excluding generated contact sheets."""
    source_refs = request_data.get("source_reference_images")
    if source_refs:
        return _snapshot_reference_images(source_refs)

    return [
        ref
        for ref in _snapshot_reference_images(request_data.get("reference_images", []))
        if not is_reference_contact_sheet_url(ref)
    ]


def _can_inherit_repeat_source_references(task: Any, viewer_user_id: int | None) -> bool:
    try:
        owner_id = int(getattr(task, "user_id", None) or 0)
    except (TypeError, ValueError):
        owner_id = 0
    try:
        viewer_id = int(viewer_user_id or 0)
    except (TypeError, ValueError):
        viewer_id = 0
    return bool(owner_id and viewer_id and owner_id == viewer_id)


def _is_identity_sensitive_prompt(prompt: str) -> bool:
    text = f" {(prompt or '').lower()} "
    keywords = (
        "person",
        "people",
        "human",
        "face",
        "portrait",
        "woman",
        "man",
        "girl",
        "boy",
        "model",
        "character",
        "selfie",
        "человек",
        "люди",
        "лицо",
        "портрет",
        "селфи",
        "девуш",
        "женщ",
        "мужчин",
        "парн",
        "модель",
        "персонаж",
        "герой",
        "героиня",
    )
    return any(keyword in text for keyword in keywords)


def _prepare_banana_reference_images(
    img_service: str, reference_images: list[str] | None, prompt: str = ""
) -> list[str]:
    normalized = _snapshot_reference_images(reference_images)
    if img_service not in {*BANANA_IMAGE_SERVICES, "seedream_edit", "seedream_5_pro"}:
        return normalized
    max_refs = 5 if img_service in {"seedream_edit", "seedream_5_pro"} else 8
    direct_refs = [
        ref for ref in normalized if not is_reference_contact_sheet_url(ref)
    ]
    return direct_refs[:max_refs]


def _resolve_image_unit_cost(img_service: str, img_quality: str) -> float:
    quality_value = str(img_quality or "").strip()
    quality_upper = quality_value.upper()
    if img_service in {
        "banana_pro",
        "nano_banana_pro",
        "nano-banana-pro",
        "banana_2",
        "nanobanana",
    }:
        return QUALITY_COSTS.get(quality_upper, 2)
    if img_service == "seedream_5_pro":
        return SEEDREAM_5_PRO_QUALITY_COSTS.get(
            quality_value,
            SEEDREAM_5_PRO_QUALITY_COSTS.get(quality_upper, 2),
        )
    return preset_manager.get_generation_cost(img_service)


async def _start_image_generation_task(
    *,
    user,
    telegram_id: int,
    img_service: str,
    prompt: str,
    img_ratio: str,
    reference_images: list[str],
    unit_cost: int,
    img_quality: str = "basic",
    img_nsfw_checker: bool = False,
    nsfw_enabled: bool = False,
    callback_url: Optional[str] = None,
    source_feed_gen_id: Optional[int] = None,
    parent_generation_id: Optional[int] = None,
    action_type: Optional[str] = None,
    prompt_source_id: Optional[int] = None,
    on_task_created=None,
):
    """Launch one image generation task and persist enough data for repeats."""
    runtime_img_service = img_service
    policy_error = _enforce_image_prompt_policy(prompt)
    if policy_error:
        logger.warning(
            "Blocked image prompt by policy: user_id=%s telegram_id=%s model=%s prompt_prefix=%s",
            getattr(user, "id", None),
            telegram_id,
            runtime_img_service,
            (prompt or "")[:200],
        )
        return {
            "status": "failed",
            "task_id": None,
            "runtime_img_service": runtime_img_service,
            "error": policy_error,
        }
    img_ratio = _resolve_image_aspect_ratio(runtime_img_service, img_ratio, prompt)
    reference_images, missing_reference_images = _available_reference_images(
        reference_images
    )
    if missing_reference_images:
        logger.warning(
            "Image task blocked before provider call: telegram_id=%s model=%s missing_local_refs=%s sample=%s",
            telegram_id,
            runtime_img_service,
            len(missing_reference_images),
            missing_reference_images[:3],
        )
        return {
            "status": "failed",
            "task_id": None,
            "runtime_img_service": runtime_img_service,
            "error": "missing_local_references",
        }
    source_reference_images = [
        ref for ref in reference_images if not is_reference_contact_sheet_url(ref)
    ]
    reference_images = _prepare_banana_reference_images(
        runtime_img_service, reference_images, prompt
    )
    provider_model = _get_image_provider_model(runtime_img_service, reference_images)
    effective_prompt = (
        _apply_reference_detail_preservation(
            runtime_img_service, prompt, reference_images
        )
        if runtime_img_service in BANANA_IMAGE_SERVICES and reference_images
        else ""
    )
    banana_provider_prompt = effective_prompt or prompt

    local_task_id = f"img_{uuid.uuid4().hex[:12]}"
    request_snapshot = {
        "img_service": img_service,
        "prompt": prompt,
        "img_ratio": img_ratio,
        "reference_images": reference_images,
        "source_reference_images": source_reference_images,
        "img_quality": img_quality,
        "img_nsfw_checker": img_nsfw_checker,
        "nsfw_enabled": nsfw_enabled,
        "provider_model": provider_model,
        "source_feed_gen_id": source_feed_gen_id,
        "parent_generation_id": parent_generation_id,
        "action_type": action_type,
        "prompt_source_id": prompt_source_id,
    }
    if effective_prompt:
        request_snapshot["effective_prompt"] = effective_prompt
    await add_generation_task(
        user.id,
        telegram_id,
        local_task_id,
        "image",
        runtime_img_service,
        model=runtime_img_service,
        aspect_ratio=img_ratio,
        prompt=prompt,
        cost=unit_cost,
        request_data=request_snapshot,
        source_feed_gen_id=source_feed_gen_id,
        parent_generation_id=parent_generation_id,
        action_type=action_type,
    )
    logger.info(
        "Image route: local_task_id=%s selected_model=%s runtime_model=%s provider_model=%s references=%s ratio=%s ref_sample=%s prompt_len=%s",
        local_task_id,
        img_service,
        runtime_img_service,
        provider_model,
        len(reference_images),
        img_ratio,
        reference_images[:3],
        len(prompt or ""),
    )

    if on_task_created:
        try:
            await on_task_created(local_task_id)
        except Exception:
            logger.exception("Image local task notification failed: local_task_id=%s", local_task_id)

    if runtime_img_service in {"banana_2", "nano-banana-2-lite"}:
        image_callback_url = (
            config.kie_market_notification_url
            if runtime_img_service == "nano-banana-2-lite" and config.WEBHOOK_HOST
            else callback_url
        )
        result = await nano_banana_2_service.generate_image(
            prompt=banana_provider_prompt,
            aspect_ratio=img_ratio,
            resolution=img_quality.upper(),
            image_input=reference_images,
            callback_url=image_callback_url,
            model=_get_image_provider_model(runtime_img_service, reference_images),
        )
    elif runtime_img_service in {"banana_pro", "nanobanana"}:
        result = await nano_banana_pro_service.generate_image(
            prompt=banana_provider_prompt,
            aspect_ratio=img_ratio,
            resolution=img_quality.upper(),
            image_input=reference_images,
            callback_url=callback_url,
        )
    elif runtime_img_service in {"seedream_edit", "seedream_5_pro"}:
        if runtime_img_service == "seedream_edit" or reference_images:
            result = await seedream_service.generate_image(
                prompt=prompt,
                model=(
                    "seedream/4.5-edit"
                    if runtime_img_service == "seedream_edit"
                    else "seedream/5-pro-image-to-image"
                ),
                aspect_ratio=img_ratio,
                image_urls=reference_images,
                quality=img_quality,
                nsfw_checker=False,
                callBackUrl=callback_url,
            )
        else:
            result = await seedream_service.generate_text_to_image(
                prompt=prompt,
                model="seedream/5-pro-text-to-image",
                aspect_ratio=img_ratio,
                quality=img_quality,
                callBackUrl=callback_url,
            )
    elif runtime_img_service == "flux_pro":
        if reference_images:
            result = await gpt_image_service.generate_image_to_image(
                prompt=prompt,
                input_urls=reference_images,
                model="gpt-image-2-image-to-image",
                aspect_ratio=img_ratio,
                nsfw_checker=False,
                callBackUrl=callback_url,
            )
        else:
            result = await gpt_image_service.generate_image(
                prompt=prompt,
                model="gpt-image-2-text-to-image",
                aspect_ratio=img_ratio,
                nsfw_checker=False,
                callBackUrl=callback_url,
            )
    elif runtime_img_service in {"seedream", "seedream_45"}:
        result = await gemini_service.generate_image(
            prompt=prompt,
            model="pro",
            aspect_ratio=img_ratio,
            reference_image_urls=reference_images,
        )
    elif runtime_img_service == "grok_imagine_i2i":
        result = await grok_service.generate_image_to_image(
            image_urls=reference_images,
            prompt=prompt,
            nsfw_checker=False,
            callBackUrl=callback_url,
        )
    elif runtime_img_service == "wan_27":
        result = await wan27_service.generate_image(
            prompt=prompt,
            aspect_ratio=img_ratio,
            input_urls=reference_images,
            n=1,
            resolution="2K",
            pro=True,
            enable_sequential=False,
            thinking_mode=False,
            watermark=False,
            seed=random.randint(1, 2147483647),
            nsfw_checker=False,
            callBackUrl=callback_url,
        )
    else:
        result = await nano_banana_pro_service.generate_image(
            prompt=prompt,
            aspect_ratio=img_ratio,
            resolution=img_quality.upper(),
            image_input=reference_images,
            callback_url=callback_url,
        )

    result_status, error_message = _classify_image_generation_result(result)

    if result_status == "queued":
        api_task_id = result["task_id"]
        provider_name = str(result.get("provider") or "").strip()
        provider_model_name = str(result.get("provider_model") or provider_model).strip()
        provider_task_id = str(
            result.get("provider_task_id") or api_task_id or ""
        ).strip()

        async with db_backend.connect() as db:
            db.row_factory = db_backend.Row
            cursor = await db.execute(
                "SELECT request_data FROM generation_tasks WHERE task_id = ? AND user_id = ?",
                (local_task_id, user.id),
            )
            row = await cursor.fetchone()
            request_data = {}
            if row and row["request_data"]:
                try:
                    request_data = json.loads(row["request_data"])
                except Exception:
                    request_data = {}
            request_data = _merge_task_id_aliases(
                request_data,
                local_task_id,
                api_task_id,
                provider_task_id,
            )
            if provider_name:
                request_data["provider"] = provider_name
            if provider_model_name:
                request_data["provider_model"] = provider_model_name
            if provider_task_id:
                request_data["provider_task_id"] = provider_task_id
            await db.execute(
                "UPDATE generation_tasks SET task_id = ?, request_data = ? WHERE task_id = ? AND user_id = ?",
                (api_task_id, json.dumps(request_data, ensure_ascii=False), local_task_id, user.id),
            )
            await db.commit()
        logger.info(
            "Image route confirmed: local_task_id=%s api_task_id=%s selected_model=%s runtime_model=%s provider_model=%s",
            local_task_id,
            api_task_id,
            img_service,
            runtime_img_service,
            provider_model_name,
        )
        return {
            "status": "queued",
            "task_id": api_task_id,
            "local_task_id": local_task_id,
            "runtime_img_service": runtime_img_service,
        }

    if result_status == "done":
        if isinstance(result, dict) and "image_bytes" in result:
            result_bytes = result["image_bytes"]
            provider_task_id = str(
                result.get("provider_task_id") or result.get("task_id") or ""
            ).strip()
            if provider_task_id:
                async with db_backend.connect() as db:
                    db.row_factory = db_backend.Row
                    cursor = await db.execute(
                        "SELECT request_data FROM generation_tasks WHERE task_id = ? AND user_id = ?",
                        (local_task_id, user.id),
                    )
                    row = await cursor.fetchone()
                    request_data = {}
                    if row and row["request_data"]:
                        try:
                            request_data = json.loads(row["request_data"])
                        except Exception:
                            request_data = {}
                    request_data = _merge_task_id_aliases(
                        request_data,
                        local_task_id,
                        provider_task_id,
                    )
                    await db.execute(
                        "UPDATE generation_tasks SET request_data = ? WHERE task_id = ? AND user_id = ?",
                        (json.dumps(request_data, ensure_ascii=False), local_task_id, user.id),
                    )
                    await db.commit()
        else:
            result_bytes = bytes(result)
            provider_task_id = ""
        saved_url = save_uploaded_file(result_bytes, "png")
        await complete_video_task(local_task_id, saved_url)
        return {
            "status": "done",
            "task_id": local_task_id,
            "provider_task_id": provider_task_id,
            "result_bytes": result_bytes,
            "saved_url": saved_url,
            "runtime_img_service": runtime_img_service,
        }

    if error_message:
        logger.error(
            "Image generation failed before queueing: local_task_id=%s selected_model=%s runtime_model=%s provider_model=%s error=%s",
            local_task_id,
            img_service,
            runtime_img_service,
            provider_model,
            error_message,
        )
    await complete_video_task(local_task_id, None)
    return {
        "status": "failed",
        "task_id": local_task_id,
        "runtime_img_service": runtime_img_service,
    }


# =============================================================================
# НОВЫЙ UX: МЕНЮ СОЗДАНИЯ ВИДЕО (get_create_video_keyboard)
# =============================================================================


@router.callback_query(F.data == "create_video_new")
async def show_create_video_menu(callback: types.CallbackQuery, state: FSMContext):
    """Пошаговый вход в видео: модель -> настройки/медиа/промпт."""
    await _init_default_video_state(state)
    await state.update_data(video_flow_step="select_model")
    await _show_video_model_selection_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "create_image_refs_new")
async def show_create_image_menu(callback: types.CallbackQuery, state: FSMContext):
    """Показывает меню создания фото - начинаем с загрузки референсов"""
    user_credits = await get_user_credits(callback.from_user.id)

    # Инициализируем опции по умолчанию
    await state.update_data(**_default_image_flow_data(img_flow_step="upload_refs"))

    # Показываем экран загрузки референсов (ШАГ 1)
    text = (
        "🖼 <b>Создание фото</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code> бананов\n\n"
        "<b>Шаг 1. Референсы</b>\n"
        "Этот шаг можно пропустить.\n"
        "Фото-референсы помогают, если важно:\n"
        "• сохранить внешность человека или предмета\n"
        "• повторить стиль и детали\n"
        "• опираться на конкретный исходник\n\n"
        "<i>Можно загрузить до 9 фото.</i>\n"
        "Когда всё готово, нажмите <b>▶️ Продолжить</b>.\n"
        "Если референсы не нужны — выберите <b>⏭ Пропустить</b>."
    )
    try:
        await callback.message.edit_text(
            text,
            reply_markup=get_reference_images_upload_keyboard(0, _get_max_image_references("banana_pro"), "new"),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            text,
            reply_markup=get_reference_images_upload_keyboard(0, _get_max_image_references("banana_pro"), "new"),
            parse_mode="HTML",
        )
    await callback.answer()
    await state.set_state(GenerationStates.uploading_reference_images)


@router.callback_query(F.data == "create_image_text_new")
async def show_create_image_text_menu(callback: types.CallbackQuery, state: FSMContext):
    """Пошаговый вход в фото: модель -> референсы -> настройки."""
    await state.update_data(**_default_image_flow_data(img_flow_step="select_model"))
    await _show_image_model_selection_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "model_wan_27")
async def select_model_wan_27(callback: types.CallbackQuery, state: FSMContext):
    """Select Wan 2.7 Pro and open reference upload step."""
    logger.info("Wan 2.7 selected by user_id=%s", callback.from_user.id)
    user_credits = await get_user_credits(callback.from_user.id)

    await state.update_data(
        generation_type="image",
        img_service="wan_27",
        img_ratio="1:1",
        img_count=1,
        reference_images=[],
        img_quality="2K",
        img_nsfw_checker=False,
        nsfw_enabled=False,
        preset_id="new",
        img_flow_step="refs",
    )
    await state.set_state(GenerationStates.uploading_reference_images)

    text = (
        "🧪 <b>Wan 2.7 Pro — тест</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code> бананов\n\n"
        "<b>Шаг 1. Референсы</b>\n"
        "Загрузите фото, если хотите проверить редактирование или генерацию по исходнику.\n"
        "Можно загрузить до 9 фото.\n\n"
        "Если референсы не нужны — нажмите <b>⏭ Пропустить</b>.\n"
        "Когда всё готово — нажмите <b>✅ Продолжить</b>."
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_reference_images_upload_keyboard(0, _get_max_image_references("wan_27"), "new"),
        parse_mode="HTML",
    )
    await callback.answer("Wan 2.7 Pro выбран")


async def _restore_image_task_to_state(
    task,
    state: FSMContext,
    *,
    include_references: bool = True,
    repeat_source_task_id: str | None = None,
    hide_prompt: bool = False,
) -> tuple[bool, str | None]:
    if not task or task.type != "image":
        return False, "Не удалось найти данные задачи."

    try:
        request_data = json.loads(task.request_data) if task.request_data else {}
    except Exception:
        return False, "Данные исходной задачи повреждены."

    img_service = request_data.get("img_service", task.model or "banana_pro")
    img_ratio = request_data.get("img_ratio", task.aspect_ratio or "1:1")
    original_reference_images = _source_reference_images_from_request(request_data)
    img_quality = request_data.get("img_quality", "2K")
    img_nsfw_checker = bool(request_data.get("img_nsfw_checker", False))
    nsfw_enabled = bool(request_data.get("nsfw_enabled", False))
    prompt = request_data.get("prompt", task.prompt or "")

    await state.clear()
    available_reference_images, missing_reference_images = _available_reference_images(
        original_reference_images
    )
    reference_images = available_reference_images if include_references else []
    updates = {
        "generation_type": "image",
        "img_service": img_service,
        "img_ratio": img_ratio,
        "img_count": 1,
        "reference_images": reference_images,
        "img_quality": img_quality,
        "img_nsfw_checker": img_nsfw_checker,
        "nsfw_enabled": nsfw_enabled,
        "preset_id": "new",
        "img_flow_step": "configure",
    }
    if include_references and missing_reference_images:
        updates["repeat_missing_ref_count"] = len(missing_reference_images)
    if repeat_source_task_id:
        updates.update(
            {
                "repeat_source_task_id": repeat_source_task_id,
                "repeat_prompt": prompt,
                "repeat_prompt_hidden": bool(hide_prompt),
                "repeat_unit_cost": task.cost or 0,
                "repeat_original_ref_count": len(original_reference_images),
                "repeat_inherited_reference_count": len(reference_images),
                "repeat_user_references_replaced": False,
            }
        )
    await state.update_data(**updates)
    await state.set_state(GenerationStates.waiting_for_input)
    return True, None


@router.callback_query(F.data.startswith("retry_prompt_image_"))
async def retry_image_with_new_prompt(callback: types.CallbackQuery, state: FSMContext):
    """Открывает тот же image flow с теми же референсами и настройками, но ждёт новый промпт."""
    task_id = callback.data.replace("retry_prompt_image_", "", 1)
    task = await get_task_by_id(task_id)

    restored, error_message = await _restore_image_task_to_state(task, state)
    if not restored:
        await callback.answer(error_message or "Не удалось открыть повтор.", show_alert=True)
        return

    await _show_image_creation_screen(callback, state)
    data = await state.get_data()
    if data.get("repeat_missing_ref_count"):
        await callback.answer(
            "Часть старых фото уже очищена — добавьте фото заново",
            show_alert=True,
        )
    else:
        await callback.answer("Отправь новый промпт — рефы и настройки сохранены")


_GROK_LEGACY_VIDEO_RATIOS = {"16:9", "9:16", "1:1", "3:2", "2:3"}
_GROK_V15_VIDEO_RATIOS = {
    "auto",
    "16:9",
    "9:16",
    "1:1",
    "4:3",
    "3:4",
    "3:2",
    "2:3",
}
_GROK_VIDEO_MODELS = {"grok_imagine", "grok_imagine_v15"}


def _grok_video_ratio_from_image_task(task, model: str = "grok_imagine") -> str:
    ratio = str(getattr(task, "aspect_ratio", "") or "").strip()
    if model == "grok_imagine_v15":
        return ratio if ratio in _GROK_V15_VIDEO_RATIOS else "auto"
    return ratio if ratio in _GROK_LEGACY_VIDEO_RATIOS else "16:9"


def _publication_confirm_keyboard(confirm_data: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтверждаю", callback_data=confirm_data)
    builder.button(text="❌ Отмена", callback_data="ignore")
    builder.adjust(1, 1)
    return builder.as_markup()


def _feed_publication_keyboard(
    task_id: int | str,
    *,
    prompt_visible: bool = False,
    references_visible: bool = False,
    blurred: bool = False,
) -> types.InlineKeyboardMarkup:
    task_value = str(task_id)
    prompt_flag = int(bool(prompt_visible))
    refs_flag = int(bool(references_visible))
    blur_flag = int(bool(blurred))
    prompt_icon = "✅" if prompt_visible else "🔒"
    refs_icon = "✅" if references_visible else "🔒"
    blur_icon = "✅" if blurred else "👁"
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"{prompt_icon} Prompt",
        callback_data=f"feedpubopt_{task_value}_{1 - prompt_flag}_{refs_flag}_{blur_flag}",
    )
    builder.button(
        text=f"{refs_icon} Референсы",
        callback_data=f"feedpubopt_{task_value}_{prompt_flag}_{1 - refs_flag}_{blur_flag}",
    )
    builder.button(
        text=f"{blur_icon} Blur",
        callback_data=f"feedpubopt_{task_value}_{prompt_flag}_{refs_flag}_{1 - blur_flag}",
    )
    builder.button(
        text="✅ Опубликовать",
        callback_data=f"feedpubok_{task_value}_{prompt_flag}_{refs_flag}_{blur_flag}",
    )
    builder.button(text="❌ Отмена", callback_data="ignore")
    builder.adjust(2, 1, 1, 1)
    return builder.as_markup()


def _feed_publication_text(
    *,
    prompt_visible: bool = False,
    references_visible: bool = False,
    blurred: bool = False,
) -> str:
    prompt_state = "открыт" if prompt_visible else "скрыт"
    refs_state = "открыты" if references_visible else "скрыты"
    blur_state = "включён" if blurred else "выключен"
    nl = chr(10)
    return (
        _publication_disclaimer_text("feed")
        + nl
        + nl
        + "<b>Что увидят в ленте</b>"
        + nl
        + f"• Prompt: <code>{prompt_state}</code>"
        + nl
        + f"• Референсы: <code>{refs_state}</code>"
        + nl
        + f"• Blur: <code>{blur_state}</code>"
        + nl
        + nl
        + "По умолчанию prompt и референсы закрыты, blur выключен. "
        + "Откройте только то, что автор разрешает показывать."
    )


def _parse_feed_publish_payload(value: str) -> tuple[str, bool, bool, bool]:
    parts = str(value or "").rsplit("_", 3)
    task_id = parts[0] if parts else ""
    prompt_visible = bool(int(parts[1])) if len(parts) == 4 and parts[1] in {"0", "1"} else False
    references_visible = bool(int(parts[2])) if len(parts) == 4 and parts[2] in {"0", "1"} else False
    blurred = bool(int(parts[3])) if len(parts) == 4 and parts[3] in {"0", "1"} else False
    return task_id, prompt_visible, references_visible, blurred


def _published_feed_link(bot_username: str | None, card: dict) -> str:
    return feed_link(
        bot_username,
        card["id"],
        card.get("author_referral_code"),
    )


def _published_feed_bot_link(bot_username: str | None, card: dict) -> str:
    return feed_bot_link(
        bot_username,
        card["id"],
        card.get("author_referral_code"),
    )


def _published_feed_link_keyboard(
    url: str,
    bot_url: str,
) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="📋 Скопировать ссылку",
                    copy_text=types.CopyTextButton(text=url),
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🤖 Открыть работу в боте",
                    url=bot_url,
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="📱 Открыть работу в Mini App",
                    url=url,
                )
            ]
        ]
    )


def _publication_disclaimer_text(kind: str) -> str:
    target = "ленту работ" if kind == "feed" else "ленту промптов"
    return (
        f"⚠️ <b>Публикация в {target}</b>\n\n"
        "Публикуя материал, вы подтверждаете, что у вас есть права или согласие "
        "на исходники, результат и текст промпта.\n\n"
        "Ответственность за опубликованный пользовательский контент несёт пользователь. "
        "Администрация бота не проводит предварительную модерацию и не отвечает за "
        "материалы, которые пользователи выкладывают самостоятельно.\n\n"
        "Спорный материал может быть удалён по жалобе правообладателя или другого "
        "заинтересованного лица."
    )


async def _owned_completed_image_task(
    callback: types.CallbackQuery, task_id: str
):
    user = await get_or_create_user(callback.from_user.id)
    task = await get_task_by_id(task_id)
    if not task or task.user_id != user.id:
        return None, "Не удалось найти эту генерацию."
    if task.type != "image" or task.status != "completed" or not task.result_url:
        return None, "Действие доступно только для готового изображения."
    return task, None


async def _owned_completed_feed_task(
    callback: types.CallbackQuery, task_id: str
):
    user = await get_or_create_user(callback.from_user.id)
    task = await get_task_by_id(task_id)
    if not task or task.user_id != user.id:
        return None, "Не удалось найти эту генерацию."
    if task.type not in {"image", "video"} or task.status != "completed" or not task.result_url:
        return None, "Действие доступно только для готового фото или видео."
    return task, None


async def _refresh_image_result_reply_markup(
    callback: types.CallbackQuery,
    task_id: str,
) -> None:
    task = await get_task_by_id(task_id)
    if not task or not task.result_url or not callback.message:
        return
    try:
        await callback.message.edit_reply_markup(
            reply_markup=get_image_result_keyboard(
                task.result_url,
                task_id=str(task.id),
                is_public_feed=task.is_public_feed,
                is_prompt_library=task.is_prompt_library,
            )
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.debug("Unable to refresh image result keyboard: %s", e)
    except Exception:
        logger.exception("Unable to refresh image result keyboard")


async def _refresh_feed_result_reply_markup(
    callback: types.CallbackQuery,
    task_id: str,
) -> None:
    task = await get_task_by_id(task_id)
    if not task or not task.result_url or not callback.message:
        return
    if task.type == "video":
        reply_markup = get_video_result_keyboard(
            task.result_url,
            task_id=str(task.id),
            model=task.model,
            is_public_feed=task.is_public_feed,
        )
    else:
        reply_markup = get_image_result_keyboard(
            task.result_url,
            task_id=str(task.id),
            is_public_feed=task.is_public_feed,
            is_prompt_library=task.is_prompt_library,
        )
    try:
        await callback.message.edit_reply_markup(reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.debug("Unable to refresh feed result keyboard: %s", e)
    except Exception:
        logger.exception("Unable to refresh feed result keyboard")


@router.callback_query(F.data.startswith("grokvid_"))
async def animate_image_result_with_grok(
    callback: types.CallbackQuery, state: FSMContext
):
    """Передаёт готовую картинку в Grok Imagine i2v как стартовый кадр."""
    task_id = callback.data.replace("grokvid_", "", 1)
    task, error_message = await _owned_completed_image_task(callback, task_id)
    if not task:
        await callback.answer(error_message or "Не удалось открыть Grok.", show_alert=True)
        return

    await state.clear()
    await _init_default_video_state(
        state,
        v_type="imgtxt",
        v_model="grok_imagine",
        v_duration=6,
        v_ratio=_grok_video_ratio_from_image_task(task, "grok_imagine"),
    )
    await state.update_data(
        v_image_url=task.result_url,
        reference_images=[],
        v_reference_videos=[],
        video_flow_step="configure",
        source_image_task_id=task.task_id,
        source_image_generation_id=task.id,
        grok_mode="normal",
    )
    await _show_video_creation_screen(callback, state)
    await callback.answer("Фото передано в Grok. Напишите промпт движения.")


@router.callback_query(F.data.startswith("grok15vid_"))
async def animate_image_result_with_grok_v15(
    callback: types.CallbackQuery, state: FSMContext
):
    """Передаёт готовую картинку в Grok Imagine 1.5 как стартовый кадр."""
    task_id = callback.data.replace("grok15vid_", "", 1)
    task, error_message = await _owned_completed_image_task(callback, task_id)
    if not task:
        await callback.answer(error_message or "Не удалось открыть Grok 1.5.", show_alert=True)
        return

    await state.clear()
    await _init_default_video_state(
        state,
        v_type="imgtxt",
        v_model="grok_imagine_v15",
        v_duration=8,
        v_ratio=_grok_video_ratio_from_image_task(task, "grok_imagine_v15"),
    )
    await state.update_data(
        v_image_url=task.result_url,
        reference_images=[],
        v_reference_videos=[],
        video_flow_step="configure",
        source_image_task_id=task.task_id,
        source_image_generation_id=task.id,
        grok_resolution="480p",
    )
    await _show_video_creation_screen(callback, state)
    await callback.answer("Фото передано в Grok 1.5. Напишите промпт движения.")


@router.callback_query(F.data.startswith("feedpub_"))
async def publish_image_result_to_feed(
    callback: types.CallbackQuery, state: FSMContext
):
    """Показывает предупреждение перед публикацией готовой генерации."""
    task_id = callback.data.replace("feedpub_", "", 1)
    task, error_message = await _owned_completed_feed_task(callback, task_id)
    if not task:
        await callback.answer(error_message or "Нельзя добавить в ленту.", show_alert=True)
        return

    await callback.message.answer(
        _feed_publication_text(),
        parse_mode="HTML",
        reply_markup=_feed_publication_keyboard(task.id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("feedpubopt_"))
async def update_feed_publication_options(
    callback: types.CallbackQuery, state: FSMContext
):
    payload = callback.data.replace("feedpubopt_", "", 1)
    task_id, prompt_visible, references_visible, blurred = _parse_feed_publish_payload(payload)
    task, error_message = await _owned_completed_feed_task(callback, task_id)
    if not task:
        await callback.answer(error_message or "Нельзя добавить в ленту.", show_alert=True)
        return

    try:
        await callback.message.edit_text(
            _feed_publication_text(
                prompt_visible=prompt_visible,
                references_visible=references_visible,
                blurred=blurred,
            ),
            parse_mode="HTML",
            reply_markup=_feed_publication_keyboard(
                task.id,
                prompt_visible=prompt_visible,
                references_visible=references_visible,
                blurred=blurred,
            ),
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.debug("Unable to update feed publication options: %s", e)
    await callback.answer()


@router.callback_query(F.data.startswith("feedpubok_"))
async def confirm_publish_image_result_to_feed(
    callback: types.CallbackQuery, state: FSMContext
):
    """Публикует готовую генерацию в miniapp-ленту после подтверждения."""
    task_id, prompt_visible, references_visible, blurred = _parse_feed_publish_payload(
        callback.data.replace("feedpubok_", "", 1)
    )
    task, error_message = await _owned_completed_feed_task(callback, task_id)
    if not task:
        logger.warning(
            "Bot feed publish rejected before share: telegram_id=%s callback_task_id=%r reason=%s",
            callback.from_user.id if callback.from_user else None,
            task_id,
            error_message,
        )
        await callback.answer(error_message or "Нельзя добавить в ленту.", show_alert=True)
        return

    card = await share_to_feed(
        task.task_id,
        task.user_id,
        prompt_visible=prompt_visible,
        references_visible=references_visible,
        blurred=blurred,
    )
    if not card:
        logger.warning(
            "Bot feed publish rejected in share_to_feed: telegram_id=%s user_id=%s callback_task_id=%r db_task_id=%r db_id=%s status=%s type=%s result_url=%s source_feed_gen_id=%s",
            callback.from_user.id if callback.from_user else None,
            task.user_id,
            task_id,
            task.task_id,
            task.id,
            task.status,
            task.type,
            bool(task.result_url),
            task.source_feed_gen_id,
        )
        await callback.answer("Эту генерацию нельзя опубликовать в ленту.", show_alert=True)
        return

    try:
        from bot.handlers.common import _invalidate_feed_and_profile_caches

        _invalidate_feed_and_profile_caches()
    except Exception:
        logger.exception("Failed to invalidate feed caches after publish")

    await _refresh_feed_result_reply_markup(callback, task.task_id)
    me = await callback.bot.get_me()
    publication_url = _published_feed_link(me.username, card)
    publication_bot_url = _published_feed_bot_link(me.username, card)
    await callback.message.answer(
        "✅ Работа опубликована в общей ленте.\n\n"
        f"🔗 Ссылка на работу:\n{publication_url}",
        reply_markup=_published_feed_link_keyboard(
            publication_url,
            publication_bot_url,
        ),
        disable_web_page_preview=True,
    )
    await callback.answer("Готово — ссылка отправлена сообщением")


@router.callback_query(F.data.startswith("feedrm_"))
async def remove_image_result_from_feed(
    callback: types.CallbackQuery, state: FSMContext
):
    """Убирает готовую генерацию автора из miniapp-ленты."""
    task_id = callback.data.replace("feedrm_", "", 1)
    task, error_message = await _owned_completed_feed_task(callback, task_id)
    if not task:
        await callback.answer(error_message or "Нельзя убрать из ленты.", show_alert=True)
        return

    removed = await remove_from_feed(task.task_id, task.user_id)
    if not removed:
        await callback.answer("Не удалось убрать из ленты.", show_alert=True)
        return

    try:
        from bot.handlers.common import _invalidate_feed_and_profile_caches

        _invalidate_feed_and_profile_caches()
    except Exception:
        logger.exception("Failed to invalidate feed caches after remove")

    await _refresh_feed_result_reply_markup(callback, task.task_id)
    await callback.answer("Убрано из ленты.")


@router.callback_query(F.data.startswith("promptsave_"))
async def save_image_result_prompt_to_library(
    callback: types.CallbackQuery, state: FSMContext
):
    """Показывает предупреждение перед сохранением prompt в miniapp."""
    task_id = callback.data.replace("promptsave_", "", 1)
    task, error_message = await _owned_completed_image_task(callback, task_id)
    if not task:
        await callback.answer(error_message or "Нельзя сохранить prompt.", show_alert=True)
        return

    await callback.message.answer(
        _publication_disclaimer_text("prompts"),
        parse_mode="HTML",
        reply_markup=_publication_confirm_keyboard(f"promptsaveok_{task.id}"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("promptsaveok_"))
async def confirm_save_image_result_prompt_to_library(
    callback: types.CallbackQuery, state: FSMContext
):
    """Сохраняет prompt готовой фото-генерации для miniapp после подтверждения."""
    task_id = callback.data.replace("promptsaveok_", "", 1)
    task, error_message = await _owned_completed_image_task(callback, task_id)
    if not task:
        await callback.answer(error_message or "Нельзя сохранить prompt.", show_alert=True)
        return

    saved = await share_to_library(task.task_id, task.user_id)
    if not saved:
        await callback.answer("Prompt этой генерации нельзя сохранить.", show_alert=True)
        return

    await _refresh_image_result_reply_markup(callback, task.task_id)
    await callback.answer("Промпт сохранён в Mini App.")


@router.callback_query(F.data.startswith("promptrm_"))
async def remove_image_result_prompt_from_library(
    callback: types.CallbackQuery, state: FSMContext
):
    """Убирает prompt автора из miniapp-библиотеки."""
    task_id = callback.data.replace("promptrm_", "", 1)
    task, error_message = await _owned_completed_image_task(callback, task_id)
    if not task:
        await callback.answer(error_message or "Нельзя убрать prompt.", show_alert=True)
        return

    removed = await remove_from_library(task.task_id, task.user_id)
    if not removed:
        await callback.answer("Не удалось убрать prompt.", show_alert=True)
        return

    await _refresh_image_result_reply_markup(callback, task.task_id)
    await callback.answer("Убрано из промптов.")


def _repeat_image_keyboard(task_id: str, reference_count: int = 0, inherited_ref_count: int = 0) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📸 Добавить своё фото" if reference_count == 0 else "📸 Добавить ещё фото",
        callback_data=f"repeat_refs_{task_id}",
    )
    builder.button(
        text="🚀 Запустить с фото" if reference_count else "🚀 Повторить без фото",
        callback_data=f"repeat_run_{task_id}",
    )
    if reference_count > 0 and inherited_ref_count > 0:
        builder.button(text="🗑 Убрать референсы", callback_data=f"repeat_clear_refs_{task_id}")
    builder.button(text="✏️ Изменить prompt", callback_data=f"repeat_prompt_{task_id}")
    if inherited_ref_count == 0:
        builder.button(text="🎨 Что поменять?", callback_data=f"repeat_changes_{task_id}")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1, 1, 1, 1)
    return builder.as_markup()


def _repeat_image_text(data: dict, task_id: str) -> str:
    prompt = " ".join(str(data.get("repeat_prompt") or "").split())
    prompt_hidden = bool(data.get("repeat_prompt_hidden"))
    prompt_preview = html.escape(prompt[:500] + ("..." if len(prompt) > 500 else ""))
    img_service = data.get("img_service", "banana_pro")
    img_ratio = str(data.get("img_ratio") or "1:1")
    img_quality = data.get("img_quality", "2K")
    reference_images = list(data.get("reference_images") or [])
    unit_cost = data.get("repeat_unit_cost", 0)
    original_ref_count = int(data.get("repeat_original_ref_count") or 0)
    missing_ref_count = int(data.get("repeat_missing_ref_count") or 0)
    inherited_ref_count = int(data.get("repeat_inherited_reference_count") or 0)
    user_ref_count = len(reference_images)
    if missing_ref_count:
        ref_note = (
            f"<code>{len(reference_images)}</code> доступно, "
            f"<code>{missing_ref_count}</code> очищено"
            if reference_images
            else "<code>0</code> — прежние фото уже очищены, добавьте их заново"
        )
    elif reference_images:
        ref_note = f"<code>{len(reference_images)}</code>"
    elif data.get("repeat_refs_cleared") or inherited_ref_count == 0:
        ref_note = "<code>0</code> — добавьте своё фото, если нужно сохранить лицо"
    else:
        ref_note = f"<code>{inherited_ref_count}</code> прежних референсов"
    replace_note = ""
    if data.get("repeat_refs_cleared"):
        replace_note = "🗑 Референсы автора удалены. Загрузите свои фото или запустите генерацию без референсов.\n\n"
    elif inherited_ref_count == 0:
        replace_note = (
            "⚠️ Референсы автора скрыты. Новые референсы не подтянуты — вы начинаете с нуля. "
            "Загрузите своё фото и опишите в prompt, что хотите изменить.\n\n"
        )
    elif inherited_ref_count and user_ref_count > inherited_ref_count:
        replace_note = (
            f"📸 Загружено своей замены: <code>{user_ref_count - inherited_ref_count}</code> — "
            f"всего референсов: <code>{user_ref_count}</code>\n\n"
        )
    elif inherited_ref_count:
        replace_note = (
            "📸 Загрузите свои фото — они добавятся к существующим референсам. "
            "Прежние референсы не удаляются, все фото пойдут в генерацию.\n\n"
        )
    else:
        replace_note = ""

    changes_hint = ""
    if inherited_ref_count == 0:
        changes_hint = (
            "\n🎨 <b>Что можно поменять через prompt:</b>\n"
            "• Цвет волос — напишите, на какой цвет поменять\n"
            "• Одежду — опишите новый образ\n"
            "• Фон — укажите другую обстановку\n"
            "• Стиль — задайте новое настроение\n"
        )

    return (
        "🔁 <b>Повторить prompt</b>\n\n"
        "Чтобы не получить результат без вашего лица, сначала отправьте фото прямо в чат. "
        "Генерация запустится только после отдельного подтверждения.\n\n"
        f"{replace_note}"
        "<b>Текущие настройки</b>\n"
        f"• Модель: <code>{get_image_model_label(img_service)}</code>\n"
        f"• Формат: <code>{img_ratio.replace(':', '∶')}</code>\n"
        f"• Референсы: {ref_note}\n"
        f"• Стоимость: <code>{unit_cost}</code>🍌\n"
        f"{changes_hint}"
        "\n<b>Prompt</b>\n"
        + (
            "<i>Скрыт автором. В генерацию уйдёт исходный prompt без показа текста.</i>"
            if prompt_hidden
            else f"<pre>{prompt_preview or html.escape(task_id)}</pre>"
        )
    )


async def _show_repeat_image_screen(
    message_or_callback,
    state: FSMContext,
    *,
    edit: bool = False,
) -> None:
    data = await state.get_data()
    task_id = str(data.get("repeat_source_task_id") or "")
    reference_count = len(data.get("reference_images") or [])
    inherited_ref_count = int(data.get("repeat_inherited_reference_count") or 0)
    text = _repeat_image_text(data, task_id)
    keyboard = _repeat_image_keyboard(task_id, reference_count, inherited_ref_count)

    try:
        if isinstance(message_or_callback, types.CallbackQuery):
            if edit:
                await message_or_callback.message.edit_text(
                    text, reply_markup=keyboard, parse_mode="HTML"
                )
            else:
                await message_or_callback.message.answer(
                    text, reply_markup=keyboard, parse_mode="HTML"
                )
        else:
            await message_or_callback.answer(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramBadRequest:
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.message.answer(
                text, reply_markup=keyboard, parse_mode="HTML"
            )
        else:
            await message_or_callback.answer(text, reply_markup=keyboard, parse_mode="HTML")

    await state.set_state(GenerationStates.uploading_reference_images)


async def _ensure_repeat_image_state(
    callback: types.CallbackQuery,
    state: FSMContext,
    task_id: str,
) -> tuple[bool, str | None]:
    task_id, task = await _resolve_repeat_image_task(task_id)
    data = await state.get_data()
    if data.get("repeat_source_task_id") == task_id:
        return True, None

    user = await get_or_create_user(callback.from_user.id)
    return await _restore_image_task_to_state(
        task,
        state,
        include_references=False,
        repeat_source_task_id=task_id,
        hide_prompt=bool(task and task.is_public_feed and task.user_id != user.id),
    )


async def _resolve_repeat_image_task(raw_task_id: str):
    task_id = str(raw_task_id or "").strip()
    task = await get_task_by_id(task_id)
    if task or not task_id.isdigit():
        return task_id, task

    card = await get_feed_generation_card(task_id)
    resolved_task_id = str((card or {}).get("task_id") or "").strip()
    if not resolved_task_id or resolved_task_id == task_id:
        return task_id, None
    return resolved_task_id, await get_task_by_id(resolved_task_id)


@router.callback_query(F.data.startswith("repeat_image_"))
async def repeat_image_generation(callback: types.CallbackQuery, state: FSMContext):
    """Opens a safe repeat flow instead of launching generation immediately."""
    task_id = callback.data.replace("repeat_image_", "", 1)
    task_id, task = await _resolve_repeat_image_task(task_id)
    user = await get_or_create_user(callback.from_user.id)

    hide_prompt = bool(task and task.is_public_feed and task.user_id != user.id)
    restored, error_message = await _restore_image_task_to_state(
        task,
        state,
        include_references=_can_inherit_repeat_source_references(task, user.id),
        repeat_source_task_id=task_id,
        hide_prompt=hide_prompt,
    )
    if not restored:
        await callback.answer(error_message or "Не удалось открыть повтор.", show_alert=True)
        return

    await _show_repeat_image_screen(callback, state)
    await callback.answer("Сначала можно добавить своё фото")


@router.callback_query(F.data.startswith("repeat_refs_"))
async def repeat_image_wait_for_references(callback: types.CallbackQuery, state: FSMContext):
    task_id = callback.data.replace("repeat_refs_", "", 1)
    restored, error_message = await _ensure_repeat_image_state(callback, state, task_id)
    if not restored:
        await callback.answer(error_message or "Не удалось открыть повтор.", show_alert=True)
        return

    await state.set_state(GenerationStates.uploading_reference_images)
    await callback.answer("Отправьте фото прямо в чат")


@router.callback_query(F.data.startswith("repeat_clear_refs_"))
async def repeat_image_clear_refs(callback: types.CallbackQuery, state: FSMContext):
    """Очищает все референсы при повторе (унаследованные + свои)."""
    task_id = callback.data.replace("repeat_clear_refs_", "", 1)
    data = await state.get_data()
    if data.get("repeat_source_task_id") != task_id:
        await callback.answer("Повтор не найден, откройте заново.", show_alert=True)
        return

    await state.update_data(reference_images=[], repeat_refs_cleared=True)
    await _show_repeat_image_screen(callback, state, edit=True)
    await callback.answer("Референсы удалены")


@router.callback_query(F.data.startswith("repeat_prompt_"))
async def repeat_image_wait_for_prompt(callback: types.CallbackQuery, state: FSMContext):
    task_id = callback.data.replace("repeat_prompt_", "", 1)
    restored, error_message = await _ensure_repeat_image_state(callback, state, task_id)
    if not restored:
        await callback.answer(error_message or "Не удалось открыть повтор.", show_alert=True)
        return

    data = await state.get_data()
    current_prompt = " ".join(str(data.get("repeat_prompt") or "").split())
    prompt_hidden = bool(data.get("repeat_prompt_hidden"))
    prompt_preview = (
        "<i>Скрыт автором. Новый текст можно написать своим сообщением.</i>"
        if prompt_hidden
        else f"<pre>{html.escape(current_prompt[:700] + ('...' if len(current_prompt) > 700 else '')) or html.escape(task_id)}</pre>"
    )
    await state.set_state(GenerationStates.waiting_for_repeat_prompt)
    await callback.message.answer(
        "✏️ <b>Новый prompt для повтора</b>\n\n"
        "Отправьте одним сообщением новый текст. Фото и настройки останутся как на экране повтора.\n\n"
        "<b>Сейчас</b>\n"
        f"{prompt_preview}",
        parse_mode="HTML",
    )
    await callback.answer("Жду новый prompt")


@router.message(GenerationStates.waiting_for_repeat_prompt, F.text)
async def handle_repeat_image_prompt_text(message: types.Message, state: FSMContext):
    prompt = message.text.strip()
    if not prompt:
        await message.answer("Нужен текстовый prompt для повтора.")
        return

    data = await state.get_data()
    task_id = str(data.get("repeat_source_task_id") or "")
    if not task_id:
        await state.clear()
        await message.answer(
            "Не нашёл исходную задачу для повтора. Откройте повтор заново.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return

    await state.update_data(repeat_prompt=prompt, repeat_prompt_hidden=False)
    await message.answer("✅ Prompt обновлён.")
    await _show_repeat_image_screen(message, state)


@router.callback_query(F.data.startswith("repeat_changes_"))
async def repeat_image_show_changes_hint(callback: types.CallbackQuery, state: FSMContext):
    """Show what the user can change when repeating with hidden references."""
    task_id = callback.data.replace("repeat_changes_", "", 1)
    data = await state.get_data()
    current_prompt = " ".join(str(data.get("repeat_prompt") or "").split())
    prompt_hidden = bool(data.get("repeat_prompt_hidden"))
    if prompt_hidden:
        prompt_info = "<i>Текущий prompt скрыт. Напишите новый prompt или только изменения, и он будет использован для генерации.</i>"
    else:
        prompt_info = f"<pre>{html.escape(current_prompt[:700] + ('...' if len(current_prompt) > 700 else '')) or html.escape(task_id)}</pre>"
    await state.set_state(GenerationStates.waiting_for_repeat_prompt)
    await callback.message.answer(
        "🎨 <b>Что можно поменять через prompt</b>\n\n"
        "У вас сейчас нет старых референсов — вы начинаете с нуля. "
        "Опишите в prompt, что хотите изменить, или напишите полный новый prompt:\n\n"
        "• <b>Цвет волос</b> — напишите, на какой цвет поменять\n"
        "  Пример: <i>сделай волосы ярко-рыжими</i>\n\n"
        "• <b>Одежду</b> — опишите новый образ\n"
        "  Пример: <i>одень в чёрное кожаное пальто</i>\n\n"
        "• <b>Фон</b> — укажите другую обстановку\n"
        "  Пример: <i>перенеси на пляж на закате</i>\n\n"
        "• <b>Стиль</b> — задайте новое настроение\n"
        "  Пример: <i>сделай в стиле киберпанк</i>\n\n"
        "• <b>Детали</b> — добавьте или уберите элементы\n"
        "  Пример: <i>добавь солнечные очки и шляпу</i>\n\n"
        "<b>Текущий prompt</b>\n"
        f"{prompt_info}\n\n"
        "Отправьте новым сообщением текст. Фото и настройки останутся как на экране повтора.",
        parse_mode="HTML",
    )
    await callback.answer("Жду новый prompt")


@router.callback_query(F.data.startswith("repeat_run_"))
async def run_repeat_image_generation(callback: types.CallbackQuery, state: FSMContext):
    """Launches repeat generation after explicit user confirmation."""
    task_id = callback.data.replace("repeat_run_", "", 1)
    task = await get_task_by_id(task_id)

    if not task or task.type != "image":
        await callback.answer("Не удалось найти данные для повтора.", show_alert=True)
        return

    try:
        request_data = json.loads(task.request_data) if task.request_data else {}
    except Exception:
        await callback.answer("Данные исходной задачи повреждены.", show_alert=True)
        return

    user = await get_or_create_user(callback.from_user.id)
    data = await state.get_data()
    state_matches_repeat = data.get("repeat_source_task_id") == task_id

    img_service = request_data.get("img_service", task.model or "banana_pro")
    prompt = (
        data.get("repeat_prompt")
        if state_matches_repeat and data.get("repeat_prompt")
        else request_data.get("prompt", task.prompt or "")
    )
    img_ratio = request_data.get("img_ratio", task.aspect_ratio or "1:1")
    if state_matches_repeat:
        raw_reference_images = [
            ref
            for ref in _snapshot_reference_images(data.get("reference_images", []))
            if not is_reference_contact_sheet_url(ref)
        ]
    elif task.user_id == user.id:
        raw_reference_images = _source_reference_images_from_request(request_data)
    else:
        raw_reference_images = []
    reference_images, missing_reference_images = _available_reference_images(
        raw_reference_images
    )
    img_quality = request_data.get("img_quality", "2K")
    img_nsfw_checker = bool(request_data.get("img_nsfw_checker", False))
    nsfw_enabled = bool(request_data.get("nsfw_enabled", False))

    if missing_reference_images:
        await state.update_data(
            generation_type="image",
            img_service=img_service,
            img_ratio=img_ratio,
            img_count=1,
            reference_images=reference_images,
            img_quality=img_quality,
            img_nsfw_checker=img_nsfw_checker,
            nsfw_enabled=nsfw_enabled,
            preset_id="new",
            img_flow_step="configure",
            repeat_source_task_id=task_id,
            repeat_prompt=prompt,
            repeat_prompt_hidden=bool(data.get("repeat_prompt_hidden")),
            repeat_unit_cost=task.cost or 0,
            repeat_original_ref_count=len(raw_reference_images),
            repeat_missing_ref_count=len(missing_reference_images),
        )
        await _show_repeat_image_screen(callback, state, edit=True)
        await callback.answer(
            "Часть старых фото уже очищена. Добавьте фото заново.",
            show_alert=True,
        )
        return

    if img_service in {"grok_imagine_i2i", "seedream_edit"} and not reference_images:
        await callback.answer("Для этой модели сначала отправьте фото.", show_alert=True)
        await state.set_state(GenerationStates.uploading_reference_images)
        return

    unit_cost = task.cost or 0
    is_admin = config.is_admin(callback.from_user.id)
    if unit_cost > 0 and not is_admin:
        can_afford = await check_can_afford(callback.from_user.id, unit_cost)
        if not can_afford:
            await callback.answer("Недостаточно бананов для повтора.", show_alert=True)
            return
        if not await deduct_credits(callback.from_user.id, unit_cost):
            await callback.answer("Не удалось списать бананы.", show_alert=True)
            return

    callback_url = config.kie_notification_url if config.WEBHOOK_HOST else None
    model_label = get_image_model_label(img_service)
    source_feed_gen_id = task.id if task.is_public_feed and task.user_id != user.id else None
    progress_message = await callback.message.answer(
        "🔁 <b>Повторяю генерацию</b>\n"
        f"• Модель: <code>{model_label}</code>\n"
        f"• Формат: <code>{img_ratio.replace(':', '∶')}</code>\n"
        f"• Референсы: <code>{len(reference_images)}</code>",
        parse_mode="HTML",
    )

    async def notify_local_task_created(local_task_id: str):
        try:
            await progress_message.edit_text(
                "🔁 <b>Повтор поставлен в запуск</b>\n"
                f"• Модель: <code>{model_label}</code>\n"
                f"• ID: <code>{local_task_id}</code>\n"
                f"• Формат: <code>{img_ratio.replace(':', '∶')}</code>\n"
                f"• Референсы: <code>{len(reference_images)}</code>\n\n"
                "Жду ответ провайдера.",
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass

    try:
        launch_result = await _start_image_generation_task(
            user=user,
            telegram_id=callback.from_user.id,
            img_service=img_service,
            prompt=_build_image_variant_prompt(prompt, 0, 1),
            img_ratio=img_ratio,
            reference_images=reference_images,
            unit_cost=unit_cost,
            img_quality=img_quality,
            img_nsfw_checker=img_nsfw_checker,
            nsfw_enabled=nsfw_enabled,
            callback_url=callback_url,
            source_feed_gen_id=source_feed_gen_id,
            parent_generation_id=source_feed_gen_id,
            action_type="repeat" if source_feed_gen_id else None,
            on_task_created=notify_local_task_created,
        )
        await progress_message.delete()

        if launch_result["status"] == "queued":
            if source_feed_gen_id:
                await credit_feed_prompt_repeat(
                    task.id,
                    user.id,
                    repeat_task_id=str(launch_result.get("task_id") or ""),
                    credits_spent=unit_cost,
                )

            queued_task_id = str(launch_result["task_id"])
            local_task_id = str(launch_result.get("local_task_id") or "")
            public_task_id, provider_id_line = _format_public_task_id_lines(
                queued_task_id, local_task_id
            )
            await callback.message.answer(
                "🚀 <b>Повторная генерация запущена</b>\n"
                f"• Модель: <code>{model_label}</code>\n"
                f"• ID: <code>{public_task_id}</code>\n"
                f"{provider_id_line}"
                f"• Списано: <code>{unit_cost}</code>🍌 {'(админ бесплатно)' if is_admin else ''}\n\n"
                "Результат придёт в этот чат.",
                parse_mode="HTML",
            )
        elif launch_result["status"] == "done":
            if source_feed_gen_id:
                await credit_feed_prompt_repeat(
                    task.id,
                    user.id,
                    repeat_task_id=str(launch_result.get("task_id") or ""),
                    credits_spent=unit_cost,
                )
            result_bytes = launch_result["result_bytes"]
            saved_url = launch_result["saved_url"]
            await callback.message.answer_photo(
                photo=types.BufferedInputFile(result_bytes, filename=f"{launch_result['task_id']}.png"),
                caption=(
                    "✅ <b>Повтор готов</b>\n"
                    f"• Модель: <code>{model_label}</code>\n"
                    f"• ID: <code>{launch_result['task_id']}</code>\n"
                    f"• Списано: <code>{unit_cost}</code>🍌 {'(админ бесплатно)' if is_admin else ''}"
                ),
                parse_mode="HTML",
                reply_markup=get_image_result_keyboard(
                    saved_url, task_id=launch_result["task_id"]
                ),
            )
            await _send_original_document(
                callback.message.answer_document,
                result_bytes,
                saved_url,
                filename=f"{launch_result['task_id']}_original.png",
            )
            await _send_used_prompt_message_to_chat(
                callback.message.answer,
                prompt,
                task_id=launch_result["task_id"],
                model_label=model_label,
                hidden=bool(data.get("repeat_prompt_hidden")),
            )
        else:
            if unit_cost > 0 and not is_admin:
                await add_credits(callback.from_user.id, unit_cost)
            await callback.message.answer(
                "❌ Не получилось повторить генерацию. Бананы за попытку уже возвращены."
            )

        await state.clear()
        try:
            await callback.answer("Повтор запускаю")
        except TelegramBadRequest:
            pass  # stale callback — ignore
    except Exception:
        logger.exception("Repeat image generation failed")
        if unit_cost > 0 and not is_admin:
            await add_credits(callback.from_user.id, unit_cost)
        try:
            await progress_message.delete()
        except Exception:
            pass
        try:
            await callback.answer("Не удалось повторить генерацию.", show_alert=True)
        except TelegramBadRequest:
            pass  # stale callback — ignore


@router.callback_query(F.data.startswith("repeat_result_"))
async def quick_repeat_image_result(callback: types.CallbackQuery, state: FSMContext):
    """Быстрый повтор генерации изображения с теми же параметрами (из кнопки «🔁 Повторить»)."""
    task_id = callback.data.replace("repeat_result_", "", 1)
    task = await get_task_by_id(task_id)

    if not task or task.type != "image":
        await callback.answer("Не удалось найти данные для повтора.", show_alert=True)
        return

    try:
        request_data = json.loads(task.request_data) if task.request_data else {}
    except Exception:
        await callback.answer("Данные исходной задачи повреждены.", show_alert=True)
        return

    user = await get_or_create_user(callback.from_user.id)

    img_service = request_data.get("img_service", task.model or "banana_pro")
    prompt = request_data.get("prompt", task.prompt or "")
    img_ratio = request_data.get("img_ratio", task.aspect_ratio or "1:1")
    img_quality = request_data.get("img_quality", "2K")
    img_nsfw_checker = bool(request_data.get("img_nsfw_checker", False))
    nsfw_enabled = bool(request_data.get("nsfw_enabled", False))

    if task.user_id == user.id:
        reference_images = _source_reference_images_from_request(request_data)
    else:
        reference_images = []

    reference_images, missing_reference_images = _available_reference_images(reference_images)
    if missing_reference_images:
        reference_images = []

    if img_service in {"grok_imagine_i2i", "seedream_edit"} and not reference_images:
        await callback.answer("Для этой модели нужны референсы, а они уже не доступны.", show_alert=True)
        return

    unit_cost = task.cost or 0
    is_admin = config.is_admin(callback.from_user.id)
    if unit_cost > 0 and not is_admin:
        can_afford = await check_can_afford(callback.from_user.id, unit_cost)
        if not can_afford:
            await callback.answer("Недостаточно бананов для повтора.", show_alert=True)
            return
        if not await deduct_credits(callback.from_user.id, unit_cost):
            await callback.answer("Не удалось списать бананы.", show_alert=True)
            return

    callback_url = config.kie_notification_url if config.WEBHOOK_HOST else None
    model_label = get_image_model_label(img_service)
    source_feed_gen_id = task.id if task.is_public_feed and task.user_id != user.id else None

    progress_message = await callback.message.answer(
        "🔁 <b>Повторяю генерацию</b>\n"
        f"• Модель: <code>{model_label}</code>\n"
        f"• Формат: <code>{img_ratio.replace(':', '∶')}</code>\n"
        f"• Референсы: <code>{len(reference_images)}</code>",
        parse_mode="HTML",
    )

    async def notify_local_task_created(local_task_id: str):
        try:
            await progress_message.edit_text(
                "🔁 <b>Повтор поставлен в запуск</b>\n"
                f"• Модель: <code>{model_label}</code>\n"
                f"• ID: <code>{local_task_id}</code>\n"
                f"• Формат: <code>{img_ratio.replace(':', '∶')}</code>\n"
                f"• Референсы: <code>{len(reference_images)}</code>\n\n"
                "Жду ответ провайдера.",
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass

    try:
        launch_result = await _start_image_generation_task(
            user=user,
            telegram_id=callback.from_user.id,
            img_service=img_service,
            prompt=_build_image_variant_prompt(prompt, 0, 1),
            img_ratio=img_ratio,
            reference_images=reference_images,
            unit_cost=unit_cost,
            img_quality=img_quality,
            img_nsfw_checker=img_nsfw_checker,
            nsfw_enabled=nsfw_enabled,
            callback_url=callback_url,
            source_feed_gen_id=source_feed_gen_id,
            parent_generation_id=source_feed_gen_id,
            action_type="repeat" if source_feed_gen_id else None,
            on_task_created=notify_local_task_created,
        )
        await progress_message.delete()

        if launch_result["status"] == "queued":
            if source_feed_gen_id:
                await credit_feed_prompt_repeat(
                    task.id,
                    user.id,
                    repeat_task_id=str(launch_result.get("task_id") or ""),
                    credits_spent=unit_cost,
                )

            queued_task_id = str(launch_result["task_id"])
            local_task_id = str(launch_result.get("local_task_id") or "")
            public_task_id, provider_id_line = _format_public_task_id_lines(
                queued_task_id, local_task_id
            )
            await callback.message.answer(
                "🚀 <b>Повторная генерация запущена</b>\n"
                f"• Модель: <code>{model_label}</code>\n"
                f"• ID: <code>{public_task_id}</code>\n"
                f"{provider_id_line}"
                f"• Списано: <code>{unit_cost}</code>🍌 {'(админ бесплатно)' if is_admin else ''}\n\n"
                "Результат придёт в этот чат.",
                parse_mode="HTML",
            )
        elif launch_result["status"] == "done":
            if source_feed_gen_id:
                await credit_feed_prompt_repeat(
                    task.id,
                    user.id,
                    repeat_task_id=str(launch_result.get("task_id") or ""),
                    credits_spent=unit_cost,
                )
            result_bytes = launch_result["result_bytes"]
            saved_url = launch_result["saved_url"]
            await callback.message.answer_photo(
                photo=types.BufferedInputFile(result_bytes, filename=f"{launch_result['task_id']}.png"),
                caption=(
                    "✅ <b>Повтор готов</b>\n"
                    f"• Модель: <code>{model_label}</code>\n"
                    f"• ID: <code>{launch_result['task_id']}</code>\n"
                    f"• Списано: <code>{unit_cost}</code>🍌 {'(админ бесплатно)' if is_admin else ''}"
                ),
                parse_mode="HTML",
                reply_markup=get_image_result_keyboard(
                    saved_url, task_id=launch_result["task_id"]
                ),
            )
            await _send_original_document(
                callback.message.answer_document,
                result_bytes,
                saved_url,
                filename=f"{launch_result['task_id']}_original.png",
            )
            await _send_used_prompt_message_to_chat(
                callback.message.answer,
                prompt,
                task_id=launch_result["task_id"],
                model_label=model_label,
                hidden=bool(source_feed_gen_id),
            )
        else:
            if unit_cost > 0 and not is_admin:
                await add_credits(callback.from_user.id, unit_cost)
            await callback.message.answer(
                "❌ Не получилось повторить генерацию. Бананы за попытку уже возвращены."
            )

        try:
            await callback.answer("Повтор запускаю")
        except TelegramBadRequest:
            pass
    except Exception:
        logger.exception("Quick repeat image generation failed")
        if unit_cost > 0 and not is_admin:
            await add_credits(callback.from_user.id, unit_cost)
        try:
            await progress_message.delete()
        except Exception:
            pass
        try:
            await callback.answer("Не удалось повторить генерацию.", show_alert=True)
        except TelegramBadRequest:
            pass


@router.callback_query(F.data.startswith("repeat_video_result_"))
async def quick_repeat_video_result(callback: types.CallbackQuery, state: FSMContext):
    """Быстрый повтор генерации видео с теми же параметрами (из кнопки «🔁 Повторить»)."""
    task_id = callback.data.replace("repeat_video_result_", "", 1)
    task = await get_task_by_id(task_id)

    if not task or task.type != "video":
        await callback.answer("Не удалось найти данные для повтора.", show_alert=True)
        return

    try:
        request_data = json.loads(task.request_data) if task.request_data else {}
    except Exception:
        await callback.answer("Данные исходной задачи повреждены.", show_alert=True)
        return

    user = await get_or_create_user(callback.from_user.id)

    v_model = request_data.get("v_model", task.model or "v3_std")
    v_type = request_data.get("v_type", "text")
    prompt = request_data.get("user_prompt", task.prompt or "")
    v_duration = int(request_data.get("v_duration", task.duration or 5))
    v_ratio = request_data.get("v_ratio", task.aspect_ratio or "16:9")

    if task.user_id == user.id:
        reference_images = _source_reference_images_from_request(request_data)
        v_image_url = request_data.get("v_image_url")
        reference_videos = normalize_reference_urls(
            request_data.get("v_reference_videos", []),
            max_count=get_max_video_references(v_model),
        )
    else:
        reference_images = []
        v_image_url = None
        reference_videos = []

    reference_images, _ = _available_reference_images(reference_images)

    unit_cost = task.cost or 0
    is_admin = config.is_admin(callback.from_user.id)
    if unit_cost > 0 and not is_admin:
        can_afford = await check_can_afford(callback.from_user.id, unit_cost)
        if not can_afford:
            await callback.answer("Недостаточно бананов для повтора.", show_alert=True)
            return
        if not await deduct_credits(callback.from_user.id, unit_cost):
            await callback.answer("Не удалось списать бананы.", show_alert=True)
            return

    model_label = get_video_model_label(v_model)
    progress_message = await callback.message.answer(
        "🔁 <b>Повторяю генерацию видео</b>\n"
        f"• Модель: <code>{model_label}</code>\n"
        f"• Длительность: <code>{v_duration}с</code>\n"
        f"• Формат: <code>{v_ratio.replace(':', '∶')}</code>",
        parse_mode="HTML",
    )

    try:
        # Перенаправляем в общую логику запуска видео через state
        await state.update_data(
            generation_type="video",
            video_flow_step="configure",
            v_type=v_type,
            v_model=v_model,
            v_duration=v_duration,
            v_ratio=v_ratio,
            v_image_url=v_image_url,
            reference_images=reference_images,
            v_reference_videos=reference_videos,
            user_prompt=prompt,
            v_mode=request_data.get("v_mode", "720p"),
            grok_mode=request_data.get("grok_mode", "normal"),
            grok_resolution=request_data.get("grok_resolution", "480p"),
            veo_generation_type=request_data.get("veo_generation_type", "TEXT_2_VIDEO"),
            veo_translation=request_data.get("veo_translation", True),
            veo_resolution=request_data.get("veo_resolution", "720p"),
            veo_seed=request_data.get("veo_seed"),
            veo_watermark=request_data.get("veo_watermark", ""),
            kling_negative_prompt=request_data.get("kling_negative_prompt", ""),
            kling_cfg_scale=float(request_data.get("kling_cfg_scale", 0.5)),
            omni_resolution=request_data.get("omni_resolution", "720p"),
            omni_seed=request_data.get("omni_seed"),
            omni_audio_ids=request_data.get("omni_audio_ids", []),
            omni_character_ids=request_data.get("omni_character_ids", []),
            omni_base_voice=request_data.get("omni_base_voice", "achernar"),
            omni_voice_name=request_data.get("omni_voice_name", ""),
            omni_character_name=request_data.get("omni_character_name", ""),
            avatar_audio_url=request_data.get("avatar_audio_url"),
        )

        await progress_message.delete()
        await run_no_preset_video_from_callback(callback, state, prompt, unit_cost, is_admin)
    except Exception:
        logger.exception("Quick repeat video generation failed")
        if unit_cost > 0 and not is_admin:
            await add_credits(callback.from_user.id, unit_cost)
        try:
            await progress_message.delete()
        except Exception:
            pass
        try:
            await callback.answer("Не удалось повторить генерацию видео.", show_alert=True)
        except TelegramBadRequest:
            pass


@router.callback_query(F.data == "main_img_banana_pro")
async def show_main_img_banana_pro(callback: types.CallbackQuery, state: FSMContext):
    await _open_image_model_from_main(callback, state, model="banana_pro")


@router.callback_query(F.data == "main_img_banana_2")
async def show_main_img_banana_2(callback: types.CallbackQuery, state: FSMContext):
    await _open_image_model_from_main(callback, state, model="banana_2")


@router.callback_query(F.data == "main_img_nano_banana_2_lite")
async def show_main_img_nano_banana_2_lite(callback: types.CallbackQuery, state: FSMContext):
    await _open_image_model_from_main(callback, state, model="nano-banana-2-lite")


@router.callback_query(F.data == "main_img_seedream")
async def show_main_img_seedream(callback: types.CallbackQuery, state: FSMContext):
    await _open_image_model_from_main(callback, state, model="seedream_edit")


@router.callback_query(F.data == "main_img_flux")
async def show_main_img_flux(callback: types.CallbackQuery, state: FSMContext):
    await _open_image_model_from_main(callback, state, model="flux_pro")


@router.callback_query(F.data == "main_img_grok")
async def show_main_img_grok(callback: types.CallbackQuery, state: FSMContext):
    await _open_image_model_from_main(
        callback, state, model="grok_imagine_i2i", upload_first=True
    )


@router.callback_query(F.data == "main_img_wan_27")
async def show_main_img_wan_27(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(
        img_service="wan_27", preset_id="new", img_flow_step="settings"
    )
    await _show_image_creation_screen(callback, state)
    await callback.answer("Выбрана тестовая модель Wan 2.7 Pro")


@router.callback_query(F.data == "main_vid_v3_std")
async def show_main_vid_v3_std(callback: types.CallbackQuery, state: FSMContext):
    await _open_video_model_from_main(callback, state, model="v3_std")


@router.callback_query(F.data == "main_vid_v3_pro")
async def show_main_vid_v3_pro(callback: types.CallbackQuery, state: FSMContext):
    await _open_video_model_from_main(callback, state, model="v3_pro")


@router.callback_query(F.data == "main_vid_veo3")
async def show_main_vid_veo3(callback: types.CallbackQuery, state: FSMContext):
    await _open_video_model_from_main(
        callback, state, model="veo3", duration=6, ratio="9:16"
    )


@router.callback_query(F.data == "main_vid_veo3_fast")
async def show_main_vid_veo3_fast(callback: types.CallbackQuery, state: FSMContext):
    await _open_video_model_from_main(
        callback, state, model="veo3_fast", duration=6, ratio="9:16"
    )


@router.callback_query(F.data == "main_vid_veo3_lite")
async def show_main_vid_veo3_lite(callback: types.CallbackQuery, state: FSMContext):
    await _open_video_model_from_main(
        callback, state, model="veo3_lite", duration=6, ratio="9:16"
    )


@router.callback_query(F.data == "main_vid_grok")
async def show_main_vid_grok(callback: types.CallbackQuery, state: FSMContext):
    await _open_video_model_from_main(
        callback,
        state,
        model="grok_imagine",
        v_type="imgtxt",
        duration=6,
        ratio="16:9",
    )


@router.callback_query(F.data == "main_vid_grok_v15")
async def show_main_vid_grok_v15(callback: types.CallbackQuery, state: FSMContext):
    await _open_video_model_from_main(
        callback,
        state,
        model="grok_imagine_v15",
        v_type="imgtxt",
        duration=8,
        ratio="auto",
    )


@router.callback_query(F.data == "main_vid_glow")
async def show_main_vid_glow(callback: types.CallbackQuery, state: FSMContext):
    await _open_video_model_from_main(
        callback, state, model="glow", v_type="video", duration=5, ratio="16:9"
    )


@router.callback_query(F.data == "quick_product_image")
async def show_quick_product_image(callback: types.CallbackQuery, state: FSMContext):
    """Быстрый сценарий для товара/рекламы."""
    await state.update_data(
        generation_type="image",
        img_service="banana_pro",
        img_ratio="16:9",
        img_count=1,
        reference_images=[],
        preset_id="new",
    )
    await _show_image_creation_screen(callback, state)
    await callback.answer("Формат 16:9 и Banana Pro выбраны для рекламного кадра")


@router.callback_query(F.data.in_({"edit_style_image", "edit_background_image"}))
async def show_edit_reference_upload(callback: types.CallbackQuery, state: FSMContext):
    """Сценарии редактирования фото через загрузку исходника/референсов."""
    user_credits = await get_user_credits(callback.from_user.id)
    is_background = callback.data == "edit_background_image"
    title = "🖼 <b>Сменить фон</b>" if is_background else "🎨 <b>Сменить стиль</b>"
    hint = (
        "Загрузите фото, у которого нужно заменить фон.\n"
        "Потом нажмите <b>Продолжить</b> и напишите, какой фон нужен."
        if is_background
        else "Загрузите фото.\n"
        "При желании добавьте ещё стиль-референсы.\n"
        "Потом нажмите <b>Продолжить</b> и опишите нужный стиль."
    )

    await state.update_data(
        generation_type="image",
        img_service="seedream_edit",
        img_ratio="1:1",
        img_count=1,
        img_quality="2K",
        img_nsfw_checker=False,
        reference_images=[],
        preset_id="new",
    )
    await callback.message.edit_text(
        f"{title}\n"
        f"🍌 Баланс: <code>{user_credits}</code> бананов\n\n"
        f"{hint}\n\n"
        f"<i>Можно загрузить до {_get_max_image_references('seedream_edit')} фото.</i>",
        reply_markup=get_reference_images_upload_keyboard(0, _get_max_image_references("seedream_edit"), "new"),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.uploading_reference_images)


@router.callback_query(F.data == "edit_grok_i2i")
async def show_grok_i2i_upload(callback: types.CallbackQuery, state: FSMContext):
    """Быстрый вход в Grok Imagine i2i."""
    user_credits = await get_user_credits(callback.from_user.id)
    await state.update_data(
        generation_type="image",
        img_service="grok_imagine_i2i",
        img_ratio="1:1",
        img_count=1,
        reference_images=[],
        nsfw_enabled=False,
        preset_id="new",
    )
    await callback.message.edit_text(
        "🧠 <b>Grok Imagine i2i</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code> бананов\n\n"
        "Загрузите фото для изменения.\n"
        "Потом нажмите <b>Продолжить</b> и напишите, что нужно поменять.",
        reply_markup=get_reference_images_upload_keyboard(0, _get_max_image_references("grok_imagine_i2i"), "new"),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.uploading_reference_images)


@router.callback_query(F.data == "quick_reels_video")
async def show_quick_reels_video(callback: types.CallbackQuery, state: FSMContext):
    """Быстрый сценарий вертикального ролика."""
    await _init_default_video_state(
        state,
        v_type="text",
        v_model="veo3_fast",
        v_duration=6,
        v_ratio="9:16",
    )
    await _show_video_creation_screen(callback, state)
    await callback.answer("Выбраны настройки для Reels/TikTok: 9:16, 6 сек")


@router.callback_query(F.data == "quick_image_to_video")
async def show_quick_image_to_video(callback: types.CallbackQuery, state: FSMContext):
    """Быстрый сценарий фото -> видео."""
    await _init_default_video_state(
        state,
        v_type="imgtxt",
        v_model="v3_std",
        v_duration=5,
        v_ratio="9:16",
    )
    await _show_video_creation_screen(callback, state)
    await callback.answer("Загрузите фото, затем промпт движения")


@router.callback_query(F.data == "quick_video_reference")
async def show_quick_video_reference(callback: types.CallbackQuery, state: FSMContext):
    """Быстрый вход в видео-референсы."""
    user_credits = await get_user_credits(callback.from_user.id)
    default_model = "seedance_2"
    max_video_refs = get_max_video_references(default_model)
    await _init_default_video_state(
        state,
        v_type="video",
        v_model=default_model,
        v_duration=5,
        v_ratio="16:9",
    )
    text = (
        "🎞 <b>Видео-референс</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code>\n\n"
        f"Загрузите до {max_video_refs} коротких видео, если хотите передать движение, стиль камеры "
        "или атмосферу.\nЭтот режим работает через Seedance 2.0."
    )
    await callback.message.edit_text(
        text,
        reply_markup=get_reference_videos_upload_keyboard(
            0, max_video_refs, "video_new"
        ),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.uploading_reference_videos)


@router.callback_query(F.data == "photo_prompt")
async def show_photo_prompt(callback: types.CallbackQuery, state: FSMContext):
    """Простой промпт для фото (без референсов и выбора параметров)"""
    from bot.database import get_user_credits

    user_credits = await get_user_credits(callback.from_user.id)

    await state.update_data(
        generation_type="image",
        img_service="banana_pro",
        img_ratio="1:1",
        img_count=1,
    )
    await _show_image_creation_screen(callback, state)

    await callback.answer()


@router.callback_query(F.data == "img_ref_upload_new")
async def handle_img_ref_upload_new(callback: types.CallbackQuery, state: FSMContext):
    """Показывает меню загрузки референсных изображений для нового UX"""
    data = await state.get_data()
    current_service = data.get("img_service", "banana_pro")
    current_ratio = data.get("img_ratio", "1:1")
    current_refs = len(data.get("reference_images", []))
    max_refs = _get_max_image_references(current_service)

    # Показываем клавиатуру загрузки референсов
    await callback.message.edit_text(
        "📎 <b>Загрузка референсов</b>\n"
        "Добавьте фото, если хотите точнее передать стиль, человека или объект.\n\n"
        "<i>Можно загрузить до 9 фото.</i>\n"
        "Когда всё готово, нажмите <b>Продолжить</b> или <b>Пропустить</b>.",
        reply_markup=get_reference_images_upload_keyboard(
            current_refs, max_refs, "new"
        ),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.uploading_reference_images)


# =============================================================================
# СЛУЖЕБНЫЕ ФУНКЦИИ ДЛЯ UNIFIED UX
# =============================================================================


async def _init_default_video_state(
    state: FSMContext,
    *,
    v_type: str = "text",
    v_model: str = "v3_std",
    v_duration: int = 5,
    v_ratio: str = "16:9",
):
    """Инициализирует единый state для новых видео-сценариев."""
    await state.update_data(
        generation_type="video",
        v_type=v_type,
        v_model=v_model,
        v_duration=v_duration,
        v_ratio=v_ratio,
        v_mode="720p",
        v_orientation="video",
        reference_images=[],
        v_reference_videos=[],
        v_image_url=None,
        user_prompt="",
        grok_mode="normal",
        grok_resolution="480p",
        veo_generation_type=(
            "FIRST_AND_LAST_FRAMES_2_VIDEO"
            if v_type == "imgtxt" and v_model.startswith("veo3")
            else "TEXT_2_VIDEO"
        ),
        veo_translation=True,
        veo_resolution="720p",
        veo_seed=None,
        veo_watermark="",
        kling_negative_prompt="",
        kling_cfg_scale=0.5,
        avatar_audio_url=None,
        omni_resolution="720p",
        omni_seed=None,
        omni_audio_ids=[],
        omni_character_ids=[],
        omni_base_voice="achernar",
        omni_voice_name="",
        omni_voice_description="",
        omni_example_dialogue="",
        omni_character_name="",
        omni_character_audio_ids=[],
    )


async def _open_image_model_from_main(
    callback: types.CallbackQuery,
    state: FSMContext,
    *,
    model: str,
    upload_first: bool = False,
):
    """Прямой вход из главного меню в нужную модель фото."""
    await state.update_data(
        generation_type="image",
        img_service=model,
        img_ratio="auto" if model in {"flux_pro", "nano-banana-2-lite"} else "1:1",
        img_count=1,
        img_quality="basic" if model in {"seedream_edit", "seedream_5_pro"} else "2K",
        img_nsfw_checker=False,
        reference_images=[],
        preset_id="new",
    )

    if model == "flux_pro":
        await state.update_data(img_flow_step="upload_refs")
        await _show_image_references_screen(callback, state)
    elif upload_first:
        user_credits = await get_user_credits(callback.from_user.id)
        await callback.message.edit_text(
            "🧠 <b>Grok Imagine</b>\n"
            f"🍌 Баланс: <code>{user_credits}</code> бананов\n\n"
            "Сначала загрузите фото для редактирования, затем нажмите "
            "<b>Продолжить</b> и опишите изменение.",
            reply_markup=get_reference_images_upload_keyboard(0, 9, "new"),
            parse_mode="HTML",
        )
        await state.set_state(GenerationStates.uploading_reference_images)
    else:
        await _show_image_creation_screen(callback, state)
    await callback.answer()


async def _open_video_model_from_main(
    callback: types.CallbackQuery,
    state: FSMContext,
    *,
    model: str,
    v_type: str = "text",
    duration: int = 5,
    ratio: str = "16:9",
):
    """Прямой вход из главного меню в нужную модель видео."""
    if v_type == "video":
        model = choose_video_reference_model(model)

    await _init_default_video_state(
        state,
        v_type=v_type,
        v_model=model,
        v_duration=duration,
        v_ratio=ratio,
    )

    if v_type == "video":
        user_credits = await get_user_credits(callback.from_user.id)
        max_video_refs = get_max_video_references(model)
        text = (
            "🎞 <b>Видео-референс</b>\n"
            f"🍌 Баланс: <code>{user_credits}</code>\n\n"
            f"Загрузите до {max_video_refs} коротких видео, чтобы передать движение, стиль камеры "
            "или атмосферу. Можно пропустить и продолжить без референсов."
        )
        await callback.message.edit_text(
            text,
            reply_markup=get_reference_videos_upload_keyboard(
                0, max_video_refs, "video_new"
            ),
            parse_mode="HTML",
        )
        await state.set_state(GenerationStates.uploading_reference_videos)
    else:
        await _show_video_creation_screen(callback, state)
    await callback.answer()


async def _show_video_creation_screen(
    message_or_callback, state: FSMContext, edit: bool = True
):
    """
    Показывает единый экран создания видео с параметрами и промптом.
    Используется после загрузки референсов или при пропуске.
    """
    data = await state.get_data()

    # Получаем текущие параметры
    current_v_type = data.get("v_type", "text")
    current_model = data.get("v_model", "v3_std")
    current_duration = data.get("v_duration", 5)
    current_ratio = data.get("v_ratio", "16:9")
    max_video_refs = get_max_video_references(current_model)
    reference_images = data.get("reference_images", [])
    v_reference_videos = data.get("v_reference_videos", [])
    v_image_url = data.get("v_image_url")
    avatar_audio_url = data.get("avatar_audio_url")
    user_prompt = data.get("user_prompt", "")
    grok_mode = data.get("grok_mode", "normal")
    grok_resolution = data.get("grok_resolution", "480p")
    veo_generation_type = data.get("veo_generation_type", "TEXT_2_VIDEO")
    veo_translation = data.get("veo_translation", True)
    veo_resolution = data.get("veo_resolution", "720p")
    veo_seed = data.get("veo_seed")
    veo_watermark = data.get("veo_watermark", "")
    kling_negative_prompt = data.get("kling_negative_prompt", "")
    kling_cfg_scale = float(data.get("kling_cfg_scale", 0.5))
    omni_resolution = data.get("omni_resolution", "720p")
    omni_seed = data.get("omni_seed")
    omni_audio_ids = data.get("omni_audio_ids", [])
    omni_character_ids = data.get("omni_character_ids", [])
    omni_base_voice = data.get("omni_base_voice", "achernar")
    omni_voice_name = data.get("omni_voice_name", "")
    omni_voice_description = data.get("omni_voice_description", "")
    omni_example_dialogue = data.get("omni_example_dialogue", "")
    omni_character_name = data.get("omni_character_name", "")
    omni_character_audio_ids = data.get("omni_character_audio_ids", [])

    await _normalize_veo_state(state)
    await _normalize_video_duration_state(state)
    data = await state.get_data()
    current_v_type = data.get("v_type", current_v_type)
    current_model = data.get("v_model", current_model)
    current_duration = data.get("v_duration", current_duration)
    current_ratio = data.get("v_ratio", current_ratio)
    grok_mode = data.get("grok_mode", grok_mode)
    grok_resolution = data.get("grok_resolution", grok_resolution)
    veo_generation_type = data.get("veo_generation_type", veo_generation_type)
    veo_translation = data.get("veo_translation", veo_translation)
    veo_resolution = data.get("veo_resolution", veo_resolution)
    veo_seed = data.get("veo_seed", veo_seed)
    veo_watermark = data.get("veo_watermark", veo_watermark)
    omni_resolution = data.get("omni_resolution", omni_resolution)
    omni_seed = data.get("omni_seed", omni_seed)
    omni_audio_ids = data.get("omni_audio_ids", omni_audio_ids)
    omni_character_ids = data.get("omni_character_ids", omni_character_ids)
    omni_base_voice = data.get("omni_base_voice", omni_base_voice)
    omni_voice_name = data.get("omni_voice_name", omni_voice_name)
    omni_voice_description = data.get("omni_voice_description", omni_voice_description)
    omni_example_dialogue = data.get("omni_example_dialogue", omni_example_dialogue)
    omni_character_name = data.get("omni_character_name", omni_character_name)
    omni_character_audio_ids = data.get(
        "omni_character_audio_ids",
        omni_character_audio_ids,
    )

    # Формируем текст о референсах
    ref_text = ""
    omni_image_urls = []
    omni_video_urls = []
    omni_units = 0
    has_omni_video_ref = False
    if current_model == "gemini_omni_video":
        omni_image_urls = _collect_gemini_omni_image_urls(v_image_url, reference_images)
        omni_video_urls = _collect_gemini_omni_video_urls(v_reference_videos)
        omni_units = _gemini_omni_input_units(
            omni_image_urls,
            omni_video_urls,
            omni_character_ids,
        )
        has_omni_video_ref = bool(omni_video_urls)
        ref_text = (
            f"🎛 Входы Gemini Omni: <code>{omni_units}/7</code> "
            f"(фото {len(omni_image_urls)}, видео {len(omni_video_urls)}×2, "
            f"Character ID {len(omni_character_ids)})\n"
        )
    elif reference_images:
        ref_text = f"📎 Изображений реф: <code>{len(reference_images)}</code>\n"
    if v_reference_videos and current_model != "gemini_omni_video":
        ref_text += f"📹 Видео реф: <code>{len(v_reference_videos)}</code>\n"

    # Формируем статус медиа в зависимости от типа
    media_status = ""
    if current_v_type == "avatar":
        media_status = (
            f"{'✅' if v_image_url else '🖼'} <b>Аватар:</b> "
            f"<code>{'загружен' if v_image_url else 'не загружен'}</code>\n"
            f"{'✅' if avatar_audio_url else '🎵'} <b>Аудио:</b> "
            f"<code>{'загружено' if avatar_audio_url else 'не загружено'}</code>\n"
        )
    elif current_v_type == "imgtxt":
        start_count = 1 if v_image_url else 0
        ref_count = len(reference_images)
        total = start_count + ref_count
        if total > 0:
            max_image_refs = get_max_video_image_references(current_model)
            media_status = (
                f"✅ <b>Фото загружено: {total}/{max_image_refs}</b> (старт + рефы)\n"
            )
        else:
            media_status = "📷 <b>Загрузите стартовое изображение</b>\n"
    elif current_v_type == "video":
        if v_reference_videos:
            media_status = (
                f"✅ <b>{len(v_reference_videos)} реф. видео загружено!</b>\n"
            )
        else:
            media_status = (
                f"📹 <b>Загрузите референсные видео (до {max_video_refs})</b>\n"
            )
    elif current_v_type == "character":
        media_status = (
            f"{'✅' if v_image_url else '🖼'} <b>Character image:</b> "
            f"<code>{'загружено' if v_image_url else 'не загружено'}</code>\n"
        )

    # Формируем текст о промпте
    prompt_text = ""
    if user_prompt:
        prompt_text = f"\n📝 <b>Промпт:</b> <code>{user_prompt[:100]}{'...' if len(user_prompt) > 100 else ''}</code>\n"

    settings_lines = [
        f"   📝 Тип: <code>{get_video_type_label(current_v_type)}</code>",
        f"   🤖 Модель: <code>{get_video_model_label(current_model)}</code>",
    ]
    if current_model not in {"avatar_std", "avatar_pro", "gemini_omni_audio", "gemini_omni_character"}:
        if has_omni_video_ref:
            settings_lines.append(
                "   ⏱ Длительность: <code>по видео-референсу</code>"
            )
        else:
            settings_lines.append(
                f"   ⏱ Длительность: <code>{current_duration} сек</code>"
            )
    if current_model not in {"avatar_std", "avatar_pro", "gemini_omni_audio", "gemini_omni_character"}:
        settings_lines.append(f"   📐 Формат: <code>{current_ratio}</code>")

    if current_model == "grok_imagine":
        settings_lines.append(f"   🧠 Режим Grok: <code>{grok_mode}</code>")
    if current_model == "grok_imagine_v15":
        settings_lines.append(f"   🖥 Качество Grok: <code>{grok_resolution}</code>")
    if current_model == "v26_pro":
        settings_lines.append(
            f"   🚫 Negative: <code>{kling_negative_prompt or 'off'}</code>"
        )
        settings_lines.append(f"   🎚 CFG: <code>{kling_cfg_scale:.1f}</code>")
    if current_model.startswith("veo3"):
        veo_mode_label_map = {
            "TEXT_2_VIDEO": "Text -> Video",
            "FIRST_AND_LAST_FRAMES_2_VIDEO": "Frames -> Video",
            "REFERENCE_2_VIDEO": "Reference -> Video",
        }
        settings_lines.append(
            f"   🎥 Veo режим: <code>{veo_mode_label_map.get(veo_generation_type, veo_generation_type)}</code>"
        )
        settings_lines.append(
            f"   🌐 Перевод: <code>{'вкл' if veo_translation else 'выкл'}</code>"
        )
        settings_lines.append(f"   🖥 Качество: <code>{veo_resolution}</code>")
        if veo_seed is not None:
            settings_lines.append(f"   🎲 Seed: <code>{veo_seed}</code>")
        if veo_watermark:
            settings_lines.append(f"   🏷 Метка: <code>{veo_watermark}</code>")
    if current_model == "gemini_omni_video":
        settings_lines.append(f"   🖥 Качество: <code>{omni_resolution}</code>")
        if omni_seed is not None:
            settings_lines.append(f"   🎲 Seed: <code>{omni_seed}</code>")
        if omni_audio_ids:
            settings_lines.append(f"   🎧 Audio ID: <code>{len(omni_audio_ids)}</code>")
        if omni_character_ids:
            settings_lines.append(
                f"   🧍 Character ID: <code>{len(omni_character_ids)}</code>"
            )
    if current_model == "gemini_omni_audio":
        settings_lines.append(f"   🎙 Базовый голос: <code>{omni_base_voice}</code>")
        settings_lines.append(
            f"   🏷 Имя: <code>{omni_voice_name or 'авто из промпта'}</code>"
        )
        if omni_voice_description:
            settings_lines.append("   🗣 Описание: <code>заполнено</code>")
        if omni_example_dialogue:
            settings_lines.append("   💬 Пример фразы: <code>заполнено</code>")
    if current_model == "gemini_omni_character":
        settings_lines.append(
            f"   🏷 Персонаж: <code>{omni_character_name or 'авто из промпта'}</code>"
        )
        if omni_character_audio_ids:
            settings_lines.append(
                f"   🎧 Audio ID: <code>{len(omni_character_audio_ids)}</code>"
            )

    if current_model == "gemini_omni_audio":
        prompt_title = "Опишите голос"
        prompt_guidance = (
            "Напишите простыми словами:\n"
            "• тембр и возраст звучания\n"
            "• темп, эмоцию и акцент\n"
            "• для каких роликов нужен голос"
        )
    elif current_model == "gemini_omni_character":
        prompt_title = "Опишите персонажа"
        prompt_guidance = (
            "Напишите простыми словами:\n"
            "• внешность и одежду\n"
            "• характер и настроение\n"
            "• какую роль персонаж будет играть в видео"
        )
    else:
        prompt_title = "Опишите видео"
        prompt_guidance = (
            "Напишите простыми словами:\n"
            "• что происходит в кадре\n"
            "• как двигается камера\n"
            "• какой нужен стиль или настроение"
        )

    text = (
        f"🎬 <b>Создание видео</b>\n"
        f"<b>Шаг 3. Настройки и промпт</b>\n"
        f"{ref_text}"
        f"⚙️ <b>Текущие настройки:</b>\n" + "\n".join(settings_lines) + "\n"
        f"{media_status}"
        f"{prompt_text}\n"
        f"<b>{prompt_title}</b>\n"
        f"{prompt_guidance}"
    )

    # Напоминание о загрузке медиа
    if current_v_type == "avatar" and not (v_image_url and avatar_audio_url):
        text += "<i>🗣 Сначала загрузите фото аватара и аудио.</i>"
    elif current_v_type == "character" and not v_image_url:
        text += "<i>🖼 Сначала загрузите изображение персонажа.</i>"
    elif (
        current_v_type == "imgtxt"
        and not v_image_url
        and current_model != "gemini_omni_video"
    ):
        text += f"<i>📷 Сначала загрузите фото для первого кадра.</i>"
    elif current_v_type == "video" and not v_reference_videos:
        text += (
            f"<i>📹 При желании загрузите до {max_video_refs} коротких "
            "видео-референсов.</i>"
        )
    elif current_model == "gemini_omni_video" and has_omni_video_ref:
        text += (
            "\n<i>Когда добавлен видео-референс, настройка секунд не гарантирует "
            "финальную длину ролика.</i>"
        )

    keyboard = _build_video_creation_keyboard(data)

    # Используем edit для callback, send для message
    try:
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.message.edit_text(
                text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        elif edit:
            await message_or_callback.edit_text(
                text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        else:
            await message_or_callback.answer(
                text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
    except TelegramBadRequest as e:
        error_msg = str(e).lower()
        if "message is not modified" in error_msg:
            pass
        elif isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.message.answer(
                text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        else:
            await message_or_callback.answer(
                text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
    except AttributeError:
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.answer("Экран создания уже открыт")
        else:
            await message_or_callback.answer(
                text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )

    # Устанавливаем состояние ожидания промпта для видео
    await state.set_state(GenerationStates.waiting_for_video_prompt)
    logger.info(
        f"[DEBUG] State set to waiting_for_video_prompt for user {message_or_callback.from_user.id if hasattr(message_or_callback, 'from_user') else 'callback'}"
    )


def _build_video_creation_keyboard(data: dict):
    return get_create_video_keyboard(
        current_v_type=data.get("v_type", "text"),
        current_model=data.get("v_model", "v3_std"),
        current_duration=data.get("v_duration", 5),
        current_ratio=data.get("v_ratio", "16:9"),
        current_mode=data.get("v_mode", "720p"),
        current_orientation=data.get("v_orientation", "video"),
        current_grok_mode=data.get("grok_mode", "normal"),
        current_grok_resolution=data.get("grok_resolution", "480p"),
        current_veo_generation_type=data.get("veo_generation_type", "TEXT_2_VIDEO"),
        current_veo_translation=data.get("veo_translation", True),
        current_veo_resolution=data.get("veo_resolution", "720p"),
        current_veo_seed=data.get("veo_seed"),
        current_veo_watermark=data.get("veo_watermark", ""),
        current_kling_negative_prompt=data.get("kling_negative_prompt", ""),
        current_kling_cfg_scale=float(data.get("kling_cfg_scale", 0.5)),
        current_omni_resolution=data.get("omni_resolution", "720p"),
        current_omni_seed=data.get("omni_seed"),
        current_omni_audio_ids=data.get("omni_audio_ids", []),
        current_omni_character_ids=data.get("omni_character_ids", []),
        current_omni_base_voice=data.get("omni_base_voice", "achernar"),
        current_omni_voice_name=data.get("omni_voice_name", ""),
        current_omni_character_name=data.get("omni_character_name", ""),
        current_omni_character_audio_ids=data.get("omni_character_audio_ids", []),
    )


def _get_supported_video_durations(model: str) -> list[int]:
    """Return supported durations for the Telegram video flow."""
    if model.startswith("veo3"):
        return [4, 6, 8]
    if model in {"gemini_omni", "gemini_omni_video"}:
        return [4, 6, 8, 10]
    if model in {"gemini_omni_audio", "gemini_omni_character"}:
        return [6]
    if model == "grok_imagine_v15":
        return list(range(1, 16))
    if model in {"avatar_std", "avatar_pro", "motion_control_v26", "motion_control_v30"}:
        return [5]

    model_config = (
        preset_manager._price_config.get("costs_reference", {})
        .get("video_models", {})
        .get(model, {})
    )
    duration_costs = model_config.get("duration_costs", {})
    if duration_costs:
        return sorted(int(value) for value in duration_costs.keys())
    return [5, 10, 15]


def _normalize_video_duration_value(model: str, duration: int) -> int:
    """Snap duration to the closest supported value for the selected model."""
    if model in {"motion_control_v26", "motion_control_v30"}:
        # Motion Control тарифицируется по фактической длине загруженного видео,
        # поэтому не прижимаем его к фиксированным длительностям из общего video UX.
        return max(1, min(30, int(duration)))

    supported = _get_supported_video_durations(model)
    duration = int(duration)
    if duration in supported:
        return duration
    return min(supported, key=lambda value: (abs(value - duration), value))


async def _normalize_video_duration_state(state: FSMContext) -> None:
    """Keep stored duration aligned with the selected model."""
    data = await state.get_data()
    current_model = data.get("v_model", "v3_std")
    current_duration = int(data.get("v_duration", 5))
    normalized_duration = _normalize_video_duration_value(
        current_model, current_duration
    )
    if normalized_duration != current_duration:
        await state.update_data(v_duration=normalized_duration)


async def _normalize_veo_state(state: FSMContext):
    data = await state.get_data()
    current_model = data.get("v_model", "v3_std")
    if not current_model.startswith("veo3"):
        return

    updates = {}
    current_v_type = data.get("v_type", "text")
    current_ratio = data.get("v_ratio", "16:9")
    veo_generation_type = data.get("veo_generation_type")

    if current_ratio not in {"16:9", "9:16", "Auto"}:
        updates["v_ratio"] = "16:9"

    if current_v_type == "text":
        if veo_generation_type != "TEXT_2_VIDEO":
            updates["veo_generation_type"] = "TEXT_2_VIDEO"
    elif current_v_type == "imgtxt":
        if veo_generation_type not in {
            "FIRST_AND_LAST_FRAMES_2_VIDEO",
            "REFERENCE_2_VIDEO",
        }:
            updates["veo_generation_type"] = "FIRST_AND_LAST_FRAMES_2_VIDEO"
        if current_model != "veo3_fast" and veo_generation_type == "REFERENCE_2_VIDEO":
            updates["veo_generation_type"] = "FIRST_AND_LAST_FRAMES_2_VIDEO"
    else:
        updates["v_type"] = "text"
        updates["veo_generation_type"] = "TEXT_2_VIDEO"

    if "veo_translation" not in data:
        updates["veo_translation"] = True
    if "veo_resolution" not in data:
        updates["veo_resolution"] = "720p"
    if "veo_watermark" not in data:
        updates["veo_watermark"] = ""

    if updates:
        await state.update_data(**updates)


def _build_video_run_summary(
    v_model: str,
    v_type: str,
    v_ratio: str,
    v_duration: int,
    data: dict,
) -> str:
    parts = [
        f"🤖 <code>{get_video_model_label(v_model)}</code>",
        f"📝 <code>{get_video_type_label(v_type)}</code>",
    ]
    has_omni_video_ref = (
        v_model == "gemini_omni_video"
        and bool(_collect_gemini_omni_video_urls(data.get("v_reference_videos", [])))
    )
    if v_model not in {"avatar_std", "avatar_pro", "gemini_omni_audio", "gemini_omni_character"}:
        parts.append(f"📐 <code>{v_ratio}</code>")
    if v_model not in {"avatar_std", "avatar_pro", "gemini_omni_audio", "gemini_omni_character"}:
        if has_omni_video_ref:
            parts.append("⏱ <code>по видео-рефу</code>")
        else:
            parts.append(f"⏱ <code>{v_duration}s</code>")

    if v_model == "grok_imagine":
        parts.append(f"🧠 <code>{data.get('grok_mode', 'normal')}</code>")
    if v_model == "grok_imagine_v15":
        parts.append(f"🖥 <code>{data.get('grok_resolution', '480p')}</code>")
    if v_model == "v26_pro":
        negative = data.get("kling_negative_prompt", "")
        parts.append(f"🎚 <code>{float(data.get('kling_cfg_scale', 0.5)):.1f}</code>")
        if negative:
            parts.append("🚫 <code>negative on</code>")

    if v_model.startswith("veo3"):
        veo_mode = data.get("veo_generation_type", "TEXT_2_VIDEO")
        veo_mode_label_map = {
            "TEXT_2_VIDEO": "Text -> Video",
            "FIRST_AND_LAST_FRAMES_2_VIDEO": "Frames -> Video",
            "REFERENCE_2_VIDEO": "Reference -> Video",
        }
        parts.append(f"🎥 <code>{veo_mode_label_map.get(veo_mode, veo_mode)}</code>")
        parts.append(
            f"🌐 <code>{'перевод вкл' if data.get('veo_translation', True) else 'перевод выкл'}</code>"
        )
        parts.append(f"🖥 <code>{data.get('veo_resolution', '720p')}</code>")
        veo_seed = data.get("veo_seed")
        if veo_seed is not None:
            parts.append(f"🎲 <code>{veo_seed}</code>")
        veo_watermark = data.get("veo_watermark")
        if veo_watermark:
            parts.append(f"🏷 <code>{veo_watermark}</code>")
    if v_model == "gemini_omni_video":
        parts.append(f"🖥 <code>{data.get('omni_resolution', '720p')}</code>")
        if data.get("omni_seed") is not None:
            parts.append(f"🎲 <code>{data.get('omni_seed')}</code>")
        if data.get("omni_audio_ids"):
            parts.append(f"🎧 <code>{len(data.get('omni_audio_ids') or [])}</code>")
        if data.get("omni_character_ids"):
            parts.append(
                f"🧍 <code>{len(data.get('omni_character_ids') or [])}</code>"
            )
    if v_model == "gemini_omni_audio":
        parts.append(f"🎙 <code>{data.get('omni_base_voice', 'achernar')}</code>")
    if v_model == "gemini_omni_character":
        parts.append(f"🧍 <code>{data.get('omni_character_name') or 'auto'}</code>")

    return " | ".join(parts)


def _build_image_creation_text(data: dict) -> str:
    current_service = data.get("img_service", "banana_pro")
    current_ratio = data.get(
        "img_ratio",
        "auto" if current_service == "flux_pro" else "1:1",
    )
    current_count = data.get("img_count", 1)
    reference_images = data.get("reference_images", [])
    nsfw_enabled = data.get("nsfw_enabled", False)
    img_quality = data.get("img_quality", "2K")
    img_nsfw_checker = data.get("img_nsfw_checker", False)
    ratio_label = current_ratio.replace(":", "∶")
    # nano_quality_cost_display_v1
    unit_cost = _resolve_image_unit_cost(current_service, img_quality)
    total_cost = unit_cost * current_count

    info_lines = [
        f"• Модель: <code>{get_image_model_label(current_service)}</code>",
        f"• Формат: <code>{ratio_label}</code>",
        f"• Количество: <code>{current_count}</code>",
        f"• Стоимость: <code>{unit_cost}🍌 × {current_count} = {total_cost}🍌</code>",
    ]
    if reference_images:
        info_lines.append(f"• Референсы: <code>{len(reference_images)}</code>")
    elif current_service in {"flux_pro", "seedream_5_pro"}:
        info_lines.append("• Референсы: <code>0 (text-to-image)</code>")
    if current_service in {"seedream_edit", "seedream_5_pro"}:
        info_lines.append(f"• Quality: <code>{img_quality}</code>")

    prompt_hint = (
        "Опишите, что нужно изменить на загруженном изображении."
        if current_service == "seedream_edit"
        else (
            "Опишите, что хотите создать с нуля или как переработать загруженные фото."
            if current_service == "seedream_5_pro"
            else (
            "Опишите, что нужно изменить на загруженных фото."
            if current_service == "grok_imagine_i2i"
            else (
                "Опишите, что хотите создать или как переработать загруженные изображения."
                if current_service == "flux_pro"
                else "Опишите, что хотите создать."
            )
            )
        )
    )

    return (
        "🖼 <b>Создание фото</b>\n"
        + "<b>Шаг 3. Настройки и промпт</b>\n"
        + "Модель уже выбрана. Ниже можно настроить результат и отправить описание.\n\n"
        + "<b>Текущие настройки</b>\n"
        + "\n".join(info_lines)
        + "\n\n<b>Промпт</b>\n"
        + prompt_hint
    )


async def _show_image_model_selection_screen(
    message_or_callback, state: FSMContext, edit: bool = True
):
    data = await state.get_data()
    current_service = data.get("img_service", "banana_pro")
    user_id = (
        message_or_callback.from_user.id
        if hasattr(message_or_callback, "from_user")
        else None
    )
    user_credits = await get_user_credits(user_id) if user_id else 0
    max_refs = _get_max_image_references(current_service)
    text = (
        "🖼 <b>Создание фото</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code> бананов\n\n"
        "<b>Шаг 1. Выберите модель</b>\n"
        "Сначала выберите модель.\n"
        "После этого бот покажет следующий шаг: референсы или настройки."
    )
    keyboard = get_image_model_selection_keyboard(current_service)

    try:
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.message.edit_text(
                text, reply_markup=keyboard, parse_mode="HTML"
            )
        elif edit:
            await message_or_callback.edit_text(
                text, reply_markup=keyboard, parse_mode="HTML"
            )
        else:
            await message_or_callback.answer(
                text, reply_markup=keyboard, parse_mode="HTML"
            )
    except Exception:
        await message_or_callback.answer(text, reply_markup=keyboard, parse_mode="HTML")

    await state.set_state(GenerationStates.waiting_for_input)


async def _show_image_references_screen(
    message_or_callback,
    state: FSMContext,
    *,
    current_count: int = 0,
):
    data = await state.get_data()
    current_service = data.get("img_service", "banana_pro")
    user_id = (
        message_or_callback.from_user.id
        if hasattr(message_or_callback, "from_user")
        else None
    )
    user_credits = await get_user_credits(user_id) if user_id else 0
    max_refs = _get_max_image_references(current_service)
    text = (
        "🖼 <b>Создание фото</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code> бананов\n\n"
        "<b>Шаг 2. Референсы</b>\n"
        f"Выбрана модель: <code>{get_image_model_label(current_service)}</code>\n\n"
        + (
            "Для <b>GPT Image 2</b> фото не обязательны.\n"
            "Если загрузите фото, бот изменит его.\n"
            "Если пропустите шаг, бот создаст картинку с нуля.\n\n"
            if current_service == "flux_pro"
            else (
                "Для <b>Seedream 5 Pro</b> фото не обязательны.\n"
                "Без фото модель работает как text-to-image, а с фото переключается в image-to-image.\n\n"
                if current_service == "seedream_5_pro"
                else (
                "Для <b>Seedream 4.5 Edit</b> нужно хотя бы одно исходное фото.\n"
                "Можно добавить и дополнительные фото, если это поможет.\n\n"
                if current_service == "seedream_edit"
                else "Референсы не обязательны, но помогают сохранить человека, "
                "стиль, одежду, товар или композицию.\n\n"
                )
            )
        )
        + f"<i>Можно загрузить до {max_refs} фото. Когда всё готово, нажмите «Продолжить».</i>"
    )

    try:
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.message.edit_text(
                text,
                reply_markup=get_reference_images_upload_keyboard(
                    current_count, max_refs, "new"
                ),
                parse_mode="HTML",
            )
        else:
            await message_or_callback.answer(
                text,
                reply_markup=get_reference_images_upload_keyboard(
                    current_count, max_refs, "new"
                ),
                parse_mode="HTML",
            )
    except Exception:
        await message_or_callback.answer(
            text,
            reply_markup=get_reference_images_upload_keyboard(
                current_count, max_refs, "new"
            ),
            parse_mode="HTML",
        )

    await state.set_state(GenerationStates.uploading_reference_images)


async def _show_image_creation_screen(
    message_or_callback,
    state: FSMContext,
    *,
    edit: bool = True,
    intro_text: str = "",
):
    data = await state.get_data()
    text = f"{intro_text}{_build_image_creation_text(data)}"
    reply_markup = get_create_image_keyboard(
        current_service=data.get("img_service", "banana_pro"),
        current_ratio=data.get("img_ratio", "1:1"),
        current_count=data.get("img_count", 1),
        num_refs=len(data.get("reference_images", [])),
        nsfw_enabled=data.get("nsfw_enabled", False),
        img_quality=data.get("img_quality", "2K"),
        img_nsfw_checker=data.get("img_nsfw_checker", False),
    )

    try:
        if isinstance(message_or_callback, types.CallbackQuery):
            if edit:
                await message_or_callback.message.edit_text(
                    text,
                    reply_markup=reply_markup,
                    parse_mode="HTML",
                )
            else:
                await message_or_callback.message.answer(
                    text,
                    reply_markup=reply_markup,
                    parse_mode="HTML",
                )
        elif edit:
            await message_or_callback.edit_text(
                text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        else:
            await message_or_callback.answer(
                text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
    except TelegramBadRequest as e:
        error_msg = str(e).lower()
        if "message is not modified" in error_msg:
            pass
        elif isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.message.answer(
                text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        else:
            await message_or_callback.answer(
                text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
    except AttributeError:
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.message.answer(
                text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        else:
            await message_or_callback.answer(
                text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )

    await state.set_state(GenerationStates.waiting_for_input)


async def _show_video_model_selection_screen(
    message_or_callback, state: FSMContext, edit: bool = True
):
    data = await state.get_data()
    current_model = data.get("v_model", "v3_pro")
    user_id = (
        message_or_callback.from_user.id
        if hasattr(message_or_callback, "from_user")
        else None
    )
    user_credits = await get_user_credits(user_id) if user_id else 0
    text = (
        "🎬 <b>Создание видео</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code> бананов\n\n"
        "<b>Шаг 1. Выберите модель</b>\n"
        "Сначала выберите модель видео.\n"
        "После этого бот покажет следующий шаг именно для неё."
    )
    keyboard = get_video_model_selection_keyboard(current_model)

    try:
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.message.edit_text(
                text, reply_markup=keyboard, parse_mode="HTML"
            )
        elif edit:
            await message_or_callback.edit_text(
                text, reply_markup=keyboard, parse_mode="HTML"
            )
        else:
            await message_or_callback.answer(
                text, reply_markup=keyboard, parse_mode="HTML"
            )
    except Exception:
        await message_or_callback.answer(text, reply_markup=keyboard, parse_mode="HTML")

    await state.set_state(GenerationStates.waiting_for_input)


async def _show_gemini_omni_mode_screen(
    message_or_callback, state: FSMContext, edit: bool = True
):
    user_id = (
        message_or_callback.from_user.id
        if hasattr(message_or_callback, "from_user")
        else None
    )
    user_credits = await get_user_credits(user_id) if user_id else 0
    audio_cost = preset_manager.get_video_cost("gemini_omni_audio", 6)
    character_cost = preset_manager.get_video_cost("gemini_omni_character", 6)
    video_cost_6 = preset_manager.get_video_cost_with_quality(
        "gemini_omni_video", 6, "720p"
    )

    text = (
        "🔷 <b>Gemini Omni</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code> бананов\n\n"
        "<b>Что умеет</b>\n"
        "• <b>Video</b> — генерирует видео из текста, стартового изображения, фото-референсов, одного видео-рефа, Audio ID и Character ID.\n"
        "  Длительность: <code>4/6/8/10</code> сек, формат: <code>16:9</code> или <code>9:16</code>, качество: <code>720p/1080p/4k</code>, seed опционален.\n"
        "  Можно добавить до <code>7</code> визуальных референсов; один видео-реф тоже занимает часть этого лимита.\n\n"
        "• <b>Audio ID</b> — создаёт сохранённый голос: выберите базовый голос, имя, описание тембра и пример фразы. Бот вернёт ID, который потом вставляется в Video.\n\n"
        "• <b>Character ID</b> — создаёт сохранённого персонажа по одному изображению, описанию, имени и опциональному Audio ID. Бот вернёт ID персонажа для Video.\n\n"
        "<b>Как лучше пользоваться</b>\n"
        "1. Если нужен фирменный голос — сначала сделайте <b>Audio ID</b>.\n"
        "2. Если нужен постоянный герой — сделайте <b>Character ID</b> и при желании привяжите к нему Audio ID.\n"
        "3. Затем откройте <b>Video</b> и добавьте нужные ID вместе с промптом и референсами.\n\n"
        "<b>Подсказка</b>: ID можно скопировать из результата и вставить в настройки Gemini Omni Video.\n\n"
        f"<b>Стоимость</b>: Video от <code>{video_cost_6}</code>🍌 за 6 сек, "
        f"Audio ID <code>{audio_cost}</code>🍌, Character ID <code>{character_cost}</code>🍌."
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="🎬 Video", callback_data="omni_mode_video")
    builder.button(text="🎧 Audio ID", callback_data="omni_mode_audio")
    builder.button(text="🧍 Character ID", callback_data="omni_mode_character")
    builder.button(text="🤖 К моделям", callback_data="video_change_model")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1, 2, 2)
    keyboard = builder.as_markup()

    try:
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.message.edit_text(
                text, reply_markup=keyboard, parse_mode="HTML"
            )
        elif edit:
            await message_or_callback.edit_text(
                text, reply_markup=keyboard, parse_mode="HTML"
            )
        else:
            await message_or_callback.answer(
                text, reply_markup=keyboard, parse_mode="HTML"
            )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise
    except Exception:
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.message.answer(
                text, reply_markup=keyboard, parse_mode="HTML"
            )
        else:
            await message_or_callback.answer(
                text, reply_markup=keyboard, parse_mode="HTML"
            )

    await state.set_state(GenerationStates.waiting_for_input)


async def _show_video_media_screen(
    message_or_callback, state: FSMContext, edit: bool = True
):
    def _fit_telegram_text(raw: str, limit: int = 4096) -> str:
        if len(raw) <= limit:
            return raw
        return raw[: limit - 1].rstrip() + "…"

    async def _safe_answer_message(target_message, raw_text: str):
        try:
            await target_message.answer(
                raw_text, reply_markup=keyboard, parse_mode="HTML"
            )
        except TelegramBadRequest as send_error:
            send_error_msg = str(send_error).lower()
            if "message_too_long" in send_error_msg or "message is too long" in send_error_msg:
                await target_message.answer(
                    _fit_telegram_text(raw_text, 3500),
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
            elif "message is not modified" in send_error_msg:
                pass
            else:
                raise

    data = await state.get_data()
    current_model = data.get("v_model", "v3_pro")
    current_v_type = data.get("v_type", "text")
    max_video_refs = get_max_video_references(current_model)
    v_image_url = data.get("v_image_url")
    avatar_audio_url = data.get("avatar_audio_url")
    reference_images = data.get("reference_images", [])
    v_reference_videos = data.get("v_reference_videos", [])
    user_id = (
        message_or_callback.from_user.id
        if hasattr(message_or_callback, "from_user")
        else None
    )
    user_credits = await get_user_credits(user_id) if user_id else 0

    if current_v_type == "avatar":
        body = (
            "<b>Шаг 2. Аватар и аудио</b>\n"
            f"Модель: <code>{get_video_model_label(current_model)}</code>\n\n"
            "Загрузите 1 фото аватара и 1 аудиофайл.\n"
            "После этого можно переходить к описанию."
        )
        next_state = GenerationStates.waiting_for_video_prompt
    elif current_model == "gemini_omni_video":
        omni_image_urls = _collect_gemini_omni_image_urls(v_image_url, reference_images)
        omni_video_urls = _collect_gemini_omni_video_urls(v_reference_videos)
        omni_character_ids = data.get("omni_character_ids", [])
        omni_units = _gemini_omni_input_units(
            omni_image_urls,
            omni_video_urls,
            omni_character_ids,
        )
        body = (
            "<b>Шаг 2. Фото + видео</b>\n"
            f"Модель: <code>{get_video_model_label(current_model)}</code>\n\n"
            "Можно отправить фото, одно видео или сразу промпт. "
            "Фото задают объект/сцену/стиль, видео задаёт движение или камеру.\n"
            f"Входы: <code>{omni_units}/7</code> "
            f"(фото {len(omni_image_urls)}, видео {len(omni_video_urls)}×2, "
            f"Character ID {len(omni_character_ids)})."
        )
        next_state = GenerationStates.waiting_for_video_prompt
    elif current_v_type == "character":
        body = (
            "<b>Шаг 2. Character image</b>\n"
            f"Модель: <code>{get_video_model_label(current_model)}</code>\n\n"
            "Отправьте одно изображение персонажа. После этого можно переходить к описанию."
        )
        next_state = GenerationStates.waiting_for_video_prompt
    elif current_v_type == "audio":
        body = (
            "<b>Шаг 2. Audio ID</b>\n"
            f"Модель: <code>{get_video_model_label(current_model)}</code>\n\n"
            "Медиа не требуется. Настройте базовый голос и имя, затем отправьте описание."
        )
        next_state = GenerationStates.waiting_for_video_prompt
    elif current_v_type == "imgtxt":
        if current_model == "grok_imagine_v15":
            media_hint = (
                "Выбран режим <b>Фото + Текст → Видео</b>.\n"
                "Для Grok Imagine 1.5 нужно одно стартовое фото."
            )
        elif current_model == "grok_imagine":
            media_hint = (
                "Выбран режим <b>Фото + Текст → Видео</b>.\n"
                "Сначала отправьте стартовое фото. После него можно добавить "
                "дополнительные фото-референсы для старого Grok."
            )
        elif current_model == "v26_pro":
            media_hint = (
                "Выбран режим <b>Фото + Текст → Видео</b>.\n"
                "Для Kling 2.5 Turbo нужно только одно стартовое фото."
            )
        else:
            media_hint = (
                "Выбран режим <b>Фото + Текст → Видео</b>.\n"
                "Сначала отправьте стартовое фото.\n"
                "При желании потом можно добавить ещё фото-референсы."
            )
        body = (
            "<b>Шаг 2. Тип и медиа</b>\n"
            f"Модель: <code>{get_video_model_label(current_model)}</code>\n\n"
            + media_hint
        )
        next_state = GenerationStates.waiting_for_video_prompt
    elif current_v_type == "video":
        body = (
            "<b>Шаг 2. Тип и медиа</b>\n"
            f"Модель: <code>{get_video_model_label(current_model)}</code>\n\n"
            "Выбран режим <b>Видео + Текст → Видео</b>.\n"
            f"Загрузите до {max_video_refs} коротких видео или пропустите шаг."
        )
        next_state = GenerationStates.uploading_reference_videos
    else:
        body = (
            "<b>Шаг 2. Тип и медиа</b>\n"
            f"Модель: <code>{get_video_model_label(current_model)}</code>\n\n"
            "Выбран режим <b>Текст → Видео</b>.\n"
            "Ничего загружать не нужно. Можно сразу переходить дальше."
        )
        next_state = GenerationStates.waiting_for_video_prompt

    text = (
        "🎬 <b>Создание видео</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code> бананов\n\n"
        f"{body}"
    )
    text = _fit_telegram_text(text)
    keyboard = get_video_media_step_keyboard(
        current_v_type=current_v_type,
        current_model=current_model,
        has_start_image=bool(v_image_url),
        reference_image_count=len(reference_images),
        reference_video_count=len(v_reference_videos),
        has_avatar_audio=bool(avatar_audio_url),
        max_reference_video_count=max_video_refs,
    )

    try:
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.message.edit_text(
                text, reply_markup=keyboard, parse_mode="HTML"
            )
        elif edit:
            await message_or_callback.edit_text(
                text, reply_markup=keyboard, parse_mode="HTML"
            )
        else:
            await message_or_callback.answer(
                text, reply_markup=keyboard, parse_mode="HTML"
            )
    except TelegramBadRequest as e:
        error_msg = str(e).lower()
        if "message is not modified" in error_msg:
            pass
        elif isinstance(message_or_callback, types.CallbackQuery):
            await _safe_answer_message(message_or_callback.message, text)
        else:
            await _safe_answer_message(message_or_callback, text)
    except AttributeError:
        if isinstance(message_or_callback, types.CallbackQuery):
            await _safe_answer_message(message_or_callback.message, text)
        else:
            await _safe_answer_message(message_or_callback, text)
    except Exception:
        logger.exception("Failed to render video media screen")

    await state.set_state(next_state)


@router.callback_query(F.data == "img_ref_continue_new")
async def handle_img_ref_continue_new(callback: types.CallbackQuery, state: FSMContext):
    """Продолжает после загрузки референсов - сразу к параметрам видео (без проверки наличия референсов)"""
    # УБРАНА ПРОВЕРКА: референсы опциональны, всегда продолжаем
    data = await state.get_data()
    generation_type = data.get("generation_type")
    current_service = data.get("img_service", "banana_pro")
    reference_images = data.get("reference_images", [])

    if data.get("repeat_source_task_id"):
        await _show_repeat_image_screen(callback, state, edit=True)
        await callback.answer("Проверьте фото и запустите повтор")
        return

    if (
        generation_type == "image"
        and current_service == "seedream_edit"
        and not reference_images
    ):
        await callback.answer(
            "Для Seedream 4.5 Edit нужно загрузить хотя бы одно изображение",
            show_alert=True,
        )
        return

    if generation_type == "video":
        # Сразу показываем единый экран с параметрами и промптом (без подтверждения)
        await _show_video_creation_screen(callback.message, state)
        await callback.answer()
        return
    else:
        await state.update_data(img_flow_step="configure")
        await _show_image_creation_screen(callback, state)
        await callback.answer()


async def _update_reference_upload_message(bot: Bot, chat_id: int, message_id: int, state: FSMContext) -> None:
    data = await state.get_data()
    img_service = data.get("img_service", "banana_pro")
    preset_id = data.get("preset_id", "new")
    reference_images = list(data.get("reference_images") or [])
    max_refs = _get_max_image_references(img_service)
    await bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=(
            f"📎 <b>Загрузка референсов</b>\n"
            f"Загружено: <code>{len(reference_images)}/{max_refs}</code>\n\n"
            "Можно отправить ещё фото или открыть сохранённые рефы."
        ),
        reply_markup=get_reference_images_upload_keyboard(
            len(reference_images), max_refs, preset_id
        ),
        parse_mode="HTML",
    )


async def _send_saved_reference_preview(
    target_message: types.Message,
    state: FSMContext,
    *,
    refs: list,
    index: int,
) -> types.Message | None:
    if not refs:
        return None

    safe_index = max(0, min(index, len(refs) - 1))
    ref = refs[safe_index]
    data = await state.get_data()
    reference_images = list(data.get("reference_images") or [])
    already_selected = ref.file_url in reference_images
    created_at = ref.created_at.strftime("%d.%m.%Y %H:%M") if ref.created_at else "—"
    filename = ref.original_filename or os.path.basename(ref.file_url or "") or "reference"
    caption = (
        f"📚 <b>Сохранённый реф</b>\n"
        f"• {safe_index + 1} из {len(refs)}\n"
        f"• Файл: <code>{filename[:64]}</code>\n"
        f"• Сохранён: <code>{created_at}</code>\n"
        f"• Статус: <code>{'уже добавлен в текущую сессию' if already_selected else 'готов к использованию'}</code>"
    )
    reply_markup = get_saved_reference_picker_keyboard(
        ref.id,
        safe_index,
        len(refs),
        already_selected=already_selected,
    )

    try:
        return await target_message.answer_photo(
            photo=ref.file_url,
            caption=caption,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
    except TelegramBadRequest:
        from bot.services.media_input_utils import resolve_local_upload_path

        local_path = resolve_local_upload_path(ref.file_url)
        if not local_path or not os.path.exists(local_path):
            await target_message.answer(
                "Не удалось открыть сохранённый реф. Возможно, файл больше недоступен.",
                reply_markup=get_main_menu_button_keyboard(),
            )
            return None

        with open(local_path, "rb") as f:
            image_bytes = f.read()
        return await target_message.answer_photo(
            photo=types.BufferedInputFile(image_bytes, filename=filename),
            caption=caption,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )


@router.callback_query(F.data == "savedref_noop")
async def saved_reference_noop(callback: types.CallbackQuery):
    await callback.answer()


@router.callback_query(F.data == "savedref_close")
async def close_saved_reference_preview(callback: types.CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer("Закрыл")


@router.callback_query(F.data == "ref_saved_library")
async def open_saved_reference_library(callback: types.CallbackQuery, state: FSMContext):
    saved_refs = await list_saved_references(callback.from_user.id, kind="image", limit=50)
    if not saved_refs:
        await callback.answer("Сохранённых рефов пока нет", show_alert=True)
        return

    await state.update_data(
        saved_ref_return_chat_id=callback.message.chat.id,
        saved_ref_return_message_id=callback.message.message_id,
    )
    await _send_saved_reference_preview(callback.message, state, refs=saved_refs, index=0)
    await callback.answer()


@router.callback_query(F.data.startswith("savedref_nav_"))
async def navigate_saved_reference_library(callback: types.CallbackQuery, state: FSMContext):
    try:
        index = int(callback.data.rsplit("_", 1)[-1])
    except ValueError:
        await callback.answer("Не удалось открыть реф", show_alert=True)
        return

    saved_refs = await list_saved_references(callback.from_user.id, kind="image", limit=50)
    if not saved_refs:
        await callback.answer("Сохранённых рефов больше нет", show_alert=True)
        try:
            await callback.message.delete()
        except Exception:
            pass
        return

    try:
        await callback.message.delete()
    except Exception:
        pass
    await _send_saved_reference_preview(callback.message, state, refs=saved_refs, index=index)
    await callback.answer()


@router.callback_query(F.data.startswith("savedref_use_"))
async def use_saved_reference_from_library(callback: types.CallbackQuery, state: FSMContext):
    try:
        reference_id = int(callback.data.rsplit("_", 1)[-1])
    except ValueError:
        await callback.answer("Не удалось добавить реф", show_alert=True)
        return

    saved_refs = await list_saved_references(callback.from_user.id, kind="image", limit=50)
    candidate = next((ref for ref in saved_refs if ref.id == reference_id), None)
    if not candidate:
        await callback.answer("Реф не найден", show_alert=True)
        return

    data = await state.get_data()
    img_service = data.get("img_service", "banana_pro")
    max_refs = _get_max_image_references(img_service)
    reference_images = list(data.get("reference_images") or [])
    if candidate.file_url in reference_images:
        await callback.answer("Этот реф уже добавлен", show_alert=True)
        return
    if len(reference_images) >= max_refs:
        await callback.answer("Уже достигнут лимит референсов", show_alert=True)
        return

    reference_images.append(candidate.file_url)
    await state.update_data(reference_images=reference_images)

    return_chat_id = data.get("saved_ref_return_chat_id")
    return_message_id = data.get("saved_ref_return_message_id")
    if return_chat_id and return_message_id:
        try:
            await _update_reference_upload_message(callback.bot, return_chat_id, return_message_id, state)
        except Exception:
            logger.exception("Failed to refresh upload screen after selecting saved ref")

    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer("Реф добавлен")
    await callback.message.answer(
        f"✅ Сохранённый реф добавлен. Сейчас в сессии: <code>{len(reference_images)}/{max_refs}</code>",
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("savedref_delete_"))
async def delete_saved_reference_from_library(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    if len(parts) < 4:
        await callback.answer("Не удалось удалить реф", show_alert=True)
        return
    try:
        reference_id = int(parts[2])
        current_index = int(parts[3])
    except ValueError:
        await callback.answer("Не удалось удалить реф", show_alert=True)
        return

    deleted = await delete_saved_reference(callback.from_user.id, reference_id)
    if not deleted:
        await callback.answer("Реф уже удалён", show_alert=True)
        return

    data = await state.get_data()
    reference_images = list(data.get("reference_images") or [])
    saved_refs_after = await list_saved_references(callback.from_user.id, kind="image", limit=50)
    valid_urls = {ref.file_url for ref in saved_refs_after}
    updated_reference_images = [url for url in reference_images if url in valid_urls]
    if len(updated_reference_images) != len(reference_images):
        await state.update_data(reference_images=updated_reference_images)
        return_chat_id = data.get("saved_ref_return_chat_id")
        return_message_id = data.get("saved_ref_return_message_id")
        if return_chat_id and return_message_id:
            try:
                await _update_reference_upload_message(callback.bot, return_chat_id, return_message_id, state)
            except Exception:
                logger.exception("Failed to refresh upload screen after deleting saved ref")

    try:
        await callback.message.delete()
    except Exception:
        pass

    if not saved_refs_after:
        await callback.answer("Реф удалён")
        await callback.message.answer("Сохранённых рефов больше нет.")
        return

    next_index = min(current_index, len(saved_refs_after) - 1)
    await _send_saved_reference_preview(callback.message, state, refs=saved_refs_after, index=next_index)
    await callback.answer("Реф удалён")


@router.callback_query(F.data == "ref_reload_new")
async def handle_ref_reload_new(callback: types.CallbackQuery, state: FSMContext):
    """Перезагружает референсы (очищает и начинает заново) для нового UX"""
    data = await state.get_data()
    generation_type = data.get("generation_type")

    # Очищаем референсы
    await state.update_data(reference_images=[])

    # Определяем preset_id для клавиатуры
    preset_id = "new" if generation_type != "video" else "video_new"
    current_service = data.get("img_service", "banana_pro")
    max_refs = _get_max_image_references(current_service)

    await callback.message.edit_text(
        (
            f"📎 <b>Перезагрузка референсов</b>\n"
            f"Загружено: <code>0/{max_refs}</code>\n"
            f"Отправьте новые фотографии для загрузки референсов:"
        ),
        reply_markup=get_reference_images_upload_keyboard(0, max_refs, preset_id),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.uploading_reference_images)


@router.callback_query(F.data == "image_change_model")
async def handle_image_change_model(callback: types.CallbackQuery, state: FSMContext):
    """Возвращает пользователя к шагу выбора модели."""
    await state.update_data(img_flow_step="select_model")
    await _show_image_model_selection_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "video_change_model")
async def handle_video_change_model(callback: types.CallbackQuery, state: FSMContext):
    """Возвращает пользователя к шагу выбора модели видео."""
    await state.update_data(video_flow_step="select_model")
    await _show_video_model_selection_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "video_change_media")
async def handle_video_change_media(callback: types.CallbackQuery, state: FSMContext):
    """Возвращает пользователя к шагу выбора типа и медиа."""
    await state.update_data(video_flow_step="media")
    await _show_video_media_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "video_media_skip")
async def handle_video_media_skip(callback: types.CallbackQuery, state: FSMContext):
    """Пропускает медиашаг, если он опционален."""
    data = await state.get_data()
    current_v_type = data.get("v_type", "text")
    current_model = data.get("v_model", "v3_std")
    if current_v_type == "avatar":
        await callback.answer("Для Avatar нужны и фото, и аудио", show_alert=True)
        return
    if current_v_type == "character":
        await callback.answer("Для Character нужно изображение", show_alert=True)
        return
    if current_v_type == "imgtxt" and current_model != "gemini_omni_video":
        await callback.answer(
            "Для режима Фото + Текст сначала загрузите стартовое фото", show_alert=True
        )
        return
    if current_v_type == "video":
        await state.update_data(v_reference_videos=[])
    await state.update_data(video_flow_step="configure")
    await _show_video_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "video_media_continue")
async def handle_video_media_continue(callback: types.CallbackQuery, state: FSMContext):
    """Переходит к шагу настроек после выбора типа и загрузки медиа."""
    data = await state.get_data()
    current_v_type = data.get("v_type", "text")
    current_model = data.get("v_model", "v3_std")
    if current_v_type == "avatar":
        if not data.get("v_image_url"):
            await callback.answer("Сначала загрузите фото аватара", show_alert=True)
            return
        if not data.get("avatar_audio_url"):
            await callback.answer("Сначала загрузите аудио", show_alert=True)
            return
        await state.update_data(video_flow_step="configure")
        await _show_video_creation_screen(callback, state)
        await callback.answer()
        return
    if current_v_type == "character" and not data.get("v_image_url"):
        await callback.answer("Сначала загрузите изображение персонажа", show_alert=True)
        return
    if (
        current_v_type == "imgtxt"
        and not data.get("v_image_url")
        and current_model != "gemini_omni_video"
    ):
        await callback.answer("Сначала загрузите стартовое фото", show_alert=True)
        return
    await state.update_data(video_flow_step="configure")
    await _show_video_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "avatar_upload_image")
async def handle_avatar_upload_image(
    callback: types.CallbackQuery, state: FSMContext
):
    """Переводит Avatar flow в режим ожидания фото."""
    await state.update_data(video_flow_step="media", v_type="avatar")
    await state.set_state(GenerationStates.waiting_for_video_prompt)
    await callback.answer("Отправьте фото аватара")


@router.callback_query(F.data == "avatar_upload_audio")
async def handle_avatar_upload_audio(
    callback: types.CallbackQuery, state: FSMContext
):
    """Переводит Avatar flow в режим ожидания аудио."""
    await state.update_data(video_flow_step="media", v_type="avatar")
    await state.set_state(GenerationStates.waiting_for_video_prompt)
    await callback.answer("Отправьте аудиофайл или голосовое")


@router.callback_query(F.data == "ref_confirm_new")
async def handle_ref_confirm_new(callback: types.CallbackQuery, state: FSMContext):
    """Подтверждает референсы для нового UX - переходит к выбору модели/формата"""
    data = await state.get_data()
    current_refs = data.get("reference_images", [])

    if not current_refs:
        await callback.answer("Нет загруженных изображений", show_alert=True)
        return

    await _show_image_creation_screen(callback, state)
    await callback.answer()


# Обработчики для меню создания видео
@router.callback_query(F.data == "v_type_text")
async def handle_v_type_text(callback: types.CallbackQuery, state: FSMContext):
    """Выбор типа генерации: текст"""
    data = await state.get_data()
    current_model = data.get("v_model", "v26_pro")

    if current_model in _GROK_VIDEO_MODELS:
        await state.update_data(v_type="imgtxt")
        await _show_video_media_screen(callback, state)
        await callback.answer("Grok Imagine работает через стартовое фото")
        return

    updates = {"v_type": "text"}
    if current_model.startswith("veo3"):
        updates["veo_generation_type"] = "TEXT_2_VIDEO"
    await state.update_data(**updates)
    await _show_video_media_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "v_type_imgtxt")
async def handle_v_type_imgtxt(callback: types.CallbackQuery, state: FSMContext):
    """Выбор типа генерации: фото+текст."""
    data = await state.get_data()
    current_model = data.get("v_model", "v26_pro")

    updates = {"v_type": "imgtxt"}
    if current_model.startswith("veo3"):
        updates["veo_generation_type"] = "FIRST_AND_LAST_FRAMES_2_VIDEO"
    await state.update_data(**updates)
    await _show_video_media_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_video_prompt)


@router.callback_query(F.data == "v_type_video")
async def handle_v_type_video(callback: types.CallbackQuery, state: FSMContext):
    """Выбор типа генерации: видео+текст."""
    data = await state.get_data()
    current_model = data.get("v_model")
    if current_model in _GROK_VIDEO_MODELS:
        await state.update_data(v_type="imgtxt")
        await _show_video_media_screen(callback, state)
        await callback.answer("Grok Imagine принимает фото, а не видео-референс")
        return
    selected_model = choose_video_reference_model(current_model)
    updates = {"v_type": "video", "v_duration": 5, "v_model": selected_model}
    await state.update_data(**updates)
    await _show_video_media_screen(callback, state)
    if selected_model != current_model:
        await callback.answer("Для видео-референсов выбрана Seedance 2.0")
    else:
        await callback.answer("Загрузите видео-референсы")


@router.callback_query(F.data == "vid_ref_continue_new")
async def handle_vid_ref_continue_new(callback: types.CallbackQuery, state: FSMContext):
    """Продолжает после загрузки видео референсов"""
    await state.update_data(video_flow_step="configure")
    await _show_video_creation_screen(callback.message, state)
    await callback.answer()


@router.callback_query(F.data.startswith("v_model_"))
async def handle_v_model(callback: types.CallbackQuery, state: FSMContext):
    """Generic handler for all video model selections"""
    model = callback.data.replace("v_model_", "")
    await _apply_video_model_selection(callback, state, model)


@router.callback_query(
    F.data.in_({"omni_mode_video", "omni_mode_audio", "omni_mode_character"})
)
async def handle_gemini_omni_mode(callback: types.CallbackQuery, state: FSMContext):
    """Select a concrete Gemini Omni capability from the unified menu."""
    mode_to_model = {
        "omni_mode_video": "gemini_omni_video",
        "omni_mode_audio": "gemini_omni_audio",
        "omni_mode_character": "gemini_omni_character",
    }
    await state.update_data(video_flow_step="select_model")
    await _apply_video_model_selection(callback, state, mode_to_model[callback.data])


@router.callback_query(F.data.startswith("video_model_"))
async def handle_video_model_legacy(callback: types.CallbackQuery, state: FSMContext):
    """Legacy handler for get_video_models_inline_keyboard callbacks"""
    model = callback.data.replace("video_model_", "")
    await _apply_video_model_selection(callback, state, model)


@router.callback_query(F.data.startswith("video_gen_model_"))
async def handle_video_generation_model_legacy(
    callback: types.CallbackQuery, state: FSMContext
):
    """Legacy handler for get_video_generation_model_keyboard callbacks"""
    model = callback.data.replace("video_gen_model_", "")
    await _apply_video_model_selection(callback, state, model)


@router.callback_query(F.data.startswith("opt_v_model_"))
async def handle_video_options_model_legacy(
    callback: types.CallbackQuery, state: FSMContext
):
    """Legacy handler for opt_v_model_* callbacks"""
    model = callback.data.replace("opt_v_model_", "")
    await _apply_video_model_selection(callback, state, model)


@router.callback_query(F.data.startswith("grok_mode_"))
async def handle_grok_mode(callback: types.CallbackQuery, state: FSMContext):
    """Handler for Grok Imagine mode selection (normal/fun/spicy)"""
    mode = callback.data.replace("grok_mode_", "")
    await state.update_data(grok_mode=mode)
    await _show_video_creation_screen(callback, state)
    await callback.answer(f"Режим Grok: {mode.title()}")


@router.callback_query(F.data.startswith("grok_resolution_"))
async def handle_grok_resolution(callback: types.CallbackQuery, state: FSMContext):
    """Set Grok Imagine Video 1.5 resolution."""
    resolution = callback.data.replace("grok_resolution_", "")
    if resolution not in {"480p", "720p"}:
        await callback.answer()
        return
    await state.update_data(grok_resolution=resolution)
    await _show_video_creation_screen(callback, state)
    await callback.answer(f"Качество Grok: {resolution}")


async def _apply_video_model_selection(
    callback: types.CallbackQuery, state: FSMContext, model: str
):
    """Apply video model selection across all keyboard variants."""
    data = await state.get_data()
    if model == "gemini_omni":
        await state.update_data(
            v_model="gemini_omni",
            v_type="text",
            video_flow_step="omni_menu",
            reference_images=[],
            v_reference_videos=[],
        )
        await _show_gemini_omni_mode_screen(callback, state)
        await callback.answer()
        return

    current_v_type = data.get("v_type", "text")
    current_duration = data.get("v_duration", 5)
    current_ratio = data.get("v_ratio", "16:9")

    if model == "grok_imagine":
        current_v_type = "imgtxt"
        current_duration = (
            current_duration if current_duration in {6, 10, 20, 30} else 6
        )
        current_ratio = (
            current_ratio if current_ratio in _GROK_LEGACY_VIDEO_RATIOS else "16:9"
        )
        await state.update_data(
            grok_mode="normal",
            v_reference_videos=[],
        )
    elif model == "grok_imagine_v15":
        current_v_type = "imgtxt"
        current_duration = (
            current_duration if 1 <= int(current_duration) <= 15 else 8
        )
        current_ratio = current_ratio if current_ratio in _GROK_V15_VIDEO_RATIOS else "auto"
        await state.update_data(
            grok_resolution=data.get("grok_resolution", "480p"),
            reference_images=[],
            v_reference_videos=[],
        )
    elif model == "v26_pro":
        await state.update_data(
            kling_negative_prompt=data.get("kling_negative_prompt", ""),
            kling_cfg_scale=float(data.get("kling_cfg_scale", 0.5)),
            reference_images=[],
            v_reference_videos=[],
        )
    elif model in {"avatar_std", "avatar_pro"}:
        await state.update_data(
            reference_images=[],
            v_reference_videos=[],
            v_image_url=None,
            avatar_audio_url=None,
        )
    elif model.startswith("veo3"):
        await state.update_data(
            veo_generation_type=(
                "TEXT_2_VIDEO"
                if current_v_type == "text"
                else "FIRST_AND_LAST_FRAMES_2_VIDEO"
            ),
            veo_translation=data.get("veo_translation", True),
            veo_resolution=data.get("veo_resolution", "720p"),
        )
    elif model == "gemini_omni_video":
        await state.update_data(
            omni_resolution=data.get("omni_resolution", "720p"),
            omni_seed=data.get("omni_seed"),
            omni_audio_ids=data.get("omni_audio_ids", []),
            omni_character_ids=data.get("omni_character_ids", []),
        )
    elif model == "gemini_omni_audio":
        await state.update_data(
            reference_images=[],
            v_reference_videos=[],
            v_image_url=None,
            omni_base_voice=data.get("omni_base_voice", "achernar"),
            omni_voice_name=data.get("omni_voice_name", ""),
            omni_voice_description=data.get("omni_voice_description", ""),
            omni_example_dialogue=data.get("omni_example_dialogue", ""),
        )
    elif model == "gemini_omni_character":
        await state.update_data(
            reference_images=[],
            v_reference_videos=[],
            v_image_url=data.get("v_image_url"),
            omni_character_name=data.get("omni_character_name", ""),
            omni_character_audio_ids=data.get("omni_character_audio_ids", []),
        )

    # WanX LoRA is text-to-video only, so we force the UI into text mode
    # to expose aspect ratio and duration controls immediately.
    if model.startswith("wanx"):
        current_v_type = "text"
    if model == "glow":
        current_v_type = "video"
    if model in {"avatar_std", "avatar_pro"}:
        current_v_type = "avatar"
    if model == "gemini_omni_audio":
        current_v_type = "audio"
    if model == "gemini_omni_character":
        current_v_type = "character"
    if current_v_type == "video" and not video_model_supports_reference_videos(model):
        current_v_type = "text"
    if model == "v26_pro" and current_v_type == "video":
        current_v_type = "text"
    if model.startswith("veo3") and current_v_type == "video":
        current_v_type = "text"
    if model in _GROK_VIDEO_MODELS:
        current_v_type = "imgtxt"

    updates = {
        "v_model": model,
        "v_type": current_v_type,
        "v_ratio": current_ratio,
        "v_duration": current_duration,
    }
    if data.get("video_flow_step") == "select_model":
        updates["video_flow_step"] = "media"
    await state.update_data(**updates)
    await _normalize_veo_state(state)
    await _normalize_video_duration_state(state)
    if model.startswith("wanx"):
        await state.update_data(
            wanx_lora_settings=[{"lora_type": "nsfw-general", "lora_strength": 1.0}]
        )

    if data.get("video_flow_step") == "select_model":
        await _show_video_media_screen(callback, state)
    elif model.startswith("wanx"):
        await callback.message.edit_text(
            "🎬 <b>WanX LoRA</b>"
            "Выберите формат и длительность для генерации:\n"
            "• 📐 Доступные aspect ratio\n"
            "• ⏱ Доступное время"
            "После выбора параметров введите промпт.",
            reply_markup=get_create_video_keyboard(
                current_v_type=current_v_type,
                current_model=model,
                current_duration=current_duration,
                current_ratio=current_ratio,
            ),
            parse_mode="HTML",
        )
    else:
        await _show_video_creation_screen(callback, state)
    await callback.answer()
    current_data = await state.get_data()
    if current_data.get("video_flow_step") == "media":
        current_type = current_data.get("v_type", "text")
        if current_type in {"imgtxt", "avatar"}:
            await state.set_state(GenerationStates.waiting_for_video_prompt)
        elif current_type == "text":
            await state.set_state(GenerationStates.waiting_for_video_prompt)
        elif current_type == "video":
            await state.set_state(GenerationStates.uploading_reference_videos)
        else:
            await state.set_state(GenerationStates.waiting_for_video_prompt)
    else:
        await state.set_state(GenerationStates.waiting_for_video_prompt)


# Обработчики формата видео
@router.callback_query(F.data == "ratio_1_1")
async def handle_video_ratio_1_1(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата 1:1"""
    data = await state.get_data()
    current_v_type = data.get("v_type", "text")
    current_model = data.get("v_model", "v26_pro")
    current_duration = data.get("v_duration", 5)

    await state.update_data(v_ratio="1:1")

    await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_video_prompt)


@router.callback_query(F.data == "ratio_16_9")
async def handle_video_ratio_16_9(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата 16:9"""
    data = await state.get_data()
    current_v_type = data.get("v_type", "text")
    current_model = data.get("v_model", "v26_pro")
    current_duration = data.get("v_duration", 5)

    await state.update_data(v_ratio="16:9")

    await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_video_prompt)


@router.callback_query(F.data == "ratio_9_16")
async def handle_video_ratio_9_16(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата 9:16"""
    data = await state.get_data()
    current_v_type = data.get("v_type", "text")
    current_model = data.get("v_model", "v26_pro")
    current_duration = data.get("v_duration", 5)

    await state.update_data(v_ratio="9:16")

    await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_video_prompt)


@router.callback_query(F.data == "ratio_4_3")
async def handle_video_ratio_4_3(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата 4:3"""
    data = await state.get_data()
    current_v_type = data.get("v_type", "text")
    current_model = data.get("v_model", "v26_pro")
    current_duration = data.get("v_duration", 5)

    await state.update_data(v_ratio="4:3")

    await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_video_prompt)


@router.callback_query(F.data == "ratio_3_4")
async def handle_video_ratio_3_4(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата 3:4"""
    await state.update_data(v_ratio="3:4")
    await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_video_prompt)


@router.callback_query(F.data == "ratio_3_2")
async def handle_video_ratio_3_2(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата 3:2"""
    data = await state.get_data()
    current_v_type = data.get("v_type", "text")
    current_model = data.get("v_model", "v26_pro")
    current_duration = data.get("v_duration", 5)

    await state.update_data(v_ratio="3:2")

    await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_video_prompt)


@router.callback_query(F.data == "ratio_2_3")
async def handle_video_ratio_2_3(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата 2:3"""
    await state.update_data(v_ratio="2:3")
    await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_video_prompt)


@router.callback_query(F.data.in_({"ratio_Auto", "ratio_auto"}))
async def handle_video_ratio_auto(callback: types.CallbackQuery, state: FSMContext):
    """Выбор автоматического формата для моделей, где он поддерживается."""
    ratio = "Auto" if callback.data == "ratio_Auto" else "auto"
    await state.update_data(v_ratio=ratio)
    await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_video_prompt)


# Обработчик длительности видео
@router.callback_query(F.data.startswith("video_dur_"))
async def handle_video_duration(callback: types.CallbackQuery, state: FSMContext):
    """Выбор длительности видео для всех моделей."""
    try:
        duration = int(callback.data.replace("video_dur_", ""))
    except ValueError:
        await callback.answer()
        return

    if duration < 1 or duration > 30:
        await callback.answer()
        return

    data = await state.get_data()
    current_model = data.get("v_model", "v3_std")
    if duration not in _get_supported_video_durations(current_model):
        await callback.answer("Эта длительность недоступна для выбранной модели")
        return

    await state.update_data(v_duration=duration)
    await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_video_prompt)


# =============================================================================
# НОВЫЙ UX: МЕНЮ СОЗДАНИЯ ФОТО (get_create_image_keyboard)
# =============================================================================


@router.callback_query(F.data == "model_flux_pro")
async def handle_model_flux_pro(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели GPT Image 2."""
    await state.update_data(
        img_service="flux_pro",
        img_ratio="auto",
        img_nsfw_checker=False,
        reference_images=[],
    )
    data = await state.get_data()
    if data.get("img_flow_step") == "select_model":
        await state.update_data(img_flow_step="upload_refs")
        await _show_image_references_screen(callback, state)
    else:
        await _show_image_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "model_nanobanana")
async def handle_model_nanobanana(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели Nano Banana"""
    await state.update_data(img_service="nanobanana")
    await _show_image_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "model_banana_pro")
async def handle_model_banana_pro(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели Banana Pro"""
    await state.update_data(img_service="banana_pro")
    data = await state.get_data()
    if data.get("img_flow_step") == "select_model":
        await state.update_data(img_flow_step="upload_refs")
        await _show_image_references_screen(callback, state)
    else:
        await _show_image_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "model_banana_2")
async def handle_model_banana_2(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели Banana 2."""
    await state.update_data(img_service="banana_2")
    data = await state.get_data()
    if data.get("img_flow_step") == "select_model":
        await state.update_data(img_flow_step="upload_refs")
        await _show_image_references_screen(callback, state)
    else:
        await _show_image_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "model_nano_banana_2_lite")
async def handle_model_nano_banana_2_lite(
    callback: types.CallbackQuery, state: FSMContext
):
    """Выбор модели Nano Banana 2 Lite."""
    await state.update_data(
        img_service="nano-banana-2-lite",
        img_ratio="auto",
        img_quality="2K",
    )
    data = await state.get_data()
    if data.get("img_flow_step") == "select_model":
        await state.update_data(img_flow_step="upload_refs")
        await _show_image_references_screen(callback, state)
    else:
        await _show_image_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "model_seedream_edit")
async def handle_model_seedream_edit(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели Seedream 4.5"""
    await state.update_data(
        img_service="seedream_edit",
        img_ratio="1:1",
        img_quality="basic",
        img_nsfw_checker=False,
    )
    data = await state.get_data()
    if data.get("img_flow_step") == "select_model":
        await state.update_data(img_flow_step="upload_refs")
        await _show_image_references_screen(callback, state)
    else:
        await _show_image_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "model_seedream_5_pro")
async def handle_model_seedream_5_pro(
    callback: types.CallbackQuery, state: FSMContext
):
    """Выбор модели Seedream 5 Pro."""
    await state.update_data(
        img_service="seedream_5_pro",
        img_ratio="1:1",
        img_quality="basic",
        img_nsfw_checker=False,
    )
    data = await state.get_data()
    if data.get("img_flow_step") == "select_model":
        await state.update_data(img_flow_step="upload_refs")
        await _show_image_references_screen(callback, state)
    else:
        await _show_image_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "model_grok_i2i")
async def handle_model_grok_i2i(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели Grok Imagine i2i (фото + текст)"""
    data = await state.get_data()
    nsfw_enabled = data.get("nsfw_enabled", False)

    await state.update_data(img_service="grok_imagine_i2i", nsfw_enabled=nsfw_enabled)
    data = await state.get_data()
    if data.get("img_flow_step") == "select_model":
        await state.update_data(img_flow_step="upload_refs")
        await _show_image_references_screen(callback, state)
    else:
        await _show_image_creation_screen(callback, state)
    await callback.answer()


# Обработчики формата изображения
@router.callback_query(F.data == "img_ratio_auto")
async def handle_img_ratio_auto(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата изображения auto."""
    await state.update_data(img_ratio="auto")
    await _show_image_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "img_ratio_1_1")
async def handle_img_ratio_1_1(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата изображения 1:1"""
    await state.update_data(img_ratio="1:1")
    await _show_image_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "img_ratio_16_9")
async def handle_img_ratio_16_9(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата изображения 16:9"""
    await state.update_data(img_ratio="16:9")
    await _show_image_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "img_ratio_9_16")
async def handle_img_ratio_9_16(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата изображения 9:16"""
    await state.update_data(img_ratio="9:16")
    await _show_image_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "img_ratio_4_3")
async def handle_img_ratio_4_3(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата изображения 4:3"""
    await state.update_data(img_ratio="4:3")
    await _show_image_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "img_ratio_4_5")
async def handle_img_ratio_4_5(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата изображения 4:5"""
    await state.update_data(img_ratio="4:5")
    await _show_image_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "img_ratio_5_4")
async def handle_img_ratio_5_4(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата изображения 5:4"""
    await state.update_data(img_ratio="5:4")
    await _show_image_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "img_ratio_3_2")
async def handle_img_ratio_3_2(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата изображения 3:2"""
    await state.update_data(img_ratio="3:2")
    await _show_image_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "img_ratio_2_3")
async def handle_img_ratio_2_3(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата изображения 2:3"""
    await state.update_data(img_ratio="2:3")
    await _show_image_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "img_ratio_3_4")
async def handle_img_ratio_3_4(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата изображения 3:4"""
    await state.update_data(img_ratio="3:4")
    await _show_image_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "img_ratio_21_9")
async def handle_img_ratio_21_9(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата изображения 21:9"""
    await state.update_data(img_ratio="21:9")
    await _show_image_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data.startswith("img_count_"))
async def handle_img_count(callback: types.CallbackQuery, state: FSMContext):
    """Выбор количества изображений для пакетной генерации."""
    try:
        img_count = int(callback.data.replace("img_count_", ""))
    except ValueError:
        await callback.answer()
        return

    if img_count not in {1, 2, 4, 6}:
        await callback.answer()
        return

    await state.update_data(img_count=img_count)
    await _show_image_creation_screen(callback, state)
    await callback.answer(f"Количество: {img_count}")


@router.callback_query(F.data == "img_quality_basic")
async def handle_img_quality_basic(callback: types.CallbackQuery, state: FSMContext):
    """Seedream quality: basic."""
    await state.update_data(img_quality="basic")
    await _show_image_creation_screen(callback, state)
    await callback.answer("Quality: basic")


@router.callback_query(F.data == "img_quality_high")
async def handle_img_quality_high(callback: types.CallbackQuery, state: FSMContext):
    """Seedream quality: high."""
    await state.update_data(img_quality="high")
    await _show_image_creation_screen(callback, state)
    await callback.answer("Quality: high")


# =============================================================================
# СЛУЖЕБНЫЕ ФУНКЦИИ ДЛЯ РАБОТЫ С ФАЙЛАМИ
# =============================================================================


def save_uploaded_file(file_bytes: bytes, file_ext: str = "png") -> Optional[str]:
    """
    Сохраняет загруженный файл в папку static/uploads и возвращает публичный URL.
    """
    try:
        if not isinstance(file_bytes, (bytes, bytearray)):
            logger.error(
                "save_uploaded_file expected bytes, got %s",
                type(file_bytes).__name__,
            )
            return None

        # Создаём поддиректорию по дате
        date_str = datetime.now().strftime("%Y%m%d")
        upload_dir = os.path.join("static", "uploads", date_str)
        os.makedirs(upload_dir, exist_ok=True)

        # Генерируем уникальное имя файла
        file_id = str(uuid.uuid4())[:8]
        filename = f"{file_id}.{file_ext}"
        filepath = os.path.join(upload_dir, filename)

        # Сохраняем файл
        with open(filepath, "wb") as f:
            f.write(bytes(file_bytes))

        # Формируем публичный URL
        # nginx настроен на /uploads/ -> static/uploads/
        base_url = config.static_base_url
        public_url = f"{base_url}/uploads/{date_str}/{filename}"

        logger.info(f"Saved uploaded file: {public_url}")
        return public_url

    except Exception as e:
        logger.exception(f"Error saving uploaded file: {e}")
        return None


async def _send_original_document(
    send_callable,
    result: bytes,
    saved_url: Optional[str],
    filename: str = "original.png",
):
    """Helper to send original document with fallbacks and logging.

    send_callable: coroutine function like message.answer_document
    """
    try:
        logger.info("Sending original document via BufferedInputFile")
        doc = types.BufferedInputFile(result, filename=filename)
        await send_callable(
            document=doc, caption="📥 Исходный файл (оригинал)", parse_mode="HTML"
        )
        logger.info("Original document sent (BufferedInputFile)")
        return
    except Exception:
        logger.exception(
            "Failed to send original document via BufferedInputFile, trying fallback"
        )

    try:
        if saved_url:
            logger.info("Sending original document via saved URL")
            await send_callable(
                document=saved_url,
                caption="📥 Исходный файл (оригинал)",
                parse_mode="HTML",
            )
            logger.info("Original document sent via URL")
            return

        bio = io.BytesIO(result)
        bio.name = filename
        bio.seek(0)
        logger.info("Sending original document via BytesIO fallback")
        await send_callable(
            document=bio, caption="📥 Исходный файл (оригинал)", parse_mode="HTML"
        )
        logger.info("Original document sent via BytesIO")
    except Exception:
        logger.exception("Fallback to send original document failed")


async def _send_download_link(send_callable, saved_url: str):
    """Send a small message with an inline URL button to download the original file."""
    try:
        kb = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [types.InlineKeyboardButton(text="📥 Скачать оригинал", url=saved_url)]
            ]
        )
        await send_callable(
            f"📥 <b>Исходник</b> — можно скачать по ссылке:",
            reply_markup=kb,
            parse_mode="HTML",
        )
        logger.info("Sent download link to user")
    except Exception:
        logger.exception("Failed to send download link")


# =============================================================================
# ОСНОВНЫЕ ОБРАБОТЧИКИ БЕЗ ПРЕСЕТОВ
# =============================================================================


@router.callback_query(F.data == "generate_image")
async def start_image_generation(callback: types.CallbackQuery, state: FSMContext):
    """Начинает генерацию изображения - Шаг 1: загрузка референсов"""
    user_credits = await get_user_credits(callback.from_user.id)
    settings = await get_user_settings(callback.from_user.id)
    image_service = settings.get("image_service", "nanobanana")

    # Инициализируем опции
    await state.set_state(GenerationStates.waiting_for_image)
    await state.update_data(
        generation_type="image",
        image_service=image_service,
        reference_images=[],
        generation_options={
            "model": image_service,
            "aspect_ratio": "1:1",
            "quality": "pro",
        },
    )

    # Названия и стоимость в зависимости от сервиса
    if image_service == "novita" or image_service == "flux_pro":
        model_name = "✨ FLUX.2 Pro"
        model_cost = str(preset_manager.get_generation_cost("z_image_turbo"))
    elif image_service == "seedream":
        model_name = "🎨 Seedream"
        model_cost = str(preset_manager.get_generation_cost("seedream"))
    elif image_service == "z_image_turbo":
        model_name = "🚀 Z-Image Turbo LoRA"
        model_cost = str(preset_manager.get_generation_cost("z_image_turbo"))
    else:  # banana_2 / fallback banana family
        model_name = "🍌 Nano Banana 2"
        model_cost = str(preset_manager.get_generation_cost("banana_2"))

    # Шаг 1: Загрузка референсов
    await callback.message.edit_text(
        f"🖼 <b>Генерация фото</b>"
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов\n"
        f"🤖 Модель: {model_name} ({model_cost}🍌)"
        f"<b>Шаг 1: Референсы (опционально)</b>"
        f"Загрузите изображения для:\n"
        f"• Точного сходства с объектом\n"
        f"• Сохранения стиля\n"
        f"• Персонажей (до 4 фото)"
        f"После загрузки нажмите ▶️ Продолжить\n"
        f"Или ⏭ Пропустить, если референсы не нужны",
        reply_markup=get_reference_images_upload_keyboard(0, _get_max_image_references("banana_pro"), "generate_image"),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "edit_image")
async def start_image_editing(callback: types.CallbackQuery, state: FSMContext):
    """Начинает редактирование изображения с возможностью сохранения лиц через референсы"""
    await state.set_state(GenerationStates.waiting_for_image)

    user_credits = await get_user_credits(callback.from_user.id)

    # Сохраняем модель и тип генерации в state + инициализируем референсы
    await state.update_data(
        generation_type="image_edit",
        preferred_model="pro",  # Для редактирования используем Pro для лучшего качества
        reference_images=[],  # Для сохранения лиц
    )

    # Получаем стоимость редактирования через preset_manager
    edit_cost = preset_manager.get_generation_cost("gemini-3-pro-image-preview")

    await callback.message.edit_text(
        f"✏️ <b>Редактирование фото</b>"
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов\n"
        f"🤖 Модель: 💎 Banano Pro ({edit_cost}🍌, 4K, сохранение лиц)"
        f"<b>Как редактировать:</b>\n"
        f"1. Загрузите <b>главное фото</b> для редактирования\n"
        f"2. Добавьте до <b>4 фото лица</b> для сохранения (опционально)\n"
        f"3. Опишите что изменить"
        f"<i>💡 Для сохранения лица: загрузите сначала главное фото,\n"
        f"потом фото лица для сохранения, затем введите промпт</i>",
        reply_markup=get_back_keyboard("back_main"),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "generate_video")
async def start_video_generation(callback: types.CallbackQuery, state: FSMContext):
    """Начинает генерацию видео без пресета - сразу запрашивает промпт"""
    await state.set_state(GenerationStates.waiting_for_video_prompt)
    await state.update_data(generation_type="video", video_flow_step="configure")

    user_credits = await get_user_credits(callback.from_user.id)
    settings = await get_user_settings(callback.from_user.id)
    video_model = settings["preferred_video_model"]

    # Map model codes to names
    model_names = {
        "v3_std": "Kling 3 Std",
        "v3_pro": "Kling 3 Pro",
        "v3_omni_std": "Kling 3 Std",
        "v3_omni_pro": "Kling 3 Pro",
    }
    # Используем preset_manager для получения стоимости
    model_cost = str(preset_manager.get_video_cost(video_model, 5))
    model_name = model_names.get(video_model, video_model)

    # Простые опции видео
    video_options = {
        "duration": 5,
        "aspect_ratio": "16:9",
        "quality": "std",
        "generate_audio": True,
    }
    await state.update_data(video_options=video_options)

    await callback.message.edit_text(
        f"🎬 <b>Генерация видео</b>"
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов\n"
        f"🤖 Модель: {model_name} ({model_cost}🍌)"
        f"<b>Опции видео:</b>\n"
        f"   ⏱ Длительность: <code>{video_options.get('duration', 5)} сек</code>\n"
        f"   📐 Формат: <code>{video_options.get('aspect_ratio', '16:9')}</code>\n"
        f"   🔊 Со звуком: <code>{'Да' if video_options.get('generate_audio') else 'Нет'}</code>"
        f"Опишите видео, которое хотите создать:\n"
        f"• Что происходит в сцене\n"
        f"• Движение камеры\n"
        f"• Стиль и атмосфера"
        f"<i>Чем подробнее описание — тем лучше результат!</i>",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="⚙️ Изменить опции", callback_data="video_options_change"
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="🔙 Назад", callback_data="back_main"
                    )
                ],
            ]
        ),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "video_options_change")
async def handle_video_options_change(callback: types.CallbackQuery, state: FSMContext):
    """Показывает клавиатуру опций видео (длительность, формат, звук)"""
    data = await state.get_data()
    video_options = data.get(
        "video_options",
        {
            "duration": 5,
            "aspect_ratio": "16:9",
            "quality": "std",
            "generate_audio": True,
        },
    )

    user_prompt = data.get("user_prompt", "")

    # Если промпт ещё не введён, показываем дефолтный текст
    prompt_text = user_prompt if user_prompt else "<i>Опишите видео ниже</i>"

    await callback.message.edit_text(
        f"🎬 <b>Настройка видео</b>"
        f"Промпт: <code>{prompt_text[:100]}{'...' if len(prompt_text) > 100 else ''}</code>"
        f"Выберите параметры и нажмите ▶️ Запустить:"
        f"<i>⏱ Длительность: {video_options.get('duration', 5)} сек\n"
        f"📐 Формат: {video_options.get('aspect_ratio', '16:9')}\n"
        f"🔊 Звук: {'Да' if video_options.get('generate_audio') else 'Нет'}</i>",
        reply_markup=get_video_options_no_preset_keyboard(
            video_options.get("duration", 5),
            video_options.get("aspect_ratio", "16:9"),
            video_options.get("generate_audio", True),
        ),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_video_prompt)


@router.callback_query(F.data == "edit_video")
async def start_video_editing(callback: types.CallbackQuery, state: FSMContext):
    """Начинает редактирование видео - предлагает выбрать тип входных данных"""
    await state.clear()

    user_credits = await get_user_credits(callback.from_user.id)
    settings = await get_user_settings(callback.from_user.id)
    video_model = settings["preferred_i2v_model"]

    # Map model codes to names
    model_names = {
        "v3_std": "Kling 3 Std",
        "v3_pro": "Kling 3 Pro",
        "v3_omni_std": "Kling 3 Std",
        "v3_omni_pro": "Kling 3 Pro",
    }
    # Используем preset_manager для получения стоимости
    model_cost = str(preset_manager.get_video_cost(video_model, 5))
    model_name = model_names.get(video_model, video_model)

    # Инициализируем опции для видео-эффектов
    video_edit_options = {
        "quality": "std",  # std или pro
        "duration": 5,
        "aspect_ratio": "16:9",
    }
    await state.update_data(video_edit_options=video_edit_options)

    from bot.keyboards import get_video_edit_input_type_keyboard

    await callback.message.edit_text(
        f"✂️ <b>Видео-эффекты</b>"
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов\n"
        f"🤖 Модель: {model_name} ({model_cost}🍌)"
        f"<b>Преобразование видео</b>\n"
        f"Выберите, что хотите загрузить:"
        f"🎬 <b>Видео</b> - преобразование видео\n"
        f"🖼 <b>Фото</b> - создание видео из изображения"
        f"<i>Загрузите медиафайл и опишите эффект</i>",
        reply_markup=get_video_edit_input_type_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "image_to_video")
async def start_image_to_video(callback: types.CallbackQuery, state: FSMContext):
    """Начинает генерацию видео из фото - запрашивает фото"""
    await state.set_state(GenerationStates.waiting_for_image)
    await state.update_data(generation_type="image_to_video")

    user_credits = await get_user_credits(callback.from_user.id)
    settings = await get_user_settings(callback.from_user.id)
    video_model = settings["preferred_i2v_model"]

    # Map model codes to names
    model_names = {
        "v3_std": "Kling 3 Std",
        "v3_pro": "Kling 3 Pro",
        "v3_omni_std": "Kling 3 Std",
        "v3_omni_pro": "Kling 3 Pro",
    }
    # Используем preset_manager для получения стоимости
    model_cost = str(preset_manager.get_video_cost(video_model, 5))
    model_name = model_names.get(video_model, video_model)

    # Простые опции видео
    video_options = {
        "duration": 5,
        "aspect_ratio": "16:9",
        "quality": "std",
        "generate_audio": True,
    }
    await state.update_data(video_options=video_options)

    await callback.message.edit_text(
        f"🖼 <b>Фото в видео</b>"
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов\n"
        f"🤖 Модель: {model_name} ({model_cost}🍌)"
        f"<b>Image to Video</b>\n"
        f"Загрузите изображение,\n"
        f"которое хотите превратить в видео.\n"
        f"После загрузки опишите движение."
        f"<i>Например: птица летит в небе, волны накатывают на берег</i>",
        reply_markup=get_back_keyboard("back_main"),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


# =============================================================================
# ОБРАБОТЧИКИ ОПЦИЙ ВИДЕО-ЭФФЕКТОВ
# =============================================================================


@router.callback_query(F.data.startswith("video_edit_input_"))
async def handle_video_edit_input_type(
    callback: types.CallbackQuery, state: FSMContext
):
    """Выбор типа входного медиа для видео-эффектов: видео или изображение"""
    choice = callback.data.replace("video_edit_input_", "")

    if choice == "video":
        await state.set_state(GenerationStates.waiting_for_video)
        await state.update_data(
            generation_type="video_edit",
            video_edit_input_type="video",
            has_video=False,
            has_image=False,
        )
        text = (
            "✂️ <b>Видео-эффекты</b>"
            "<b>Режим: Преобразование видео</b>"
            "Загрузите видео (3-10 секунд), которое хотите преобразить.\n"
            "После загрузки опишите желаем эффект."
        )
    else:
        await state.set_state(GenerationStates.waiting_for_image)
        await state.update_data(
            generation_type="video_edit_image",
            video_edit_input_type="image",
            has_video=False,
            has_image=False,
        )
        text = (
            "✂️ <b>Видео-эффекты</b>"
            "<b>Режим: Создание видео из фото</b>"
            "Загрузите изображение, которое хотите превратить в видео.\n"
            "После загрузки опишите движение и эффект."
        )

    await callback.message.edit_text(
        text,
        reply_markup=get_back_keyboard("edit_video"),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "video_edit_change_type")
async def handle_video_edit_change_type(
    callback: types.CallbackQuery, state: FSMContext
):
    """Сброс и выбор нового типа входного медиа для видео-эффектов"""
    video_edit_options = {"quality": "std", "duration": 5, "aspect_ratio": "16:9"}
    await state.update_data(video_edit_options=video_edit_options)

    user_credits = await get_user_credits(callback.from_user.id)

    await callback.message.edit_text(
        f"✂️ <b>Видео-эффекты</b>"
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов"
        f"<b>Преобразование видео</b>\n"
        f"Выберите, что хотите загрузить:"
        f"🎬 <b>Видео</b> - преобразование видео\n"
        f"🖼 <b>Фото</b> - создание видео из изображения"
        f"<i>Загрузите медиафайл и опишите эффект</i>",
        reply_markup=get_video_edit_input_type_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("video_edit_quality_"))
async def handle_video_edit_quality(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора качества для видео-эффектов"""
    quality = callback.data.replace("video_edit_quality_", "")

    data = await state.get_data()
    video_edit_options = data.get("video_edit_options", {})
    video_edit_options["quality"] = quality
    await state.update_data(video_edit_options=video_edit_options)

    await show_video_edit_options(callback, state, quality, video_edit_options)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("video_edit_duration_"))
async def handle_video_edit_duration(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора длительности для видео-эффектов"""
    duration = int(callback.data.replace("video_edit_duration_", ""))

    data = await state.get_data()
    video_edit_options = data.get("video_edit_options", {})
    video_edit_options["duration"] = duration
    await state.update_data(video_edit_options=video_edit_options)

    await show_video_edit_options(
        callback, state, video_edit_options.get("quality", "std"), video_edit_options
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("video_edit_ratio_"))
async def handle_video_edit_ratio(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора формата для видео-эффектов"""
    # Формат: video_edit_ratio_9_16 -> 9:16
    ratio_part = callback.data.replace("video_edit_ratio_", "")
    aspect_ratio = ratio_part.replace("_", ":")

    data = await state.get_data()
    video_edit_options = data.get("video_edit_options", {})
    video_edit_options["aspect_ratio"] = aspect_ratio
    await state.update_data(video_edit_options=video_edit_options)

    await show_video_edit_options(
        callback, state, video_edit_options.get("quality", "std"), video_edit_options
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


async def show_video_edit_options(
    callback: types.CallbackQuery, state: FSMContext, quality: str, options: dict
):
    data = await state.get_data()
    input_type = data.get("video_edit_input_type", "video")
    has_video = data.get("has_video", False)
    has_image = data.get("has_image", False)
    user_prompt = data.get("video_edit_prompt", "")

    quality_emoji = "💎" if quality == "pro" else "⚡"

    if input_type == "video":
        media_status = "✅ Загружено" if has_video else "⏳ Ожидание загрузки"
        media_text = "🎬 Видео"
    else:
        media_status = "✅ Загружено" if has_image else "⏳ Ожидание загрузки"
        media_text = "🖼 Изображение"

    text = f"✂️ <b>Видео-эффекты</b>"
    text += f"<b>Опции:</b>\n"
    text += f"   {quality_emoji} Качество: <code>{quality.upper()}</code>\n"
    text += f"   ⏱ Длительность: <code>{options.get('duration', 5)} сек</code>\n"
    text += f"   📐 Формат: <code>{options.get('aspect_ratio', '16:9')}</code>"
    text += f"{media_text}: {media_status}\n"
    if user_prompt:
        text += f"📝 Промпт: <code>{user_prompt[:50]}...</code>\n"
    text += f"\n<i>Загрузите {'видео' if input_type == 'video' else 'фото'} и опишите эффект</i>"

    await callback.message.edit_text(
        text,
        reply_markup=get_video_edit_keyboard(
            input_type=input_type,
            quality=quality,
            duration=options.get("duration", 5),
            aspect_ratio=options.get("aspect_ratio", "16:9"),
        ),
        parse_mode="HTML",
    )


# =============================================================================
# ОБРАБОТЧИКИ ПРЕСЕТОВ (ЕСЛИ НУЖНО ВЕРНУТЬ)
# =============================================================================


# =============================================================================
# ОБРАБОТЧИКИ ОПЦИЙ ГЕНЕРАЦИИ (НОВОЕ СОГЛАСНО banana_api.md)
# =============================================================================


@router.callback_query(F.data.startswith("model_"))
async def handle_model_selection(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора модели генерации"""
    parts = callback.data.split("_")
    if len(parts) >= 3:
        preset_id = parts[1]
        model_type = parts[2]  # "flash" или "pro"

        model = (
            "gemini-2.5-flash-image"
            if model_type == "flash"
            else "gemini-3-pro-image-preview"
        )

        # Обновляем опции
        data = await state.get_data()
        generation_options = data.get("generation_options", {})
        generation_options["model"] = model
        await state.update_data(generation_options=generation_options)

        # Показываем подтверждение
        preset = preset_manager.get_preset(preset_id)
        if preset:
            model_emoji = "💎" if "pro" in model else "⚡"
            text = f"✅ <b>Модель изменена</b>"
            text += f"{model_emoji} Теперь используется: <code>{model}</code>"

            if model_type == "flash":
                text += "<i>Быстрая генерация, до 1024px</i>\n"
            else:
                text += "<i>Высокое качество, до 4K, с thinking</i>\n"

            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(
                    preset_id, preset.requires_input, preset.category
                ),
                parse_mode="HTML",
            )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("resolution_"))
async def handle_resolution_selection(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора разрешения изображения"""
    parts = callback.data.split("_")
    if len(parts) >= 3:
        preset_id = parts[1]
        resolution = parts[2]  # "1K", "2K", "4K"

        # Обновляем опции
        data = await state.get_data()
        generation_options = data.get("generation_options", {})
        generation_options["resolution"] = resolution
        await state.update_data(generation_options=generation_options)

        # Показываем подтверждение
        preset = preset_manager.get_preset(preset_id)
        if preset:
            res_emoji = {"1K": "⚡", "2K": "💎", "4K": "👑"}.get(resolution, "⚡")
            text = f"✅ <b>Разрешение изменено</b>"
            text += f"{res_emoji} Теперь используется: <code>{resolution}</code>"

            resolutions = {
                "1K": "Стандартное качество, 1024px",
                "2K": "HD качество, 2048px",
                "4K": "Максимальное качество, 4096px",
            }
            text += f"<i>{resolutions.get(resolution, '')}</i>\n"

            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(
                    preset_id, preset.requires_input, preset.category
                ),
                parse_mode="HTML",
            )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(
    F.data.startswith("img_ratio_") & ~F.data.startswith("img_ratio_no_preset")
)
async def handle_image_ratio_selection(
    callback: types.CallbackQuery, state: FSMContext
):
    """Обработка выбора формата изображения для пресетов"""
    parts = callback.data.split("_")
    if len(parts) >= 4:
        preset_id = parts[1]
        ratio = f"{parts[2]}:{parts[3]}"  # "16:9"

        # Обновляем опции
        data = await state.get_data()
        generation_options = data.get("generation_options", {})
        generation_options["aspect_ratio"] = ratio
        await state.update_data(generation_options=generation_options)

        # Показываем подтверждение
        preset = preset_manager.get_preset(preset_id)
        if preset:
            text = f"✅ <b>Формат изменён</b>"
            text += f"📐 Теперь используется: <code>{ratio}</code>"

            ratios_desc = {
                "1:1": "Квадрат (Instagram, Facebook)",
                "16:9": "Горизонтальный (YouTube)",
                "9:16": "Вертикальный (TikTok, Reels)",
                "4:5": "Портретный (Instagram)",
                "21:9": "Панорамный (Кино)",
            }
            text += f"<i>{ratios_desc.get(ratio, '')}</i>\n"

            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(
                    preset_id, preset.requires_input, preset.category
                ),
                parse_mode="HTML",
            )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("grounding_"))
async def handle_search_grounding(callback: types.CallbackQuery, state: FSMContext):
    """Обработка поискового заземления (Grounding)"""
    parts = callback.data.split("_")
    if len(parts) >= 2:
        preset_id = parts[1]

        # Переключаем опцию
        data = await state.get_data()
        generation_options = data.get("generation_options", {})
        generation_options["enable_search"] = not generation_options.get(
            "enable_search", False
        )
        await state.update_data(generation_options=generation_options)

        # Показываем подтверждение
        preset = preset_manager.get_preset(preset_id)
        if preset:
            enabled = generation_options["enable_search"]
            status = "🟢 ВКЛ" if enabled else "🔴 ВЫКЛ"
            text = f"✅ <b>Поиск в интернете: {status}</b>"

            if enabled:
                text += "<i>AI будет использовать Google Search для актуальной информации</i>\n"
                text += "\nПримеры:\n"
                text += "• Погода на 5 дней\n"
                text += "• Последние новости\n"
                text += "• Актуальные события"
            else:
                text += "<i>Поиск отключён</i>\n"

            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(
                    preset_id, preset.requires_input, preset.category
                ),
                parse_mode="HTML",
            )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


async def show_preset_details(
    message_or_callback,
    preset,
    user_id: int,
    state: FSMContext = None,
):
    """Show preset details screen."""
    desc_line = f"— {preset.description}\n" if preset.description else ""
    text = (
        f"📋 <b>{preset.name}</b>\n"
        f"💰 Стоимость: <code>{preset.cost}🍌</code>\n"
        f"{desc_line}\n"
        f"Выберите действие:\n"
    )
    await message_or_callback.edit_text(
        text,
        reply_markup=get_preset_action_keyboard(
            preset.id, preset.requires_input, preset.category
        ),
        parse_mode="HTML",
    )
    if state:
        await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("ref_"))
async def handle_reference_images(callback: types.CallbackQuery, state: FSMContext):
    """
    Обработка работы с референсными изображениями (до 14 шт)
    Поддерживает загрузку, управление и подтверждение референсов
    """
    parts = callback.data.split("_")
    # parts[0] is "ref", parts[1] is action (upload, clear, skip, confirm, reload, accept)
    action = parts[1] if len(parts) > 1 else ""
    # Handle preset_id that may contain underscores (e.g. "my_preset")
    if len(parts) > 2:
        preset_id = "_".join(parts[2:])
    else:
        preset_id = None

    data = await state.get_data()
    img_service = data.get("img_service", "banana_pro")
    current_refs = data.get("reference_images", [])
    max_refs = _get_max_image_references(img_service)

    if action == "upload":
        # Начинаем загрузку референсных изображений
        await state.set_state(GenerationStates.uploading_reference_images)
        await state.update_data(preset_id=preset_id, reference_images=current_refs)

        await callback.message.edit_text(
            f"📎 <b>Загрузка референсов</b>\n"
            f"Загружено: <code>{len(current_refs)}/{max_refs}</code>\n\n"
            f"Отправьте фото, которые помогут точнее передать внешний вид, стиль или детали.\n"
            f"После загрузки нажмите <b>▶️ Продолжить</b>.",
            reply_markup=get_reference_images_upload_keyboard(
                len(current_refs), max_refs, preset_id
            ),
            parse_mode="HTML",
        )

    elif action == "clear":
        # Очищаем все референсы
        await state.update_data(reference_images=[])
        await callback.message.edit_text(
            f"📎 <b>Референсы очищены</b>\n"
            f"Загружено: <code>0/{max_refs}</code>\n"
            f"Теперь можно загрузить новые фото.",
            reply_markup=get_reference_images_upload_keyboard(0, max_refs, preset_id),
            parse_mode="HTML",
        )

    elif action == "skip":
        # Skip loading references
        if preset_id and preset_id != "new":
            preset = preset_manager.get_preset(preset_id)
            if preset:
                await show_preset_details(
                    callback.message, preset, callback.from_user.id, state
                )
                await callback.answer()
                return
        skip_data = await state.get_data()
        if skip_data.get("generation_type") == "video":
            await _show_video_creation_screen(callback.message, state)
        else:
            await _show_image_creation_screen(callback, state)

    elif action == "confirm":
        # Переходим к подтверждению
        if not current_refs:
            await callback.answer("❌ Нет загруженных изображений", show_alert=True)
            return

        # Для нового UX (preset_id == "new") - сразу переходим к выбору модели
        # (пропускаем экран подтверждения референсов)
        if preset_id == "new":
            accept_gen_type = data.get("generation_type", "")
            if accept_gen_type == "video":
                await _show_video_creation_screen(callback.message, state)
            else:
                await _show_image_creation_screen(callback, state)
            await callback.answer()
            await state.set_state(GenerationStates.waiting_for_input)
        else:
            # Для пресетов - сразу переходим к экрану пресета (пропускаем экран подтверждения)
            preset = preset_manager.get_preset(preset_id)
            if preset:
                await show_preset_details(
                    callback.message, preset, callback.from_user.id, state
                )
            else:
                await _show_image_creation_screen(callback, state)
                await state.set_state(GenerationStates.waiting_for_input)

    elif action == "reload":
        # Перезагружаем — очищаем и начинаем заново
        await state.update_data(reference_images=[])
        await state.set_state(GenerationStates.uploading_reference_images)

        await callback.message.edit_text(
            f"📎 <b>Начнём заново</b>\n"
            f"Загружено: <code>0/{max_refs}</code>\n"
            f"Отправьте новые фото-референсы.",
            reply_markup=get_reference_images_upload_keyboard(0, max_refs, preset_id),
            parse_mode="HTML",
        )

    elif action == "accept":
        # Сохраняем референсы в generation_options
        generation_options = data.get("generation_options", {})
        generation_options["reference_images"] = current_refs
        await state.update_data(generation_options=generation_options)

        # Для нового UX (preset_id == "new") - переходим к экрану выбора модели/формата
        # (пропускаем промежуточное меню подтверждения)
        if preset_id == "new":
            await _show_image_creation_screen(callback, state)
            await state.set_state(GenerationStates.waiting_for_input)
        else:
            # Для пресетов - возвращаемся к экрану пресета
            preset = preset_manager.get_preset(preset_id)
            if preset:
                await show_preset_details(
                    callback.message, preset, callback.from_user.id, state
                )
            else:
                # Этот код не должен достигаться в нормальном потоке, но оставим для совместимости
                await callback.message.edit_text(
                    "✅ Референсы сохранены!",
                    reply_markup=get_back_keyboard("back_main"),
                )

    else:
        # Показываем справку о референсах (стандартное поведение)
        help_text = get_reference_images_help()

        await callback.message.edit_text(
            help_text,
            reply_markup=get_reference_images_keyboard(preset_id),
            parse_mode="HTML",
        )

    await callback.answer()
    # Route state based on generation type
    gen_type_final = (await state.get_data()).get("generation_type", "")
    if gen_type_final == "video":
        await state.set_state(GenerationStates.waiting_for_video_prompt)
    else:
        await state.set_state(GenerationStates.waiting_for_input)


# =============================================================================
# ОБРАБОТЧИКИ ВВОДА ПОЛЬЗОВАТЕЛЯ
# =============================================================================


@router.callback_query(F.data.startswith("custom_"))
async def request_custom_input(callback: types.CallbackQuery, state: FSMContext):
    """Запрашивает пользовательский ввод для пресета"""
    preset_id = callback.data.replace("custom_", "")
    preset = preset_manager.get_preset(preset_id)

    if not preset:
        await callback.answer("Пресет не найден")
        return

    await state.update_data(preset_id=preset_id, input_type="custom")

    # UX: Показываем подсказки по промптам
    tips_text = get_prompt_tips()

    # Если требуется загрузка файла
    if preset.requires_upload:
        await state.set_state(GenerationStates.waiting_for_image)

        hint = UserHints.get_hint_for_stage("input")
        await callback.message.edit_text(
            f"📎 <b>Загрузите изображение</b>"
            f"Для пресета: {preset.name}"
            f"После загрузки изображения, {preset.input_prompt or 'введите описание'}"
            f"<i>{hint}</i>",
            reply_markup=get_back_keyboard(f"preset_{preset_id}"),
            parse_mode="HTML",
        )
    else:
        await state.set_state(GenerationStates.waiting_for_input)

        hint = UserHints.get_hint_for_stage("input")
        await callback.message.edit_text(
            f"✏️ <b>Введите ваш вариант</b>"
            f"{preset.input_prompt or 'Опишите, что хотите создать'}"
            f"Примеры для вдохновения:\n"
            f"• Стиль: минимализм, винтаж, футуризм\n"
            f"• Цветовая схема: яркий, пастельный, тёмный\n"
            f"• Эмоция: радостное, удивлённое, задумчивое"
            f"<i>{hint}</i>",
            reply_markup=get_back_keyboard(f"preset_{preset_id}"),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("default_"))
async def use_default_values(callback: types.CallbackQuery, state: FSMContext):
    """Использует пример значений для пресета"""
    preset_id = callback.data.replace("default_", "")
    preset = preset_manager.get_preset(preset_id)

    if not preset:
        await callback.answer("Пресет не найден")
        return

    # Заполняем плейсхолдеры значениями по умолчанию
    defaults = preset_manager.get_default_values("styles") or ["минимализм"]
    color_defaults = preset_manager.get_default_values("color_schemes") or ["яркий"]
    expr_defaults = preset_manager.get_default_values("expressions") or ["радостное"]

    placeholder_values = {}
    for placeholder in preset.placeholders:
        if "style" in placeholder.lower():
            placeholder_values[placeholder] = defaults[0]
        elif "color" in placeholder.lower():
            placeholder_values[placeholder] = color_defaults[0]
        elif "expr" in placeholder.lower():
            placeholder_values[placeholder] = expr_defaults[0]
        else:
            placeholder_values[placeholder] = "пример"

    try:
        final_prompt = preset.format_prompt(**placeholder_values)
    except Exception:
        final_prompt = preset.prompt.replace("{", "").replace("}", "")

    await state.update_data(
        preset_id=preset_id, final_prompt=final_prompt, input_type="default"
    )

    # Показываем финальный промпт с подтверждением
    data = await state.get_data()
    generation_options = data.get("generation_options", {})

    await callback.message.edit_text(
        f"▶️ <b>Подтвердите генерацию</b>"
        f"Пресет: <b>{preset.name}</b>\n"
        f"Стоимость: <code>{preset.cost}</code>🍌"
        f"<b>Промпт:</b>\n"
        f"<code>{final_prompt[:300]}{'...' if len(final_prompt) > 300 else ''}</code>"
        f"{format_generation_options(generation_options)}",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="✅ Запустить", callback_data=f"run_{preset_id}"
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="❌ Отмена", callback_data=f"preset_{preset_id}"
                    )
                ],
            ]
        ),
        parse_mode="HTML",
    )


@router.message(
    GenerationStates.waiting_for_video_prompt,
    F.photo
    | (
        F.document & F.document.mime_type.in_(["image/jpeg", "image/png", "image/webp"])
    ),
)
async def process_photo_for_video_prompt_state(
    message: types.Message, state: FSMContext
):
    """
    Обрабатывает фото для imgtxt видео в состоянии waiting_for_video_prompt.
    Первое фото - v_image_url (старт кадр), остальные - reference_images (до 8 рефов, total 9).
    """
    data = await state.get_data()
    v_type = data.get("v_type")
    current_model = data.get("v_model", "v3_std")
    is_gemini_omni_video = current_model == "gemini_omni_video"
    if v_type not in {"imgtxt", "avatar", "character"} and not is_gemini_omni_video:
        await message.answer(
            "Пожалуйста, отправьте текстовое описание.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return

    # Download photo
    if message.photo:
        photo = message.photo[-1]
    else:
        photo = message.document

    file_size = getattr(photo, "file_size", 0) or 0
    if v_type in {"avatar", "character"} and file_size and file_size > 20 * 1024 * 1024:
        await message.answer(
            "❌ Фото слишком большое. Максимум 20MB.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return
    file = await message.bot.get_file(photo.file_id)
    image_bytes = await message.bot.download_file(file.file_path)
    image_data = image_bytes.read()

    # Validate
    try:

        img = Image.open(io.BytesIO(image_data))
        width, height = img.size
        logger.info(f"Image validated for Kling: {width}×{height}")
        if v_type != "avatar" and (width < 300 or height < 300):
            await message.answer(
                f"❌ Изображение слишком маленькое: {width}×{height} (мин 300px)",
                reply_markup=get_main_menu_button_keyboard(),
            )
            return
    except Exception as e:
        logger.error(f"Image validation failed: {e}")
        await message.answer(
            "❌ Не удалось обработать изображение.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return

    if message.photo:
        file_ext = "jpg"
    else:
        mime_type = message.document.mime_type
        file_ext = (
            "jpg"
            if mime_type == "image/jpeg"
            else "png" if mime_type == "image/png" else "webp"
        )

    content_type = "image/jpeg" if file_ext == "jpg" else f"image/{file_ext}"
    image_url = await _persist_reusable_image_reference(
        message.from_user.id,
        image_data,
        file_ext,
        original_filename=f"video_ref_{photo.file_id}.{file_ext}",
        content_type=content_type,
    )
    if not image_url:
        await message.answer(
            "❌ Не удалось сохранить фото.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return

    v_image_url = data.get("v_image_url")
    reference_images = data.get("reference_images", [])

    if v_type == "avatar":
        await state.update_data(v_image_url=image_url)
        await message.answer("✅ Фото аватара загружено. Можно перейти дальше.")
        if data.get("video_flow_step") == "media":
            await _show_video_media_screen(message, state, edit=False)
        else:
            await _show_video_creation_screen(message, state, edit=False)
        return

    if v_type == "character":
        await state.update_data(v_image_url=image_url)
        await message.answer("✅ Изображение персонажа загружено.")
        if data.get("video_flow_step") == "media":
            await _show_video_media_screen(message, state, edit=False)
        else:
            await _show_video_creation_screen(message, state, edit=False)
        return

    if is_gemini_omni_video:
        existing_images = _collect_gemini_omni_image_urls(v_image_url, reference_images)
        existing_videos = _collect_gemini_omni_video_urls(
            data.get("v_reference_videos", [])
        )
        validation_error = _validate_gemini_omni_video_inputs(
            image_urls=[*existing_images, image_url],
            video_urls=existing_videos,
            character_ids=data.get("omni_character_ids", []),
            audio_ids=data.get("omni_audio_ids", []),
        )
        if validation_error:
            await message.answer(f"❌ {validation_error}")
            return

        if v_type == "imgtxt" and not v_image_url:
            await state.update_data(v_image_url=image_url)
            status = (
                f"✅ Стартовое фото добавлено. "
                f"Фото: {len(existing_images) + 1}"
            )
        else:
            reference_images = _clean_unique_urls([*reference_images, image_url])
            await state.update_data(reference_images=reference_images)
            status = (
                f"✅ Фото-референс добавлен. "
                f"Фото: {len(_collect_gemini_omni_image_urls(v_image_url, reference_images))}"
            )

        await message.answer(status)
        if data.get("video_flow_step") == "media":
            await _show_video_media_screen(message, state, edit=False)
        else:
            await _show_video_creation_screen(message, state, edit=False)
        return

    if current_model in {"v26_pro", "grok_imagine_v15"} and v_image_url:
        model_label = get_video_model_label(current_model)
        await message.answer(
            f"Для {model_label} можно использовать только одно стартовое фото."
        )
        return

    start_count = 1 if v_image_url else 0
    current_refs = len(reference_images)
    total = start_count + current_refs + 1  # +1 for this photo
    max_images = get_max_video_image_references(current_model)
    if total > max_images:
        await message.answer(
            f"❌ Можно загрузить максимум {max_images} фото для выбранной модели."
        )
        return

    if not v_image_url:
        # Первое фото - стартовый кадр
        await state.update_data(v_image_url=image_url)
        logger.info(f"Saved start image for video (1st photo): {image_url}")
        status = f"✅ Основное фото загружено. (1/{max_images})"
    else:
        # Последующие - референсы
        reference_images.append(image_url)
        await state.update_data(reference_images=reference_images)
        logger.info(
            f"Saved reference image for video (ref #{current_refs + 1}): {image_url}"
        )
        status = f"✅ Дополнительное фото загружено. Всего: {total}/{max_images}"

    # Update UI with current count
    data = await state.get_data()
    current_model = data.get("v_model", "v3_std")
    current_duration = data.get("v_duration", 5)
    current_ratio = data.get("v_ratio", "16:9")

    start_count = 1 if data.get("v_image_url") else 0
    ref_count = len(data.get("reference_images", []))
    total_photos = start_count + ref_count

    if data.get("video_flow_step") == "media":
        await message.answer(
            f"{status}\nНиже открыт обновлённый шаг с файлами.",
            parse_mode="HTML",
        )
        await _show_video_media_screen(message, state, edit=False)
    else:
        text = (
            f"🎬 <b>Фото + Текст → Видео</b>\n"
            f"📎 Загружено фото: <code>{total_photos}/{max_images}</code>\n"
            f"{status}\n"
            f"⚙️ Модель: <code>{current_model}</code> | {current_duration}с | {current_ratio}\n\n"
            f"<b>Можно отправить ещё фото или сразу написать описание видео.</b>"
        )

        await message.answer(
            text,
            reply_markup=get_create_video_keyboard(
                current_v_type="imgtxt",
                current_model=current_model,
                current_duration=current_duration,
                current_ratio=current_ratio,
            ),
            parse_mode="HTML",
        )


@router.message(
    GenerationStates.waiting_for_video_prompt,
    F.video | (F.document & F.document.mime_type.startswith("video/")),
)
async def process_video_for_gemini_omni_prompt_state(
    message: types.Message,
    state: FSMContext,
):
    """Accept one Gemini Omni video reference without forcing the old video mode."""
    data = await state.get_data()
    if data.get("v_model") != "gemini_omni_video":
        await message.answer(
            "Пожалуйста, отправьте текстовое описание.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return

    if message.video:
        video_obj = message.video
    elif message.document and message.document.mime_type.startswith("video/"):
        video_obj = message.document
    else:
        await message.answer("❌ Отправьте видео-файл.")
        return

    file_size = getattr(video_obj, "file_size", 0) or 0
    if file_size > 20 * 1024 * 1024:
        await message.answer("❌ Видео слишком большое (макс 20MB).")
        return

    existing_videos = _collect_gemini_omni_video_urls(
        data.get("v_reference_videos", [])
    )
    if len(existing_videos) >= gemini_omni_service.MAX_VIDEO_INPUTS:
        await message.answer(
            "❌ Gemini Omni принимает только один видео-референс. "
            "Удалите текущий или начните заново."
        )
        return

    validation_error = _validate_gemini_omni_video_inputs(
        image_urls=_collect_gemini_omni_image_urls(
            data.get("v_image_url"),
            data.get("reference_images", []),
        ),
        video_urls=[*existing_videos, "__new_video__"],
        character_ids=data.get("omni_character_ids", []),
        audio_ids=data.get("omni_audio_ids", []),
    )
    if validation_error:
        await message.answer(f"❌ {validation_error}")
        return

    file = await message.bot.get_file(video_obj.file_id)
    video_bytes = await message.bot.download_file(file.file_path)
    video_url = await _persist_reusable_media_reference(
        message.from_user.id,
        video_bytes.read(),
        "mp4",
        kind="video",
        original_filename=f"video_ref_{video_obj.file_id}.mp4",
        content_type=getattr(video_obj, "mime_type", None) or "video/mp4",
    )
    if not video_url:
        await message.answer("❌ Не удалось сохранить видео. Попробуйте ещё раз.")
        return

    await state.update_data(v_reference_videos=[*existing_videos, video_url])
    await message.answer("✅ Видео-референс добавлен. Можно отправить промпт.")
    if data.get("video_flow_step") == "media":
        await _show_video_media_screen(message, state, edit=False)
    else:
        await _show_video_creation_screen(message, state, edit=False)


@router.callback_query(F.data.startswith("motion_mode_"))
async def handle_motion_mode(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик режимов Motion Control"""
    mode = callback.data.replace("motion_mode_", "")
    await state.update_data(motion_mode=mode)
    data = await state.get_data()
    current_orientation = data.get("motion_orientation", "video")
    await callback.message.edit_reply_markup(
        get_motion_control_keyboard(mode, current_orientation)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("motion_orientation_"))
async def handle_motion_orientation(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик ориентации Motion Control"""
    orientation = callback.data.replace("motion_orientation_", "")
    await state.update_data(motion_orientation=orientation)
    data = await state.get_data()
    current_mode = data.get("motion_mode", "720p")
    await callback.message.edit_reply_markup(
        get_motion_control_keyboard(current_mode, orientation)
    )
    await callback.answer()


@router.message(GenerationStates.waiting_for_video_prompt, F.text)
async def handle_video_prompt_text(message: types.Message, state: FSMContext):
    """Обрабатывает ввод промпта для видео и motion control (новый UX)."""
    logger.info(f"[DEBUG STATE] Current state: {await state.get_state()}")
    logger.info(f"Video prompt handler triggered for user {message.from_user.id}")
    prompt = message.text.strip()

    if not prompt:
        await message.answer("⚠️ Введите описание видео перед запуском генерации.")
        return

    data = await state.get_data()
    generation_type = data.get("generation_type", "")
    v_type = data.get("v_type", "")
    is_gemini_omni_video = data.get("v_model") == "gemini_omni_video"
    if (
        generation_type == "video"
        and v_type in ("imgtxt", "avatar", "video", "character")
        and data.get("video_flow_step") != "configure"
    ):
        if (
            v_type == "imgtxt"
            and not data.get("v_image_url")
            and not is_gemini_omni_video
        ):
            await message.answer("Сначала отправьте стартовое фото.")
            return
        if v_type == "avatar":
            if not data.get("v_image_url"):
                await message.answer("Сначала отправьте фото аватара.")
                return
            if not data.get("avatar_audio_url"):
                await message.answer("Сначала отправьте аудио для аватара.")
                return
        if v_type == "character" and not data.get("v_image_url"):
            await message.answer("Сначала отправьте изображение персонажа.")
            return
        await state.update_data(video_flow_step="configure")
    logger.info(f"Generation type: {generation_type}")

    await state.update_data(user_prompt=prompt)

    logger.info("Calling run_no_preset_video_from_message")
    await run_no_preset_video_from_message(message, state, prompt)


def _detect_avatar_audio_duration_seconds(message: types.Message, audio_data: bytes, file_ext: str) -> int | None:
    if message.audio and message.audio.duration:
        return int(message.audio.duration)
    if message.voice and message.voice.duration:
        return int(message.voice.duration)

    temp_path = f"/tmp/avatar_audio_{uuid.uuid4().hex}.{file_ext}"
    try:
        with open(temp_path, "wb") as fh:
            fh.write(audio_data)
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                temp_path,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        value = (result.stdout or "").strip()
        if not value:
            return None
        return int(float(value))
    except Exception:
        logger.exception("Failed to detect avatar audio duration")
        return None
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


@router.message(
    GenerationStates.waiting_for_video_prompt,
    F.audio
    | F.voice
    | (
        F.document
        & F.document.mime_type.in_(
            [
                "audio/mpeg",
                "audio/wav",
                "audio/x-wav",
                "audio/aac",
                "audio/mp4",
                "audio/ogg",
            ]
        )
    ),
)
async def process_avatar_audio_upload(message: types.Message, state: FSMContext):
    """Handles audio uploads for Kling AI Avatar flow."""
    data = await state.get_data()
    if data.get("v_type") != "avatar":
        await message.answer("Пожалуйста, отправьте текстовое описание.")
        return

    media = message.audio or message.voice or message.document
    file_size = getattr(media, "file_size", 0) or 0
    if file_size and file_size > 10 * 1024 * 1024:
        await message.answer("❌ Аудиофайл слишком большой. Максимум 10MB.")
        return

    file = await message.bot.get_file(media.file_id)
    audio_bytes = await message.bot.download_file(file.file_path)
    audio_data = audio_bytes.read()

    if message.audio:
        mime_type = message.audio.mime_type or "audio/mpeg"
    elif message.voice:
        mime_type = "audio/ogg"
    else:
        mime_type = message.document.mime_type or "audio/mpeg"

    ext_map = {
        "audio/mpeg": "mp3",
        "audio/wav": "wav",
        "audio/x-wav": "wav",
        "audio/aac": "aac",
        "audio/mp4": "m4a",
        "audio/ogg": "ogg",
    }
    file_ext = ext_map.get(mime_type, "mp3")
    audio_duration_seconds = _detect_avatar_audio_duration_seconds(
        message, audio_data, file_ext
    )
    if audio_duration_seconds is None:
        await message.answer(
            "❌ Не удалось определить длительность аудио. Отправьте файл до 1 минуты."
        )
        return
    if audio_duration_seconds > AVATAR_AUDIO_MAX_SECONDS:
        await message.answer(
            "❌ Для Kling Avatar аудио должно быть не длиннее 1 минуты."
        )
        return

    audio_url = save_uploaded_file(audio_data, file_ext)
    if not audio_url:
        await message.answer("❌ Не удалось сохранить аудио.")
        return

    await state.update_data(avatar_audio_url=audio_url)
    await message.answer("✅ Аудио загружено.")
    if data.get("video_flow_step") == "media":
        await _show_video_media_screen(message, state, edit=False)
    else:
        await _show_video_creation_screen(message, state, edit=False)


async def run_no_preset_video_from_callback(
    callback: types.CallbackQuery, state: FSMContext, prompt: str, cost: int, is_admin: bool
):
    """Запускает видео-повтор из callback-кнопки «🔁 Повторить». 
    Делегирует в общую логику run_no_preset_video_from_message."""
    data = await state.get_data()

    v_type = data.get("v_type", "text")
    v_model = data.get("v_model", "v3_std")
    v_duration = _normalize_video_duration_value(v_model, int(data.get("v_duration", 5)))
    v_ratio = data.get("v_ratio", "16:9")
    v_image_url = data.get("v_image_url")
    v_reference_videos = data.get("v_reference_videos", [])
    reference_images = data.get("reference_images", [])
    avatar_audio_url = data.get("avatar_audio_url")

    user = await get_or_create_user(callback.from_user.id)
    
    try:
        from bot.services.kling_service import kling_service
        from bot.services.seedance_service import seedance_service

        if v_model == "gemini_omni_video":
            omni_images = _collect_gemini_omni_image_urls(v_image_url, reference_images)
            omni_video_urls = _collect_gemini_omni_video_urls(v_reference_videos)
            omni_video_list = _build_gemini_omni_video_list(omni_video_urls, v_duration)
            omni_character_ids = data.get("omni_character_ids", [])
            omni_audio_ids = data.get("omni_audio_ids", [])
            omni_seed = data.get("omni_seed")
            omni_resolution = data.get("omni_resolution", "720p")

            validation_error = _validate_gemini_omni_video_inputs(
                image_urls=omni_images,
                video_urls=omni_video_urls,
                character_ids=omni_character_ids,
                audio_ids=omni_audio_ids,
            )
            if validation_error:
                await callback.message.answer(f"❌ {validation_error}")
                if not is_admin:
                    await add_credits(callback.from_user.id, cost)
                return

            result = await gemini_omni_service.generate_video(
                prompt=prompt,
                duration=v_duration,
                aspect_ratio=v_ratio,
                resolution=omni_resolution,
                image_urls=omni_images or None,
                audio_ids=omni_audio_ids,
                video_list=omni_video_list or None,
                character_ids=omni_character_ids,
                seed=omni_seed,
                callBackUrl=config.kie_notification_url if config.WEBHOOK_HOST else None,
            )
        elif v_model.startswith("veo3"):
            veo_image_urls = []
            veo_gen_type = data.get("veo_generation_type", "TEXT_2_VIDEO")
            if veo_gen_type == "FIRST_AND_LAST_FRAMES_2_VIDEO":
                if v_image_url:
                    veo_image_urls.append(v_image_url)
                if reference_images:
                    for ref_url in reference_images:
                        if ref_url not in veo_image_urls:
                            veo_image_urls.append(ref_url)
                            if len(veo_image_urls) >= 2:
                                break
            elif veo_gen_type == "REFERENCE_2_VIDEO":
                if v_image_url:
                    veo_image_urls.append(v_image_url)
                for ref_url in reference_images:
                    if ref_url not in veo_image_urls:
                        veo_image_urls.append(ref_url)
                    if len(veo_image_urls) >= 3:
                        break
            result = await veo_service.generate_video(
                prompt=prompt,
                model=v_model,
                duration=v_duration,
                generation_type=veo_gen_type,
                image_urls=veo_image_urls or None,
                aspect_ratio=v_ratio,
                enable_translation=data.get("veo_translation", True),
                watermark=data.get("veo_watermark") or None,
                resolution=data.get("veo_resolution", "720p"),
                seeds=data.get("veo_seed"),
                callBackUrl=config.kie_notification_url if config.WEBHOOK_HOST else None,
            )
        elif v_model == "grok_imagine":
            if not v_image_url:
                await callback.message.answer("❌ Grok Imagine требует стартовое изображение.")
                if not is_admin:
                    await add_credits(callback.from_user.id, cost)
                return
            result = await grok_service.generate_image_to_video(
                image_urls=[v_image_url] + (reference_images or [])[:6],
                prompt=prompt,
                mode=data.get("grok_mode", "normal"),
                duration=v_duration,
                resolution="720p",
                aspect_ratio=v_ratio,
                callBackUrl=config.kie_notification_url if config.WEBHOOK_HOST else None,
            )
        elif v_model == "grok_imagine_v15":
            if not v_image_url:
                await callback.message.answer("❌ Grok Imagine 1.5 требует стартовое изображение.")
                if not is_admin:
                    await add_credits(callback.from_user.id, cost)
                return
            result = await grok_service.generate_image_to_video_v15(
                image_urls=[v_image_url],
                prompt=prompt,
                duration=v_duration,
                resolution=data.get("grok_resolution", "480p"),
                aspect_ratio=v_ratio,
                callBackUrl=config.kie_notification_url if config.WEBHOOK_HOST else None,
            )
        elif v_model == "seedance_2":
            (
                seedance_first_frame,
                seedance_refs,
                seedance_video_refs,
            ) = _seedance_media_inputs(
                v_type,
                v_image_url,
                reference_images,
                v_reference_videos,
            )
            result = await seedance_service.generate_video(
                prompt=prompt,
                duration=v_duration,
                aspect_ratio=v_ratio,
                resolution="720p",
                generate_audio=True,
                first_frame_url=seedance_first_frame,
                reference_image_urls=seedance_refs or None,
                reference_video_urls=seedance_video_refs or None,
                callBackUrl=config.kie_notification_url if config.WEBHOOK_HOST else None,
            )
        elif v_model in {"avatar_std", "avatar_pro"}:
            if not v_image_url:
                await callback.message.answer("❌ Для Kling AI Avatar нужно фото аватара.")
                if not is_admin:
                    await add_credits(callback.from_user.id, cost)
                return
            if not avatar_audio_url:
                await callback.message.answer("❌ Для Kling AI Avatar нужно аудио.")
                if not is_admin:
                    await add_credits(callback.from_user.id, cost)
                return
            result = await kling_service.generate_video(
                prompt=prompt,
                model=v_model,
                duration=v_duration,
                aspect_ratio=v_ratio,
                image_url=v_image_url,
                video_urls=[avatar_audio_url],
                webhook_url=config.kling_notification_url if config.WEBHOOK_HOST else None,
            )
        else:
            result = await kling_service.generate_video(
                prompt=prompt,
                model=v_model,
                duration=v_duration,
                aspect_ratio=v_ratio,
                image_url=v_image_url,
                video_urls=v_reference_videos if v_type in {"video", "motion"} else None,
                image_input=reference_images if v_type != "imgtxt" else None,
                negative_prompt=data.get("kling_negative_prompt") or None,
                cfg_scale=float(data.get("kling_cfg_scale", 0.5)),
                webhook_url=config.kling_notification_url if config.WEBHOOK_HOST else None,
            )

        if result and "task_id" in result:
            await add_generation_task(
                user.id,
                callback.from_user.id,
                result["task_id"],
                "video",
                "no_preset_video",
                model=v_model,
                duration=v_duration,
                aspect_ratio=v_ratio,
                prompt=prompt,
                cost=cost,
                request_data={
                    "source": "telegram",
                    "v_type": v_type,
                    "v_model": v_model,
                    "user_prompt": prompt,
                    "v_duration": v_duration,
                    "v_ratio": v_ratio,
                    "v_image_url": v_image_url,
                    "reference_images": reference_images,
                    "v_reference_videos": v_reference_videos,
                    "v_mode": data.get("v_mode", "720p"),
                },
            )
            model_label = get_video_model_label(v_model)
            await callback.message.answer(
                "🚀 <b>Повторное видео запущено</b>\n"
                f"• Модель: <code>{model_label}</code>\n"
                f"• ID: <code>{result['task_id']}</code>\n"
                f"• Списано: <code>{cost}</code>🍌 {'(админ бесплатно)' if is_admin else ''}\n\n"
                "Результат придёт в этот чат.",
                parse_mode="HTML",
            )
            try:
                await callback.answer("Повтор видео запускаю")
            except TelegramBadRequest:
                pass
        elif result and result.get("status") == "done":
            video_url = result.get("video_url") or result.get("result_url")
            if video_url:
                await callback.message.answer_video(
                    video=video_url,
                    caption=(
                        "✅ <b>Повтор готов</b>\n"
                        f"• Модель: <code>{get_video_model_label(v_model)}</code>\n"
                        f"• Списано: <code>{cost}</code>🍌 {'(админ бесплатно)' if is_admin else ''}"
                    ),
                    parse_mode="HTML",
                    reply_markup=get_video_result_keyboard(
                        video_url,
                        user_credits=await get_user_credits(callback.from_user.id),
                        task_id=result.get("task_id"),
                        model=v_model,
                    ),
                )
            else:
                await callback.message.answer("✅ Видео готово, но ссылка не получена.")
            try:
                await callback.answer("Повтор видео готов")
            except TelegramBadRequest:
                pass
        else:
            error_info = ""
            if isinstance(result, dict):
                error_info = make_user_friendly_generation_error(
                    result.get("message") or result.get("error") or ""
                ) or ""
            if not is_admin:
                await add_credits(callback.from_user.id, cost)
            await callback.message.answer(
                f"❌ Не получилось повторить видео. Бананы за попытку уже возвращены."
                + (f"\nПричина: <code>{html.escape(error_info[:300])}</code>" if error_info else ""),
                parse_mode="HTML",
            )
    except Exception:
        logger.exception("Video repeat from callback failed")
        if not is_admin:
            await add_credits(callback.from_user.id, cost)
        await callback.message.answer(
            "❌ Не получилось повторить видео. Бананы за попытку уже возвращены."
        )
    
    await state.clear()


async def run_no_preset_video_from_message(
    message: types.Message, state: FSMContext, prompt: str
):
    """Запускает видео генерацию без пресета (новый UX с v_type, v_model и т.д.)"""
    data = await state.get_data()
    v_type = data.get("v_type", "text")
    v_model = data.get("v_model", "v3_std")
    max_video_refs = get_max_video_references(v_model)
    raw_video_urls = _clean_unique_urls(data.get("v_reference_videos", []))

    v_duration = _normalize_video_duration_value(
        v_model, int(data.get("v_duration", 5))
    )
    v_ratio = data.get("v_ratio", "16:9")
    v_image_url = data.get("v_image_url")
    v_video_url = data.get("v_video_url")
    grok_resolution = data.get("grok_resolution", "480p")
    veo_generation_type = data.get("veo_generation_type", "TEXT_2_VIDEO")
    veo_translation = data.get("veo_translation", True)
    veo_resolution = data.get("veo_resolution", "720p")
    veo_seed = data.get("veo_seed")
    veo_watermark = data.get("veo_watermark", "")
    motion_mode = data.get("v_mode", "720p")
    motion_direction = data.get("v_orientation", "video")
    omni_resolution = data.get("omni_resolution", "720p")
    omni_seed = data.get("omni_seed")
    omni_audio_ids = data.get("omni_audio_ids", [])
    omni_character_ids = data.get("omni_character_ids", [])
    omni_base_voice = data.get("omni_base_voice", "achernar")
    omni_voice_name = data.get("omni_voice_name", "")
    omni_voice_description = data.get("omni_voice_description", "")
    omni_example_dialogue = data.get("omni_example_dialogue", "")
    omni_character_name = data.get("omni_character_name", "")
    omni_character_audio_ids = data.get("omni_character_audio_ids", [])

    image_url = data.get("v_image_url")
    avatar_audio_url = data.get("avatar_audio_url")
    if v_model == "gemini_omni_video":
        video_urls = raw_video_urls
        image_refs = _clean_unique_urls(data.get("reference_images", []))
    else:
        video_urls = normalize_reference_urls(
            raw_video_urls,
            max_count=max_video_refs,
        )
        video_urls = (
            video_urls
            if v_type in {"video", "motion"} or v_model == "seedance_2"
            else None
        )
        image_refs = normalize_reference_urls(
            data.get("reference_images", []),
            max_count=get_max_video_image_references(v_model),
        )

    video_image_sources = _clean_unique_urls([image_url, *image_refs])
    missing_video_image_sources = missing_local_upload_sources(video_image_sources)
    if missing_video_image_sources:
        missing_set = set(missing_video_image_sources)
        await state.update_data(
            v_image_url=None if image_url in missing_set else image_url,
            reference_images=[ref for ref in image_refs if ref not in missing_set],
            repeat_missing_ref_count=len(missing_video_image_sources),
        )
        await message.answer(
            "Часть старых фото для видео уже очищена, поэтому я не запускаю задачу с битыми ссылками.\n"
            "Загрузите эти фото заново и отправьте prompt ещё раз.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return

    elements_list = None
    if v_type == "imgtxt" and len(image_refs) >= 2:
        elements_list = [
            {
                "description": "reference photos for video generation consistency and style",
                "reference_image_urls": image_refs[
                    :12
                ],  # Kling elements support up to 3x4=12 refs
            }
        ]

    if v_type == "video" and not video_model_supports_reference_videos(v_model):
        await message.answer(
            "❌ Эта модель не принимает видео-референсы. Выберите Seedance 2.0 "
            "или быстрый режим «Видео-референс»."
        )
        await state.clear()
        return

    omni_images: list[str] = []
    omni_video_urls: list[str] = []
    if v_model == "gemini_omni_video":
        omni_images = _collect_gemini_omni_image_urls(image_url, image_refs)
        omni_video_urls = _collect_gemini_omni_video_urls(video_urls or [])
        validation_error = _validate_gemini_omni_video_inputs(
            image_urls=omni_images,
            video_urls=omni_video_urls,
            character_ids=omni_character_ids,
            audio_ids=omni_audio_ids,
        )
        if validation_error:
            await message.answer(f"❌ {validation_error}")
            return

    pricing_quality = None
    if v_model.startswith("veo3"):
        pricing_quality = veo_resolution
    elif v_model == "gemini_omni_video":
        pricing_quality = omni_resolution
    elif v_type == "motion" or v_model.startswith("motion_control"):
        pricing_quality = motion_mode
    cost = preset_manager.get_video_cost_with_quality(
        v_model, v_duration, pricing_quality
    )
    cost = apply_video_reference_cost(v_model, cost, video_urls)

    user = await get_or_create_user(message.from_user.id)
    is_admin = config.is_admin(message.from_user.id)

    # Admin free access
    if is_admin:
        logger.info(
            f"Admin {message.from_user.id} - free access (skipped {cost} credits)"
        )
    else:
        if not await check_can_afford(message.from_user.id, cost):
            await message.answer(
                f"❌ Недостаточно бананов!\nНужно: <code>{cost}</code>🍌\nПополните баланс.",
                reply_markup=get_main_menu_keyboard(
                    await get_user_credits(message.from_user.id)
                ),
                parse_mode="HTML",
            )
            await state.clear()
            return
        await deduct_credits(message.from_user.id, cost)

    run_summary = _build_video_run_summary(v_model, v_type, v_ratio, v_duration, data)

    processing_msg = await message.answer(
        f"🎬 <b>Видео генерируется...</b>"
        f"{run_summary}\n"
        f"💰 Стоимость: <code>{cost}</code>🍌"
        f"<i>Ожидайте 1-5 минут</i>",
        parse_mode="HTML",
    )

    try:
        from bot.services.kling_service import kling_service
        from bot.services.seedance_service import seedance_service

        if v_model == "gemini_omni_video":
            omni_video_list = _build_gemini_omni_video_list(
                omni_video_urls,
                v_duration,
            )

            result = await gemini_omni_service.generate_video(
                prompt=prompt,
                duration=v_duration,
                aspect_ratio=v_ratio,
                resolution=omni_resolution,
                image_urls=omni_images or None,
                audio_ids=omni_audio_ids,
                video_list=omni_video_list or None,
                character_ids=omni_character_ids,
                seed=omni_seed,
                callBackUrl=(
                    config.kie_notification_url if config.WEBHOOK_HOST else None
                ),
            )

        elif v_model == "gemini_omni_audio":
            audio_name = omni_voice_name or _derive_omni_name(prompt, "Omni Voice")
            result = await gemini_omni_service.create_audio(
                audio_id=omni_base_voice,
                name=audio_name,
                voice_description=omni_voice_description or prompt,
                example_dialogue=omni_example_dialogue,
            )

        elif v_model == "gemini_omni_character":
            if not image_url:
                await message.answer(
                    "❌ Gemini Omni Character требует изображение персонажа."
                )
                if not is_admin:
                    await add_credits(message.from_user.id, cost)
                await processing_msg.delete()
                await state.clear()
                return

            character_name = omni_character_name or _derive_omni_name(
                prompt,
                "Character",
            )
            result = await gemini_omni_service.create_character(
                description=prompt,
                image_urls=[image_url],
                character_name=character_name,
                audio_ids=omni_character_audio_ids,
            )

        elif v_model.startswith("veo3"):
            veo_image_urls = []
            if veo_generation_type == "TEXT_2_VIDEO":
                veo_image_urls = []
            elif veo_generation_type == "FIRST_AND_LAST_FRAMES_2_VIDEO":
                if image_url:
                    veo_image_urls.append(image_url)
                elif image_refs:
                    veo_image_urls.append(image_refs[0])
                if image_refs:
                    for ref_url in image_refs:
                        if ref_url not in veo_image_urls:
                            veo_image_urls.append(ref_url)
                            if len(veo_image_urls) >= 2:
                                break
            elif veo_generation_type == "REFERENCE_2_VIDEO":
                if v_model != "veo3_fast":
                    await message.answer(
                        "❌ Изображение слишком маленькое (мин 300px)."
                    )
                    if not is_admin:
                        await add_credits(message.from_user.id, cost)
                    await processing_msg.delete()
                    await state.clear()
                    return

                if image_url:
                    veo_image_urls.append(image_url)
                for ref_url in image_refs:
                    if ref_url not in veo_image_urls:
                        veo_image_urls.append(ref_url)
                    if len(veo_image_urls) >= 3:
                        break

            if veo_generation_type != "TEXT_2_VIDEO" and not veo_image_urls:
                await message.answer(
                    "❌ Для выбранного режима Veo нужно загрузить фото."
                )
                if not is_admin:
                    await add_credits(message.from_user.id, cost)
                await processing_msg.delete()
                await state.clear()
                return

            result = await veo_service.generate_video(
                prompt=prompt,
                model=v_model,
                duration=v_duration,
                generation_type=veo_generation_type,
                image_urls=veo_image_urls or None,
                aspect_ratio=v_ratio,
                enable_translation=veo_translation,
                watermark=veo_watermark or None,
                resolution=veo_resolution,
                seeds=veo_seed,
                callBackUrl=(
                    config.kie_notification_url if config.WEBHOOK_HOST else None
                ),
            )

        elif v_model == "grok_imagine":
            if not image_url:
                await message.answer(
                    "❌ Grok Imagine требует стартовое изображение (фото+текст режим)."
                )
                if not is_admin:
                    await add_credits(message.from_user.id, cost)
                await processing_msg.delete()
                await state.clear()
                return

            result = await grok_service.generate_image_to_video(
                image_urls=[image_url] + image_refs[:6],
                prompt=prompt,
                mode=data.get("grok_mode", "normal"),
                duration=v_duration,
                resolution="720p",
                aspect_ratio=v_ratio,
                callBackUrl=(
                    config.kie_notification_url if config.WEBHOOK_HOST else None
                ),
            )
        elif v_model == "grok_imagine_v15":
            if not image_url:
                await message.answer(
                    "❌ Grok Imagine 1.5 требует стартовое изображение."
                )
                if not is_admin:
                    await add_credits(message.from_user.id, cost)
                await processing_msg.delete()
                await state.clear()
                return

            result = await grok_service.generate_image_to_video_v15(
                image_urls=[image_url],
                prompt=prompt,
                duration=v_duration,
                resolution=grok_resolution,
                aspect_ratio=v_ratio,
                callBackUrl=(
                    config.kie_notification_url if config.WEBHOOK_HOST else None
                ),
            )
        elif v_model == "seedance_2":
            (
                seedance_first_frame,
                seedance_reference_images,
                seedance_reference_videos,
            ) = _seedance_media_inputs(
                v_type,
                image_url,
                image_refs,
                video_urls or [],
            )

            if v_type == "imgtxt":
                if not image_url:
                    await message.answer(
                        "❌ Для Seedance 2.0 в режиме Фото + Текст нужно стартовое фото."
                    )
                    if not is_admin:
                        await add_credits(message.from_user.id, cost)
                    await processing_msg.delete()
                    await state.clear()
                    return

                result = await seedance_service.generate_video(
                    prompt=prompt,
                    duration=v_duration,
                    aspect_ratio=v_ratio,
                    resolution="720p",
                    generate_audio=True,
                    first_frame_url=seedance_first_frame,
                    reference_image_urls=seedance_reference_images or None,
                    reference_video_urls=seedance_reference_videos or None,
                    callBackUrl=(
                        config.kie_notification_url if config.WEBHOOK_HOST else None
                    ),
                )
            else:
                result = await seedance_service.generate_video(
                    prompt=prompt,
                    duration=v_duration,
                    aspect_ratio=v_ratio,
                    resolution="720p",
                    generate_audio=True,
                    reference_image_urls=seedance_reference_images or None,
                    reference_video_urls=seedance_reference_videos or None,
                    callBackUrl=(
                        config.kie_notification_url if config.WEBHOOK_HOST else None
                    ),
                )
        else:
            if v_model == "v26_pro" and v_type == "video":
                await message.answer(
                    "❌ Kling 2.5 Turbo не поддерживает режим Видео + Текст."
                )
                if not is_admin:
                    await add_credits(message.from_user.id, cost)
                await processing_msg.delete()
                await state.clear()
                return
            if v_model in {"avatar_std", "avatar_pro"}:
                if not image_url:
                    await message.answer("❌ Для Kling AI Avatar нужно фото аватара.")
                    if not is_admin:
                        await add_credits(message.from_user.id, cost)
                    await processing_msg.delete()
                    await state.clear()
                    return
                if not avatar_audio_url:
                    await message.answer("❌ Для Kling AI Avatar нужно аудио.")
                    if not is_admin:
                        await add_credits(message.from_user.id, cost)
                    await processing_msg.delete()
                    await state.clear()
                    return

            kling_negative_prompt = data.get("kling_negative_prompt", "")
            kling_cfg_scale = float(data.get("kling_cfg_scale", 0.5))

            result = await kling_service.generate_video(
                prompt=prompt,
                model=v_model,
                duration=v_duration,
                aspect_ratio=v_ratio,
                image_url=image_url,
                video_urls=(
                    [avatar_audio_url]
                    if v_model in {"avatar_std", "avatar_pro"} and avatar_audio_url
                    else video_urls
                ),
                image_input=(
                    image_refs if v_type != "imgtxt" or not elements_list else None
                ),
                elements=elements_list,
                negative_prompt=kling_negative_prompt or None,
                cfg_scale=kling_cfg_scale,
                motion_direction=motion_direction,
                motion_mode=motion_mode,
                webhook_url=(
                    config.kling_notification_url if config.WEBHOOK_HOST else None
                ),
            )

        await processing_msg.delete()

        if result and result.get("status") == "done" and result.get("asset_id"):
            asset_kind = result.get("asset_kind") or "asset"
            task_type = "audio" if asset_kind == "audio" else "character"
            asset_id = str(result["asset_id"])
            await add_generation_task(
                user.id,
                message.from_user.id,
                asset_id,
                task_type,
                "no_preset_video",
                model=v_model,
                duration=v_duration,
                aspect_ratio=v_ratio,
                prompt=prompt,
                cost=cost,
                request_data={
                    "source": "telegram",
                    "v_type": v_type,
                    "v_model": v_model,
                    "asset_kind": asset_kind,
                    "asset_id": asset_id,
                    "v_image_url": image_url,
                    "reference_images": image_refs,
                    "omni_base_voice": omni_base_voice,
                    "omni_voice_name": omni_voice_name,
                    "omni_voice_description": omni_voice_description,
                    "omni_example_dialogue": omni_example_dialogue,
                    "omni_character_name": omni_character_name,
                    "omni_character_audio_ids": omni_character_audio_ids,
                },
            )
            await complete_video_task(asset_id, asset_id)
            result_title = (
                "Audio ID создан"
                if asset_kind == "audio"
                else "Character ID создан"
            )
            await message.answer(
                f"✅ <b>{result_title}</b>\n"
                f"• Модель: <code>{get_video_model_label(v_model)}</code>\n"
                f"• ID: <code>{asset_id}</code>\n"
                f"💰 <code>{cost}</code>🍌 {'списано' if not is_admin else '(админ бесплатно)'}\n\n"
                "Этот ID можно использовать в Gemini Omni Video.",
                parse_mode="HTML",
                reply_markup=get_gemini_omni_result_keyboard(),
            )
            await state.clear()
            return

        if result and "task_id" in result:
            task_type = (
                "audio"
                if v_model == "gemini_omni_audio"
                else "character" if v_model == "gemini_omni_character" else "video"
            )
            await add_generation_task(
                user.id,
                message.from_user.id,
                result["task_id"],
                task_type,
                "no_preset_video",
                model=v_model,
                duration=v_duration,
                aspect_ratio=v_ratio,
                prompt=prompt,
                cost=cost,
                request_data={
                    "source": "telegram",
                    "v_type": v_type,
                    "v_model": v_model,
                    "v_image_url": image_url,
                    "reference_images": image_refs,
                    "v_reference_videos": video_urls or [],
                    "avatar_audio_url": avatar_audio_url,
                    "grok_mode": data.get("grok_mode", "normal"),
                    "grok_resolution": (
                        grok_resolution if v_model == "grok_imagine_v15" else ""
                    ),
                    "resolution": (
                        grok_resolution
                        if v_model == "grok_imagine_v15"
                        else "720p" if v_model == "grok_imagine" else ""
                    ),
                    "veo_generation_type": veo_generation_type,
                    "veo_translation": veo_translation,
                    "veo_resolution": veo_resolution,
                    "veo_seed": veo_seed,
                    "veo_watermark": veo_watermark,
                    "kling_negative_prompt": data.get("kling_negative_prompt", ""),
                    "kling_cfg_scale": data.get("kling_cfg_scale", 0.5),
                    "motion_mode": motion_mode,
                    "motion_direction": motion_direction,
                    "omni_resolution": omni_resolution,
                    "omni_seed": omni_seed,
                    "omni_audio_ids": omni_audio_ids,
                    "omni_character_ids": omni_character_ids,
                    "omni_base_voice": omni_base_voice,
                    "omni_voice_name": omni_voice_name,
                    "omni_voice_description": omni_voice_description,
                    "omni_example_dialogue": omni_example_dialogue,
                    "omni_character_name": omni_character_name,
                    "omni_character_audio_ids": omni_character_audio_ids,
                },
            )
            queued_title = (
                "Audio ID создается"
                if v_model == "gemini_omni_audio"
                else (
                    "Character ID создается"
                    if v_model == "gemini_omni_character"
                    else "Видео задача запущена"
                )
            )
            await message.answer(
                f"✅ <b>{queued_title}!</b>"
                f"🆔 <code>{result['task_id']}</code>\n"
                f"{run_summary}\n"
                f"💰 <code>{cost}</code>🍌 {'списано' if not is_admin else '(админ бесплатно)'}"
                f"⏳ Результат через 1-5 мин в этом чате.",
                parse_mode="HTML",
            )
        else:
            if not is_admin:
                await add_credits(message.from_user.id, cost)
            error_text = ""
            if isinstance(result, dict):
                error_text = make_user_friendly_generation_error(
                    result.get("message") or result.get("error") or ""
                ) or ""
            details = (
                f"\nПричина: <code>{html.escape(error_text[:500])}</code>"
                if error_text
                else ""
            )
            await message.answer(
                "❌ Не получилось создать задачу. Бананы за попытку уже возвращены."
                f"{details}",
                parse_mode="HTML",
            )
    except Exception as e:
        logger.exception(f"Video generation error: {e}")
        if not is_admin:
            await add_credits(message.from_user.id, cost)
        await message.answer(
            "❌ Не получилось завершить запуск генерации. Бананы за попытку уже возвращены."
        )

    await state.clear()


# Service callback for informational inline buttons.
# Prevents Telegram loading spinner on non-action buttons like price/status.
@router.callback_query(F.data == "ignore")
async def ignore_callback(callback: types.CallbackQuery):
    """Service callback for informational inline buttons."""
    await callback.answer()


@router.message(
    StateFilter(None, "AIAssistantStates:waiting_for_message"),
    F.photo
    | (F.document & F.document.mime_type.in_(IMAGE_REFERENCE_DOCUMENT_MIME_TYPES)),
)
async def start_image_creation_from_idle_reference(
    message: types.Message,
    state: FSMContext,
):
    """Start image creation from a photo sent while no flow is active."""
    user_id = message.from_user.id
    intro_text = "✅ <b>Фото принято как референс.</b>\n\n"
    async with _get_reference_upload_lock(user_id):
        current_state = await state.get_state()
        current_data = await state.get_data()
        if (
            current_state == GenerationStates.waiting_for_input
            and current_data.get("generation_type") == "image"
        ):
            reference_images = list(current_data.get("reference_images") or [])
            img_service = current_data.get("img_service", "banana_pro")
            max_refs = _get_max_image_references(img_service)
            if len(reference_images) >= max_refs:
                await message.answer(
                    f"❌ Можно загрузить максимум {max_refs} фото. Дальше нажмите «Продолжить» или очистите список.",
                    parse_mode="HTML",
                    reply_markup=get_main_menu_button_keyboard(),
                )
                return
        else:
            await state.clear()
            reference_images = []
        image_url, error_message = await _save_reference_image_from_message(
            message,
            original_filename_prefix="quick_reference",
        )
        if not image_url:
            await message.answer(
                error_message or "❌ Не удалось сохранить фото. Попробуйте ещё раз.",
                reply_markup=get_main_menu_button_keyboard(),
            )
            return

        if reference_images:
            reference_images.append(image_url)
            await state.update_data(
                reference_images=reference_images,
                img_flow_step="configure",
            )
            intro_text = "✅ <b>Фото добавлено в текущие референсы.</b>\n\n"
        else:
            await state.update_data(
                **_default_image_flow_data(
                    reference_images=[image_url],
                    img_flow_step="configure",
                )
            )

    await _show_image_creation_screen(
        message,
        state,
        edit=False,
        intro_text=intro_text,
    )
    logger.info(
        "Started image creation from idle reference: user_id=%s reference_url=%s",
        user_id,
        image_url,
    )


def _motion_quality_per_second(model_key: str, quality: str) -> float:
    total = preset_manager.get_video_cost_with_quality(model_key, 5, quality)
    raw = total / 5
    return preset_manager._format_cost(raw)


def get_motion_control_model_keyboard(current_model: str = "motion_control_v26"):
    builder = InlineKeyboardBuilder()
    rows = [
        ("motion_control_v26", "🎯 Kling 2.6 Motion Control"),
        ("motion_control_v30", "🚀 Kling 3.0 Motion Control"),
    ]
    for model_key, label in rows:
        check = "✅ " if current_model == model_key else ""
        ps_720 = _motion_quality_per_second(model_key, "720p")
        ps_1080 = _motion_quality_per_second(model_key, "1080p")
        builder.button(
            text=f"{check}{label} • {ps_720}-{ps_1080}🍌/с",
            callback_data=f"motion_model_{model_key}",
        )
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1, 1, 1)
    return builder.as_markup()


# =============================================================================
# MOTION CONTROL DEDICATED MENU
# =============================================================================


@router.callback_query(F.data == "motion_control")
async def open_motion_control_menu(callback: types.CallbackQuery, state: FSMContext):
    """Open dedicated Motion Control version chooser."""
    await state.clear()
    user_credits = await get_user_credits(callback.from_user.id)
    await state.update_data(
        generation_type="video",
        v_type="motion",
        v_model="motion_control_v26",
        v_duration=5,
        v_ratio="1:1",
        v_image_url=None,
        v_reference_videos=[],
        v_mode="1080p",
        v_orientation="video",
    )
    text = (
        "🎯 <b>Motion Control</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code> бананов\n\n"
        "Выберите версию Kling. На кнопках указана только цена за 1 секунду."
    )
    await callback.message.edit_text(
        text,
        reply_markup=get_motion_control_model_keyboard("motion_control_v26"),
        parse_mode="HTML",
    )
    await callback.answer()


def get_motion_quality_keyboard(model: str, current_mode: str = "1080p"):
    builder = InlineKeyboardBuilder()
    check_720 = "✅ " if current_mode == "720p" else ""
    check_1080 = "✅ " if current_mode == "1080p" else ""
    ps_720 = _motion_quality_per_second(model, "720p")
    ps_1080 = _motion_quality_per_second(model, "1080p")
    builder.button(
        text=f"{check_720}📱 720p • {ps_720}🍌/с",
        callback_data=f"motion_quality_{model}_720p",
    )
    builder.button(
        text=f"{check_1080}🖥 1080p • {ps_1080}🍌/с",
        callback_data=f"motion_quality_{model}_1080p",
    )
    builder.button(text="◀️ Назад", callback_data="motion_control")
    builder.adjust(2, 1)
    return builder.as_markup()


@router.callback_query(
    F.data.in_({"motion_model_motion_control_v26", "motion_model_motion_control_v30"})
)
async def select_motion_control_model(callback: types.CallbackQuery, state: FSMContext):
    """Select Motion Control model — show quality chooser."""
    model = callback.data.replace("motion_model_", "")
    label = (
        "Kling 3.0 Motion Control"
        if model == "motion_control_v30"
        else "Kling 2.6 Motion Control"
    )
    user_credits = await get_user_credits(callback.from_user.id)
    await state.update_data(
        generation_type="video",
        v_type="motion",
        v_model=model,
        v_duration=5,
        v_ratio="1:1",
        v_image_url=None,
        v_reference_videos=[],
        v_mode="1080p",
        v_orientation="video",
    )
    ps_720 = _motion_quality_per_second(model, "720p")
    ps_1080 = _motion_quality_per_second(model, "1080p")
    text = (
        f"🎯 <b>{label}</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code> бананов\n"
        f"💰 Стоимость: <code>{ps_720}</code>-<code>{ps_1080}</code>🍌/с "
        f"(зависит от качества)\n\n"
        "Выберите качество:"
    )
    await callback.message.edit_text(
        text, parse_mode="HTML", reply_markup=get_motion_quality_keyboard(model)
    )
    await callback.answer(label)


@router.callback_query(F.data.startswith("motion_quality_"))
async def select_motion_control_quality(
    callback: types.CallbackQuery, state: FSMContext
):
    """Select quality for Motion Control and ask for character photo."""
    # callback_data format: motion_quality_<model>_<quality>
    parts = callback.data.split("_")
    # parts: ["motion", "quality", "motion", "control", "v26/v30", "720p/1080p"]
    quality = parts[-1]  # "720p" or "1080p"
    model = "_".join(parts[2:-1])  # "motion_control_v26" or "motion_control_v30"

    await state.update_data(v_mode=quality)
    await state.set_state(GenerationStates.waiting_for_video_start_image)

    user_credits = await get_user_credits(callback.from_user.id)
    label = (
        "Kling 3.0 Motion Control"
        if model == "motion_control_v30"
        else "Kling 2.6 Motion Control"
    )
    mode_label = "Pro / 1080p" if quality == "1080p" else "Std / 720p"
    ps_quality = _motion_quality_per_second(model, quality)
    text = (
        f"🎯 <b>{label}</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code> бананов\n"
        f"💰 Стоимость: <code>{ps_quality}</code>🍌/с "
        f"(списывается по длине вашего видео)\n"
        f"⚙️ Режим: <b>{mode_label}</b>\n\n"
        "Шаг 1. Отправьте <b>фото персонажа</b>, которого нужно оживить."
    )
    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer(quality)


@router.message(GenerationStates.waiting_for_video_start_image, F.photo)
async def motion_control_character_photo_upload(
    message: types.Message, state: FSMContext
):
    """Upload character photo for dedicated Motion Control flow."""
    data = await state.get_data()
    if data.get("v_type") != "motion":
        return

    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    downloaded = await message.bot.download_file(file.file_path)
    image_url = save_uploaded_file(downloaded.read(), "jpg")
    await state.update_data(v_image_url=image_url)
    await state.set_state(GenerationStates.uploading_reference_videos)
    await message.answer(
        "✅ Фото персонажа загружено.\n\n"
        "Шаг 2. Теперь отправьте <b>видео движения</b>.",
        parse_mode="HTML",
    )


@router.message(
    GenerationStates.uploading_reference_videos,
    F.video | (F.document & F.document.mime_type.startswith("video/")),
)
async def motion_control_reference_video_upload(
    message: types.Message, state: FSMContext
):
    """Upload movement video for dedicated Motion Control flow."""
    data = await state.get_data()
    if data.get("v_type") != "motion":
        raise SkipHandler

    if message.video:
        video_obj = message.video
    elif message.document and message.document.mime_type.startswith("video/"):
        video_obj = message.document
    else:
        await message.answer(
            "❌ Неверный тип файла. Отправьте видео.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return

    file = await message.bot.get_file(video_obj.file_id)
    downloaded = await message.bot.download_file(file.file_path)
    video_url = save_uploaded_file(downloaded.read(), "mp4")

    raw_duration = getattr(video_obj, "duration", 0) or 0
    v_duration = max(1, min(30, raw_duration)) if raw_duration > 0 else 5

    await state.update_data(v_reference_videos=[video_url], v_duration=v_duration)
    data = await state.get_data()
    v_model = data.get("v_model", "motion_control_v26")
    v_mode = data.get("v_mode", "1080p")
    detected_cost = preset_manager.get_video_cost_with_quality(
        v_model, v_duration, v_mode
    )
    await state.set_state(GenerationStates.waiting_for_video_prompt)
    await message.answer(
        f"✅ Видео движения загружено ({v_duration} сек).\n"
        f"💰 Стоимость: <code>{detected_cost}</code>🍌\n\n"
        "Шаг 3. Отправьте короткое описание результата.\n"
        "Например: <i>сохранить лицо, плавное движение, кинематографичный свет</i>.",
        parse_mode="HTML",
    )


@router.message(
    GenerationStates.uploading_reference_videos,
    F.video | (F.document & F.document.mime_type.startswith("video/")),
)
async def process_reference_video_upload(message: types.Message, state: FSMContext):
    """
    Обрабатывает загрузку нескольких референсных видео для режима video+text.
    """
    data = await state.get_data()
    if data.get("v_type") == "motion":
        return  # Propagate to motion_control_reference_video_upload
    generation_type = data.get("generation_type")
    v_type = data.get("v_type")
    current_model = data.get("v_model", "seedance_2")
    max_refs = get_max_video_references(current_model)
    v_reference_videos = normalize_reference_urls(
        data.get("v_reference_videos", []),
        max_count=max_refs,
    )
    if v_reference_videos != (data.get("v_reference_videos", []) or []):
        await state.update_data(v_reference_videos=v_reference_videos)

    if generation_type == "video" and v_type == "video":
        # Определяем источник файла
        if message.video:
            video_obj = message.video
        elif message.document and message.document.mime_type.startswith("video/"):
            video_obj = message.document
        else:
            await message.answer(
                "❌ Неверный тип файла. Отправьте видео.",
                reply_markup=get_main_menu_button_keyboard(),
            )
            return

        # Проверяем размер (макс 20MB)
        file_size = getattr(video_obj, "file_size", 0)
        if file_size > 20 * 1024 * 1024:
            await message.answer(
                "❌ Видео слишком большое (макс 20MB).",
                reply_markup=get_main_menu_button_keyboard(),
            )
            return

        if len(v_reference_videos) >= max_refs:
            await message.answer(
                f"❌ Можно загрузить максимум {max_refs} видео. Дальше нажмите «Продолжить».",
                parse_mode="HTML",
                reply_markup=get_main_menu_button_keyboard(),
            )
            return

        if current_model == "gemini_omni_video":
            validation_error = _validate_gemini_omni_video_inputs(
                image_urls=_collect_gemini_omni_image_urls(
                    data.get("v_image_url"),
                    data.get("reference_images", []),
                ),
                video_urls=[*v_reference_videos, "__new_video__"],
                character_ids=data.get("omni_character_ids", []),
                audio_ids=data.get("omni_audio_ids", []),
            )
            if validation_error:
                await message.answer(f"❌ {validation_error}", parse_mode="HTML")
                return

        file = await message.bot.get_file(video_obj.file_id)
        video_bytes = await message.bot.download_file(file.file_path)
        video_data = video_bytes.read()

        # Сохраняем видео и получаем URL
        video_url = await _persist_reusable_media_reference(
            message.from_user.id,
            video_data,
            "mp4",
            kind="video",
            original_filename=f"video_ref_{video_obj.file_id}.mp4",
            content_type=getattr(video_obj, "mime_type", None) or "video/mp4",
        )
        if video_url:
            v_reference_videos.append(video_url)
            v_reference_videos = normalize_reference_urls(
                v_reference_videos,
                max_count=max_refs,
            )
            await state.update_data(v_reference_videos=v_reference_videos)
            logger.info(f"Added reference video {len(v_reference_videos)}: {video_url}")

            if data.get("video_flow_step") == "media":
                await message.answer(
                    f"✅ Видео загружено. Сейчас файлов: <code>{len(v_reference_videos)}/{max_refs}</code>",
                    parse_mode="HTML",
                )
                await _show_video_media_screen(message, state, edit=False)
            else:
                current_count = len(v_reference_videos)
                text = (
                    f"📹 <b>Загрузка видео-референсов</b>\n"
                    f"Загружено: <code>{current_count}/{max_refs}</code>\n"
                    f"✅ Видео добавлено.\n"
                    f"Можно отправить ещё одно или нажать кнопку ниже."
                )
                await message.reply(
                    text,
                    reply_markup=get_reference_videos_upload_keyboard(
                        current_count, max_refs, "video_new"
                    ),
                    parse_mode="HTML",
                )
        else:
            await message.answer(
                "❌ Не удалось сохранить видео. Попробуйте ещё раз.",
                reply_markup=get_main_menu_button_keyboard(),
            )
        return

    await message.answer(
        "Пожалуйста, отправьте видео.",
        reply_markup=get_main_menu_button_keyboard(),
    )


@router.message(
    GenerationStates.uploading_reference_images,
    F.photo
    | (F.document & F.document.mime_type.in_(IMAGE_REFERENCE_DOCUMENT_MIME_TYPES)),
)
async def process_reference_photo_upload(message: types.Message, state: FSMContext):
    """Handles reference photo uploads during image creation."""
    async with _get_reference_upload_lock(message.from_user.id):
        data = await state.get_data()
        reference_images = list(data.get("reference_images") or [])
        img_service = data.get("img_service")
        max_refs = _get_max_image_references(img_service) if img_service else 9

        if len(reference_images) >= max_refs:
            await message.answer(
                f"❌ Можно загрузить максимум {max_refs} фото. Дальше нажмите «Продолжить» или очистите список.",
                parse_mode="HTML",
                reply_markup=get_main_menu_button_keyboard(),
            )
            return

        image_url, error_message = await _save_reference_image_from_message(
            message,
            original_filename_prefix="reference",
        )

        if image_url:
            if data.get("repeat_source_task_id"):
                inherited_ref_count = int(data.get("repeat_inherited_reference_count") or 0)
                already_replaced = bool(data.get("repeat_user_references_replaced"))
                if inherited_ref_count > 0 and not already_replaced:
                    reference_images = [image_url]
                else:
                    reference_images.append(image_url)
                await state.update_data(
                    reference_images=reference_images,
                    repeat_user_references_replaced=True,
                )
                await _show_repeat_image_screen(message, state)
                return

            reference_images.append(image_url)
            await state.update_data(reference_images=reference_images)

            preset_id = data.get("preset_id", "new")
            current_count = len(reference_images)

            text = (
                f"📎 <b>Загрузка референсов</b>\n"
                f"Загружено: <code>{current_count}/{max_refs}</code>\n"
                f"✅ Фото добавлено.\n"
                f"Можно отправить ещё одно или нажать кнопку ниже."
            )

            try:
                await message.reply(
                    text,
                    reply_markup=get_reference_images_upload_keyboard(
                        current_count, max_refs, preset_id
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                await message.answer(
                    text,
                    reply_markup=get_reference_images_upload_keyboard(
                        current_count, max_refs, preset_id
                    ),
                    parse_mode="HTML",
                )
            logger.info(f"Reference photo {current_count} added: {image_url}")
        else:
            await message.answer(
                error_message or "❌ Не удалось сохранить фото. Попробуйте ещё раз.",
                reply_markup=get_main_menu_button_keyboard(),
            )


@router.message(GenerationStates.waiting_for_input, F.text)
async def handle_image_prompt_text(message: types.Message, state: FSMContext):
    """Handles text prompt for image generation in waiting_for_input state"""
    data = await state.get_data()
    if data.get("generation_type") != "image":
        return  # Not for images, let other handlers catch

    prompt, confirmed_no_reference = _extract_no_reference_confirmation(message.text)
    if not prompt:
        await message.answer(
            "Нужен текстовый промпт — опишите, какое изображение хотите получить.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return

    img_service = data.get("img_service", "nanobanana")
    img_ratio = data.get("img_ratio", "1:1")
    img_count = data.get("img_count", 1)
    img_quality = data.get("img_quality", "2K")
    img_nsfw_checker = data.get("img_nsfw_checker", False)
    reference_images = data.get("reference_images", [])
    nsfw_enabled = data.get("nsfw_enabled", False)
    reference_images, missing_reference_images = _available_reference_images(
        reference_images
    )
    if missing_reference_images:
        await state.update_data(
            reference_images=reference_images,
            repeat_missing_ref_count=len(missing_reference_images),
        )
        await message.answer(
            "Часть старых фото уже очищена, поэтому я не запускаю задачу с битыми ссылками.\n"
            "Загрузите фото заново и отправьте prompt ещё раз.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return

    if (
        not reference_images
        and not confirmed_no_reference
        and _prompt_expects_reference_image(prompt)
    ):
        await message.answer(
            "⚠️ <b>Референс не прикреплён.</b>\n\n"
            "В prompt есть указание на референс/сохранение лица, но сейчас загружено "
            "<code>0</code> фото.\n\n"
            "Загрузите фото-референс и отправьте prompt ещё раз.\n"
            "Если хотите запустить именно без референса, отправьте prompt повторно с началом "
            "<code>Без рефа:</code>",
            reply_markup=get_reference_images_upload_keyboard(
                len(reference_images),
                _get_max_image_references(img_service),
                data.get("preset_id", "new"),
            ),
            parse_mode="HTML",
        )
        return

    if img_service == "grok_imagine_i2i" and not reference_images:
        await message.answer(
            "Для Grok Imagine сначала добавьте хотя бы одно фото-референс.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return
    if img_service == "seedream_edit" and not reference_images:
        await message.answer(
            "Для Seedream 4.5 Edit сначала добавьте хотя бы одно исходное изображение.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return

    user = await get_or_create_user(message.from_user.id)
    unit_cost = _resolve_image_unit_cost(img_service, img_quality)
    total_cost = unit_cost * img_count

    if user.credits < total_cost:
        await message.answer(
            f"❌ Недостаточно бананов! Нужно: <code>{total_cost}</code>🍌",
            reply_markup=get_main_menu_keyboard(user.credits, message.from_user.id),
            parse_mode="HTML",
        )
        return

    await deduct_credits(message.from_user.id, total_cost)

    model_label = get_image_model_label(img_service)
    ratio_label = img_ratio.replace(":", "∶")
    processing_msg = await message.answer(
        "🖼 <b>Запускаю генерацию</b>\n"
        f"• Модель: <code>{model_label}</code>\n"
        f"• Формат: <code>{ratio_label}</code>\n"
        f"• Количество: <code>{img_count}</code>\n"
        f"• Референсы: <code>{len(reference_images)}</code>",
        parse_mode="HTML",
    )

    started_task_ids = []
    started_task_infos = []
    created_task_ids = []
    immediate_success_count = 0
    refunded_count = 0
    current_local_task_id = None

    async def notify_local_task_created(local_task_id: str):
        created_task_ids.append(local_task_id)
        ids_preview = "\n".join(f"• <code>{task_id}</code>" for task_id in created_task_ids[:6])
        extra_count = len(created_task_ids) - 6
        if extra_count > 0:
            ids_preview += f"\n• ещё <code>{extra_count}</code>"
        try:
            await processing_msg.edit_text(
                "🖼 <b>Задача создана и отправляется провайдеру</b>\n"
                f"• Модель: <code>{model_label}</code>\n"
                f"• Формат: <code>{ratio_label}</code>\n"
                f"• Количество: <code>{img_count}</code>\n"
                f"• Референсы: <code>{len(reference_images)}</code>\n\n"
                f"{ids_preview}\n\n"
                "Жду ответ провайдера.",
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass

    try:
        callback_url = config.kie_notification_url if config.WEBHOOK_HOST else None
        stable_reference_images = _prepare_banana_reference_images(
            img_service, reference_images, prompt
        )

        for index in range(img_count):
            variant_prompt = _build_image_variant_prompt(prompt, index, img_count)
            task_reference_images = list(stable_reference_images)
            logger.info(
                "Launching image variant %s/%s with %s references for model=%s",
                index + 1,
                img_count,
                len(task_reference_images),
                img_service,
            )

            launch_result = await _start_image_generation_task(
                user=user,
                telegram_id=message.from_user.id,
                img_service=img_service,
                prompt=variant_prompt,
                img_ratio=img_ratio,
                reference_images=task_reference_images,
                unit_cost=unit_cost,
                img_quality=img_quality,
                img_nsfw_checker=img_nsfw_checker,
                nsfw_enabled=nsfw_enabled,
                callback_url=callback_url,
                on_task_created=notify_local_task_created,
            )
            current_local_task_id = launch_result.get(
                "local_task_id"
            ) or launch_result.get("task_id")

            if launch_result["status"] == "queued":
                started_task_ids.append(launch_result["task_id"])
                started_task_infos.append((launch_result["task_id"], launch_result.get("local_task_id")))
                current_local_task_id = None
            elif launch_result["status"] == "done":
                immediate_success_count += 1
                result_bytes = launch_result["result_bytes"]
                saved_url = launch_result["saved_url"]
                await message.answer_document(
                    document=types.BufferedInputFile(
                        result_bytes, filename=f"{launch_result['task_id']}.png"
                    ),
                    caption=(
                        "✅ <b>Изображение готово</b>\n"
                        f"• Вариант: <code>{index + 1}/{img_count}</code>\n"
                        f"• Модель: <code>{model_label}</code>\n"
                        f"• ID: <code>{launch_result['task_id']}</code>\n"
                        f"• Списано: <code>{unit_cost}</code>🍌\n"
                        "• Отправлено без сжатия"
                    ),
                    parse_mode="HTML",
                    reply_markup=get_image_result_keyboard(
                        saved_url, task_id=launch_result["task_id"]
                    ),
                )
                await _send_used_prompt_message_to_chat(
                    message.answer,
                    variant_prompt,
                    task_id=launch_result["task_id"],
                    model_label=model_label,
                )
                current_local_task_id = None
            else:
                refunded_count += 1
                await add_credits(message.from_user.id, unit_cost)
                current_local_task_id = None

        await processing_msg.delete()

        if started_task_ids:
            id_lines = []
            for task_id, local_task_id in started_task_infos[:6]:
                public_task_id, provider_id_line = _format_public_task_id_lines(task_id, local_task_id)
                line = f"• <code>{public_task_id}</code>"
                if provider_id_line:
                    line += f"\n  {provider_id_line.strip()}"
                id_lines.append(line)
            ids_preview = "\n".join(id_lines)
            await message.answer(
                "🚀 <b>Генерация запущена</b>\n"
                f"• Модель: <code>{model_label}</code>\n"
                f"• Формат: <code>{ratio_label}</code>\n"
                f"• Запущено задач: <code>{len(started_task_ids)}</code>\n"
                f"• Списано: <code>{unit_cost * len(started_task_ids) + unit_cost * immediate_success_count}</code>🍌\n\n"
                f"{ids_preview}\n\n"
                "Обычно результат приходит в течение 1-3 минут.",
                parse_mode="HTML",
            )


        if refunded_count:
            await message.answer(
                "Часть вариантов не удалось запустить.\n"
                f"Возвращено: <code>{refunded_count * unit_cost}</code>🍌",
                parse_mode="HTML",
            )

        if not started_task_ids and not immediate_success_count:
            await message.answer(
                "Не получилось запустить генерацию.\n"
                "Бананы за эту попытку уже вернулись на баланс."
            )

    except Exception as e:
        logger.exception(f"Image generation error: {e}")
        exception_refund_units = 0
        if current_local_task_id:
            refunded_count += 1
            exception_refund_units += 1
            await complete_video_task(current_local_task_id, None)
            current_local_task_id = None

        launched_or_refunded = (
            len(started_task_ids) + immediate_success_count + refunded_count
        )
        remaining_to_refund = max(0, img_count - launched_or_refunded)
        refund_amount = (exception_refund_units + remaining_to_refund) * unit_cost
        if refund_amount > 0:
            await add_credits(message.from_user.id, refund_amount)
        await message.answer(
            "Что-то пошло не так при запуске генерации.\n"
            "Незапущенные варианты уже возвращены на баланс."
        )

    await state.clear()


@router.message(GenerationStates.waiting_for_reference_video)
async def invalid_reference_video_input(message: types.Message, state: FSMContext):
    """
    Обрабатывает невалидный ввод в состоянии waiting_for_reference_video.
    """
    await message.answer(
        "⚠️ Пожалуйста, отправьте видео файл (макс 50MB)."
        "Это видео будет использовано как референс для стиля/движения."
    )


@router.callback_query(F.data.startswith("v_mode_"))
async def handle_v_mode(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик режимов видео (720p/1080p)"""
    mode = callback.data.replace("v_mode_", "")
    await state.update_data(v_mode=mode)
    await _show_video_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data.startswith("v_orientation_"))
async def handle_v_orientation(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик ориентации видео (image/video)"""
    orientation = callback.data.replace("v_orientation_", "")
    await state.update_data(v_orientation=orientation)
    await _show_video_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "veo_translation_toggle")
async def handle_veo_translation_toggle(
    callback: types.CallbackQuery, state: FSMContext
):
    """Toggle prompt translation for Veo."""
    data = await state.get_data()
    await state.update_data(veo_translation=not data.get("veo_translation", True))
    await _show_video_creation_screen(callback, state)
    await callback.answer("Настройка перевода обновлена")


@router.callback_query(F.data.startswith("veo_resolution_"))
async def handle_veo_resolution(callback: types.CallbackQuery, state: FSMContext):
    """Set Veo resolution."""
    resolution = callback.data.replace("veo_resolution_", "")
    await state.update_data(veo_resolution=resolution)
    await _show_video_creation_screen(callback, state)
    await callback.answer(f"Качество: {resolution}")


@router.callback_query(F.data.startswith("veo_gen_"))
async def handle_veo_generation_type(callback: types.CallbackQuery, state: FSMContext):
    """Set Veo image generation subtype."""
    generation_type = callback.data.replace("veo_gen_", "")
    data = await state.get_data()
    current_model = data.get("v_model", "veo3_fast")
    if generation_type == "REFERENCE_2_VIDEO" and current_model != "veo3_fast":
        await callback.answer(
            "❌ Изображение слишком маленькое (мин 300px).",
            show_alert=True,
        )
        return
    await state.update_data(
        v_type="imgtxt",
        veo_generation_type=generation_type,
    )
    await _show_video_creation_screen(callback, state)
    await callback.answer("Режим Veo обновлён")


@router.callback_query(F.data == "veo_seed_edit")
async def handle_veo_seed_edit(callback: types.CallbackQuery, state: FSMContext):
    """Prompt user to enter Veo seed."""
    data = await state.get_data()
    current_seed = data.get("veo_seed")
    await callback.message.answer(
        "🎲 Введите seed для Veo (целое число 10000-99999) или `auto`, чтобы сбросить автогенерацию.\n"
        f"Сейчас: <code>{current_seed if current_seed is not None else 'auto'}</code>",
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_veo_seed)
    await callback.answer()


@router.callback_query(F.data == "veo_watermark_edit")
async def handle_veo_watermark_edit(callback: types.CallbackQuery, state: FSMContext):
    """Prompt user to enter Veo watermark."""
    data = await state.get_data()
    current_watermark = data.get("veo_watermark") or "off"
    await callback.message.answer(
        "🏷 Введите метку для Veo или `off`, чтобы убрать её.\n"
        f"Сейчас: <code>{current_watermark}</code>",
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_veo_watermark)
    await callback.answer()


@router.callback_query(F.data == "kling_negative_prompt_edit")
async def handle_kling_negative_prompt_edit(
    callback: types.CallbackQuery, state: FSMContext
):
    """Prompt user to enter Kling 2.5 negative prompt."""
    data = await state.get_data()
    current_negative = data.get("kling_negative_prompt") or "off"
    await callback.message.answer(
        "🚫 Введите negative prompt для Kling 2.5 Turbo или `off`, чтобы отключить.\n"
        "До 500 символов.\n"
        f"Сейчас: <code>{current_negative}</code>",
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_kling_negative_prompt)
    await callback.answer()


@router.callback_query(F.data == "kling_cfg_scale_edit")
async def handle_kling_cfg_scale_edit(callback: types.CallbackQuery, state: FSMContext):
    """Prompt user to enter Kling 2.5 CFG scale."""
    data = await state.get_data()
    current_cfg = float(data.get("kling_cfg_scale", 0.5))
    await callback.message.answer(
        "🎚 Введите CFG scale для Kling 2.5 Turbo от `0.0` до `1.0` с шагом `0.1`.\n"
        f"Сейчас: <code>{current_cfg:.1f}</code>",
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_kling_cfg_scale)
    await callback.answer()


@router.callback_query(F.data.startswith("omni_resolution_"))
async def handle_omni_resolution(callback: types.CallbackQuery, state: FSMContext):
    """Set Gemini Omni Video resolution."""
    resolution = callback.data.replace("omni_resolution_", "")
    if resolution not in {"720p", "1080p", "4k"}:
        await callback.answer()
        return
    await state.update_data(omni_resolution=resolution)
    await _show_video_creation_screen(callback, state)
    await callback.answer(f"Качество: {resolution}")


@router.callback_query(F.data == "omni_seed_edit")
async def handle_omni_seed_edit(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    current_seed = data.get("omni_seed")
    await callback.message.answer(
        "🎲 Введите seed для Gemini Omni (0-2147483647) или `auto`.\n"
        f"Сейчас: <code>{current_seed if current_seed is not None else 'auto'}</code>",
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_omni_seed)
    await callback.answer()


@router.callback_query(F.data == "omni_audio_ids_edit")
async def handle_omni_audio_ids_edit(
    callback: types.CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()
    current_ids = ", ".join(data.get("omni_audio_ids") or []) or "off"
    await callback.message.answer(
        "🎧 Введите Audio ID для Gemini Omni Video или `off`.\n"
        f"Сейчас: <code>{current_ids}</code>",
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_omni_audio_ids)
    await callback.answer()


@router.callback_query(F.data == "omni_character_ids_edit")
async def handle_omni_character_ids_edit(
    callback: types.CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()
    current_ids = ", ".join(data.get("omni_character_ids") or []) or "off"
    await callback.message.answer(
        "🧍 Введите до 3 Character ID через пробел/запятую или `off`.\n"
        f"Сейчас: <code>{current_ids}</code>",
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_omni_character_ids)
    await callback.answer()


@router.callback_query(F.data == "omni_voice_base_edit")
async def handle_omni_voice_base_edit(
    callback: types.CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()
    current_voice = data.get("omni_base_voice", "achernar")
    voices = ", ".join(sorted(gemini_omni_service.BASE_VOICES))
    await callback.message.answer(
        "🎙 Введите базовый голос для Gemini Omni Audio.\n"
        f"Сейчас: <code>{current_voice}</code>\n"
        f"Доступно: <code>{voices}</code>",
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_omni_voice_base)
    await callback.answer()


@router.callback_query(F.data == "omni_voice_name_edit")
async def handle_omni_voice_name_edit(
    callback: types.CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()
    current_name = data.get("omni_voice_name") or "auto"
    await callback.message.answer(
        "🏷 Введите имя голоса до 20 символов или `auto`.\n"
        f"Сейчас: <code>{current_name}</code>",
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_omni_voice_name)
    await callback.answer()


@router.callback_query(F.data == "omni_voice_desc_edit")
async def handle_omni_voice_desc_edit(
    callback: types.CallbackQuery,
    state: FSMContext,
):
    await callback.message.answer(
        "🗣 Введите описание голоса до 2000 символов или `off`.",
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_omni_voice_description)
    await callback.answer()


@router.callback_query(F.data == "omni_voice_dialogue_edit")
async def handle_omni_voice_dialogue_edit(
    callback: types.CallbackQuery,
    state: FSMContext,
):
    await callback.message.answer(
        "💬 Введите пример реплики до 2000 символов или `off`.",
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_omni_example_dialogue)
    await callback.answer()


@router.callback_query(F.data == "omni_character_name_edit")
async def handle_omni_character_name_edit(
    callback: types.CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()
    current_name = data.get("omni_character_name") or "auto"
    await callback.message.answer(
        "🏷 Введите имя персонажа до 20 символов или `auto`.\n"
        f"Сейчас: <code>{current_name}</code>",
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_omni_character_name)
    await callback.answer()


@router.callback_query(F.data == "omni_character_audio_ids_edit")
async def handle_omni_character_audio_ids_edit(
    callback: types.CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()
    current_ids = ", ".join(data.get("omni_character_audio_ids") or []) or "off"
    await callback.message.answer(
        "🎧 Введите Audio ID для Gemini Omni Character или `off`.\n"
        f"Сейчас: <code>{current_ids}</code>",
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_omni_character_audio_ids)
    await callback.answer()


@router.message(GenerationStates.waiting_for_veo_seed, F.text)
async def handle_veo_seed_input(message: types.Message, state: FSMContext):
    """Store Veo seed and return to video creation screen."""
    value = message.text.strip().lower()
    if value in {"auto", "off", "none", "random"}:
        await state.update_data(veo_seed=None)
    else:
        if not value.isdigit():
            await message.answer("❌ Seed должен быть числом 10000-99999 или `auto`.")
            return
        seed = int(value)
        if seed < 10000 or seed > 99999:
            await message.answer("❌ Seed должен быть в диапазоне 10000-99999.")
            return
        await state.update_data(veo_seed=seed)
    await _show_video_creation_screen(message, state)


@router.message(GenerationStates.waiting_for_veo_watermark, F.text)
async def handle_veo_watermark_input(message: types.Message, state: FSMContext):
    """Store Veo watermark and return to video creation screen."""
    value = message.text.strip()
    await state.update_data(
        veo_watermark="" if value.lower() in {"off", "none"} else value[:32]
    )
    await _show_video_creation_screen(message, state)


@router.message(GenerationStates.waiting_for_kling_negative_prompt, F.text)
async def handle_kling_negative_prompt_input(message: types.Message, state: FSMContext):
    """Store Kling 2.5 negative prompt and return to video creation screen."""
    value = message.text.strip()
    if value.lower() in {"off", "none", "disable", "disabled"}:
        await state.update_data(kling_negative_prompt="")
    else:
        await state.update_data(kling_negative_prompt=value[:500])
    await _show_video_creation_screen(message, state)


@router.message(GenerationStates.waiting_for_kling_cfg_scale, F.text)
async def handle_kling_cfg_scale_input(message: types.Message, state: FSMContext):
    """Store Kling 2.5 CFG scale and return to video creation screen."""
    value = message.text.strip().replace(",", ".")
    try:
        cfg_scale = float(value)
    except ValueError:
        await message.answer("❌ CFG scale должен быть числом от 0.0 до 1.0.")
        return

    if cfg_scale < 0 or cfg_scale > 1:
        await message.answer("❌ CFG scale должен быть в диапазоне 0.0-1.0.")
        return

    await state.update_data(kling_cfg_scale=round(cfg_scale, 1))
    await _show_video_creation_screen(message, state)


@router.message(GenerationStates.waiting_for_omni_seed, F.text)
async def handle_omni_seed_input(message: types.Message, state: FSMContext):
    value = message.text.strip().lower()
    if value in {"auto", "off", "none", "random"}:
        await state.update_data(omni_seed=None)
    else:
        if not value.isdigit():
            await message.answer("❌ Seed должен быть числом 0-2147483647 или `auto`.")
            return
        seed = int(value)
        if seed < 0 or seed > 2_147_483_647:
            await message.answer("❌ Seed должен быть в диапазоне 0-2147483647.")
            return
        await state.update_data(omni_seed=seed)
    await _show_video_creation_screen(message, state)


@router.message(GenerationStates.waiting_for_omni_audio_ids, F.text)
async def handle_omni_audio_ids_input(message: types.Message, state: FSMContext):
    ids = _parse_omni_ids(message.text)
    if len(ids) > gemini_omni_service.MAX_AUDIO_IDS:
        await message.answer("❌ Gemini Omni Video принимает один Audio ID.")
        return
    await state.update_data(omni_audio_ids=ids)
    await _show_video_creation_screen(message, state)


@router.message(GenerationStates.waiting_for_omni_character_ids, F.text)
async def handle_omni_character_ids_input(message: types.Message, state: FSMContext):
    ids = _parse_omni_ids(message.text)
    if len(ids) > gemini_omni_service.MAX_CHARACTER_IDS:
        await message.answer("❌ Gemini Omni принимает максимум 3 Character ID.")
        return
    await state.update_data(omni_character_ids=ids)
    await _show_video_creation_screen(message, state)


@router.message(GenerationStates.waiting_for_omni_voice_base, F.text)
async def handle_omni_voice_base_input(message: types.Message, state: FSMContext):
    voice = message.text.strip().lower()
    if voice not in gemini_omni_service.BASE_VOICES:
        await message.answer("❌ Такого базового голоса нет в Gemini Omni.")
        return
    await state.update_data(omni_base_voice=voice)
    await _show_video_creation_screen(message, state)


@router.message(GenerationStates.waiting_for_omni_voice_name, F.text)
async def handle_omni_voice_name_input(message: types.Message, state: FSMContext):
    value = message.text.strip()
    await state.update_data(
        omni_voice_name="" if value.lower() in {"auto", "off", "none"} else value[:20]
    )
    await _show_video_creation_screen(message, state)


@router.message(GenerationStates.waiting_for_omni_voice_description, F.text)
async def handle_omni_voice_description_input(
    message: types.Message,
    state: FSMContext,
):
    value = message.text.strip()
    await state.update_data(
        omni_voice_description=""
        if value.lower() in {"off", "none"}
        else value[:2000]
    )
    await _show_video_creation_screen(message, state)


@router.message(GenerationStates.waiting_for_omni_example_dialogue, F.text)
async def handle_omni_example_dialogue_input(
    message: types.Message,
    state: FSMContext,
):
    value = message.text.strip()
    await state.update_data(
        omni_example_dialogue=""
        if value.lower() in {"off", "none"}
        else value[:2000]
    )
    await _show_video_creation_screen(message, state)


@router.message(GenerationStates.waiting_for_omni_character_name, F.text)
async def handle_omni_character_name_input(message: types.Message, state: FSMContext):
    value = message.text.strip()
    await state.update_data(
        omni_character_name="" if value.lower() in {"auto", "off", "none"} else value[:20]
    )
    await _show_video_creation_screen(message, state)


@router.message(GenerationStates.waiting_for_omni_character_audio_ids, F.text)
async def handle_omni_character_audio_ids_input(
    message: types.Message,
    state: FSMContext,
):
    ids = _parse_omni_ids(message.text)
    if len(ids) > gemini_omni_service.MAX_CHARACTER_AUDIO_IDS:
        await message.answer("❌ Gemini Omni Character принимает один Audio ID.")
        return
    await state.update_data(omni_character_audio_ids=ids)
    await _show_video_creation_screen(message, state)


@router.callback_query(F.data.startswith("veo1080_"))
async def handle_veo_1080p_upgrade(callback: types.CallbackQuery, state: FSMContext):
    """Fetch or request Veo 1080p video."""
    task_id = callback.data.replace("veo1080_", "")
    task = await get_task_by_id(task_id)
    if not task or not (task.model or "").startswith("veo3"):
        await callback.answer("Задача Veo не найдена", show_alert=True)
        return
    provider_task_id = task.task_id

    from bot.services.veo_service import veo_service

    result = await veo_service.get_1080p_video(provider_task_id)
    if not result:
        await callback.answer(
            "Пока не получилось получить версию 1080p. Попробуйте ещё раз чуть позже.",
            show_alert=True,
        )
        return

    if result.get("code") == 200:
        result_url = ((result.get("data") or {}).get("resultUrl")) or ""
        if result_url:
            await callback.message.answer_video(
                video=result_url,
                caption=f"✨ <b>Veo 1080p готово</b>\n🆔 <code>{provider_task_id}</code>",
                parse_mode="HTML",
            )
            await callback.answer("1080p готово")
            return

    await callback.answer(
        result.get("msg", "1080p ещё обрабатывается, попробуйте чуть позже."),
        show_alert=True,
    )


@router.callback_query(F.data.startswith("veo4k_"))
async def handle_veo_4k_upgrade(callback: types.CallbackQuery, state: FSMContext):
    """Fetch or request Veo 4K video."""
    task_id = callback.data.replace("veo4k_", "")
    task = await get_task_by_id(task_id)
    if not task or not (task.model or "").startswith("veo3"):
        await callback.answer("Задача Veo не найдена", show_alert=True)
        return
    provider_task_id = task.task_id

    result = await veo_service.get_4k_video(provider_task_id)
    if not result:
        await callback.answer(
            "Пока не получилось запросить 4K-версию. Попробуйте ещё раз чуть позже.",
            show_alert=True,
        )
        return

    data = result.get("data") or {}
    result_urls = data.get("resultUrls") or []
    if result.get("code") == 200 and result_urls:
        await callback.message.answer_video(
            video=result_urls[0],
            caption=f"🖥 <b>Veo 4K готово</b>\n🆔 <code>{provider_task_id}</code>",
            parse_mode="HTML",
        )
        await callback.answer("4K готово")
        return

    await callback.answer(
        result.get(
            "msg",
            "4K обрабатывается. Нажмите кнопку ещё раз через несколько минут.",
        ),
        show_alert=True,
    )


@router.callback_query(F.data.startswith("veoextend_"))
async def handle_veo_extend_request(callback: types.CallbackQuery, state: FSMContext):
    """Ask for extend prompt for Veo."""
    task_id = callback.data.replace("veoextend_", "")
    task = await get_task_by_id(task_id)
    if not task or not (task.model or "").startswith("veo3"):
        await callback.answer("Задача Veo не найдена", show_alert=True)
        return

    await state.update_data(veo_extend_task_id=task.task_id, veo_extend_model=task.model)
    await state.set_state(GenerationStates.waiting_for_veo_extend_prompt)
    await callback.message.answer(
        "➕ Отправьте промпт для продолжения Veo-видео.\n"
        "Опишите, как должна развиваться сцена дальше."
    )
    await callback.answer()


@router.message(GenerationStates.waiting_for_veo_extend_prompt, F.text)
async def handle_veo_extend_prompt(message: types.Message, state: FSMContext):
    """Start Veo extension task from user prompt."""
    prompt = message.text.strip()
    if not prompt:
        await message.answer("⚠️ Введите промпт для продолжения видео.")
        return

    data = await state.get_data()
    source_task_id = data.get("veo_extend_task_id")
    source_model = data.get("veo_extend_model", "veo3_fast")
    if not source_task_id:
        await message.answer("❌ Не найден исходный task_id Veo.")
        await state.clear()
        return

    extend_model_map = {
        "veo3": "quality",
        "veo3_fast": "fast",
        "veo3_lite": "lite",
    }
    extend_model = extend_model_map.get(source_model, "fast")
    cost_map = {"quality": 22, "fast": 15, "lite": 10}
    cost = cost_map.get(extend_model, 15)

    if not await check_can_afford(message.from_user.id, cost):
        await message.answer(
            f"❌ Недостаточно бананов для продления. Нужно: <code>{cost}</code>🍌",
            parse_mode="HTML",
        )
        return

    await deduct_credits(message.from_user.id, cost)
    await message.answer("🎬 Продлеваю Veo-видео...")

    result = await veo_service.extend_video(
        task_id=source_task_id,
        prompt=prompt,
        model=extend_model,
        callBackUrl=(config.kie_notification_url if config.WEBHOOK_HOST else None),
    )

    if not result or "task_id" not in result:
        await add_credits(message.from_user.id, cost)
        await message.answer(
            "❌ Не получилось запустить продление. Бананы за попытку уже возвращены."
        )
        await state.clear()
        return

    user = await get_or_create_user(message.from_user.id)
    await add_generation_task(
        user.id,
        message.from_user.id,
        result["task_id"],
        "video",
        "veo_extend",
        model=source_model,
        prompt=prompt,
        cost=cost,
    )
    await message.answer(
        f"✅ Продление Veo запущено!\n🆔 <code>{result['task_id']}</code>\n💰 <code>{cost}</code>🍌",
        parse_mode="HTML",
    )
    await state.clear()


@router.callback_query(F.data == "avatar_service")
async def open_avatar_service(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await state.update_data(
        generation_type="video",
        video_flow_step="media",
        v_model="avatar_pro",
        v_type="avatar",
        v_duration=5,
        v_ratio="avatar",
        v_image_url=None,
        avatar_audio_url=None,
        audio_url=None,
    )
    await callback.message.edit_text(
        "🗣 <b>Kling Avatar</b>\n\n"
        "Создаёт говорящий аватар по фото и аудио.\n\n"
        "1. Загрузите фото персонажа\n"
        "2. Загрузите аудио или голосовое\n"
        "3. Отправьте короткую инструкцию",
        reply_markup=get_video_media_step_keyboard(
            current_v_type="avatar",
            current_model="avatar_pro",
            has_start_image=False,
            has_avatar_audio=False,
        ),
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_video_prompt)
    await callback.answer()




@router.callback_query(F.data == "img_quality_1k")
async def set_image_quality_1k(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(img_quality="1K")
    await callback.answer("Выбрано 1K")
    await _show_image_creation_screen(callback, state)

@router.callback_query(F.data == "img_quality_2k")
async def set_image_quality_2k(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(img_quality="2K")
    await callback.answer("Выбрано 2K")
    await _show_image_creation_screen(callback, state)


@router.callback_query(F.data == "img_quality_4k")
async def set_image_quality_4k(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(img_quality="4K")
    await callback.answer("Выбрано 4K")
    await _show_image_creation_screen(callback, state)
