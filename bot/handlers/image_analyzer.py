"""Photo to prompt handler."""

import asyncio
import html
import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.config import config
from bot.keyboards import (
    get_back_keyboard,
    get_main_menu_button_keyboard,
    get_photo_prompt_result_keyboard,
    get_video_prompt_result_keyboard,
)
from bot.services.media_input_utils import resolve_local_upload_path
from bot.services.photo_prompt_billing import (
    PhotoPromptInsufficientBalance,
    photo_prompt_price_label,
    refund_photo_prompt_charge,
    reserve_photo_prompt_charge,
)
from bot.services.photo_prompt_service import photo_prompt_service
from bot.services.preset_manager import preset_manager
from bot.services.video_prompt_service import video_prompt_service
from bot.states import ImageAnalyzerStates

logger = logging.getLogger(__name__)
router = Router()

AUDIO_PROMPT_PENDING_WAIT_SECONDS = 8.0
AUDIO_PROMPT_PENDING_POLL_SECONDS = 0.2

AUDIO_PROMPT_MIME_TYPES = (
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
    "audio/aac",
    "audio/aiff",
    "audio/x-aiff",
    "audio/ogg",
    "audio/oga",
    "audio/flac",
    "audio/x-flac",
)

GPT_AUDIO_PROMPT_FORMATS = {
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/aac": "aac",
    "audio/aiff": "aiff",
    "audio/x-aiff": "aiff",
    "audio/ogg": "ogg",
    "audio/oga": "ogg",
    "audio/flac": "flac",
    "audio/x-flac": "flac",
}

VIDEO_PROMPT_MIME_TYPES = (
    "video/mp4",
    "video/quicktime",
    "video/webm",
    "video/x-m4v",
)

VIDEO_PROMPT_EXTENSIONS = {
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/webm": "webm",
    "video/x-m4v": "m4v",
}


def _video_prompt_cost() -> str:
    value = float(preset_manager.get_video_prompt_cost())
    return f"{value:g}"


def _clip_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _escape_clip_text(text: str, escaped_limit: int) -> str:
    raw = str(text or "")
    escaped = html.escape(raw)
    if len(escaped) <= escaped_limit:
        return escaped

    suffix = "…"
    low = 0
    high = len(raw)
    best = suffix
    while low <= high:
        mid = (low + high) // 2
        candidate = html.escape(raw[:mid].rstrip() + suffix)
        if len(candidate) <= escaped_limit:
            best = candidate
            low = mid + 1
        else:
            high = mid - 1
    return best


def _format_photo_prompt_result_text(result: dict) -> str:
    prompt_en = (result.get("prompt_en") or "").strip()
    prompt_ru = (result.get("prompt_ru") or "").strip()
    negative_prompt = (result.get("negative_prompt") or "").strip()
    provider = (result.get("provider") or "").strip()
    voice_summary = (result.get("voice_prompt_summary_ru") or "").strip()
    voice_description = (result.get("voice_description_ru") or "").strip()
    source_mode = (result.get("source_mode") or "").strip()

    provider_note = ""
    if provider and provider != "gpt-5.5":
        provider_note = f"\n\n<i>Fallback: {html.escape(provider)}</i>"

    has_voice_context = bool(voice_summary or voice_description)
    prompt_ru_limit = 680 if has_voice_context else 1600
    prompt_en_limit = 850 if has_voice_context else 950
    negative_limit = 300 if has_voice_context else 350

    voice_note = ""
    if voice_summary or voice_description:
        voice_lines = []
        if voice_summary:
            voice_lines.append(_escape_clip_text(voice_summary, 360))
        if voice_description:
            voice_lines.append(
                "Голос: " + _escape_clip_text(voice_description, 260)
            )
        voice_note = "\n\n<b>Учтён голосовой промпт:</b>\n" + "\n".join(voice_lines)

    if source_mode == "voice":
        title = "✅ <b>Промпт по голосу готов</b>"
    elif source_mode == "photo_voice":
        title = "✅ <b>Промпт по фото и голосу готов</b>"
    else:
        title = "✅ <b>Промпт по фото готов</b>"

    return (
        f"{title}\n\n"
        "<b>Prompt RU:</b>\n"
        f"<pre>{_escape_clip_text(prompt_ru or '—', prompt_ru_limit)}</pre>\n\n"
        "<b>Prompt EN:</b>\n"
        f"<pre>{_escape_clip_text(prompt_en or '—', prompt_en_limit)}</pre>\n\n"
        "<b>Negative prompt:</b>\n"
        f"<pre>{_escape_clip_text(negative_prompt or '—', negative_limit)}</pre>\n\n"
        f"{voice_note}"
        f"{provider_note}"
    )


