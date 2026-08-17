from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from foxgen.bot.callbacks import safe_edit_callback_message
from foxgen.bot.states import MusicExtendStates


router = Router(name="music-suno-upload-extend-hub")


def _button(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def _hub_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("♫ Новый трек", "music:new")],
            [_button("↗ Продолжить свой трек", "music:extend:start")],
            [_button("🎧 Cover из аудио", "music:cover:start")],
            [_button("⏩ Продолжить загруженное аудио", "music:upload-extend:start")],
            [_button("← Главное меню", "music:extend:menu")],
        ]
    )


@router.callback_query(F.data.in_({"create:music", "planned:music"}))
async def begin_music_hub_with_upload_extend(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await state.clear()
    await state.set_state(MusicExtendStates.choosing_action)
    await safe_edit_callback_message(
        callback,
        (
            "<b>Музыка · Suno V5</b>\n\n"
            "Создайте новый трек, продолжите свой результат, сделайте Cover "
            "или загрузите своё аудио и продолжите его."
        ),
        _hub_keyboard(),
    )
