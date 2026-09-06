from __future__ import annotations

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
            202: _Button("commands"),
        }
        self.set_calls: list[tuple[int | None, str]] = []

    async def get_chat_menu_button(self, chat_id: int | None = None):
        return self.buttons.get(chat_id, _Button("commands"))

    async def set_chat_menu_button(self, *, chat_id=None, menu_button):
        self.set_calls.append((chat_id, menu_button.type))
        self.buttons[chat_id] = _Button(menu_button.type)


@pytest.mark.asyncio
async def test_reconcile_menu_resets_stale_chat_specific_webapp(monkeypatch):
    bot = _FakeBot()

    async def fake_user_ids() -> list[int]:
        return [101, 202]

    monkeypatch.setattr(target, "_telegram_user_ids", fake_user_ids)

    result = await target._reconcile_command_menu(bot)

    assert (None, "commands") in bot.set_calls
    assert (101, "commands") in bot.set_calls
    assert (202, "commands") not in bot.set_calls
    assert result == {"checked": 2, "reset": 1, "skipped": 0}
