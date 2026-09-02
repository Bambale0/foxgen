from __future__ import annotations

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.suno_jobs import enqueue_suno_job

router = Router()


class SunoPriorityStates(StatesGroup):
    lyrics = State()
    sounds = State()
    id_pair = State()


def _kb(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _queued(message: types.Message, state: FSMContext, operation: str, request: dict) -> None:
    try:
        job = await enqueue_suno_job(
            "telegram",
            message.from_user.id,
            operation=operation,
            request_data=request,
        )
    except ValueError:
        await message.answer("🍌 Баланса не хватает для этой Suno-задачи.")
        return
    await state.clear()
    await message.answer(
        f"🚀 Suno-задача запущена · списано {job.cost:g}🍌. Результат придёт автоматически."
    )


@router.callback_query(F.data == "happyfox_music")
async def happyfox_music_entry(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Open the real Suno Studio from HappyFox's primary music button."""
    from bot.handlers.suno import suno_menu_keyboard

    await state.clear()
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "🎵 <b>Suno Studio</b>\n\nМузыка, вокал, каверы и профессиональная обработка в одном разделе.",
            reply_markup=await suno_menu_keyboard(),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "suno:lyrics")
async def lyrics_entry(callback: types.CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SunoPriorityStates.lyrics)
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "✍️ Опишите тему, историю и настроение будущего текста песни.",
            reply_markup=_kb([[InlineKeyboardButton(text="⬅️ Suno", callback_data="menu_suno")]]),
        )


@router.message(SunoPriorityStates.lyrics)
async def lyrics_text(message: types.Message, state: FSMContext) -> None:
    prompt = str(message.text or "").strip()
    if not prompt:
        await message.answer("Пришлите описание текста песни.")
        return
    await _queued(message, state, "lyrics", {"prompt": prompt[:3000]})


@router.callback_query(F.data == "suno:sounds")
async def sounds_entry(callback: types.CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SunoPriorityStates.sounds)
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "🌊 Опишите звук, атмосферу, background или музыкальный loop.",
            reply_markup=_kb([[InlineKeyboardButton(text="⬅️ Suno", callback_data="menu_suno")]]),
        )


@router.message(SunoPriorityStates.sounds)
async def sounds_text(message: types.Message, state: FSMContext) -> None:
    prompt = str(message.text or "").strip()
    if not prompt:
        await message.answer("Пришлите описание звука.")
        return
    await _queued(
        message,
        state,
        "sounds",
        {"prompt": prompt[:3000], "model": "V5", "soundLoop": True},
    )


@router.callback_query(F.data == "suno:tools")
async def tools_entry(callback: types.CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "🧰 <b>Suno Tools</b>\n\n"
            "Под готовым треком есть быстрые кнопки. Для ручного запуска пришлите Task ID + Audio ID.",
            reply_markup=_kb(
                [
                    [InlineKeyboardButton(text="🎚 Вокал / инструментал", callback_data="suno:priority_id:separate_vocal")],
                    [InlineKeyboardButton(text="🧩 Полные стемы", callback_data="suno:priority_id:split_stem")],
                    [InlineKeyboardButton(text="🎯 Точный стем", callback_data="suno:priority_id:split_stem_advanced")],
                    [InlineKeyboardButton(text="🎹 MIDI из стемов", callback_data="suno:priority_id:midi")],
                    [InlineKeyboardButton(text="🎧 WAV", callback_data="suno:priority_id:wav")],
                    [InlineKeyboardButton(text="🎬 Music Video", callback_data="suno:priority_id:music_video")],
                    [InlineKeyboardButton(text="📝 Текст с таймкодами", callback_data="suno:priority_id:timestamped_lyrics")],
                    [InlineKeyboardButton(text="⬅️ Suno", callback_data="menu_suno")],
                ]
            ),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("suno:priority_id:"))
async def id_entry(callback: types.CallbackQuery, state: FSMContext) -> None:
    operation = str(callback.data).split(":", 2)[2]
    allowed = {
        "separate_vocal",
        "split_stem",
        "split_stem_advanced",
        "midi",
        "wav",
        "music_video",
        "timestamped_lyrics",
    }
    if operation not in allowed:
        await callback.answer("Операция недоступна", show_alert=True)
        return
    await state.set_state(SunoPriorityStates.id_pair)
    await state.update_data(suno_priority_operation=operation)
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "Пришлите одной строкой: <code>TaskID AudioID</code>",
            reply_markup=_kb([[InlineKeyboardButton(text="⬅️ Suno", callback_data="menu_suno")]]),
            parse_mode="HTML",
        )


@router.message(SunoPriorityStates.id_pair)
async def id_pair(message: types.Message, state: FSMContext) -> None:
    parts = str(message.text or "").split()
    if len(parts) < 2:
        await message.answer("Нужны Task ID и Audio ID через пробел.")
        return
    data = await state.get_data()
    operation = str(data.get("suno_priority_operation") or "")
    await _queued(
        message,
        state,
        operation,
        {"taskId": parts[0][:200], "audioId": parts[1][:200]},
    )
