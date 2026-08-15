from pathlib import Path


MINIAPP = Path(__file__).resolve().parents[1] / "src" / "foxgen" / "miniapp_static"


def test_complete_menu_assets_are_loaded() -> None:
    html = (MINIAPP / "index.html").read_text(encoding="utf-8")

    assert "/mini-app/complete-menu.css" in html
    assert "/mini-app/complete-menu.js" in html


def test_complete_menu_surfaces_all_telegram_product_entries() -> None:
    script = (MINIAPP / "complete-menu.js").read_text(encoding="utf-8")

    expected_labels = {
        "Быстрый запуск",
        "Создать фото",
        "Создать видео",
        "Озвучка / голос",
        "Музыка / Suno",
        "Motion Control",
        "Промпты AI",
        "Gemini Omni",
        "AI-помощник",
        "Скучная работа",
        "Пополнить баланс",
        "Тарифы",
    }
    for label in expected_labels:
        assert label in script


def test_planned_tools_are_explicitly_non_interactive() -> None:
    script = (MINIAPP / "complete-menu.js").read_text(encoding="utf-8")

    assert "item.ready ? '' : 'disabled aria-disabled=\"true\"'" in script
    assert "Незавершённые функции не запускаются и не списывают кредиты" in script


def test_ready_generation_gets_result_open_download_action() -> None:
    script = (MINIAPP / "complete-menu.js").read_text(encoding="utf-8")

    assert "data-open-result" in script
    assert "Скачать / открыть результат" in script
    assert "tg.openLink" in script
