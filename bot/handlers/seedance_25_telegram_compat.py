"""Public Telegram UX and reliable first-frame upload for Seedance 2.5."""

from __future__ import annotations

import io
import json

from aiogram import F, Router, types
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from PIL import Image, UnidentifiedImageError

from . import generation as generation_module
from . import seedance_25_preview as preview_module

router = Router(name="seedance_25_telegram_compat")
MODEL_KEY = "seedance_2_5"
_REPEAT_SCENARIOS = {"text", "first_frame", "first_last", "multimodal"}


def _selected(active: bool, label: str) -> str:
    return f"✅ {label}" if active else label


def _clear_seedance_keyboard(data: dict):
    """Keep every capability while making the primary flow understandable."""
    builder = InlineKeyboardBuilder()
    scenario = str(data.get("seedance25_scenario") or "text")
    resolution = str(data.get("seedance25_resolution") or "720p")
    ratio = str(data.get("v_ratio") or "adaptive")
    duration = int(data.get("v_duration", 5))

    # What the user wants to create — human labels instead of API terminology.
    builder.button(
        text=_selected(scenario == "text", "✨ С нуля"),
        callback_data="s25_scenario_text",
    )
    builder.button(
        text=_selected(scenario == "first_frame", "🖼 Оживить фото"),
        callback_data="s25_scenario_first_frame",
    )
    builder.button(
        text=_selected(scenario == "first_last", "🎞 Между 2 фото"),
        callback_data="s25_scenario_first_last",
    )
    builder.button(
        text=_selected(scenario == "multimodal", "🧩 По референсам"),
        callback_data="s25_scenario_multimodal",
    )

    builder.button(
        text=_selected(resolution == "480p", "🖥 480p"),
        callback_data="s25_resolution_480p",
    )
    builder.button(
        text=_selected(resolution == "720p", "🖥 720p"),
        callback_data="s25_resolution_720p",
    )

    builder.button(text="➖", callback_data="s25_duration_minus")
    builder.button(
        text=f"⏱ {'Авто' if duration == -1 else f'{duration} сек'}",
        callback_data="ignore",
    )
    builder.button(text="➕", callback_data="s25_duration_plus")
    builder.button(
        text=_selected(duration == -1, "🤖 Auto"),
        callback_data="s25_duration_auto",
    )

    for value, label in (
        ("adaptive", "📐 Авто"),
        ("16:9", "16:9"),
        ("9:16", "9:16"),
        ("1:1", "1:1"),
        ("4:3", "4:3"),
        ("3:4", "3:4"),
        ("21:9", "21:9"),
    ):
        builder.button(
            text=_selected(ratio == value, label),
            callback_data=f"s25_ratio_{value.replace(':', '_')}",
        )

    builder.button(
        text=f"🔊 Звук: {'ВКЛ' if data.get('seedance25_generate_audio', True) else 'ВЫКЛ'}",
        callback_data="s25_toggle_audio",
    )
    builder.button(
        text=f"🖼 Финальный кадр: {'ДА' if data.get('seedance25_return_last_frame') else 'НЕТ'}",
        callback_data="s25_toggle_return_last",
    )
    builder.button(
        text=f"📦 {str(data.get('seedance25_output_format') or 'mp4').upper()}",
        callback_data="s25_toggle_output",
    )
    builder.button(
        text=f"🌐 Web: {'ВКЛ' if data.get('seedance25_web_search') else 'ВЫКЛ'}",
        callback_data="s25_toggle_search",
    )
    builder.button(
        text=f"🛡 Фильтр: {'ВКЛ' if data.get('seedance25_nsfw_checker') else 'ВЫКЛ'}",
        callback_data="s25_toggle_nsfw",
    )
    builder.button(text="🧹 Очистить референсы", callback_data="s25_clear_media")
    builder.button(text="🤖 Другие модели", callback_data="video_change_model")
    builder.button(text="🏠 Главное меню", callback_data="back_main")

    builder.adjust(
        2,  # creation scenario
        2,
        2,  # resolution
        4,  # duration
        3,  # ratios
        4,
        2,  # common switches
        3,  # advanced switches
        1,  # clear
        2,  # navigation
    )
    return builder.as_markup()


