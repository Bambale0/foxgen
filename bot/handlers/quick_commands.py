"""Highest-priority Telegram quick commands.

These commands intentionally run before product FSM routers so a user can leave
an AI-assistant or generation state without the slash command being consumed as
ordinary prompt text.
"""

from aiogram import Router, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext

router = Router(name="telegram_quick_commands")


@router.message(Command("photo"), StateFilter("*"))
async def quick_photo(message: types.Message, state: FSMContext) -> None:
    from bot.handlers.generation import (
        _default_image_flow_data,
        _show_image_model_selection_screen,
    )

    await state.clear()
    await state.update_data(**_default_image_flow_data(img_flow_step="select_model"))
    await _show_image_model_selection_screen(message, state, edit=False)


@router.message(Command("video"), StateFilter("*"))
async def quick_video(message: types.Message, state: FSMContext) -> None:
    from bot.handlers.generation import _init_default_video_state, _show_video_creation_screen

    await state.clear()
    await _init_default_video_state(state)
    await state.update_data(video_flow_step="configure")
    await _show_video_creation_screen(message, state, edit=False)


@router.message(Command("music"), StateFilter("*"))
async def quick_music(message: types.Message, state: FSMContext) -> None:
    from bot.handlers.suno import suno_menu_keyboard

    await state.clear()
    await message.answer(
        "🎵 <b>Suno Studio</b>\n\n"
        "Музыка, вокал, каверы и профессиональная обработка в одном разделе.",
        reply_markup=await suno_menu_keyboard(),
        parse_mode="HTML",
    )


@router.message(Command("motion"), StateFilter("*"))
async def quick_motion(message: types.Message, state: FSMContext) -> None:
    from bot.database import get_user_credits
    from bot.handlers.generation import get_motion_control_model_keyboard

    await state.clear()
    user_credits = await get_user_credits(message.from_user.id)
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
    await message.answer(
        "🎯 <b>Motion Control</b>\n"
        f"🐾 Баланс: <code>{user_credits}</code> лапок\n\n"
        "Выбери версию Kling. На кнопках указана только цена за 1 секунду.",
        reply_markup=get_motion_control_model_keyboard("motion_control_v26"),
        parse_mode="HTML",
    )


@router.message(Command("feed"), StateFilter("*"))
async def quick_feed(message: types.Message, state: FSMContext) -> None:
    from bot.handlers.common import _render_feed_by_source

    await state.clear()
    await _render_feed_by_source(
        message,
        telegram_id=message.from_user.id,
        source_code="r",
        index=0,
        photo_index=0,
    )


@router.message(Command("trends", "prompts"), StateFilter("*"))
async def quick_trends(message: types.Message, state: FSMContext) -> None:
    from bot.handlers.trends_compat import cmd_trends

    await state.clear()
    await cmd_trends(message, state)


@router.message(Command("balance"), StateFilter("*"))
async def quick_balance(message: types.Message, state: FSMContext) -> None:
    from bot.database import get_or_create_user, get_user_stats
    from bot.handlers.common import _build_balance_text
    from bot.keyboards import get_balance_keyboard

    await state.clear()
    user = await get_or_create_user(message.from_user.id)
    stats = await get_user_stats(message.from_user.id)
    await message.answer(
        _build_balance_text(stats),
        reply_markup=get_balance_keyboard(user.credits),
        parse_mode="HTML",
    )


@router.message(Command("help"), StateFilter("*"))
async def legacy_help(message: types.Message, state: FSMContext) -> None:
    """Keep a cached legacy /help command from falling into assistant prompt text."""
    from bot.handlers.common import cmd_help

    await state.clear()
    await cmd_help(message)


@router.message(Command("ref", "earn"), StateFilter("*"))
async def legacy_partner(message: types.Message, state: FSMContext) -> None:
    """Keep cached legacy partner commands outside assistant/generation FSM input."""
    from bot.handlers.common import cmd_partner

    await state.clear()
    await cmd_partner(message)
