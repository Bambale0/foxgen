import os
from pathlib import Path

from bot.env import _apply_runtime_defaults
from scripts.canonicalize_happyfox_runtime import canonicalize


def test_runtime_canonicalizer_uses_happyfox_public_origin(tmp_path: Path) -> None:
    runtime = tmp_path / ".env.happyfox.runtime"
    runtime.write_text(
        "WEBHOOK_HOST='https://alena.chillcreative.ru'\n"
        "MINI_APP_URL='https://old.example/mini-app/'\n"
        "PRODUCT_ID='happyfox'\n",
        encoding="utf-8",
    )

    result = canonicalize(runtime)
    content = runtime.read_text(encoding="utf-8")

    assert result == "https://alena.chillcreative.ru/mini-app/"
    assert "MINI_APP_URL='https://alena.chillcreative.ru/mini-app/'" in content
    assert "old.example" not in content


def test_runtime_defaults_preserve_explicit_happyfox_url(monkeypatch) -> None:
    monkeypatch.setenv("WEBHOOK_HOST", "https://alena.chillcreative.ru")
    monkeypatch.setenv("MINI_APP_URL", "https://app.happyfox.example/mini-app/")

    _apply_runtime_defaults()

    assert os.environ["MINI_APP_URL"] == "https://app.happyfox.example/mini-app/"


def test_runtime_defaults_repair_source_product_url(monkeypatch) -> None:
    monkeypatch.setenv("WEBHOOK_HOST", "https://alena.chillcreative.ru")
    monkeypatch.setenv(
        "MINI_APP_URL",
        "https://tanyapp.xn--e1aikcel5c5a.online/mini-app/",
    )

    _apply_runtime_defaults()

    assert os.environ["MINI_APP_URL"] == "https://alena.chillcreative.ru/mini-app/"


def test_runtime_env_has_no_hardcoded_source_product_frontend() -> None:
    source = Path("bot/env.py").read_text(encoding="utf-8")
    assert "tanyapp.xn--" not in source
    assert "DEFAULT_MINI_APP_URL" not in source


def test_production_image_bundles_happyfox_static_export() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "FROM node:22-alpine AS miniapp-builder" in dockerfile
    assert "NEXT_PUBLIC_PRODUCT_ID=happyfox" in dockerfile
    assert "COPY --from=miniapp-builder" in dockerfile
    assert "/app/frontend/miniapp-v0/out" in dockerfile
    assert "revision.txt" in dockerfile
    assert 'HAPPYFOX_RELEASE="${VCS_REF}"' in dockerfile


def test_product_normalizer_versions_webapp_without_hijacking_commands_menu() -> None:
    normalizer = Path("scripts/apply_happyfox_product_copy.py").read_text(
        encoding="utf-8"
    )

    assert 'query["release"] = release' in normalizer
    assert 'os.getenv("HAPPYFOX_RELEASE", "")' in normalizer
    assert "HappyFox Telegram menu-button anchor was not found" in normalizer
    assert "HappyFox Telegram menu button is not configured for commands" in normalizer
    assert "HappyFox Telegram menu button still points to the WebApp" in normalizer


def test_normalized_runtime_versions_webapp_and_keeps_commands_menu() -> None:
    keyboards = Path("bot/keyboards.py").read_text(encoding="utf-8")
    main = Path("bot/main.py").read_text(encoding="utf-8")
    helper = main.split("async def _set_commands_chat_menu_button() -> None:", 1)[1]
    helper = helper.split("\nasync def ", 1)[0]

    assert 'os.getenv("HAPPYFOX_RELEASE", "")' in keyboards
    assert 'query["release"] = release' in keyboards
    assert '"type": "commands"' in helper
    assert '"type": "web_app"' not in helper
    assert "_mini_app_url_with_start_param" not in helper


def test_production_miniapp_wrapper_verifies_bundled_release() -> None:
    wrapper = Path("scripts/deploy_happyfox_miniapp.sh").read_text(encoding="utf-8")
    assert "deploy_miniapp_local.sh" not in wrapper
    assert "revision.txt?revision=" in wrapper
    assert "bundled release verified" in wrapper


def test_happyfox_login_gate_uses_active_brand() -> None:
    gate = Path("frontend/miniapp-v0/components/telegram-open-gate.tsx").read_text(
        encoding="utf-8"
    )
    assert "Открыть {BRAND_NAME} в Telegram" in gate
    assert "Открыть NEUROMIX" not in gate