def _format_video_prompt_result_text(result: dict) -> str:
    prompt_ru = (result.get("prompt_ru") or "").strip()
    prompt_en = (result.get("prompt_en") or "").strip()
    negative_prompt = (result.get("negative_prompt") or "").strip()
    camera_movement = (result.get("camera_movement_ru") or "").strip()
    visual_style = (result.get("visual_style_ru") or "").strip()
    audio_notes = (result.get("audio_notes_ru") or "").strip()
    provider = (result.get("provider") or "").strip()
    timeline = result.get("timeline_ru") or []

    provider_note = ""
    if provider:
        provider_note = f"\n\n<i>Модель анализа: {html.escape(provider)}</i>"

    timeline_lines = []
    if isinstance(timeline, list):
        timeline_lines = [
            "• " + _escape_clip_text(str(item), 120)
            for item in timeline[:6]
            if str(item or "").strip()
        ]
    timeline_note = ""
    if timeline_lines:
        timeline_note = "\n\n<b>Динамика:</b>\n" + "\n".join(timeline_lines)

    audio_note = ""
    if audio_notes:
        audio_note = (
            "\n\n<b>Звук:</b>\n"
            f"{_escape_clip_text(audio_notes, 220)}"
        )

    return (
        "✅ <b>Промпт по видео готов</b>\n\n"
        "<b>Prompt RU:</b>\n"
        f"<pre>{_escape_clip_text(prompt_ru or '—', 950)}</pre>\n\n"
        "<b>Prompt EN:</b>\n"
        f"<pre>{_escape_clip_text(prompt_en or '—', 680)}</pre>\n\n"
        "<b>Камера:</b>\n"
        f"{_escape_clip_text(camera_movement or '—', 220)}"
        f"{timeline_note}\n\n"
        "<b>Стиль:</b>\n"
        f"{_escape_clip_text(visual_style or '—', 220)}"
        f"{audio_note}\n\n"
        "<b>Negative prompt:</b>\n"
        f"<pre>{_escape_clip_text(negative_prompt or '—', 220)}</pre>"
        f"{provider_note}"
    )


def _audio_prompt_media(message: Message):
    if message.voice:
        return message.voice
    if message.audio:
        return message.audio
    if message.document and message.document.mime_type in AUDIO_PROMPT_MIME_TYPES:
        return message.document
    return None


def _audio_prompt_mime_type(message: Message) -> str:
    if message.voice:
        return "audio/ogg"
    if message.audio:
        return message.audio.mime_type or "audio/mpeg"
    if message.document:
        return message.document.mime_type or "audio/mpeg"
    return "audio/ogg"


def _audio_prompt_format(mime_type: str) -> str:
    value = (mime_type or "").strip().lower()
    return GPT_AUDIO_PROMPT_FORMATS.get(value, "")


def _video_prompt_media(message: Message):
    if message.video:
        return message.video
    if message.document:
        return message.document
    return None


def _video_prompt_mime_type(message: Message) -> str:
    media = _video_prompt_media(message)
    if message.video:
        return getattr(media, "mime_type", None) or "video/mp4"
    if message.document:
        return getattr(media, "mime_type", None) or ""
    return ""


def _video_prompt_file_ext(message: Message) -> str:
    mime_type = _video_prompt_mime_type(message).lower()
    if mime_type in VIDEO_PROMPT_EXTENSIONS:
        return VIDEO_PROMPT_EXTENSIONS[mime_type]

    filename = str(getattr(_video_prompt_media(message), "file_name", "") or "")
    suffix = Path(filename).suffix.lower().lstrip(".")
    if suffix in {"mp4", "mov", "webm", "m4v"}:
        return suffix
    return "mp4"


def _video_prompt_filename(message: Message) -> str:
    media = _video_prompt_media(message)
    filename = str(getattr(media, "file_name", "") or "").strip()
    if filename:
        return filename
    return f"reference_video.{_video_prompt_file_ext(message)}"