async def _persist_image(message: types.Message, obj) -> str | None:
    mime = str(getattr(obj, "mime_type", "") or "image/jpeg").lower()
    ext = preview_module.IMAGE_MIME_TYPES.get(mime)
    if not ext:
        await message.answer("❌ Нужен JPEG, PNG, WEBP, BMP, TIFF или GIF.")
        return None
    if int(getattr(obj, "file_size", 0) or 0) > preview_module.MAX_IMAGE_BYTES:
        await message.answer("❌ Фото должно быть меньше 30 MB.")
        return None

    raw = await preview_module._download_media(message, obj)
    try:
        with Image.open(io.BytesIO(raw)) as image:
            width, height = image.size
    except (OSError, UnidentifiedImageError):
        await message.answer("❌ Не удалось прочитать фото. Попробуйте другое.")
        return None

    if not preview_module._valid_dimensions(width, height):
        await message.answer(
            "❌ Для Seedance фото должно быть 300–6000 px по стороне, ratio 0.4–2.5."
        )
        return None

    return await generation_module._persist_reusable_media_reference(
        message.from_user.id,
        raw,
        ext,
        kind="image",
        original_filename=f"seedance25_{obj.file_id}.{ext}",
        content_type=mime,
    )


def _repeat_urls(value, limit: int) -> list[str]:
    values = [value] if isinstance(value, str) else list(value or [])
    result: list[str] = []
    for raw in values:
        url = str(raw or "").strip()
        if url and url not in result:
            result.append(url)
        if len(result) >= limit:
            break
    return result


def _repeat_request_data(raw) -> dict:
    if isinstance(raw, dict):
        return dict(raw)
    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("request_data is not an object")
    return parsed


def _repeat_scenario(request_data: dict) -> str:
    scenario = str(
        request_data.get("seedance25_scenario")
        or request_data.get("scenario")
        or ""
    ).strip().lower()
    if scenario in _REPEAT_SCENARIOS:
        return scenario

    first = request_data.get("first_frame_url") or request_data.get("seedance25_first_frame_url")
    last = request_data.get("last_frame_url") or request_data.get("seedance25_last_frame_url")
    images = request_data.get("reference_images") or request_data.get("reference_image_urls")
    videos = (
        request_data.get("v_reference_videos")
        or request_data.get("reference_videos")
        or request_data.get("reference_video_urls")
    )
    audios = request_data.get("reference_audios") or request_data.get("seedance25_reference_audio_urls")
    if first and last:
        return "first_last"
    if first:
        return "first_frame"
    if images or videos or audios:
        return "multimodal"
    return "text"


def _repeat_state_payload(task, request_data: dict, prompt: str) -> dict:
    """Restore the exact Seedance 2.5 scenario instead of falling back to T2V."""
    scenario = _repeat_scenario(request_data)
    first_frame = (
        request_data.get("first_frame_url")
        or request_data.get("seedance25_first_frame_url")
        or (request_data.get("v_image_url") if scenario in {"first_frame", "first_last"} else None)
    )
    last_frame = request_data.get("last_frame_url") or request_data.get("seedance25_last_frame_url")
    image_refs = _repeat_urls(
        request_data.get("reference_images")
        or request_data.get("reference_image_urls")
        or [],
        30,
    )
    video_refs = _repeat_urls(
        request_data.get("v_reference_videos")
        or request_data.get("reference_videos")
        or request_data.get("reference_video_urls")
        or [],
        10,
    )
    audio_refs = _repeat_urls(
        request_data.get("reference_audios")
        or request_data.get("seedance25_reference_audio_urls")
        or request_data.get("reference_audio_urls")
        or [],
        10,
    )

    if scenario != "multimodal":
        image_refs = []
        video_refs = []
        audio_refs = []
    if scenario not in {"first_frame", "first_last"}:
        first_frame = None
        last_frame = None
    elif scenario != "first_last":
        last_frame = None

    duration = int(request_data.get("v_duration", getattr(task, "duration", None) or 5))
    ratio = str(request_data.get("v_ratio") or getattr(task, "aspect_ratio", None) or "adaptive")
    resolution = str(
        request_data.get("resolution")
        or request_data.get("seedance25_resolution")
        or "720p"
    ).lower()

    return {
        "generation_type": "video",
        "video_flow_step": "seedance25",
        "v_model": MODEL_KEY,
        "v_type": (
            "text"
            if scenario == "text"
            else "imgtxt"
            if scenario in {"first_frame", "first_last"}
            else "video"
        ),
        "v_duration": duration,
        "v_ratio": ratio,
        "v_image_url": first_frame,
        "reference_images": image_refs,
        "v_reference_videos": video_refs,
        "user_prompt": prompt,
        "seedance25_scenario": scenario,
        "seedance25_first_frame_url": first_frame,
        "seedance25_last_frame_url": last_frame,
        "seedance25_reference_audio_urls": audio_refs,
        "seedance25_reference_video_durations": [],
        "seedance25_resolution": resolution,
        "seedance25_generate_audio": bool(request_data.get("generate_audio", True)),
        "seedance25_return_last_frame": bool(request_data.get("return_last_frame", False)),
        "seedance25_output_format": str(request_data.get("output_format") or "mp4").lower(),
        "seedance25_web_search": bool(request_data.get("web_search", False)),
        "seedance25_nsfw_checker": bool(request_data.get("nsfw_checker", False)),
    }


