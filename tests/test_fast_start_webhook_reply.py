import asyncio
import json
from types import SimpleNamespace

from aiogram.client.default import DefaultBotProperties
from aiogram.methods import SendMessage

from bot.config import config


class _Request:
    def __init__(self, body: dict) -> None:
        self.headers = {}
        self._body = json.dumps(body).encode()

    async def read(self) -> bytes:
        return self._body


class _Dispatcher:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def feed_update(self, bot, update, **kwargs):
        self.calls.append((bot, update, kwargs))
        return self.result


def _plain_start_update() -> dict:
    return {
        "update_id": 123,
        "message": {
            "message_id": 456,
            "date": 1_700_000_000,
            "chat": {"id": 42, "type": "private", "first_name": "Test"},
            "from": {"id": 42, "is_bot": False, "first_name": "Test"},
            "text": "/start",
            "entities": [{"offset": 0, "length": 6, "type": "bot_command"}],
        },
    }


def test_plain_start_can_reply_directly_in_webhook(monkeypatch) -> None:
    from bot.main import handle_telegram_webhook

    monkeypatch.setattr(config, "WEBHOOK_SECRET_TOKEN", "")
    monkeypatch.setattr(config, "INTERNAL_API_SECRET", "")

    method = SendMessage(chat_id=42, text="ok")
    dispatcher = _Dispatcher(method)
    bot = SimpleNamespace(default=DefaultBotProperties())

    response = asyncio.run(
        handle_telegram_webhook(_Request(_plain_start_update()), bot, dispatcher)
    )

    assert response.status == 200
    payload = json.loads(response.text)
    assert payload["method"] == "sendMessage"
    assert payload["chat_id"] == 42
    assert payload["text"] == "ok"
    assert dispatcher.calls[0][2]["webhook_reply_enabled"] is True


def test_deep_link_start_stays_background(monkeypatch) -> None:
    from bot.main import handle_telegram_webhook

    monkeypatch.setattr(config, "WEBHOOK_SECRET_TOKEN", "")
    monkeypatch.setattr(config, "INTERNAL_API_SECRET", "")

    update = _plain_start_update()
    update["message"]["text"] = "/start ref_TEST"
    dispatcher = _Dispatcher(SendMessage(chat_id=42, text="should-not-be-http-reply"))
    bot = SimpleNamespace(default=DefaultBotProperties())

    response = asyncio.run(handle_telegram_webhook(_Request(update), bot, dispatcher))

    assert response.status == 200
    assert response.text == "OK"


def test_dispatcher_propagates_direct_reply_context(monkeypatch) -> None:
    from aiogram import Dispatcher
    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.types import Update

    from bot.handlers import fast_start as fast_start_module

    class _State:
        pass

    user = SimpleNamespace(
        credits=15,
        referral_code="",
    )

    async def fake_get_or_create_user(_telegram_id):
        return user

    async def fake_sync(_user):
        return None

    monkeypatch.setattr(
        fast_start_module,
        "get_or_create_user",
        fake_get_or_create_user,
    )
    monkeypatch.setattr(fast_start_module, "_sync_telegram_profile", fake_sync)
    monkeypatch.setattr(
        fast_start_module,
        "_build_main_menu_text",
        lambda _credits: "welcome",
    )
    monkeypatch.setattr(
        fast_start_module,
        "get_main_menu_keyboard",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(fast_start_module, "_set_user_menu", lambda *_args: None)

    async def scenario():
        dispatcher = Dispatcher(storage=MemoryStorage())
        dispatcher.include_router(fast_start_module.router)

        bot = SimpleNamespace(
            id=999,
            default=DefaultBotProperties(),
        )
        update = Update.model_validate(_plain_start_update(), context={"bot": bot})

        result = await dispatcher.feed_update(
            bot,
            update,
            webhook_reply_enabled=True,
        )

        assert isinstance(result, SendMessage)
        assert result.chat_id == 42
        assert result.text == "welcome"

    asyncio.run(scenario())