def _is_video_prompt_document(message: Message) -> bool:
    if not message.document:
        return False
    mime_type = _video_prompt_mime_type(message).lower()
    if mime_type.startswith("video/"):
        return True
    filename = str(getattr(message.document, "file_name", "") or "").lower()
    return Path(filename).suffix.lower() in {".mp4", ".mov", ".webm", ".m4v"}


async def _download_audio_prompt(message: Message) -> tuple[bytes, str, str]:
    media = _audio_prompt_media(message)
    if not media:
        raise ValueError("audio prompt media is required")

    file_size = getattr(media, "file_size", 0) or 0
    if file_size and file_size > config.PHOTO_PROMPT_MAX_AUDIO_BYTES:
        raise ValueError("audio prompt is too large")

    file = await message.bot.get_file(media.file_id)
    audio_io = await message.bot.download_file(file.file_path)
    audio_bytes = audio_io.read()
    if len(audio_bytes) > config.PHOTO_PROMPT_MAX_AUDIO_BYTES:
        raise ValueError("audio prompt is too large")

    mime_type = _audio_prompt_mime_type(message)
    audio_format = _audio_prompt_format(mime_type)
    if not audio_format:
        raise ValueError("audio prompt mime type is not supported")

    return audio_bytes, mime_type, audio_format


def _load_saved_audio_prompt(audio_prompt: dict | None) -> tuple[bytes | None, str]:
    if not isinstance(audio_prompt, dict):
        return None, ""

    audio_url = str(audio_prompt.get("url") or "").strip()
    audio_format = str(audio_prompt.get("format") or "").strip()
    if not audio_url or not audio_format:
        return None, ""

    local_path = resolve_local_upload_path(audio_url)
    if not local_path:
        raise RuntimeError("Не удалось найти сохранённый голосовой промпт")

    with open(local_path, "rb") as audio_file:
        return audio_file.read(), audio_format


def _photo_prompt_audio_token(message: Message) -> str:
    return str(getattr(message, "message_id", "") or id(message))


async def _wait_for_photo_prompt_audio(state: FSMContext) -> dict | None:
    attempts = int(AUDIO_PROMPT_PENDING_WAIT_SECONDS / AUDIO_PROMPT_PENDING_POLL_SECONDS)
    for _ in range(attempts):
        data = await state.get_data()
        audio_prompt = data.get("photo_prompt_audio")
        if isinstance(audio_prompt, dict):
            return audio_prompt
        if not data.get("photo_prompt_audio_pending"):
            return None
        await asyncio.sleep(AUDIO_PROMPT_PENDING_POLL_SECONDS)

    data = await state.get_data()
    audio_prompt = data.get("photo_prompt_audio")
    return audio_prompt if isinstance(audio_prompt, dict) else None


async def _clear_photo_prompt_audio_if_current(
    state: FSMContext,
    *,
    audio_url: str = "",
    pending_token: str = "",
) -> None:
    data = await state.get_data()
    updates = {}

    if pending_token and data.get("photo_prompt_audio_pending") == pending_token:
        updates["photo_prompt_audio_pending"] = None

    current_audio = data.get("photo_prompt_audio")
    consumed_url = str(data.get("photo_prompt_audio_consumed_url") or "")
    if (
        audio_url
        and isinstance(current_audio, dict)
        and current_audio.get("url") == audio_url
        and consumed_url != audio_url
    ):
        updates["photo_prompt_audio"] = None
        updates["photo_prompt_audio_consumed_url"] = None

    if updates:
        await state.update_data(**updates)


async def _safe_edit_or_answer(
    processing: Message,
    source_message: Message,
    text: str,
    reply_markup=None,
    parse_mode=None,
    disable_web_page_preview=None,
) -> None:
    try:
        await processing.edit_text(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
        )
    except TelegramBadRequest as e:
        error_text = str(e).lower()
        if "message to edit not found" in error_text or "there is no text in the message to edit" in error_text:
            await source_message.answer(
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
            )
            return
        raise


