import asyncio
import logging
from types import SimpleNamespace

from aiogram.client.default import DefaultBotProperties
from aiogram.methods import SendMessage
from aiogram.types import Update

from bot.services import telegram_telemetry as telemetry


def _update(text: str = "/start") -> Update:
    payload = {
        "update_id": 321,
        "message": {
            "message_id": 654,
            "date": 1_700_000_000,
            "chat": {"id": 42, "type": "private", "first_name": "Test"},
            "from": {"id": 7, "is_bot": False, "first_name": "Test"},
            "text": text,
        },
    }
    return Update.model_validate(payload)


def test_describe_update_routes_commands_and_callbacks() -> None:
    event_type, route, user_id, chat_id = telemetry.describe_update(
        _update("/Start@AlePolbot anything")
    )
    assert event_type == "message"
    assert route == "/start"
    assert user_id == 7
    assert chat_id == 42

    callback = Update.model_validate(
        {
            "update_id": 322,
            "callback_query": {
                "id": "cb",
                "from": {"id": 7, "is_bot": False, "first_name": "Test"},
                "chat_instance": "ci",
                "data": "menu_balance",
                "message": {
                    "message_id": 655,
                    "date": 1_700_000_000,
                    "chat": {"id": 42, "type": "private", "first_name": "Test"},
                },
            },
        }
    )
    event_type, route, user_id, chat_id = telemetry.describe_update(callback)
    assert event_type == "callback_query"
    assert route == "callback:menu_balance"
    assert user_id == 7
    assert chat_id == 42


def test_update_summary_correlates_bot_api_and_handler(caplog) -> None:
    async def resolved_handler(_event, _data):
        method = SendMessage(chat_id=42, text="ok")

        async def fake_request(_bot, _method):
            await asyncio.sleep(0)
            return True

        await telemetry.telegram_bot_api_telemetry_middleware(
            fake_request,
            SimpleNamespace(),
            method,
        )

    async def update_handler(event, data):
        handler_middleware = telemetry.TelegramResolvedHandlerTelemetryMiddleware()

        async def concrete_handler(_event, _data):
            return await resolved_handler(_event, _data)

        data = dict(data)
        data["handler"] = SimpleNamespace(callback=resolved_handler)
        return await handler_middleware(concrete_handler, event.message, data)

    async def scenario():
        middleware = telemetry.TelegramUpdateTelemetryMiddleware()
        return await middleware(update_handler, _update(), {})

    with caplog.at_level(logging.INFO, logger="bot.telemetry.telegram"):
        asyncio.run(scenario())

    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "telegram_bot_api method=sendMessage update_id=321" in text
    assert "route=/start" in text
    assert "test_update_summary_correlates_bot_api_and_handler" in text
    assert "telegram_update update_id=321" in text
    assert "bot_api_calls=1" in text
    assert "bot_api_slowest_method=sendMessage" in text


def test_bot_api_error_is_logged_and_reraised(caplog) -> None:
    async def failing_request(_bot, _method):
        raise RuntimeError("boom")

    async def scenario():
        token = telemetry._CURRENT_TELEGRAM_CONTEXT.set(
            telemetry.TelegramTelemetryContext(
                update_id=99,
                event_type="callback_query",
                route="callback:test",
            )
        )
        try:
            await telemetry.telegram_bot_api_telemetry_middleware(
                failing_request,
                SimpleNamespace(),
                SendMessage(chat_id=42, text="x"),
            )
        finally:
            telemetry._CURRENT_TELEGRAM_CONTEXT.reset(token)

    with caplog.at_level(logging.INFO, logger="bot.telemetry.telegram"):
        try:
            asyncio.run(scenario())
        except RuntimeError:
            pass
        else:
            raise AssertionError("RuntimeError was not reraised")

    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "outcome=error" in text
    assert "error_type=RuntimeError" in text


def test_install_bot_api_telemetry_is_idempotent() -> None:
    class MiddlewareManager:
        def __init__(self):
            self.items = []

        def register(self, item):
            self.items.append(item)

    session = SimpleNamespace(middleware=MiddlewareManager())
    bot = SimpleNamespace(
        session=session,
        default=DefaultBotProperties(),
    )

    telemetry.install_telegram_bot_api_telemetry(bot)
    telemetry.install_telegram_bot_api_telemetry(bot)

    assert session.middleware.items == [telemetry.telegram_bot_api_telemetry_middleware]



def test_dispatcher_captures_child_router_handler(caplog) -> None:
    from aiogram import Dispatcher, Router
    from aiogram.filters import Command
    from aiogram.fsm.storage.memory import MemoryStorage

    router = Router()

    @router.message(Command("start"))
    async def child_start(_message):
        return None

    async def scenario():
        dispatcher = Dispatcher(storage=MemoryStorage())
        dispatcher.update.outer_middleware(
            telemetry.TelegramUpdateTelemetryMiddleware()
        )
        resolved = telemetry.TelegramResolvedHandlerTelemetryMiddleware()
        for observer_name, observer in dispatcher.observers.items():
            if observer_name not in {"update", "error"}:
                observer.middleware(resolved)
        dispatcher.include_router(router)

        bot = SimpleNamespace(id=999)
        await dispatcher.feed_update(bot, _update())

    with caplog.at_level(logging.INFO, logger="bot.telemetry.telegram"):
        asyncio.run(scenario())

    summaries = [
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith("telegram_update ")
    ]
    assert len(summaries) == 1
    assert "update_id=321" in summaries[0]
    assert "route=/start" in summaries[0]
    assert "child_start" in summaries[0]



def test_webhook_ack_log_contains_mode_and_release(caplog, monkeypatch) -> None:
    monkeypatch.setattr(telemetry, "RELEASE", "deadbeef")

    with caplog.at_level(logging.INFO, logger="bot.telemetry.telegram"):
        telemetry.log_telegram_webhook_ack(
            update_id=77,
            mode="background",
            started_at=telemetry.time.perf_counter(),
        )

    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "telegram_webhook_ack update_id=77 mode=background" in text
    assert "release=deadbeef" in text
