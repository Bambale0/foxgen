from typing import Any, cast

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from foxgen.bot.app import fallback_message, stale_callback
from foxgen.bot.states import GenerationStates


class StubState:
    def __init__(self, current: str | None) -> None:
        self.current = current
        self.cleared = False

    async def get_state(self) -> str | None:
        return self.current

    async def clear(self) -> None:
        self.cleared = True
        self.current = None


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


async def test_stale_callback_does_not_destroy_an_active_draft() -> None:
    state = StubState(GenerationStates.choosing_aspect_ratio.state)
    callback = StubCallback()

    await stale_callback(
        cast(CallbackQuery, callback),
        cast(FSMContext, state),
    )

    assert state.cleared is False
    assert callback.answers == [
        (
            "Эта кнопка не относится к текущему шагу. Используйте кнопки в последнем сообщении или /menu.",
            True,
        )
    ]


async def test_stale_callback_recovers_to_menu_after_ttl_expiry() -> None:
    state = StubState(None)
    callback = StubCallback()

    await stale_callback(
        cast(CallbackQuery, callback),
        cast(FSMContext, state),
    )

    assert state.cleared is True
    assert callback.answers[0][0].startswith("Срок действия кнопки истёк")
    assert callback.answers[0][1] is True


async def test_fallback_message_preserves_known_active_state() -> None:
    state = StubState(GenerationStates.reference_choosing_product.state)
    message = StubMessage()

    await fallback_message(
        cast(Message, message),
        cast(FSMContext, state),
    )

    assert state.cleared is False
    assert "незавершённый шаг" in message.answers[0][0]
    assert message.answers[0][1] == {}


async def test_fallback_message_clears_unknown_state_from_old_release() -> None:
    state = StubState("GenerationStates:removed_state")
    message = StubMessage()

    await fallback_message(
        cast(Message, message),
        cast(FSMContext, state),
    )

    assert state.cleared is True
    assert "старой версии" in message.answers[0][0]
    assert "reply_markup" in message.answers[0][1]
