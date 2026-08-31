from pathlib import Path

from bot.max_catalog import MAX_PRICE_PATH, MaxPresetManager
from bot.max_ui import main_menu


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
    assert "seedance_2_5" in manager.video_models()