async def _send_photo_prompt_result(
    message: Message,
    result: dict,
    *,
    filename: str = "photo_prompt_full.txt",
    document_caption: str = "📝 Полный prompt: RU + EN + negative",
) -> None:
    prompt_en = (result.get("prompt_en") or "").strip()
    prompt_ru = (result.get("prompt_ru") or "").strip()
    negative_prompt = (result.get("negative_prompt") or "").strip()
    text = _format_photo_prompt_result_text(result)

    await message.answer(
        text,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=get_photo_prompt_result_keyboard(
            prompt_en=prompt_en,
            prompt_ru=prompt_ru,
            negative_prompt=negative_prompt,
        ),
    )

    full_prompt_text = (
        "VOICE PROMPT\n"
        "------------\n"
        f"{result.get('voice_transcript') or '—'}\n\n"
        "VOICE SUMMARY\n"
        "-------------\n"
        f"{result.get('voice_prompt_summary_ru') or '—'}\n\n"
        "VOICE DESCRIPTION\n"
        "-----------------\n"
        f"{result.get('voice_description_ru') or '—'}\n\n"
        "PROMPT RU\n"
        "---------\n"
        f"{prompt_ru or '—'}\n\n"
        "PROMPT EN\n"
        "---------\n"
        f"{prompt_en or '—'}\n\n"
        "NEGATIVE PROMPT\n"
        "---------------\n"
        f"{negative_prompt or '—'}\n"
    )
    await message.answer_document(
        document=BufferedInputFile(
            full_prompt_text.encode("utf-8"),
            filename=filename,
        ),
        caption=document_caption,
    )


async def _send_video_prompt_result(
    message: Message,
    result: dict,
    *,
    filename: str = "video_prompt_full.txt",
    document_caption: str = "📝 Полный video prompt: RU + EN + motion notes",
) -> None:
    prompt_en = (result.get("prompt_en") or "").strip()
    prompt_ru = (result.get("prompt_ru") or "").strip()
    negative_prompt = (result.get("negative_prompt") or "").strip()
    timeline = result.get("timeline_ru") or []
    timeline_text = "\n".join(f"- {item}" for item in timeline) if timeline else "—"
    text = _format_video_prompt_result_text(result)

    await message.answer(
        text,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=get_video_prompt_result_keyboard(),
    )

    full_prompt_text = (
        "PROMPT RU\n"
        "---------\n"
        f"{prompt_ru or '—'}\n\n"
        "PROMPT EN\n"
        "---------\n"
        f"{prompt_en or '—'}\n\n"
        "CAMERA / FRAMING\n"
        "----------------\n"
        f"{result.get('camera_movement_ru') or '—'}\n\n"
        "TIMELINE\n"
        "--------\n"
        f"{timeline_text}\n\n"
        "STYLE / LIGHT / COLOR\n"
        "---------------------\n"
        f"{result.get('visual_style_ru') or '—'}\n\n"
        "AUDIO NOTES\n"
        "-----------\n"
        f"{result.get('audio_notes_ru') or '—'}\n\n"
        "NEGATIVE PROMPT\n"
        "---------------\n"
        f"{negative_prompt or '—'}\n\n"
        "KEY DETAILS\n"
        "-----------\n"
        f"{chr(10).join('- ' + str(item) for item in (result.get('key_details') or [])) or '—'}\n"
    )
    await message.answer_document(
        document=BufferedInputFile(
            full_prompt_text.encode("utf-8"),
            filename=filename,
        ),
        caption=document_caption,
    )


@router.callback_query(F.data == "photo_to_prompt")
async def photo_to_prompt_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(ImageAnalyzerStates.waiting_for_photo)

    text = (
        "📸 <b>Промпт по фото</b>\n\n"
        f"Стоимость анализа фото: <b>{photo_prompt_price_label()}</b>\n\n"
        "Отправьте фото, голосовой промпт или сначала голос, а затем фото.\n"
        "GPT-5.5 разберёт фото отдельно, голос отдельно или объединит голос с последующим фото.\n\n"
        "В результате вы получите:\n"
        "• точный prompt на английском\n"
        "• понятную версию на русском\n"
        "• negative prompt\n"
        "• учёт голосового промпта, если он был отправлен\n\n"
        "<i>Лучше загружать чёткое фото без сильного блюра.</i>"
    )

    try:
        await callback.message.edit_text(
            text,
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )
    except Exception as e:
        if not (isinstance(e, TelegramBadRequest) and "there is no text in the message to edit" in str(e).lower()):
            logger.warning("Cannot edit message in photo_to_prompt_handler: %s", e)
        await callback.message.answer(
            text,
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )

    await callback.answer()