@router.callback_query(F.data.startswith("repeat_video_result_"))
async def seedance25_repeat_video_result(callback: types.CallbackQuery, state: FSMContext):
    """Repeat Seedance 2.5 through its own ref-aware launch/billing path."""
    task_id = str(callback.data or "").replace("repeat_video_result_", "", 1)
    task = await generation_module.get_task_by_id(task_id)
    if not task or getattr(task, "type", None) != "video":
        raise SkipHandler

    try:
        request_data = _repeat_request_data(getattr(task, "request_data", None))
    except (TypeError, ValueError, json.JSONDecodeError):
        if str(getattr(task, "model", "") or "") != MODEL_KEY:
            raise SkipHandler
        await callback.answer("Данные исходной Seedance 2.5 задачи повреждены.", show_alert=True)
        return

    model = str(request_data.get("v_model") or getattr(task, "model", "") or "")
    if model != MODEL_KEY:
        raise SkipHandler

    user = await generation_module.get_or_create_user(callback.from_user.id)
    if getattr(task, "user_id", None) != user.id:
        await callback.answer(
            "Повтор Seedance 2.5 по исходным референсам доступен только владельцу генерации.",
            show_alert=True,
        )
        return

    prompt = str(
        request_data.get("user_prompt")
        or request_data.get("prompt")
        or getattr(task, "prompt", "")
        or ""
    ).strip()
    await state.update_data(**_repeat_state_payload(task, request_data, prompt))

    # The public Seedance wrapper below owns balance checks, charging and refunds.
    # Skipping the generic repeat handler also avoids its pre-charge/double-charge.
    try:
        await callback.answer("🔄 Повторяю Seedance 2.5 по референсам…")
    except Exception:
        pass
    await generation_module.run_no_preset_video_from_callback(
        callback,
        state,
        prompt,
        float(getattr(task, "cost", 0) or 0),
        generation_module.config.is_admin(callback.from_user.id),
    )


@router.message(
    generation_module.GenerationStates.waiting_for_video_prompt,
    F.photo | (F.document & F.document.mime_type.startswith("image/")),
)
async def seedance25_public_image_upload(message: types.Message, state: FSMContext):
    """Own Seedance image routing before legacy/generic video photo handlers."""
    data = await state.get_data()
    if str(data.get("v_model") or "") != MODEL_KEY:
        raise SkipHandler

    scenario = str(data.get("seedance25_scenario") or "text")
    if scenario == "text":
        await message.answer(
            "Фото получено, но сейчас выбран режим «✨ С нуля». "
            "Нажмите «🖼 Оживить фото» или «🧩 По референсам» и отправьте фото ещё раз."
        )
        return

    obj = message.document or (message.photo[-1] if message.photo else None)
    if obj is None:
        return
    url = await _persist_image(message, obj)
    if not url:
        await message.answer("❌ Не удалось сохранить фото. Попробуйте ещё раз.")
        return

    if scenario == "first_frame":
        await state.update_data(
            seedance25_first_frame_url=url,
            seedance25_last_frame_url=None,
            reference_images=[],
            v_reference_videos=[],
            seedance25_reference_audio_urls=[],
        )
        notice = "✅ Первый кадр сохранён. Теперь отправьте промпт — будет создано видео из этого фото."
    elif scenario == "first_last":
        first = str(data.get("seedance25_first_frame_url") or "").strip()
        if not first:
            await state.update_data(seedance25_first_frame_url=url)
            notice = "✅ Первый кадр сохранён. Теперь отправьте второе фото — оно станет последним кадром."
        else:
            await state.update_data(seedance25_last_frame_url=url)
            notice = "✅ Последний кадр сохранён. Теперь отправьте промпт."
    elif scenario == "multimodal":
        refs = preview_module._clean_urls(
            [*(data.get("reference_images") or []), url],
            30,
        )
        await state.update_data(reference_images=refs)
        notice = f"✅ Фото-референс добавлен: {len(refs)}/30."
    else:
        await message.answer("❌ Неизвестный сценарий Seedance 2.5. Выберите режим заново.")
        return

    await message.answer(notice)
    await preview_module._show_seedance_25_screen(message, state, edit=False)


def install_seedance_25_telegram_compat() -> None:
    """Replace only the presentation keyboard; callback contracts stay intact."""
    preview_module._seedance_25_keyboard = _clear_seedance_keyboard
