from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from foxgen.bot.api_client import BalanceView, PriceQuote, QueuedGeneration
from foxgen.bot.keyboards import main_menu
from foxgen.bot.states import VoiceStates
from foxgen.bot.voice import (
    TTS_MODEL_SLUG,
    begin_voice,
    choose_default_voice,
    choose_speed,
    confirm_voice,
    receive_text,
)


class FakeState:
    def __init__(self) -> None:
        self.data: dict[str, object] = {}
        self.current: str | None = None

    async def clear(self) -> None:
        self.data.clear()
        self.current = None

    async def update_data(self, **kwargs: object) -> None:
        self.data.update(kwargs)

    async def set_state(self, state: object) -> None:
        self.current = getattr(state, "state", str(state))

    async def get_data(self) -> dict[str, object]:
        return dict(self.data)

    async def get_state(self) -> str | None:
        return self.current


class FakeApi:
    def __init__(self, *, price: int | None = 42, balance: int = 100) -> None:
        self.price = price
        self.balance_units = balance
        self.submit_calls: list[dict[str, object]] = []

    async def prices(self) -> dict[str, PriceQuote]:
        if self.price is None:
            return {}
        return {
            TTS_MODEL_SLUG: PriceQuote(
                model_slug=TTS_MODEL_SLUG,
                amount_units=self.price,
                currency="CREDIT",
                version=1,
            )
        }

    async def balance(self, user_id: int) -> BalanceView:
        assert user_id == 777
        return BalanceView(
            available_units=self.balance_units,
            reserved_units=0,
            currency="CREDIT",
        )

    async def submit(self, **kwargs: object) -> QueuedGeneration:
        self.submit_calls.append(dict(kwargs))
        return QueuedGeneration(
            generation_id="11111111-2222-3333-4444-555555555555",
            status="queued",
            replayed=False,
        )


def callback(data: str) -> SimpleNamespace:
    message = SimpleNamespace(
        edit_text=AsyncMock(),
        answer=AsyncMock(),
    )
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=777, username="voice_user"),
        message=message,
        answer=AsyncMock(),
    )


def message(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        from_user=SimpleNamespace(id=777, username="voice_user"),
        answer=AsyncMock(),
    )


def test_main_menu_voice_entrypoint_is_live() -> None:
    markup = main_menu(miniapp_url="https://example.test/mini-app/")
    callbacks = {
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data is not None
    }

    assert "create:voice" in callbacks
    assert "planned:voice" not in callbacks


@pytest.mark.asyncio
async def test_voice_fsm_collects_text_voice_speed_then_quotes_price() -> None:
    state = FakeState()
    api = FakeApi(price=42, balance=100)

    start = callback("create:voice")
    await begin_voice(start, state)  # type: ignore[arg-type]
    assert state.current == VoiceStates.waiting_text.state
    assert state.data["model_slug"] == TTS_MODEL_SLUG
    assert str(state.data["idempotency_key"]).startswith("tts:777:")

    text_message = message("Привет! Это тестовая озвучка FoxGen.")
    await receive_text(text_message, state)  # type: ignore[arg-type]
    assert state.current == VoiceStates.waiting_voice.state
    assert state.data["text"] == "Привет! Это тестовая озвучка FoxGen."

    voice = callback("voice:default")
    await choose_default_voice(voice, state)  # type: ignore[arg-type]
    assert state.current == VoiceStates.choosing_speed.state
    assert state.data["voice"] == "Rachel"

    speed = callback("voice:speed:1.0")
    await choose_speed(speed, state, api)  # type: ignore[arg-type]
    assert state.current == VoiceStates.confirming.state
    assert state.data["speed"] == 1.0
    assert state.data["can_submit"] is True
    rendered = speed.message.edit_text.await_args.args[0]
    assert "Стоимость" in rendered
    assert "42 CREDIT" in rendered
    assert "Rachel" in rendered


@pytest.mark.asyncio
async def test_voice_confirmation_fails_closed_without_active_price() -> None:
    state = FakeState()
    api = FakeApi(price=None, balance=100)
    await state.update_data(
        model_slug=TTS_MODEL_SLUG,
        text="Текст",
        voice="Rachel",
        speed=1.0,
        idempotency_key="tts:777:missing-price",
    )
    await state.set_state(VoiceStates.choosing_speed)

    speed = callback("voice:speed:1.0")
    await choose_speed(speed, state, api)  # type: ignore[arg-type]

    assert state.current == VoiceStates.confirming.state
    assert state.data["can_submit"] is False
    rendered = speed.message.edit_text.await_args.args[0]
    assert "не опубликована активная цена" in rendered
    markup = speed.message.edit_text.await_args.kwargs["reply_markup"]
    callbacks = {
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data is not None
    }
    assert "voice:confirm" not in callbacks
    assert "voice:refresh" in callbacks


@pytest.mark.asyncio
async def test_voice_submit_uses_shared_paid_submission_and_exact_payload() -> None:
    state = FakeState()
    api = FakeApi(price=42, balance=100)
    await state.update_data(
        model_slug=TTS_MODEL_SLUG,
        text="Готовая озвучка",
        voice="Rachel",
        speed=1.2,
        idempotency_key="tts:777:stable-key",
        can_submit=True,
    )
    await state.set_state(VoiceStates.confirming)

    submit = callback("voice:confirm")
    await confirm_voice(submit, state, api)  # type: ignore[arg-type]

    assert state.current is None
    assert len(api.submit_calls) == 1
    call = api.submit_calls[0]
    assert call["user_id"] == 777
    assert call["username"] == "voice_user"
    assert call["model_slug"] == TTS_MODEL_SLUG
    assert call["idempotency_key"] == "tts:777:stable-key"
    assert call["input_data"] == {
        "text": "Готовая озвучка",
        "voice": "Rachel",
        "stability": 0.5,
        "similarity_boost": 0.75,
        "style": 0.0,
        "speed": 1.2,
        "timestamps": False,
        "previous_text": "",
        "next_text": "",
        "language_code": "",
    }
    final_message = submit.message.answer.await_args.args[0]
    assert "Озвучка поставлена в очередь" in final_message
