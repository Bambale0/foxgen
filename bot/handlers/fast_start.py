"""Low-latency plain /start handler with optional webhook response delivery."""

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.methods import SendMessage
from aiogram.methods.base import TelegramMethod

from bot.database import get_or_create_user
from bot.handlers.common import (
    _build_main_menu_text,
    _set_user_menu,
    _sync_telegram_profile,
)
from bot.keyboards import get_main_menu_keyboard

router = Router(name=__name__)


@router.message(Command("start"), F.text.regexp(r"^/start(?:@[A-Za-z0-9_]+)?\s*$"))
async def fast_plain_start(
    message: types.Message,
    state: FSMContext,
    webhook_reply_enabled: bool = False,
) -> TelegramMethod | None:
    """Handle plain /start without referral/payment/deep-link branches."""
    await state.clear()

    user = await get_or_create_user(message.from_user.id)
    await _sync_telegram_profile(message.from_user)

    response = SendMessage(
        chat_id=message.chat.id,
        text=_build_main_menu_text(user.credits),
        reply_markup=get_main_menu_keyboard(user.credits, message.from_user.id),
        parse_mode="HTML",
    )
    _set_user_menu(message.from_user.id, "main_menu")

    if webhook_reply_enabled:
        return response

    await message.bot(response)
    return None
