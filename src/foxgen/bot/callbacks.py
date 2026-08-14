from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

_STALE_EDIT_ERRORS = (
    "message can't be edited",
    "message to edit not found",
    "there is no text in the message to edit",
)


async def safe_edit_callback_message(
    callback: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    *,
    answer_text: str | None = None,
    show_alert: bool = False,
    answer_callback: bool = True,
) -> None:
    if callback.message:
        try:
            await callback.message.edit_text(text, reply_markup=reply_markup)
        except TelegramBadRequest as exc:
            message = str(exc)
            if "message is not modified" not in message:
                if any(fragment in message for fragment in _STALE_EDIT_ERRORS):
                    await callback.message.answer(text, reply_markup=reply_markup)
                else:
                    raise
    if answer_callback:
        await callback.answer(answer_text, show_alert=show_alert)
