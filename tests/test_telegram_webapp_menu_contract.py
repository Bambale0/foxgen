from pathlib import Path

from scripts.reconcile_telegram_webapp_menu import _menu_button


def test_webapp_menu_button_uses_internal_telegram_webapp_contract() -> None:
    url = "https://app.happy-fox.online/mini-app/?release=test"
    button = _menu_button(url)

    assert button.type == "web_app"
    assert button.text == "Открыть HappyFox"
    assert button.web_app.url == url


def test_production_image_reconciles_webapp_after_webhook_setup() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    webhook_pos = dockerfile.index("ensure_telegram_webhook.py")
    webapp_pos = dockerfile.index("reconcile_telegram_webapp_menu")
    assert webapp_pos > webhook_pos
    assert "_mini_app_url_with_start_param" in dockerfile
