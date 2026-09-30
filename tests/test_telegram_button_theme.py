import pytest
from aiogram.methods import SendMessage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.services.telegram_button_theme import (
    TelegramButtonThemeMiddleware,
    style_telegram_markup,
)


def _markup():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🛠 Админ-функции", callback_data="admin_tools"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"),
            ],
            [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_main")],
        ]
    )


def test_styles_raw_handler_markup_without_keyboard_factory():
    themed = style_telegram_markup(_markup())

    buttons = [button for row in themed.inline_keyboard for button in row]
    assert [(button.text, button.style) for button in buttons] == [
        ("🛠 Админ-функции", "success"),
        ("❌ Отмена", "danger"),
        ("🏠 В главное меню", "success"),
    ]


def test_preserves_explicit_button_style():
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Особая кнопка",
                    callback_data="special",
                    style="primary",
                )
            ]
        ]
    )

    themed = style_telegram_markup(markup)

    assert themed.inline_keyboard[0][0].style == "primary"


def test_unicode_prefix_can_be_replaced_with_custom_emoji(monkeypatch):
    monkeypatch.setenv(
        "HAPPYFOX_TELEGRAM_MENU_EMOJI_IDS",
        '{"🏠":"5368324170671202286"}',
    )

    themed = style_telegram_markup(
        InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_main")]
            ]
        )
    )
    button = themed.inline_keyboard[0][0]

    assert button.text == "В главное меню"
    assert button.icon_custom_emoji_id == "5368324170671202286"
    assert button.style == "success"


@pytest.mark.asyncio
async def test_request_middleware_themes_direct_send_message_markup():
    middleware = TelegramButtonThemeMiddleware()
    method = SendMessage(chat_id=1, text="test", reply_markup=_markup())
    captured = {}

    async def make_request(bot, themed_method):
        captured["method"] = themed_method
        return "ok"

    result = await middleware(make_request, object(), method)

    assert result == "ok"
    sent = captured["method"]
    buttons = [button for row in sent.reply_markup.inline_keyboard for button in row]
    assert [button.style for button in buttons] == ["success", "danger", "success"]
    assert method.reply_markup.inline_keyboard[0][0].style is None