@router.callback_query(F.data == "video_to_prompt")
async def video_to_prompt_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(ImageAnalyzerStates.waiting_for_video_prompt)

    max_mb = max(1, config.VIDEO_PROMPT_MAX_VIDEO_BYTES // (1024 * 1024))
    max_seconds = config.VIDEO_PROMPT_MAX_DURATION_SECONDS
    text = (
        "🎞 <b>Промпт по видео</b>\n\n"
        f"Стоимость: <code>{_video_prompt_cost()}</code> 🍌\n\n"
        "Отправьте короткое видео как обычное видео или файлом.\n"
        "GPT-5.5 получит сам видеофайл и соберёт подробный prompt для генерации похожего ролика.\n\n"
        "В результате вы получите:\n"
        "• подробный prompt на русском\n"
        "• английскую версию для video-моделей\n"
        "• описание камеры и динамики\n"
        "• negative prompt\n\n"
        f"<i>Тестовый лимит: до {max_mb}MB и до {max_seconds} секунд.</i>"
    )

    try:
        await callback.message.edit_text(
            text,
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )
    except Exception as e:
        if not (isinstance(e, TelegramBadRequest) and "there is no text in the message to edit" in str(e).lower()):
            logger.warning("Cannot edit message in video_to_prompt_handler: %s", e)
        await callback.message.answer(
            text,
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )

    await callback.answer()


@router.message(
    ImageAnalyzerStates.waiting_for_photo,
    F.voice
    | F.audio
    | (F.document & F.document.mime_type.in_(AUDIO_PROMPT_MIME_TYPES)),
)
async def analyze_voice_prompt(message: Message, state: FSMContext):
    audio_token = _photo_prompt_audio_token(message)
    await state.update_data(
        photo_prompt_audio=None,
        photo_prompt_audio_consumed_url=None,
        photo_prompt_audio_pending=audio_token,
    )
    processing = await message.answer("🎙 Анализирую голосовой промпт через GPT-5.5…")
    audio_url = ""

    try:
        audio_bytes, mime_type, audio_format = await _download_audio_prompt(message)
        from bot.handlers.generation import save_uploaded_file

        audio_url = save_uploaded_file(audio_bytes, audio_format)
        if not audio_url:
            raise RuntimeError("Не удалось сохранить голосовой промпт")

        await state.update_data(
            photo_prompt_audio={
                "url": audio_url,
                "mime_type": mime_type,
                "format": audio_format,
                "token": audio_token,
            },
            photo_prompt_audio_pending=None,
            photo_prompt_audio_consumed_url=None,
        )

        result = await photo_prompt_service.analyze_photo(
            image_url="",
            preserve=(
                "смысл голосового запроса, стиль, настроение, действие, камеру, "
                "сеттинг и ограничения пользователя"
            ),
            goal="создать качественный prompt по голосовому описанию",
            audio_bytes=audio_bytes,
            audio_format=audio_format,
        )
        result["source_mode"] = "voice"

        current_data = await state.get_data()
        current_audio = current_data.get("photo_prompt_audio")
        consumed_url = str(current_data.get("photo_prompt_audio_consumed_url") or "")
        if not (
            isinstance(current_audio, dict)
            and current_audio.get("url") == audio_url
            and consumed_url != audio_url
        ):
            try:
                await processing.delete()
            except Exception:
                pass
            return

        try:
            await processing.delete()
        except Exception:
            pass

        await _send_photo_prompt_result(
            message,
            result,
            filename="voice_prompt_full.txt",
            document_caption="📝 Полный prompt по голосу: RU + EN + negative",
        )
        await message.answer(
            "Можно отправить фото следующим сообщением — тогда GPT-5.5 объединит его с этим голосовым промптом.",
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )
    except ValueError:
        await _clear_photo_prompt_audio_if_current(
            state,
            audio_url=audio_url,
            pending_token=audio_token,
        )
        await _safe_edit_or_answer(
            processing,
            message,
            "❌ Голосовой файл слишком большой или не поддерживается. Максимум 10MB.",
            reply_markup=get_back_keyboard("back_main"),
        )
    except Exception as e:
        logger.exception("Photo prompt voice analysis failed")
        await _clear_photo_prompt_audio_if_current(
            state,
            audio_url=audio_url,
            pending_token=audio_token,
        )
        await _safe_edit_or_answer(
            processing,
            message,
            _clip_text(
                f"❌ Не удалось разобрать голосовой промпт: {e}",
                700,
            ),
            reply_markup=get_back_keyboard("back_main"),
        )


@router.message(ImageAnalyzerStates.waiting_for_photo, F.photo)
async def analyze_photo(message: Message, state: FSMContext):
    processing = await message.answer("🔍 Анализирую фото и собираю точный prompt…")
    charge = None

    try:
        data = await state.get_data()
        audio_prompt = data.get("photo_prompt_audio")
        if not isinstance(audio_prompt, dict) and data.get("photo_prompt_audio_pending"):
            audio_prompt = await _wait_for_photo_prompt_audio(state)
            if not isinstance(audio_prompt, dict):
                latest_data = await state.get_data()
                latest_audio_prompt = latest_data.get("photo_prompt_audio")
                if isinstance(latest_audio_prompt, dict):
                    audio_prompt = latest_audio_prompt
                elif latest_data.get("photo_prompt_audio_pending"):
                    await _safe_edit_or_answer(
                        processing,
                        message,
                        "🎙 Голосовой промпт ещё загружается. Отправьте фото ещё раз через несколько секунд — я объединю его с голосом.",
                        reply_markup=get_back_keyboard("back_main"),
                        parse_mode="HTML",
                    )
                    return

        audio_url = ""
        if isinstance(audio_prompt, dict):
            audio_url = str(audio_prompt.get("url") or "")
            if audio_url:
                await state.update_data(photo_prompt_audio_consumed_url=audio_url)

        audio_bytes, audio_format = _load_saved_audio_prompt(audio_prompt)
        user_note = (message.caption or "").strip()
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        image_io = await message.bot.download_file(file.file_path)

        image_bytes = image_io.read()
        from bot.handlers.generation import save_uploaded_file

        image_url = save_uploaded_file(image_bytes, "jpg")

        if not image_url:
            await _safe_edit_or_answer(
                processing,
                message,
                "❌ Не удалось сохранить фото. Попробуйте загрузить другое изображение.",
                reply_markup=get_main_menu_button_keyboard(),
            )
            return

        charge = await reserve_photo_prompt_charge(message.from_user.id)

        result = await photo_prompt_service.analyze_photo(
            image_url=image_url,
            preserve="внешность/объект, композицию, свет, одежду, фон, стиль и цветовую палитру",
            goal="создать максимально похожее изображение по этому референсу",
            user_note=user_note,
            audio_bytes=audio_bytes,
            audio_format=audio_format,
        )
        result["source_mode"] = "photo_voice" if audio_bytes else "photo"

        try:
            await processing.delete()
        except Exception:
            pass

        await _send_photo_prompt_result(message, result)
        await state.clear()

    except PhotoPromptInsufficientBalance as e:
        await _safe_edit_or_answer(
            processing,
            message,
            f"❌ {html.escape(str(e))}",
            reply_markup=get_main_menu_button_keyboard(),
            parse_mode="HTML",
        )
        await state.clear()
    except Exception as e:
        logger.exception("Photo to prompt analysis failed")
        await refund_photo_prompt_charge(charge)
        await _safe_edit_or_answer(
            processing,
            message,
            _clip_text(f"❌ Не удалось разобрать фото: {e}", 700),
            reply_markup=get_main_menu_button_keyboard(),
        )
        await state.clear()


@router.message(
    ImageAnalyzerStates.waiting_for_video_prompt,
    F.video | F.document,
)
async def analyze_video_prompt(message: Message, state: FSMContext):
    if not (message.video or _is_video_prompt_document(message)):
        await message.answer(
            "Пожалуйста, отправьте видео в формате mp4, mov, webm или m4v.",
            reply_markup=get_back_keyboard("back_main"),
        )
        return

    media = _video_prompt_media(message)
    file_size = getattr(media, "file_size", 0) or 0
    max_bytes = config.VIDEO_PROMPT_MAX_VIDEO_BYTES
    if file_size and file_size > max_bytes:
        max_mb = max(1, max_bytes // (1024 * 1024))
        await message.answer(
            f"❌ Видео слишком большое. Тестовый лимит: до {max_mb}MB.",
            reply_markup=get_back_keyboard("back_main"),
        )
        return

    duration = int(getattr(media, "duration", 0) or 0)
    max_seconds = config.VIDEO_PROMPT_MAX_DURATION_SECONDS
    if duration and duration > max_seconds:
        await message.answer(
            f"❌ Видео слишком длинное. Тестовый лимит: до {max_seconds} секунд.",
            reply_markup=get_back_keyboard("back_main"),
        )
        return

    processing = await message.answer("🎞 Анализирую видео и собираю prompt…")

    try:
        file = await message.bot.get_file(media.file_id)
        video_io = await message.bot.download_file(file.file_path)
        video_bytes = video_io.read()
        if len(video_bytes) > max_bytes:
            max_mb = max(1, max_bytes // (1024 * 1024))
            await _safe_edit_or_answer(
                processing,
                message,
                f"❌ Видео слишком большое. Тестовый лимит: до {max_mb}MB.",
                reply_markup=get_back_keyboard("back_main"),
            )
            return

        from bot.handlers.generation import save_uploaded_file

        file_ext = _video_prompt_file_ext(message)
        video_url = save_uploaded_file(video_bytes, file_ext)
        if not video_url:
            await _safe_edit_or_answer(
                processing,
                message,
                "❌ Не удалось сохранить видео. Попробуйте другой файл.",
                reply_markup=get_main_menu_button_keyboard(),
            )
            return

        result = await video_prompt_service.analyze_video(
            video_url=video_url,
            user_note=(message.caption or "").strip(),
            duration_seconds=duration,
            filename=_video_prompt_filename(message),
            video_bytes=video_bytes,
        )

        try:
            await processing.delete()
        except Exception:
            pass

        await _send_video_prompt_result(message, result)
        await state.clear()

    except Exception as e:
        logger.exception("Video to prompt analysis failed")
        await _safe_edit_or_answer(
            processing,
            message,
            _clip_text(f"❌ Не удалось разобрать видео: {e}", 700),
            reply_markup=get_main_menu_button_keyboard(),
        )
        await state.clear()


@router.message(ImageAnalyzerStates.waiting_for_video_prompt)
async def video_prompt_wrong_input(message: Message):
    await message.answer(
        "Пожалуйста, отправьте короткое видео или видеофайл mp4/mov/webm/m4v.",
        reply_markup=get_back_keyboard("back_main"),
    )


@router.message(ImageAnalyzerStates.waiting_for_photo)
async def photo_prompt_wrong_input(message: Message):
    await message.answer(
        "Пожалуйста, отправьте фото или голосовой промпт. Можно отправлять их отдельно или сначала голос, затем фото.",
        reply_markup=get_back_keyboard("back_main"),
    )

# ─── VK-style simple photo to prompt (analogous to VK bot) ─────────

@router.callback_query(F.data == "photo_to_prompt_vk")
async def photo_to_prompt_vk_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(ImageAnalyzerStates.waiting_for_photo_vk)

    text = (
        "📸 Фото→Промпт (бесплатно)\n\n"
        "Отправьте одно фото, и я превращу его в подробный промпт для генерации.\n\n"
        "Это удобно, если нужно повторить стиль, композицию, образ, свет или предмет с картинки. "
        "После анализа можно использовать текст в «Создать фото» или «Создать видео»."
    )

    try:
        await callback.message.edit_text(
            text,
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )
    except TelegramBadRequest as e:
        if "there is no text in the message to edit" not in str(e).lower():
            logger.warning("Cannot edit message in photo_to_prompt_vk_handler: %s", e)
        await callback.message.answer(
            text,
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )

    await callback.answer()


async def _vk_analyze_photo(photo_url: str) -> str:
    """Analyze photo via APIYI - same as VK bot."""
    models = [config.APIYI_VISION_MODEL]
    models.extend(m for m in config.APIYI_VISION_FALLBACK_MODELS if m not in models)

    headers = {
        "Authorization": f"Bearer {config.KIE_AI_API_KEY}",
        "Content-Type": "application/json",
    }

    last_error = None
    for model in models:
        try:
            data = {
                "model": model,
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": (
                                    "Составь подробное описание изображения для генерации похожего в Banana Pro. "
                                    "Сохрани все мелкие детали, лицо, одежду, позу, освещение, стиль, цвета. "
                                    "На русском языке."
                                ),
                            },
                            {"type": "input_image", "image_url": photo_url},
                        ],
                    }
                ],
                "instructions": (
                    "Ты эксперт по промптам для генерации изображений. "
                    "Отвечай только готовым промптом без вводных фраз."
                ),
                "max_output_tokens": 1200,
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{config.APIYI_BASE_URL}/responses",
                    headers=headers,
                    json=data,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    text_result = await resp.text()

                    if resp.status != 200:
                        logger.warning(
                            "APIYI %s HTTP %s: %s", model, resp.status, text_result[:500]
                        )
                        last_error = ValueError(f"APIYI {resp.status}")
                        continue

                    try:
                        result = json.loads(text_result)
                    except json.JSONDecodeError as e:
                        logger.warning("APIYI JSON error: %s body=%s", e, text_result[:500])
                        last_error = ValueError(f"JSON error: {e}")
                        continue

                    # Try choices format
                    if result.get("choices") and result["choices"]:
                        msg = result["choices"][0].get("message", {})
                        content_text = msg.get("content")
                        if content_text:
                            return content_text.strip()

                    # Try output_text format
                    if result.get("output_text"):
                        return str(result["output_text"]).strip()

                    # Try responses format (output array)
                    output_parts = []
                    for item in result.get("output", []) or []:
                        if isinstance(item, dict) and item.get("type") == "message":
                            for c in item.get("content", []) or []:
                                if isinstance(c, dict) and c.get("type") == "output_text":
                                    text_val = c.get("text", "")
                                    if text_val:
                                        output_parts.append(str(text_val))
                    if output_parts:
                        return "\n".join(output_parts).strip()

                    logger.warning("APIYI unexpected response: %s", result)
                    last_error = ValueError("Unexpected API response")
                    continue

        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.warning("APIYI network error with %s: %s", model, e)
            last_error = e
            continue
        except Exception as e:
            logger.exception("APIYI unexpected error with %s: %s", model, e)
            last_error = e
            continue

    raise ValueError(f"APIYI photo analysis failed for all models: {last_error}")


