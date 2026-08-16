from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from foxgen.bot.api_client import BalanceView, PriceQuote, QueuedGeneration
from foxgen.bot.states import MusicExtendStates
from foxgen.bot.suno_extend_flow import (
    SUNO_EXTEND_MODEL_SLUG,
    begin_extend,
    begin_music_hub,
    choose_extend_mode,
    choose_extend_source,
    confirm_extend,
    receive_continue_at,
    receive_extend_prompt,
    receive_extend_style,
    receive_extend_title,
)
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
async def test_music_entry_opens_new_or_extend_hub() -> None:
    state = FakeState()
    start = callback("create:music")

    await begin_music_hub(start, state)  # type: ignore[arg-type]

    assert state.current == MusicExtendStates.choosing_action.state
    markup = start.message.edit_text.await_args.kwargs["reply_markup"]
    callbacks = {
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data is not None
    }
    assert "music:new" in callbacks
    assert "music:extend:start" in callbacks


@pytest.mark.asyncio
async def test_extend_source_picker_stores_only_index_selected_owner_source(
    monkeypatch: pytest.MonkeyPatch,
    owned_source: SunoSourceView,
) -> None:
    state = FakeState()
    await begin_music_hub(callback("create:music"), state)  # type: ignore[arg-type]

    async def fake_sources(*, user_id: int) -> tuple[SunoSourceView, ...]:
        assert user_id == 889
        return (owned_source,)

    monkeypatch.setattr("foxgen.bot.suno_extend_flow.list_suno_sources", fake_sources)
    start = callback("music:extend:start")
    await begin_extend(start, state)  # type: ignore[arg-type]

    assert state.current == MusicExtendStates.choosing_source.state
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
    assert state.current == MusicExtendStates.choosing_mode.state
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
        extend_source_generation_id=owned_source.generation_id,
        extend_audio_id=owned_source.audio_id,
        extend_source_title=owned_source.title,
        extend_source_duration=owned_source.duration_seconds,
        idempotency_key="suno-extend:889:inherit",
    )
    await state.set_state(MusicExtendStates.choosing_mode)

    choose = callback("music:extend:mode:inherit")
    await choose_extend_mode(choose, state, api)  # type: ignore[arg-type]

    assert state.current == MusicExtendStates.confirming.state
    assert state.data["default_param_flag"] is False
    assert state.data["can_submit"] is True
    rendered = choose.message.edit_text.await_args.args[0]
    assert "30 CREDIT" in rendered
    assert "с исходными параметрами" in rendered


@pytest.mark.asyncio
async def test_custom_extend_collects_prompt_style_title_and_continue_at(
    owned_source: SunoSourceView,
) -> None:
    state = FakeState()
    api = FakeApi()
    await state.update_data(
        extend_source_generation_id=owned_source.generation_id,
        extend_audio_id=owned_source.audio_id,
        extend_source_title=owned_source.title,
        extend_source_duration=owned_source.duration_seconds,
        idempotency_key="suno-extend:889:custom",
    )
    await state.set_state(MusicExtendStates.choosing_mode)

    await choose_extend_mode(callback("music:extend:mode:custom"), state, api)  # type: ignore[arg-type]
    assert state.current == MusicExtendStates.waiting_prompt.state

    await receive_extend_prompt(message("Continue into a bigger final chorus"), state)  # type: ignore[arg-type]
    assert state.current == MusicExtendStates.waiting_style.state

    await receive_extend_style(message("indie pop, warm female vocal"), state)  # type: ignore[arg-type]
    assert state.current == MusicExtendStates.waiting_title.state

    await receive_extend_title(message("Last Train Extended"), state)  # type: ignore[arg-type]
    assert state.current == MusicExtendStates.waiting_continue_at.state

    at = message("92.5")
    await receive_continue_at(at, state, api)  # type: ignore[arg-type]
    assert state.current == MusicExtendStates.confirming.state
    assert state.data["continue_at"] == 92.5
    assert state.data["can_submit"] is True


@pytest.mark.asyncio
async def test_custom_extend_rejects_point_after_source_end(
    owned_source: SunoSourceView,
) -> None:
    state = FakeState()
    api = FakeApi()
    await state.update_data(extend_source_duration=owned_source.duration_seconds)
    await state.set_state(MusicExtendStates.waiting_continue_at)

    at = message("120")
    await receive_continue_at(at, state, api)  # type: ignore[arg-type]

    assert state.current == MusicExtendStates.waiting_continue_at.state
    assert "раньше конца исходного трека" in at.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_extend_confirmation_fails_closed_without_price(
    owned_source: SunoSourceView,
) -> None:
    state = FakeState()
    api = FakeApi(price=None, balance=100)
    await state.update_data(
        extend_source_generation_id=owned_source.generation_id,
        extend_audio_id=owned_source.audio_id,
        extend_source_title=owned_source.title,
        extend_source_duration=owned_source.duration_seconds,
        idempotency_key="suno-extend:889:no-price",
    )
    await state.set_state(MusicExtendStates.choosing_mode)

    choose = callback("music:extend:mode:inherit")
    await choose_extend_mode(choose, state, api)  # type: ignore[arg-type]

    assert state.data["can_submit"] is False
    rendered = choose.message.edit_text.await_args.args[0]
    assert "не опубликована активная цена" in rendered


@pytest.mark.asyncio
async def test_extend_submit_calls_owner_transport_not_generic_submit(
    monkeypatch: pytest.MonkeyPatch,
    owned_source: SunoSourceView,
) -> None:
    state = FakeState()
    await state.update_data(
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
    await state.set_state(MusicExtendStates.confirming)
    calls: list[dict[str, object]] = []

    async def fake_submit(**kwargs: object) -> QueuedGeneration:
        calls.append(dict(kwargs))
        return QueuedGeneration(
            generation_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            status="queued",
            replayed=False,
        )

    monkeypatch.setattr("foxgen.bot.suno_extend_flow.submit_suno_extend", fake_submit)
    submit = callback("music:extend:confirm")
    await confirm_extend(submit, state)  # type: ignore[arg-type]

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
                "continue_at": 92.5,
                "negative_tags": "",
            },
            "idempotency_key": "suno-extend:889:stable",
        }
    ]
    assert state.current is None
