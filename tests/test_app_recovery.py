from typing import Any, cast

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from foxgen.bot.app import fallback_message, show_menu, stale_callback
from foxgen.bot.states import FeedStates, GenerationStates
from foxgen.bot.uploads import InputCleanupResult, TelegramInputMediaStorage


class StubState:
    def __init__(self, current: str | None, data: dict[str, object] | None = None) -> None:
        self.current = current
        self.data = data or {}
        self.cleared = False

    async def get_state(self) -> str | None:
        return self.current

    async def get_data(self) -> dict[str, object]:
        return dict(self.data)

    async def clear(self) -> None:
        self.cleared = True
        self.current = None
        self.data = {}


class StubInputMedia:
    def __init__(self) -> None:
        self.deleted: tuple[str, ...] = ()

    async def delete_many(self, storage_keys: tuple[str, ...]) -> InputCleanupResult:
        self.deleted = storage_keys
        return InputCleanupResult(deleted=storage_keys, failed=())


class StubCallback:
    def __init__(self) -> None:
        self.message = None
        self.answers: list[tuple[str, bool]] = []

    async def answer(self, text: str, *, show_alert: bool = False) -> None:
        self.answers.append((text, show_alert))


class StubMessage:
    def __init__(self) -> None:
        self.answers: list[tuple[str, dict[str, Any]]] = []

    async def answer(self, text: str, **kwargs: Any) -> None:
        self.answers.append((text, kwargs))


ALL_FSM_STATES = [
    *(state.state for state in GenerationStates.__all_states__),
    *(state.state for state in FeedStates.__all_states__),
]


@pytest.mark.parametrize("current", ALL_FSM_STATES)
async def test_start_interrupts_every_fsm_state_and_cleans_inputs(current: str) -> None:
    state = StubState(
        current,
        data={"media": [{"kind": "image", "storage_key": "inputs/7/file.jpg"}]},
    )
    message = StubMessage()
    media = StubInputMedia()

    await show_menu(
        cast(Message, message),
        cast(FSMContext, state),
        cast(TelegramInputMediaStorage, media),
    )

    assert state.cleared is True
    assert state.current is None
    assert media.deleted == ("inputs/7/file.jpg",)
    assert message.answers
    assert message.answers[0][0].startswith("<b>FoxGen</b>")
    assert "reply_markup" in message.answers[0][1]


async def test_stale_callback_does_not_destroy_an_active_draft() -> None:
    state = StubState(GenerationStates.choosing_aspect_ratio.state)
    callback = StubCallback()
    media = StubInputMedia()

    await stale_callback(
        cast(CallbackQuery, callback),
        cast(FSMContext, state),
        cast(TelegramInputMediaStorage, media),
    )

    assert state.cleared is False
    assert media.deleted == ()
    assert callback.answers == [
        (
            "Эта кнопка не относится к текущему шагу. Используйте кнопки в последнем сообщении или /menu.",
            True,
        )
    ]


async def test_stale_callback_recovers_to_menu_after_ttl_expiry() -> None:
    state = StubState(None)
    callback = StubCallback()
    media = StubInputMedia()

    await stale_callback(
        cast(CallbackQuery, callback),
        cast(FSMContext, state),
        cast(TelegramInputMediaStorage, media),
    )

    assert state.cleared is True
    assert callback.answers[0][0].startswith("Срок действия кнопки истёк")
    assert callback.answers[0][1] is True


async def test_fallback_message_preserves_known_active_state() -> None:
    state = StubState(GenerationStates.reference_choosing_product.state)
    message = StubMessage()
    media = StubInputMedia()

    await fallback_message(
        cast(Message, message),
        cast(FSMContext, state),
        cast(TelegramInputMediaStorage, media),
    )

    assert state.cleared is False
    assert media.deleted == ()
    assert "незавершённый шаг" in message.answers[0][0]
    assert message.answers[0][1] == {}


async def test_fallback_message_cleans_unknown_state_from_old_release() -> None:
    state = StubState(
        "GenerationStates:removed_state",
        data={"media": [{"kind": "image", "storage_key": "inputs/7/file.jpg"}]},
    )
    message = StubMessage()
    media = StubInputMedia()

    await fallback_message(
        cast(Message, message),
        cast(FSMContext, state),
        cast(TelegramInputMediaStorage, media),
    )

    assert state.cleared is True
    assert media.deleted == ("inputs/7/file.jpg",)
    assert "старой версии" in message.answers[0][0]
    assert "reply_markup" in message.answers[0][1]
