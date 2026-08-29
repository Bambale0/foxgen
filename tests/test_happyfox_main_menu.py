from pathlib import Path

from bot.config import config
from bot.keyboards import get_main_menu_keyboard, get_more_menu_keyboard


def _texts(markup):
    return [[button.text for button in row] for row in markup.inline_keyboard]


def _callbacks(markup):
    return [
        [button.callback_data for button in row]
        for row in markup.inline_keyboard
    ]


def test_happyfox_main_menu_matches_product_layout(monkeypatch):
    monkeypatch.setattr(config, "MINI_APP_URL", "https://alena.chillcreative.ru/mini-app/")

    markup = get_main_menu_keyboard(user_credits=42, mini_app_referral_code="FOX42")

    assert _texts(markup) == [
        ["🚀 Mini App"],
        ["🎬 Создать видео", "🎙 Создать озвучку"],
        ["🖼 Создать фото", "🎵 Создать музыку · Suno"],
        ["🎯 Motion Control", "✨ Прочий AI"],
        ["🔷 Gemini Omni", "🤖 AI-помощник"],
        ["🔗 Ссылки на работы", "💬 Поддержка"],
        ["🍌 Баланс: 42", "🤝 Партнёры"],
        ["💳 Тарифы"],
    ]
    assert _callbacks(markup)[1:] == [
        ["create_video_new", "omni_mode_audio"],
        ["create_image_text_new", "happyfox_music"],
        ["motion_control", "ux_more"],
        ["v_model_gemini_omni", "menu_ai_assistant"],
        ["menu_feed", "menu_support"],
        ["menu_balance", "menu_partner"],
        ["menu_topup"],
    ]

    mini_app_button = markup.inline_keyboard[0][0]
    assert mini_app_button.web_app is not None
    assert "alena.chillcreative.ru/mini-app/" in mini_app_button.web_app.url
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


def test_telegram_chat_menu_button_opens_registered_quick_commands():
    source = Path("bot/main.py").read_text(encoding="utf-8")
    helper = source.split("async def _set_commands_chat_menu_button() -> None:", 1)[1]
    helper = helper.split("\nasync def ", 1)[0]

    assert '"type": "commands"' in helper
    assert '"type": "web_app"' not in helper
    assert "_mini_app_url_with_start_param" not in helper

    for command in ("start", "feed", "prompts", "help", "ref", "earn"):
        assert f'BotCommand(command="{command}"' in source
