"""Unified prompt analyzer handlers for text, photo, and voice input."""

from __future__ import annotations

import html
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.handlers.image_analyzer import (
    AUDIO_PROMPT_MIME_TYPES,
    _clear_photo_prompt_audio_if_current,
    _download_audio_prompt,
    _load_saved_audio_prompt,
    _photo_prompt_audio_token,
    _safe_edit_or_answer,
    _wait_for_photo_prompt_audio,
)
from bot.keyboards import (
    get_back_keyboard,
    get_main_menu_button_keyboard,
    get_photo_prompt_result_keyboard,
)
from bot.services.photo_prompt_billing import (
    PhotoPromptInsufficientBalance,
    photo_prompt_price_label,
    refund_photo_prompt_charge,
    reserve_photo_prompt_charge,
)
from bot.services.prompt_analyzer_v2_service import prompt_analyzer_v2_service
from bot.states import ImageAnalyzerStates

logger = logging.getLogger(__name__)
router = Router()


def _clip_text(text: str, limit: int) -> str:
    value = str(text or "")
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


def _escape_clip_text(text: str, escaped_limit: int) -> str:
    raw = str(text or "")
    escaped = html.escape(raw)
    if len(escaped) <= escaped_limit:
        return escaped
    suffix = "…"
    low, high, best = 0, len(raw), suffix
    while low <= high:
        mid = (low + high) // 2
        candidate = html.escape(raw[:mid].rstrip() + suffix)
        if len(candidate) <= escaped_limit:
            best = candidate
            low = mid + 1
        else:
            high = mid - 1
    return best


def _format_prompt_result_text(result: dict) -> str:
    prompt_ru = str(result.get("prompt_ru") or "").strip()
    prompt_en = str(result.get("prompt_en") or "").strip()
    source_mode = str(result.get("source_mode") or "").strip()
    titles = {
        "text": "✅ <b>Промпт по описанию готов</b>",
        "voice": "✅ <b>Промпт по голосу готов</b>",
        "photo_voice": "✅ <b>Промпт по фото и голосу готов</b>",
        "photo_text": "✅ <b>Промпт по фото и описанию готов</b>",
    }
    title = titles.get(source_mode, "✅ <b>Промпт по фото готов</b>")
    return (
        f"{title}\n\n"
        "<b>Русская версия:</b>\n"
        f"<pre>{_escape_clip_text(prompt_ru or '—', 1750)}</pre>\n\n"
        "<b>English version:</b>\n"
        f"<pre>{_escape_clip_text(prompt_en or '—', 1750)}</pre>"
    )


async def _send_prompt_result(message: Message, result: dict) -> None:
    prompt_ru = str(result.get("prompt_ru") or "").strip()
    prompt_en = str(result.get("prompt_en") or "").strip()
    await message.answer(
        _format_prompt_result_text(result),
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=get_photo_prompt_result_keyboard(
            prompt_en=prompt_en,
            prompt_ru=prompt_ru,
            negative_prompt="",
        ),
    )

    full_prompt_text = (
        "PROMPT RU\n"
        "---------\n"
        f"{prompt_ru or '—'}\n\n"
        "PROMPT EN\n"
        "---------\n"
        f"{prompt_en or '—'}\n"
    )
    await message.answer_document(
        document=BufferedInputFile(
            full_prompt_text.encode("utf-8"),
            filename="photo_prompt_full.txt",
        ),
        caption="📝 Полный промпт без сокращений: RU + EN",
    )


