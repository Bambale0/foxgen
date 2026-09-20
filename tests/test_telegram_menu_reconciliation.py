from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import ensure_telegram_webhook as target


class _Button:
    def __init__(self, button_type: str):
        self.type = button_type


class _FakeBot:
    def __init__(self) -> None:
        self.buttons = {
            None: _Button("commands"),
            101: _Button("web_app"),
            202: _Button("default"),
        }
        self.set_calls: list[tuple[int | None, str]] = []

    async def get_chat_menu_button(self, chat_id: int | None = None):
        return self.buttons.get(chat_id, _Button("commands"))

    async def set_chat_menu_button(self, *, chat_id=None, menu_button):
        self.set_calls.append((chat_id, menu_button.type))
        self.buttons[chat_id] = _Button(menu_button.type)


@pytest.mark.asyncio
async def test_reconcile_menu_sets_default_webapp_and_clears_chat_overrides(monkeypatch):
    bot = _FakeBot()

    async def fake_user_ids() -> list[int]:
        return [101, 202]

    monkeypatch.setattr(target, "_telegram_user_ids", fake_user_ids)
    monkeypatch.setenv("MINI_APP_URL", "https://app.happy-fox.online/mini-app/")
    monkeypatch.setenv("HAPPYFOX_RELEASE", "release-test")

    result = await target._reconcile_miniapp_menu(bot)

    assert (None, "web_app") in bot.set_calls
    assert (101, "default") in bot.set_calls
    assert (202, "default") not in bot.set_calls
    assert result == {"checked": 2, "reset": 1, "skipped": 0}


def test_reconciliation_script_imports_when_executed_outside_repo(tmp_path):
    script = Path(target.__file__).resolve()
    probe = (
        "import importlib.util\n"
        f"path = {str(script)!r}\n"
        "spec = importlib.util.spec_from_file_location('telegram_reconcile_probe', path)\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        "assert hasattr(module, '_reconcile_miniapp_menu')\n"
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [sys.executable, "-I", "-c", probe],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


class _WebhookSession:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _WebhookBot:
    def __init__(self, info) -> None:
        self.info = info
        self.set_calls = []
        self.session = _WebhookSession()

    async def get_webhook_info(self):
        return self.info

    async def set_webhook(self, **kwargs):
        self.set_calls.append(kwargs)


@pytest.mark.asyncio
async def test_check_only_verifies_allowed_updates_without_mutating(monkeypatch):
    expected_updates = ["message", "callback_query", "pre_checkout_query"]
    info = SimpleNamespace(
        url="https://api.happy-fox.online/webhook",
        ip_address="2.27.160.11",
        allowed_updates=expected_updates,
        pending_update_count=0,
        last_error_message=None,
        last_error_date=None,
    )
    bot = _WebhookBot(info)

    async def resolve_updates():
        return expected_updates

    monkeypatch.setattr(target, "Bot", lambda token: bot)
    monkeypatch.setattr(target, "_resolve_allowed_updates", resolve_updates)
    monkeypatch.setenv("BOT_TOKEN", "test-token")
    monkeypatch.setenv(
        "TELEGRAM_WEBHOOK_URL", "https://api.happy-fox.online/webhook"
    )
    monkeypatch.setenv("TELEGRAM_WEBHOOK_IP_ADDRESS", "2.27.160.11")

    await target.ensure(repair=False, require_empty_queue=True)

    assert bot.set_calls == []
    assert bot.session.closed is True
