from pathlib import Path

from bot.config import config
from bot.keyboards import (
    get_ai_assistant_keyboard,
    get_confirm_keyboard,
    get_main_menu_keyboard,
    get_more_menu_keyboard,
)


def _texts(markup):
    return [[button.text for button in row] for row in markup.inline_keyboard]


def _callbacks(markup):
    return [
        [button.callback_data for button in row]
        for row in markup.inline_keyboard
    ]


def _buttons(markup):
    return [button for row in markup.inline_keyboard for button in row]


def test_happyfox_main_menu_matches_product_layout(monkeypatch):
    monkeypatch.setattr(config, "MINI_APP_URL", "https://app.happy-fox.online/mini-app/")

    markup = get_main_menu_keyboard(user_credits=42, mini_app_referral_code="FOX42")

    assert _texts(markup) == [
        ["🚀 Mini App"],
        ["🖼 Создать фото", "🎙 Создать озвучку"],
        ["🎬 Создать видео", "🎵 Создать музыку · Suno"],
        ["🎯 Motion Control", "✨ Промпты"],
        ["🔷 Gemini Omni", "🤖 AI-помощник"],
        ["🔗 Ссылки на работы", "💬 Поддержка"],
        ["🐾 Баланс: 42", "🤝 Партнёры"],
        ["💳 Тарифы"],
    ]
    assert _callbacks(markup)[1:] == [
        ["create_image_text_new", "omni_mode_audio"],
        ["create_video_new", "happyfox_music"],
        ["motion_control", "menu_prompts"],
        ["v_model_gemini_omni", "menu_ai_assistant"],
        ["menu_feed", "menu_support"],
        ["menu_balance", "menu_partner"],
        ["menu_topup"],
    ]

    mini_app_button = markup.inline_keyboard[0][0]
    assert mini_app_button.web_app is not None
    assert "app.happy-fox.online/mini-app/" in mini_app_button.web_app.url
    assert "ref=FOX42" in mini_app_button.web_app.url
    assert {button.style for button in _buttons(markup)} == {"success"}
    assert all(button.icon_custom_emoji_id is None for button in _buttons(markup))


def test_main_menu_uses_configured_custom_emoji_icons(monkeypatch):
    monkeypatch.setattr(config, "MINI_APP_URL", "https://app.happy-fox.online/mini-app/")
    monkeypatch.setenv(
        "HAPPYFOX_TELEGRAM_MENU_EMOJI_IDS",
        '{"mini_app":"5368324170671202286","photo":"5774022692642492953"}',
    )

    markup = get_main_menu_keyboard(user_credits=42)

    mini_app_button = markup.inline_keyboard[0][0]
    photo_button = markup.inline_keyboard[1][0]
    video_button = markup.inline_keyboard[2][0]

    assert mini_app_button.text == "Mini App"
    assert mini_app_button.icon_custom_emoji_id == "5368324170671202286"
    assert photo_button.text == "Создать фото"
    assert photo_button.icon_custom_emoji_id == "5774022692642492953"
    assert video_button.text == "🎬 Создать видео"
    assert video_button.icon_custom_emoji_id is None
    assert {button.style for button in _buttons(markup)} == {"success"}


def test_other_ai_menu_is_a_three_scenario_hub():
    markup = get_more_menu_keyboard()

    assert _texts(markup) == [
        ["🎬 Видео", "🖼 Фото"],
        ["✨ Улучшение"],
        ["🏠 Главное меню"],
    ]
    assert _callbacks(markup) == [
        ["create_video_new", "create_image_text_new"],
        ["create_image_refs_new"],
        ["back_main"],
    ]


def test_telegram_system_menu_exposes_quick_commands():
    main_text = Path("bot/main.py").read_text(encoding="utf-8")
    menu_block = main_text.split("async def _set_commands_chat_menu_button", 1)[1].split(
        "async def _complete_reconciled_order", 1
    )[0]

    assert 'json={"menu_button": {"type": "commands"}}' in menu_block
    assert '"type": "web_app"' not in menu_block
    assert "await bot.set_my_commands(" in main_text
    for command in ("photo", "video", "music", "motion", "feed", "trends", "balance", "start"):
        assert f'BotCommand(command="{command}"' in main_text


def test_text_bot_action_keyboards_are_green_and_destructive_actions_are_danger():
    assistant = get_ai_assistant_keyboard(telegram_id=None)
    assistant_buttons = _buttons(assistant)

    assert assistant_buttons
    assert {button.style for button in assistant_buttons} == {"success"}

    confirm = get_confirm_keyboard("confirm_action", "cancel_action")
    by_text = {button.text: button.style for button in _buttons(confirm)}

    assert by_text["✅ Подтвердить"] == "success"
    assert by_text["❌ Отмена"] == "danger"
    assert by_text["🏠 Главное меню"] == "success"


def test_configured_unicode_prefixes_become_animated_button_icons(monkeypatch):
    monkeypatch.setenv(
        "HAPPYFOX_TELEGRAM_MENU_EMOJI_IDS",
        '{"✅":"1111111111111111111","❌":"2222222222222222222","🏠":"3333333333333333333"}',
    )

    markup = get_confirm_keyboard("confirm_action", "cancel_action")
    buttons = _buttons(markup)

    assert [(button.text, button.icon_custom_emoji_id, button.style) for button in buttons] == [
        ("Подтвердить", "1111111111111111111", "success"),
        ("Отмена", "2222222222222222222", "danger"),
        ("Главное меню", "3333333333333333333", "success"),
    ]