@router.callback_query(F.data == "photo_to_prompt")
async def prompt_analyzer_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(ImageAnalyzerStates.waiting_for_photo)
    text = (
        "✨ <b>Анализ и создание промпта</b>\n\n"
        f"Стоимость анализа: <b>{photo_prompt_price_label()}</b>\n\n"
        "Отправьте одним сообщением:\n"
        "• текстовое описание или просто свои мысли\n"
        "• фотографию\n"
        "• голосовое сообщение\n"
        "• сначала голос, затем фотографию\n\n"
        "К фото можно добавить подпись — она будет учтена вместе с изображением.\n\n"
        "В результате вы получите две готовые версии и файл с полным текстом:\n"
        "• промпт на русском\n"
        "• prompt на английском\n"
        "• photo_prompt_full.txt без сокращений\n\n"
        "<i>Чем точнее исходная идея или фотография, тем точнее результат.</i>"
    )
    try:
        await callback.message.edit_text(
            text,
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )
    except Exception as exc:
        if not (
            isinstance(exc, TelegramBadRequest)
            and "there is no text in the message to edit" in str(exc).lower()
        ):
            logger.warning("Cannot edit prompt analyzer message: %s", exc)
        await callback.message.answer(
            text,
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(
    ImageAnalyzerStates.waiting_for_photo,
    F.voice | F.audio | (F.document & F.document.mime_type.in_(AUDIO_PROMPT_MIME_TYPES)),
)
async def analyze_voice_prompt_v2(message: Message, state: FSMContext) -> None:
    audio_token = _photo_prompt_audio_token(message)
    await state.update_data(
        photo_prompt_audio=None,
        photo_prompt_audio_consumed_url=None,
        photo_prompt_audio_pending=audio_token,
    )
    processing = await message.answer("🎙 Превращаю голосовую идею в промпт…")
    audio_url = ""
    charge = None
    try:
        audio_bytes, mime_type, audio_format = await _download_audio_prompt(message)
        from bot.handlers.generation import save_uploaded_file

        audio_url = save_uploaded_file(audio_bytes, audio_format)
        if not audio_url:
            raise RuntimeError("Не удалось сохранить голосовое сообщение")
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
        charge = await reserve_photo_prompt_charge(message.from_user.id)
        result = await prompt_analyzer_v2_service.analyze_prompt(
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
        await _send_prompt_result(message, result)
        await message.answer(
            "Можно отправить фотографию следующим сообщением — голосовая идея будет объединена с ней.",
            reply_markup=get_back_keyboard("back_main"),
        )
    except PhotoPromptInsufficientBalance as exc:
        await _clear_photo_prompt_audio_if_current(
            state,
            audio_url=audio_url,
            pending_token=audio_token,
        )
        await _safe_edit_or_answer(
            processing,
            message,
            f"❌ {html.escape(str(exc))}",
            reply_markup=get_main_menu_button_keyboard(),
            parse_mode="HTML",
        )
        await state.clear()
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
    except Exception as exc:
        logger.exception("Unified prompt voice analysis failed")
        await refund_photo_prompt_charge(charge)
        await _clear_photo_prompt_audio_if_current(
            state,
            audio_url=audio_url,
            pending_token=audio_token,
        )
        await _safe_edit_or_answer(
            processing,
            message,
            _clip_text(f"❌ Не удалось разобрать голосовое сообщение: {exc}", 700),
            reply_markup=get_back_keyboard("back_main"),
        )


@router.message(ImageAnalyzerStates.waiting_for_photo, F.photo)
async def analyze_photo_prompt_v2(message: Message, state: FSMContext) -> None:
    processing = await message.answer("🔍 Анализирую фото и собираю промпт…")
    charge = None
    try:
        data = await state.get_data()
        audio_prompt = data.get("photo_prompt_audio")
        if not isinstance(audio_prompt, dict) and data.get("photo_prompt_audio_pending"):
            audio_prompt = await _wait_for_photo_prompt_audio(state)
            if not isinstance(audio_prompt, dict):
                latest_data = await state.get_data()
                latest_audio = latest_data.get("photo_prompt_audio")
                if isinstance(latest_audio, dict):
                    audio_prompt = latest_audio
                elif latest_data.get("photo_prompt_audio_pending"):
                    await _safe_edit_or_answer(
                        processing,
                        message,
                        "🎙 Голосовое сообщение ещё загружается. Отправьте фото повторно через несколько секунд.",
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
                "❌ Не удалось сохранить фото. Попробуйте другое изображение.",
                reply_markup=get_main_menu_button_keyboard(),
            )
            return

        charge = await reserve_photo_prompt_charge(message.from_user.id)
        caption = (message.caption or "").strip()
        result = await prompt_analyzer_v2_service.analyze_prompt(
            text=caption,
            image_url=image_url,
            audio_bytes=audio_bytes,
            audio_format=audio_format,
        )
        if audio_bytes:
            result["source_mode"] = "photo_voice"
        elif caption:
            result["source_mode"] = "photo_text"
        else:
            result["source_mode"] = "photo"

        try:
            await processing.delete()
        except Exception:
            pass
        await _send_prompt_result(message, result)
        await state.clear()
    except PhotoPromptInsufficientBalance as exc:
        await _safe_edit_or_answer(
            processing,
            message,
            f"❌ {html.escape(str(exc))}",
            reply_markup=get_main_menu_button_keyboard(),
            parse_mode="HTML",
        )
        await state.clear()
    except Exception as exc:
        logger.exception("Unified photo prompt analysis failed")
        await refund_photo_prompt_charge(charge)
        await _safe_edit_or_answer(
            processing,
            message,
            _clip_text(f"❌ Не удалось разобрать фото: {exc}", 700),
            reply_markup=get_main_menu_button_keyboard(),
        )
        await state.clear()


@router.message(ImageAnalyzerStates.waiting_for_photo, F.text)
async def analyze_text_prompt_v2(message: Message, state: FSMContext) -> None:
    user_text = (message.text or "").strip()
    if len(user_text) < 3:
        await message.answer(
            "Опишите идею чуть подробнее — хотя бы несколькими словами.",
            reply_markup=get_back_keyboard("back_main"),
        )
        return
    if len(user_text) > 4000:
        await message.answer(
            "Описание слишком длинное. Сократите его до 4000 символов.",
            reply_markup=get_back_keyboard("back_main"),
        )
        return

    processing = await message.answer("✍️ Собираю промпт из вашего описания…")
    charge = None
    try:
        charge = await reserve_photo_prompt_charge(message.from_user.id)
        result = await prompt_analyzer_v2_service.analyze_prompt(text=user_text)
        result["source_mode"] = "text"
        try:
            await processing.delete()
        except Exception:
            pass
        await _send_prompt_result(message, result)
        await state.clear()
    except PhotoPromptInsufficientBalance as exc:
        await _safe_edit_or_answer(
            processing,
            message,
            f"❌ {html.escape(str(exc))}",
            reply_markup=get_main_menu_button_keyboard(),
            parse_mode="HTML",
        )
        await state.clear()
    except Exception as exc:
        logger.exception("Unified text prompt analysis failed")
        await refund_photo_prompt_charge(charge)
        await _safe_edit_or_answer(
            processing,
            message,
            _clip_text(f"❌ Не удалось составить промпт: {exc}", 700),
            reply_markup=get_main_menu_button_keyboard(),
        )
        await state.clear()


@router.message(ImageAnalyzerStates.waiting_for_photo)
async def prompt_analyzer_wrong_input(message: Message) -> None:
    await message.answer(
        "Отправьте текстовое описание, фотографию или голосовое сообщение.",
        reply_markup=get_back_keyboard("back_main"),
    )
