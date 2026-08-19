from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

from aiogram import Bot
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from foxgen.bot import app as bot_app
from foxgen.bot.uploads import TelegramInputMediaStorage
from foxgen.core.config import Settings


class StubMessage:
    def __init__(self, *, chat_type: ChatType = ChatType.PRIVATE) -> None:
        self.text = "/menu"
        self.chat = SimpleNamespace(id=4242, type=chat_type)
        self.answers: list[tuple[str, dict[str, Any]]] = []

    async def answer(self, text: str, **kwargs: Any) -> None:
        self.answers.append((text, kwargs))


async def test_show_menu_refreshes_private_chat_webapp_override(monkeypatch: Any) -> None:
    clear_state = AsyncMock()
    configure_menu = AsyncMock()
    monkeypatch.setattr(bot_app, "clear_state_with_inputs", clear_state)
    monkeypatch.setattr(bot_app, "configure_miniapp_menu", configure_menu)
    monkeypatch.setattr(bot_app, "main_menu", lambda: object())

    message = StubMessage()
    bot = cast(Bot, object())
    settings = cast(Settings, object())

    await bot_app.show_menu(
        cast(Message, message),
        cast(FSMContext, object()),
        cast(TelegramInputMediaStorage, object()),
        bot=bot,
        settings=settings,
    )

    configure_menu.assert_awaited_once_with(bot, settings, chat_id=4242)
    assert message.answers


async def test_show_menu_does_not_set_chat_override_outside_private_chat(
    monkeypatch: Any,
) -> None:
    clear_state = AsyncMock()
    configure_menu = AsyncMock()
    monkeypatch.setattr(bot_app, "clear_state_with_inputs", clear_state)
    monkeypatch.setattr(bot_app, "configure_miniapp_menu", configure_menu)
    monkeypatch.setattr(bot_app, "main_menu", lambda: object())

    message = StubMessage(chat_type=ChatType.GROUP)

    await bot_app.show_menu(
        cast(Message, message),
        cast(FSMContext, object()),
        cast(TelegramInputMediaStorage, object()),
        bot=cast(Bot, object()),
        settings=cast(Settings, object()),
    )

    configure_menu.assert_not_awaited()


async def test_configure_miniapp_menu_targets_requested_private_chat(monkeypatch: Any) -> None:
    expected_url = "https://example.test/mini-app/?release=parity-v9"
    monkeypatch.setattr(bot_app, "resolve_miniapp_url", lambda settings: expected_url)
    set_chat_menu_button = AsyncMock()
    bot = cast(Bot, SimpleNamespace(set_chat_menu_button=set_chat_menu_button))

    await bot_app.configure_miniapp_menu(
        bot,
        cast(Settings, object()),
        chat_id=4242,
    )

    kwargs = set_chat_menu_button.await_args.kwargs
    assert kwargs["chat_id"] == 4242
    assert kwargs["menu_button"].web_app.url == expected_url
