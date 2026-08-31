from pathlib import Path

from bot.max_catalog import MAX_PRICE_PATH, MaxPresetManager
from bot.max_ui import main_menu, video_model_menu, video_type_menu


def _rows(attachments):
    return attachments[0]["payload"]["buttons"]


def test_max_main_menu_matches_happyfox_telegram_layout() -> None:
    rows = _rows(main_menu(42, mini_app_url="https://example.invalid/max-app"))
    assert [[button["text"] for button in row] for row in rows] == [
        ["🚀 Mini App"],
        ["🖼 Создать фото", "🎙 Создать озвучку"],
        ["🎬 Создать видео", "🎵 Создать музыку · Suno"],
        ["🎯 Motion Control", "✨ Промпты"],
        ["🔷 Gemini Omni", "🤖 AI-помощник"],
        ["🔗 Ссылки на работы", "💬 Поддержка"],
        ["🐾 Баланс: 42", "🤝 Партнёры"],
        ["💳 Тарифы"],
    ]
    callbacks = [
        button.get("payload")
        for row in rows
        for button in row
        if button["type"] == "callback"
    ]
    assert callbacks
    assert all(str(payload).startswith("max:") for payload in callbacks)


def test_max_pricing_is_a_separate_physical_snapshot() -> None:
    manager = MaxPresetManager()
    assert manager.price_path == MAX_PRICE_PATH
    assert Path("data/max_price.json").resolve() != Path("data/price.json").resolve()
    assert manager.get_packages()
    assert "banana_2" in manager.image_models()
    assert "v3_pro" in manager.video_models("text")
    assert "seedance_2" in manager.video_models("video")
    assert "seedance_2_5" not in manager.video_models()
    assert "seedance_2_5" in manager.get_price_config()["costs_reference"]["video_models"]


def test_max_video_selector_mirrors_telegram_scenario_matrix() -> None:
    type_rows = _rows(video_type_menu())
    type_payloads = [button["payload"] for row in type_rows for button in row]
    assert type_payloads[:3] == [
        "max:vtype:text",
        "max:vtype:imgtxt",
        "max:vtype:video",
    ]

    text_rows = _rows(video_model_menu("text"))
    text_payloads = [
        button["payload"]
        for row in text_rows
        for button in row
        if button["payload"].startswith("max:video:")
    ]
    assert text_payloads == [
        "max:video:text:v3_pro",
        "max:video:text:v3_std",
        "max:video:text:v26_pro",
        "max:video:text:seedance_2",
        "max:video:text:gemini_omni",
        "max:video:text:veo3",
        "max:video:text:veo3_fast",
        "max:video:text:veo3_lite",
    ]
