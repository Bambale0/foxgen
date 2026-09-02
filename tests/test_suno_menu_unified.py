from __future__ import annotations

import pytest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import bot.handlers.suno as suno_module
import bot.handlers.suno_menu_compat as compat
from bot.handlers.suno_menu_compat import install_suno_menu_compat
from bot.handlers.suno_priority import happyfox_music_entry


def test_existing_happyfox_music_button_is_not_duplicated():
    class Keyboards:
        @staticmethod
        def get_main_menu_keyboard(*args, **kwargs):
            return InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🎵 Создать музыку · Suno",
                            callback_data="happyfox_music",
                        )
                    ],
                    [InlineKeyboardButton(text="💳 Тарифы", callback_data="menu_topup")],
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

    installed_before = compat._INSTALLED
    compat._INSTALLED = False
    try:
        common = Module()
        admin = Module()
        common.get_main_menu_keyboard = Keyboards.get_main_menu_keyboard
        common.get_admin_keyboard = Keyboards.get_admin_keyboard
        admin.get_admin_keyboard = Keyboards.get_admin_keyboard

        install_suno_menu_compat(common, admin, Keyboards)

        main = common.get_main_menu_keyboard()
        callbacks = [
            button.callback_data
            for row in main.inline_keyboard
            for button in row
        ]
        assert callbacks.count("happyfox_music") == 1
        assert "menu_suno" not in callbacks
        assert any(
            button.callback_data == "admin_suno_prices"
            for row in admin.get_admin_keyboard().inline_keyboard
            for button in row
        )
    finally:
        compat._INSTALLED = installed_before


@pytest.mark.asyncio
async def test_primary_music_button_opens_real_suno_studio(monkeypatch):
    expected_markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Suno", callback_data="suno:generate")]
        ]
    )

    async def fake_suno_menu_keyboard():
        return expected_markup

    monkeypatch.setattr(suno_module, "suno_menu_keyboard", fake_suno_menu_keyboard)

    class State:
        cleared = False

        async def clear(self):
            self.cleared = True

    class Message:
        edited = None

        async def edit_text(self, text, **kwargs):
            self.edited = (text, kwargs)

    class Callback:
        answered = False

        def __init__(self):
            self.message = Message()

        async def answer(self):
            self.answered = True

    state = State()
    callback = Callback()

    await happyfox_music_entry(callback, state)

    assert state.cleared is True
    assert callback.answered is True
    assert callback.message.edited is not None
    text, kwargs = callback.message.edited
    assert "Suno Studio" in text
    assert kwargs["reply_markup"] is expected_markup
    assert kwargs["parse_mode"] == "HTML"
