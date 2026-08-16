from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from foxgen.bot.api_client import BalanceView, PriceQuote, QueuedGeneration
from foxgen.bot.keyboards import main_menu
from foxgen.bot.music import (
    SUNO_MODEL_SLUG,
    begin_music,
    choose_mode,
    choose_vocal_mode,
    confirm_music,
    receive_prompt,
    receive_style,
    receive_title,
)
from foxgen.bot.states import MusicStates


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
    def __init__(self, *, price: int | None = 55, balance: int = 200) -> None:
        self.price = price
        self.balance_units = balance
        self.submit_calls: list[dict[str, object]] = []

    async def prices(self) -> dict[str, PriceQuote]:
        if self.price is None:
            return {}
        return {
            SUNO_MODEL_SLUG: PriceQuote(
                model_slug=SUNO_MODEL_SLUG,
                amount_units=self.price,
                currency="CREDIT",
                version=1,
            )
        }

    async def balance(self, user_id: int) -> BalanceView:
        assert user_id == 888
        return BalanceView(
            available_units=self.balance_units,
            reserved_units=0,
            currency="CREDIT",
        )

    async def submit(self, **kwargs: object) -> QueuedGeneration:
        self.submit_calls.append(dict(kwargs))
        return QueuedGeneration(
            generation_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            status="queued",
            replayed=False,
        )


def callback(data: str) -> SimpleNamespace:
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=888, username="music_user"),
        message=SimpleNamespace(edit_text=AsyncMock(), answer=AsyncMock()),
        answer=AsyncMock(),
    )


def message(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        from_user=SimpleNamespace(id=888, username="music_user"),
        answer=AsyncMock(),
    )


def test_main_menu_music_entrypoint_is_live() -> None:
    markup = main_menu(miniapp_url="https://example.test/mini-app/")
    callbacks = {
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data is not None
    }

    assert "create:music" in callbacks
    assert "planned:music" not in callbacks


@pytest.mark.asyncio
async def test_simple_music_flow_quotes_backend_price() -> None:
    state = FakeState()
    api = FakeApi(price=55, balance=200)

    start = callback("create:music")
    await begin_music(start, state)  # type: ignore[arg-type]
    assert state.current == MusicStates.choosing_mode.state
    assert str(state.data["idempotency_key"]).startswith("music:888:")

    mode = callback("music:mode:simple")
    await choose_mode(mode, state)  # type: ignore[arg-type]
    assert state.current == MusicStates.choosing_vocal_mode.state

    vocal = callback("music:vocal:no")
    await choose_vocal_mode(vocal, state)  # type: ignore[arg-type]
    assert state.current == MusicStates.waiting_prompt.state

    prompt = message("Warm indie pop song about a fox on a night train")
    await receive_prompt(prompt, state, api)  # type: ignore[arg-type]
    assert state.current == MusicStates.confirming.state
    assert state.data["can_submit"] is True
    rendered = prompt.answer.await_args.args[0]
    assert "55 CREDIT" in rendered
    assert "быстрый" in rendered
    assert "с вокалом" in rendered


@pytest.mark.asyncio
async def test_music_flow_fails_closed_without_price() -> None:
    state = FakeState()
    api = FakeApi(price=None)
    await state.update_data(
        custom_mode=False,
        instrumental=True,
        prompt="Dark cinematic instrumental",
        style="",
        title="",
        idempotency_key="music:888:no-price",
    )
    await state.set_state(MusicStates.waiting_prompt)

    prompt = message("Dark cinematic instrumental")
    await receive_prompt(prompt, state, api)  # type: ignore[arg-type]

    assert state.current == MusicStates.confirming.state
    assert state.data["can_submit"] is False
    rendered = prompt.answer.await_args.args[0]
    assert "не опубликована активная цена" in rendered
    markup = prompt.answer.await_args.kwargs["reply_markup"]
    callbacks = {
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data is not None
    }
    assert "music:confirm" not in callbacks
    assert "music:refresh" in callbacks


@pytest.mark.asyncio
async def test_custom_instrumental_skips_lyrics_and_collects_style_title() -> None:
    state = FakeState()
    api = FakeApi()
    await begin_music(callback("create:music"), state)  # type: ignore[arg-type]
    await choose_mode(callback("music:mode:custom"), state)  # type: ignore[arg-type]
    await choose_vocal_mode(callback("music:vocal:yes"), state)  # type: ignore[arg-type]

    assert state.current == MusicStates.waiting_style.state
    await receive_style(message("cinematic synthwave, 110 BPM"), state)  # type: ignore[arg-type]
    assert state.current == MusicStates.waiting_title.state
    title = message("Neon Fox")
    await receive_title(title, state, api)  # type: ignore[arg-type]

    assert state.current == MusicStates.confirming.state
    assert state.data["prompt"] == ""
    assert state.data["style"] == "cinematic synthwave, 110 BPM"
    assert state.data["title"] == "Neon Fox"
    assert state.data["can_submit"] is True


@pytest.mark.asyncio
async def test_music_submit_reuses_shared_paid_submission_exactly_once() -> None:
    state = FakeState()
    api = FakeApi()
    await state.update_data(
        custom_mode=True,
        instrumental=False,
        prompt="[Verse] City lights and empty roads",
        style="indie pop, warm female vocal",
        title="Last Train",
        negative_tags="metal",
        idempotency_key="music:888:stable-key",
        can_submit=True,
    )
    await state.set_state(MusicStates.confirming)

    submit = callback("music:confirm")
    await confirm_music(submit, state, api)  # type: ignore[arg-type]

    assert state.current is None
    assert len(api.submit_calls) == 1
    call = api.submit_calls[0]
    assert call["user_id"] == 888
    assert call["username"] == "music_user"
    assert call["model_slug"] == SUNO_MODEL_SLUG
    assert call["idempotency_key"] == "music:888:stable-key"
    assert call["input_data"] == {
        "custom_mode": True,
        "instrumental": False,
        "prompt": "[Verse] City lights and empty roads",
        "style": "indie pop, warm female vocal",
        "title": "Last Train",
        "negative_tags": "metal",
    }
    assert "Музыка поставлена в очередь" in submit.message.answer.await_args.args[0]
