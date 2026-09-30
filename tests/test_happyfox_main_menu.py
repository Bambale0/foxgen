from pathlib import Path

from bot.config import config
from bot.keyboards import (
    get_animate_hub_keyboard,
    get_create_hub_keyboard,
    get_edit_hub_keyboard,
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


def test_public_telegram_navigation_uses_green_buttons_and_custom_emoji_icons(monkeypatch):
    monkeypatch.setattr(config, "MINI_APP_URL", "https://app.happy-fox.online/mini-app/")

    markups = [
        get_main_menu_keyboard(user_credits=42),
        get_create_hub_keyboard(),
        get_edit_hub_keyboard(),
        get_animate_hub_keyboard(),
        get_more_menu_keyboard(),
    ]

    assert config.TELEGRAM_BUTTON_CUSTOM_EMOJI_ID
    for markup in markups:
        buttons = _buttons(markup)
        assert buttons
        assert all(button.style == "success" for button in buttons)
        assert all(
            button.icon_custom_emoji_id == config.TELEGRAM_BUTTON_CUSTOM_EMOJI_ID
            for button in buttons
        )


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
