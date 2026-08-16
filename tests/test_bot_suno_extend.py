from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from foxgen.bot.api_client import BalanceView, PriceQuote, QueuedGeneration
from foxgen.bot.music import (
    SUNO_EXTEND_MODEL_SLUG,
    begin_extend,
    begin_music,
    choose_extend_mode,
    choose_extend_source,
    confirm_music,
    receive_prompt,
    receive_style,
    receive_title,
)
from foxgen.bot.states import MusicStates
from foxgen.bot.suno_extend_transport import SunoSourceView


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
    def __init__(self, *, price: int | None = 30, balance: int = 100) -> None:
        self.price = price
        self.balance_units = balance
        self.submit_calls: list[dict[str, object]] = []

    async def prices(self) -> dict[str, PriceQuote]:
        if self.price is None:
            return {}
        return {
            SUNO_EXTEND_MODEL_SLUG: PriceQuote(
                model_slug=SUNO_EXTEND_MODEL_SLUG,
                amount_units=self.price,
                currency="CREDIT",
                version=1,
            )
        }

    async def balance(self, user_id: int) -> BalanceView:
        assert user_id == 889
        return BalanceView(
            available_units=self.balance_units,
            reserved_units=0,
            currency="CREDIT",
        )

    async def submit(self, **kwargs: object) -> QueuedGeneration:
        self.submit_calls.append(dict(kwargs))
        raise AssertionError("Extend must not use generic submit")


def callback(data: str) -> SimpleNamespace:
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=889, username="extend_user"),
        message=SimpleNamespace(edit_text=AsyncMock(), answer=AsyncMock()),
        answer=AsyncMock(),
    )


def message(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        from_user=SimpleNamespace(id=889, username="extend_user"),
        answer=AsyncMock(),
    )


@pytest.fixture
def owned_source() -> SunoSourceView:
    return SunoSourceView(
        generation_id="11111111-2222-3333-4444-555555555555",
        model_slug="suno-v5",
        audio_id="owned-track-a",
        title="Last Train",
        duration_seconds=120.0,
        preview_url="https://storage.example.test/owned.mp3",
    )


@pytest.mark.asyncio
async def test_extend_source_picker_stores_only_index_selected_owner_source(
    monkeypatch: pytest.MonkeyPatch,
    owned_source: SunoSourceView,
) -> None:
    state = FakeState()
    await begin_music(callback("create:music"), state)  # type: ignore[arg-type]

    async def fake_sources(*, user_id: int) -> tuple[SunoSourceView, ...]:
        assert user_id == 889
        return (owned_source,)

    monkeypatch.setattr("foxgen.bot.music.list_suno_sources", fake_sources)
    start = callback("music:extend:start")
    await begin_extend(start, state)  # type: ignore[arg-type]

    assert state.current == MusicStates.choosing_mode.state
    items = state.data["extend_sources"]
    assert isinstance(items, list)
    assert items[0]["audio_id"] == "owned-track-a"
    markup = start.message.edit_text.await_args.kwargs["reply_markup"]
    callbacks = [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    ]
    assert "music:extend:source:0" in callbacks
    assert all("owned-track-a" not in value for value in callbacks)

    select = callback("music:extend:source:0")
    await choose_extend_source(select, state)  # type: ignore[arg-type]
    assert state.current == MusicStates.choosing_vocal_mode.state
    assert state.data["extend_flow"] is True
    assert state.data["extend_source_generation_id"] == owned_source.generation_id
    assert state.data["extend_audio_id"] == owned_source.audio_id
    assert str(state.data["idempotency_key"]).startswith("suno-extend:889:")


@pytest.mark.asyncio
async def test_inherited_extend_quotes_extend_price_not_core_price(
    owned_source: SunoSourceView,
) -> None:
    state = FakeState()
    api = FakeApi(price=30, balance=100)
    await state.update_data(
        extend_flow=True,
        extend_source_generation_id=owned_source.generation_id,
        extend_audio_id=owned_source.audio_id,
        extend_source_title=owned_source.title,
        extend_source_duration=owned_source.duration_seconds,
        idempotency_key="suno-extend:889:inherit",
    )
    await state.set_state(MusicStates.choosing_vocal_mode)

    choose = callback("music:extend:mode:inherit")
    await choose_extend_mode(choose, state, api)  # type: ignore[arg-type]

    assert state.current == MusicStates.confirming.state
    assert state.data["default_param_flag"] is False
    assert state.data["can_submit"] is True
    rendered = choose.message.edit_text.await_args.args[0]
    assert "30 CREDIT" in rendered
    assert "исходными параметрами" in rendered


