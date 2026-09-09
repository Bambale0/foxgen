from __future__ import annotations

import json
import logging

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import config
from bot.database import (
    add_credits,
    check_can_afford,
    deduct_credits,
    get_or_create_user,
    get_task_by_id,
)
from bot.handlers.generation import (
    _show_video_creation_screen,
    run_no_preset_video_from_callback,
)
from bot.keyboards import get_video_model_label
from bot.model_capabilities import (
    VIDEO_MODEL_CAPABILITIES,
    get_video_capability,
    normalize_video_model_key,
)
from bot.video_generation_contract import build_repeat_video_state

logger = logging.getLogger(__name__)
router = Router()

PUBLIC_VIDEO_MODEL_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Kling", ("v3_std", "v3_pro", "v3_4k", "v26_pro")),
    ("Motion и Avatar", ("motion_control_v26", "motion_control_v30", "glow", "avatar_std", "avatar_pro")),
    ("Seedance и Grok", ("seedance_2_5", "seedance_2", "seedance_2_fast", "grok_imagine", "grok_imagine_v15")),
    ("Veo", ("veo3", "veo3_fast", "veo3_lite")),
    ("Gemini Omni", ("gemini_omni_video", "gemini_omni_audio", "gemini_omni_character")),
)

MODEL_EMOJI = {
    "v3_std": "⚡", "v3_pro": "💎", "v3_4k": "🖥", "v26_pro": "🌀",
    "motion_control_v26": "🎯", "motion_control_v30": "🚀", "glow": "✨",
    "avatar_std": "🗣", "avatar_pro": "🎙", "seedance_2_5": "🎬", "seedance_2": "🎞",
    "seedance_2_fast": "⚡", "grok_imagine": "🧠", "grok_imagine_v15": "🔥",
    "veo3": "🎥", "veo3_fast": "🚄", "veo3_lite": "🌿",
    "gemini_omni_video": "🔷", "gemini_omni_audio": "🎧", "gemini_omni_character": "🧍",
}


def _advanced_video_models_keyboard(current_model: str | None = None) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    selected = normalize_video_model_key(current_model)
    for _group_name, model_keys in PUBLIC_VIDEO_MODEL_GROUPS:
        for model_key in model_keys:
            capability = VIDEO_MODEL_CAPABILITIES[model_key]
            check = "✅ " if selected == model_key else ""
            builder.button(
                text=f"{check}{MODEL_EMOJI.get(model_key, '🎬')} {capability.label}",
                callback_data=f"advanced_v_model_{model_key}",
            )
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()


def _initial_type_for_model(model: str) -> str:
    if model in {"motion_control_v26", "motion_control_v30", "glow"}:
        return "motion"
    if model in {"avatar_std", "avatar_pro"}:
        return "avatar"
    if model == "gemini_omni_audio":
        return "audio"
    if model == "gemini_omni_character":
        return "character"
    return "text"


@router.callback_query(F.data.in_({"create_video_new", "video_change_model"}))
async def show_complete_video_model_selection(callback: types.CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if callback.data == "create_video_new":
        await state.clear()
        await state.update_data(
            generation_type="video",
            video_flow_step="select_model",
            v_model="v3_pro",
            v_type="text",
            v_duration=5,
            v_ratio="16:9",
            v_mode="720p",
            reference_images=[],
            v_reference_videos=[],
            v_reference_audio=[],
        )
        current_model = "v3_pro"
    else:
        await state.update_data(video_flow_step="select_model")
        current_model = data.get("v_model", "v3_pro")

    text = (
        "🎬 <b>Создание видео</b>\n"
        "<b>Шаг 1. Выберите модель</b>\n\n"
        "Доступны production-модели и расширенные режимы."
    )
    try:
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=_advanced_video_models_keyboard(current_model),
        )
    except TelegramBadRequest:
        await callback.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=_advanced_video_models_keyboard(current_model),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("advanced_v_model_"))
async def select_advanced_video_model(callback: types.CallbackQuery, state: FSMContext) -> None:
    model = normalize_video_model_key(
        str(callback.data or "").replace("advanced_v_model_", "", 1)
    )
    capability = get_video_capability(model)
    if capability is None:
        await callback.answer("Эта модель пока недоступна.", show_alert=True)
        return

    duration = capability.durations[0] if capability.durations else 5
    ratio = capability.aspect_ratios[0] if capability.aspect_ratios else "16:9"
    resolution = capability.resolutions[0] if capability.resolutions else "720p"
    await state.update_data(
        generation_type="video",
        video_flow_step="configure",
        v_model=model,
        v_type=_initial_type_for_model(model),
        v_duration=duration,
        v_ratio=ratio,
        v_mode=resolution,
        motion_quality=resolution,
        reference_images=[],
        v_reference_videos=[],
        v_reference_audio=[],
        v_image_url=None,
        v_end_image_url=None,
        avatar_audio_url=None,
    )
    await _show_video_creation_screen(callback, state)
    await callback.answer(f"Выбрано: {capability.label}")


@router.callback_query(F.data.startswith("repeat_video_result_"))
async def repeat_advanced_video_result(callback: types.CallbackQuery, state: FSMContext) -> None:
    task_id = str(callback.data or "").replace("repeat_video_result_", "", 1)
    task = await get_task_by_id(task_id)
    if not task or task.type != "video":
        await callback.answer("Не удалось найти данные для повтора.", show_alert=True)
        return

    try:
        request_data = json.loads(task.request_data) if task.request_data else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        await callback.answer("Данные исходной задачи повреждены.", show_alert=True)
        return

    user = await get_or_create_user(callback.from_user.id)
    restored = build_repeat_video_state(
        request_data,
        include_private_media=bool(task.user_id == user.id),
    )
    if not restored.get("user_prompt"):
        restored["user_prompt"] = str(task.prompt or "")
    restored["repeat_source_task_id"] = task_id

    unit_cost = int(task.cost or 0)
    is_admin = config.is_admin(callback.from_user.id)
    if unit_cost > 0 and not is_admin:
        if not await check_can_afford(callback.from_user.id, unit_cost):
            await callback.answer("Недостаточно бананов для повтора.", show_alert=True)
            return
        if not await deduct_credits(callback.from_user.id, unit_cost):
            await callback.answer("Не удалось списать бананы.", show_alert=True)
            return

    await state.clear()
    await state.update_data(**restored)
    model_label = get_video_model_label(restored["v_model"])
    progress = await callback.message.answer(
        "🔁 <b>Повторяю генерацию видео</b>\n"
        f"• Модель: <code>{model_label}</code>\n"
        f"• Длительность: <code>{restored['v_duration']}с</code>\n"
        f"• Фото-референсы: <code>{len(restored['reference_images'])}</code>\n"
        f"• Видео-референсы: <code>{len(restored['v_reference_videos'])}</code>",
        parse_mode="HTML",
    )

    try:
        await progress.delete()
        await run_no_preset_video_from_callback(
            callback,
            state,
            restored["user_prompt"],
            unit_cost,
            is_admin,
        )
    except Exception:
        logger.exception("Advanced video repeat failed for task_id=%s", task_id)
        if unit_cost > 0 and not is_admin:
            await add_credits(callback.from_user.id, unit_cost)
        try:
            await callback.answer(
                "Не удалось повторить видео. Бананы возвращены.",
                show_alert=True,
            )
        except TelegramBadRequest:
            pass
