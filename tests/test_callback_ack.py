import asyncio
from types import SimpleNamespace

from aiogram.methods import AnswerCallbackQuery

from bot.services import callback_ack


def test_safe_callback_allowlist() -> None:
    async def scenario():
        callback = SimpleNamespace(
            data="create_image_text_new",
            from_user=SimpleNamespace(id=7),
        )
        assert await callback_ack._should_ack_early(callback, {}) is True

    asyncio.run(scenario())


def test_seedream_missing_reference_keeps_custom_alert_path() -> None:
    class State:
        async def get_data(self):
            return {
                "generation_type": "image",
                "img_service": "seedream_edit",
                "reference_images": [],
            }

    async def scenario():
        callback = SimpleNamespace(
            data="img_ref_continue_new",
            from_user=SimpleNamespace(id=7),
        )
        assert await callback_ack._should_ack_early(
            callback,
            {"state": State()},
        ) is False

    asyncio.run(scenario())


def test_normal_reference_continue_can_ack_early() -> None:
    class State:
        async def get_data(self):
            return {
                "generation_type": "image",
                "img_service": "banana_pro",
                "reference_images": [],
            }

    async def scenario():
        callback = SimpleNamespace(
            data="img_ref_continue_new",
            from_user=SimpleNamespace(id=7),
        )
        assert await callback_ack._should_ack_early(
            callback,
            {"state": State()},
        ) is True

    asyncio.run(scenario())


def test_session_middleware_reuses_inflight_plain_ack() -> None:
    calls = 0

    async def make_request(_bot, _method):
        nonlocal calls
        calls += 1
        return "network"

    async def early_result():
        await asyncio.sleep(0)
        return True

    async def scenario():
        state = callback_ack._EarlyAckState(callback_query_id="cb-1")
        token = callback_ack._EARLY_ACK_STATE.set(state)
        state.task = asyncio.create_task(early_result())
        try:
            result = await callback_ack.early_callback_ack_session_middleware(
                make_request,
                SimpleNamespace(),
                AnswerCallbackQuery(callback_query_id="cb-1"),
            )
        finally:
            callback_ack._EARLY_ACK_STATE.reset(token)
        return result

    assert asyncio.run(scenario()) is True
    assert calls == 0


def test_custom_answer_is_never_suppressed() -> None:
    calls = 0

    async def make_request(_bot, _method):
        nonlocal calls
        calls += 1
        return "network"

    async def early_result():
        return True

    async def scenario():
        state = callback_ack._EarlyAckState(callback_query_id="cb-2")
        token = callback_ack._EARLY_ACK_STATE.set(state)
        state.task = asyncio.create_task(early_result())
        try:
            return await callback_ack.early_callback_ack_session_middleware(
                make_request,
                SimpleNamespace(),
                AnswerCallbackQuery(
                    callback_query_id="cb-2",
                    text="custom",
                    show_alert=True,
                ),
            )
        finally:
            callback_ack._EARLY_ACK_STATE.reset(token)

    assert asyncio.run(scenario()) == "network"
    assert calls == 1


def test_early_ack_middleware_overlaps_work_and_sends_once() -> None:
    import time

    from aiogram.types import CallbackQuery

    network_calls = 0
    network_started = asyncio.Event()

    async def network_request(_bot, _method):
        nonlocal network_calls
        network_calls += 1
        network_started.set()
        await asyncio.sleep(0.05)
        return True

    class FakeBot:
        id = 999

        async def __call__(self, method):
            return await callback_ack.early_callback_ack_session_middleware(
                network_request,
                self,
                method,
            )

    async def scenario():
        bot = FakeBot()
        callback = CallbackQuery.model_validate(
            {
                "id": "cb-integration",
                "from": {
                    "id": 7,
                    "is_bot": False,
                    "first_name": "Test",
                },
                "chat_instance": "ci",
                "data": "create_image_text_new",
            },
            context={"bot": bot},
        )
        middleware = callback_ack.EarlyCallbackAckMiddleware()

        async def legacy_handler(event, _data):
            await network_started.wait()
            await asyncio.sleep(0.02)
            assert await event.answer() is True
            return "ok"

        started = time.perf_counter()
        result = await middleware(legacy_handler, callback, {})
        elapsed = time.perf_counter() - started
        return result, elapsed

    result, elapsed = asyncio.run(scenario())
    assert result == "ok"
    assert network_calls == 1
    assert elapsed < 0.09