@pytest.mark.asyncio
async def test_custom_extend_collects_prompt_style_title_and_continue_at(
    owned_source: SunoSourceView,
) -> None:
    state = FakeState()
    api = FakeApi()
    await state.update_data(
        extend_flow=True,
        extend_source_generation_id=owned_source.generation_id,
        extend_audio_id=owned_source.audio_id,
        extend_source_title=owned_source.title,
        extend_source_duration=owned_source.duration_seconds,
        idempotency_key="suno-extend:889:custom",
    )
    await state.set_state(MusicStates.choosing_vocal_mode)

    await choose_extend_mode(callback("music:extend:mode:custom"), state, api)  # type: ignore[arg-type]
    assert state.current == MusicStates.waiting_prompt.state
    await receive_prompt(message("Continue into a bigger final chorus"), state, api)  # type: ignore[arg-type]
    assert state.current == MusicStates.waiting_style.state
    await receive_style(message("indie pop, warm female vocal"), state)  # type: ignore[arg-type]
    assert state.current == MusicStates.waiting_title.state
    await receive_title(message("Last Train Extended"), state, api)  # type: ignore[arg-type]
    assert state.current == MusicStates.waiting_prompt.state
    assert state.data["extend_waiting_continue"] is True

    at = message("92.5")
    await receive_prompt(at, state, api)  # type: ignore[arg-type]
    assert state.current == MusicStates.confirming.state
    assert state.data["continue_at"] == 92.5
    assert state.data["can_submit"] is True


@pytest.mark.asyncio
async def test_custom_extend_rejects_point_after_source_end(
    owned_source: SunoSourceView,
) -> None:
    state = FakeState()
    api = FakeApi()
    await state.update_data(
        extend_flow=True,
        extend_waiting_continue=True,
        extend_source_duration=owned_source.duration_seconds,
    )
    await state.set_state(MusicStates.waiting_prompt)

    at = message("120")
    await receive_prompt(at, state, api)  # type: ignore[arg-type]

    assert state.current == MusicStates.waiting_prompt.state
    assert "раньше его окончания" in at.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_extend_submit_calls_owner_transport_not_generic_submit(
    monkeypatch: pytest.MonkeyPatch,
    owned_source: SunoSourceView,
) -> None:
    state = FakeState()
    api = FakeApi()
    await state.update_data(
        extend_flow=True,
        default_param_flag=True,
        prompt="Continue into a bigger final chorus",
        style="indie pop",
        title="Last Train Extended",
        negative_tags="",
        continue_at=92.5,
        extend_source_generation_id=owned_source.generation_id,
        extend_audio_id=owned_source.audio_id,
        idempotency_key="suno-extend:889:stable",
        can_submit=True,
    )
    await state.set_state(MusicStates.confirming)
    calls: list[dict[str, object]] = []

    async def fake_submit(**kwargs: object) -> QueuedGeneration:
        calls.append(dict(kwargs))
        return QueuedGeneration(
            generation_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            status="queued",
            replayed=False,
        )

    monkeypatch.setattr("foxgen.bot.music.submit_suno_extend", fake_submit)
    submit = callback("music:confirm")
    await confirm_music(submit, state, api)  # type: ignore[arg-type]

    assert api.submit_calls == []
    assert calls == [
        {
            "user_id": 889,
            "username": "extend_user",
            "source_generation_id": owned_source.generation_id,
            "audio_id": owned_source.audio_id,
            "input_data": {
                "default_param_flag": True,
                "prompt": "Continue into a bigger final chorus",
                "style": "indie pop",
                "title": "Last Train Extended",
                "negative_tags": "",
                "continue_at": 92.5,
            },
            "idempotency_key": "suno-extend:889:stable",
        }
    ]
    assert state.current is None
