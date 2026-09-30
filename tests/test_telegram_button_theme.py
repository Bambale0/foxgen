import pytest
from aiogram.methods import SendMessage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.services import telegram_button_theme as theme
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


def test_clear_and_reset_actions_are_danger():
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🧹 Очистить медиа", callback_data="seedance_clear_media"),
                InlineKeyboardButton(text="Сбросить", callback_data="reset_filters"),
            ]
        ]
    )

    themed = style_telegram_markup(markup)
    assert [button.style for button in themed.inline_keyboard[0]] == ["danger", "danger"]


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
async def test_db_mapping_overrides_environment_fallback(monkeypatch):
    monkeypatch.setenv(
        "HAPPYFOX_TELEGRAM_MENU_EMOJI_IDS",
        '{"🏠":"1111111111111111111"}',
    )

    async def fake_get_bot_setting(key, default=None):
        assert key == theme.TELEGRAM_BUTTON_EMOJI_SETTING_KEY
        return '{"🏠":"2222222222222222222"}'

    monkeypatch.setattr("bot.database.get_bot_setting", fake_get_bot_setting)
    theme.invalidate_telegram_button_emoji_cache()

    assert await theme.get_configured_telegram_emoji_ids() == {
        "🏠": "2222222222222222222"
    }


@pytest.mark.asyncio
async def test_persisted_mapping_records_admin_actor(monkeypatch):
    captured = {}

    async def fake_set_bot_setting(key, value, *, updated_by_telegram_id=None):
        captured.update(
            key=key,
            value=value,
            updated_by_telegram_id=updated_by_telegram_id,
        )
        return True

    monkeypatch.setattr("bot.database.set_bot_setting", fake_set_bot_setting)
    theme.invalidate_telegram_button_emoji_cache()

    saved = await theme.set_configured_telegram_emoji_ids(
        {"🏠": "3333333333333333333"},
        updated_by_telegram_id=42,
    )

    assert saved == {"🏠": "3333333333333333333"}
    assert captured["key"] == theme.TELEGRAM_BUTTON_EMOJI_SETTING_KEY
    assert captured["updated_by_telegram_id"] == 42
    assert '"🏠":"3333333333333333333"' in captured["value"]


@pytest.mark.asyncio
async def test_request_middleware_themes_direct_send_message_markup(monkeypatch):
    async def configured():
        return {}

    monkeypatch.setattr(theme, "get_configured_telegram_emoji_ids", configured)
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