@router.message(ImageAnalyzerStates.waiting_for_photo_vk, F.photo)
async def photo_to_prompt_vk_photo_handler(message: Message, state: FSMContext):
    processing = await message.answer("🔍 Анализирую фото и готовлю промпт…")

    try:
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        image_io = await message.bot.download_file(file.file_path)
        image_bytes = image_io.read()

        from bot.handlers.generation import save_uploaded_file
        photo_url = save_uploaded_file(image_bytes, "jpg")

        if not photo_url:
            await processing.edit_text(
                "❌ Не удалось сохранить фото. Попробуйте другое изображение.",
                reply_markup=get_main_menu_button_keyboard(),
            )
            await state.clear()
            return

        prompt = await _vk_analyze_photo(photo_url)

        try:
            await processing.delete()
        except Exception:
            pass

        await message.answer(
            f"✅ Готовый промпт:\n\n<code>{html.escape(prompt)}</code>\n\n"
            "Как использовать: скопируйте текст и вставьте его в «Создать фото» или «Создать видео». "
            "При необходимости добавьте свои правки: формат, настроение, цвет, действие.",
            reply_markup=get_main_menu_button_keyboard(),
            parse_mode="HTML",
        )
        await state.clear()

    except ValueError as e:
        await processing.edit_text(
            f"⚠️ Не удалось разобрать фото через APIYI.\n\n"
            f"{html.escape(str(e))}\n\n"
            "Попробуйте ещё раз. Если ошибка повторится, можно использовать «📸 Промпт по фото» (GPT-5.5).",
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )
        await state.clear()
    except Exception as e:
        logger.exception("VK-style photo analysis failed")
        await processing.edit_text(
            f"❌ Ошибка: {html.escape(str(e)[:500])}",
            reply_markup=get_main_menu_button_keyboard(),
        )
        await state.clear()


@router.message(ImageAnalyzerStates.waiting_for_photo_vk)
async def photo_to_prompt_vk_wrong_input(message: Message):
    await message.answer(
        "❌ Нужна фотография. Прикрепите изображение к сообщению.",
        reply_markup=get_back_keyboard("back_main"),
    )
