from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot import suno_pricing
from bot.handlers.suno_menu_compat import install_suno_menu_compat
from bot.max_omni_channel import MaxOmniChannelService
from bot.max_suno_full_channel import MaxSunoFullChannelService
from bot.services.suno_service import SunoService


@pytest.mark.asyncio
async def test_live_prices_are_channel_specific_and_copyable(monkeypatch):
    settings: dict[str, str] = {}

    async def fake_get(key: str, default=None):
        return settings.get(key, default)

    async def fake_set(key: str, value, *, updated_by_telegram_id=None):
        settings[key] = str(value)
        return True

    monkeypatch.setattr(suno_pricing, "get_bot_setting", fake_get)
    monkeypatch.setattr(suno_pricing, "set_bot_setting", fake_set)

    telegram_default = await suno_pricing.get_suno_price("telegram", "generate", "V5_5")
    max_default = await suno_pricing.get_suno_price("max", "generate", "V5_5")
    assert telegram_default == max_default

    await suno_pricing.set_suno_price(
        "telegram",
        "generate",
        31.5,
        model="V5_5",
        updated_by_telegram_id=1,
    )
    assert await suno_pricing.get_suno_price("telegram", "generate", "V5_5") == 31.5
    assert await suno_pricing.get_suno_price("max", "generate", "V5_5") == max_default

    changed = await suno_pricing.copy_suno_prices(
        "telegram",
        "max",
        updated_by_telegram_id=1,
    )
    assert changed > 20
    assert await suno_pricing.get_suno_price("max", "generate", "V5_5") == 31.5


@pytest.mark.asyncio
async def test_every_declared_suno_price_has_a_default():
    for channel in suno_pricing.SUNO_CHANNELS:
        entries = await suno_pricing.list_suno_prices(channel)
        expected = sum(
            len(suno_pricing.SUNO_MODELS)
            if operation in suno_pricing.MODEL_PRICED_OPERATIONS
            else 1
            for operation in suno_pricing.SUNO_OPERATIONS
        )
        assert len(entries) == expected
        assert all(entry.price >= 0 for entry in entries)


def test_defaults_file_covers_telegram_and_max():
    payload = json.loads(
        Path("data/suno_price_defaults.json").read_text(encoding="utf-8")
    )
    assert set(payload) == {"telegram", "max"}
    for channel in ("telegram", "max"):
        assert set(payload[channel]) == set(suno_pricing.SUNO_OPERATIONS)


@pytest.mark.asyncio
async def test_generate_payload_uses_selected_model(monkeypatch):
    service = SunoService(api_key="test")
    captured = {}

    async def fake_request(method, path, *, json_body=None, params=None):
        captured.update(
            method=method,
            path=path,
            json_body=dict(json_body or {}),
            params=params,
        )
        return {"code": 200, "data": {"taskId": "task-1"}}

    monkeypatch.setattr(service, "_request", fake_request)
    monkeypatch.setenv("SUNO_CALLBACK_URL", "https://example.test/webhook/suno")

    result = await service.submit(
        "generate",
        {
            "prompt": "cinematic synthwave",
            "customMode": False,
            "instrumental": True,
            "model": "V5_5",
        },
    )

    assert service.task_id(result) == "task-1"
    assert captured["path"] == "/api/v1/generate"
    assert captured["json_body"]["model"] == "V5_5"
    assert captured["json_body"]["callBackUrl"].endswith("/webhook/suno")


def test_suno_result_normalization_keeps_action_ids_and_audio_url():
    payload = {
        "code": 200,
        "data": {
            "taskId": "task-42",
            "status": "SUCCESS",
            "response": {
                "sunoData": [
                    {
                        "id": "audio-7",
                        "audioUrl": "https://cdn.example.test/song.mp3",
                        "title": "Night Drive",
                    }
                ]
            },
        },
    }
    result = SunoService.normalize_result("generate", payload)
    assert result["provider_task_id"] == "task-42"
    assert result["tracks"][0]["audio_id"] == "audio-7"
    assert result["tracks"][0]["audio_url"].endswith("song.mp3")


def test_max_suno_keeps_all_existing_creator_layers():
    assert issubclass(MaxSunoFullChannelService, MaxOmniChannelService)


def test_menu_compat_adds_suno_to_user_and_admin_keyboards():
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    class Keyboards:
        @staticmethod
        def get_main_menu_keyboard(*args, **kwargs):
            return InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Home", callback_data="home")]
                ]
            )

        @staticmethod
        def get_admin_keyboard(*args, **kwargs):
            return InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Admin", callback_data="admin")]
                ]
            )

    class Module:
        pass

    import bot.handlers.suno_menu_compat as compat

    monkey_installed = compat._INSTALLED
    compat._INSTALLED = False
    try:
        common = Module()
        admin = Module()
        common.get_main_menu_keyboard = Keyboards.get_main_menu_keyboard
        common.get_admin_keyboard = Keyboards.get_admin_keyboard
        admin.get_admin_keyboard = Keyboards.get_admin_keyboard
        install_suno_menu_compat(common, admin, Keyboards)
        main = common.get_main_menu_keyboard()
        admin_markup = admin.get_admin_keyboard()
        assert any(
            button.callback_data == "menu_suno"
            for row in main.inline_keyboard
            for button in row
        )
        assert any(
            button.callback_data == "admin_suno_prices"
            for row in admin_markup.inline_keyboard
            for button in row
        )
    finally:
        compat._INSTALLED = monkey_installed
