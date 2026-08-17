from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from foxgen.bot.api_client import BalanceView, PriceQuote, QueuedGeneration
from foxgen.bot.states import MusicExtendStates, MusicUploadExtendStates
from foxgen.bot.suno_upload_cover_contract import MUSIC_UPLOAD_STATE_NAMES, is_cover_state
from foxgen.bot.suno_upload_extend_flow import (
    MODEL_SLUG,
    begin_upload_extend,
    choose_upload_extend_mode,
    choose_upload_extend_vocal,
    confirm_upload_extend,
    receive_upload_extend_audio,
    receive_upload_extend_continue_at,
    receive_upload_extend_prompt,
    receive_upload_extend_style,
    receive_upload_extend_title,
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


class FakeApi:
    def __init__(self, *, price: int | None = 25, balance: int = 100) -> None:
        self.price = price
        self.balance_units = balance

    async def prices(self) -> dict[str, PriceQuote]:
        if self.price is None:
            return {}
        return {
            MODEL_SLUG: PriceQuote(
                model_slug=MODEL_SLUG,
                amount_units=self.price,
                currency="CREDIT",
                version=1,
            )
        }

    async def balance(self, user_id: int) -> BalanceView:
        assert user_id == 515
        return BalanceView(
            available_units=self.balance_units,
            reserved_units=0,
            currency="CREDIT",
        )


class FakeInputMedia:
    def __init__(self) -> None:
        self.calls: list[int] = []

    async def upload(self, *, bot: object, message: object, user_id: int) -> SimpleNamespace:
        del bot, message
        self.calls.append(user_id)
        return SimpleNamespace(kind="audio", storage_key=f"inputs/{user_id}/extend.mp3")


def callback(data: str) -> SimpleNamespace:
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=515, username="extend_user"),
        message=SimpleNamespace(edit_text=AsyncMock(), answer=AsyncMock()),
        answer=AsyncMock(),
    )


def message(text: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        from_user=SimpleNamespace(id=515, username="extend_user"),
        answer=AsyncMock(),
    )


def test_upload_extend_states_are_preserved_by_music_upload_shell_guard() -> None:
    declared = {state.state for state in MusicUploadExtendStates.__all_states__}
    assert declared <= MUSIC_UPLOAD_STATE_NAMES
    assert all(is_cover_state(state) for state in declared)


@pytest.mark.asyncio
async def test_upload_extend_entry_waits_for_owner_audio() -> None:
    state = FakeState()
    await state.set_state(MusicExtendStates.choosing_action)
    start = callback("music:upload-extend:start")

    await begin_upload_extend(start, state)  # type: ignore[arg-type]

    assert state.current == MusicUploadExtendStates.waiting_audio.state
    assert str(state.data["idempotency_key"]).startswith("suno-upload-extend:515:")
    assert state.data["media"] == []


@pytest.mark.asyncio
async def test_upload_extend_audio_is_stored_for_cancel_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = FakeState()
    await state.set_state(MusicUploadExtendStates.waiting_audio)
    storage = FakeInputMedia()
    incoming = message()
    monkeypatch.setattr(
        "foxgen.bot.suno_upload_extend_flow.message_media_kind",
        lambda _message: "audio",
    )

    await receive_upload_extend_audio(  # type: ignore[arg-type]
        incoming,
        state,
        SimpleNamespace(),
        storage,
    )

    assert state.current == MusicUploadExtendStates.choosing_mode.state
    assert state.data["input_storage_key"] == "inputs/515/extend.mp3"
    assert state.data["media"] == [{"kind": "audio", "storage_key": "inputs/515/extend.mp3"}]
    assert storage.calls == [515]


@pytest.mark.asyncio
async def test_simple_upload_extend_goes_directly_to_prompt_and_quotes() -> None:
    state = FakeState()
    api = FakeApi(price=25, balance=100)
    await state.update_data(input_storage_key="inputs/515/extend.mp3")
    await state.set_state(MusicUploadExtendStates.choosing_mode)

    await choose_upload_extend_mode(  # type: ignore[arg-type]
        callback("music:upload-extend:mode:simple"),
        state,
    )
    assert state.current == MusicUploadExtendStates.waiting_prompt.state

    prompt = message("Continue the same groove into a wider chorus")
    await receive_upload_extend_prompt(prompt, state, api)  # type: ignore[arg-type]

    assert state.current == MusicUploadExtendStates.confirming.state
    assert state.data["default_param_flag"] is False
    assert state.data["instrumental"] is False
    assert state.data["can_submit"] is True
    assert "25 CREDIT" in prompt.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_custom_instrumental_requires_style_title_and_continue_at() -> None:
    state = FakeState()
    api = FakeApi()
    await state.update_data(input_storage_key="inputs/515/extend.mp3")
    await state.set_state(MusicUploadExtendStates.choosing_mode)

    await choose_upload_extend_mode(  # type: ignore[arg-type]
        callback("music:upload-extend:mode:custom"),
        state,
    )
    await choose_upload_extend_vocal(  # type: ignore[arg-type]
        callback("music:upload-extend:vocal:no"),
        state,
    )
    assert state.current == MusicUploadExtendStates.waiting_style.state

    await receive_upload_extend_style(message("cinematic orchestral"), state)  # type: ignore[arg-type]
    assert state.current == MusicUploadExtendStates.waiting_title.state
    await receive_upload_extend_title(message("Orchestral Continuation"), state)  # type: ignore[arg-type]
    assert state.current == MusicUploadExtendStates.waiting_continue_at.state

    continue_message = message("45.5")
    await receive_upload_extend_continue_at(continue_message, state, api)  # type: ignore[arg-type]
    assert state.current == MusicUploadExtendStates.confirming.state
    assert state.data["prompt"] == ""
    assert state.data["continue_at"] == 45.5
    assert state.data["can_submit"] is True


@pytest.mark.asyncio
async def test_continue_at_must_be_positive_number() -> None:
    state = FakeState()
    api = FakeApi()
    await state.set_state(MusicUploadExtendStates.waiting_continue_at)

    invalid = message("zero")
    await receive_upload_extend_continue_at(invalid, state, api)  # type: ignore[arg-type]
    assert state.current == MusicUploadExtendStates.waiting_continue_at.state
    assert "число секунд" in invalid.answer.await_args.args[0]

    zero = message("0")
    await receive_upload_extend_continue_at(zero, state, api)  # type: ignore[arg-type]
    assert state.current == MusicUploadExtendStates.waiting_continue_at.state
    assert "больше 0" in zero.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_upload_extend_missing_price_fails_closed() -> None:
    state = FakeState()
    api = FakeApi(price=None)
    await state.update_data(
        input_storage_key="inputs/515/extend.mp3",
        default_param_flag=False,
        instrumental=False,
    )
    await state.set_state(MusicUploadExtendStates.waiting_prompt)

    prompt = message("Continue this audio")
    await receive_upload_extend_prompt(prompt, state, api)  # type: ignore[arg-type]

    assert state.data["can_submit"] is False
    assert "не опубликована активная цена" in prompt.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_upload_extend_submit_uses_owner_transport_and_never_provider_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = FakeState()
    await state.update_data(
        input_storage_key="inputs/515/extend.mp3",
        default_param_flag=True,
        instrumental=False,
        prompt="[Verse] New bridge",
        style="dream pop",
        title="Night Extension",
        continue_at=45.0,
        negative_tags="",
        idempotency_key="upload-extend:515:stable",
        can_submit=True,
        media=[{"kind": "audio", "storage_key": "inputs/515/extend.mp3"}],
    )
    await state.set_state(MusicUploadExtendStates.confirming)
    calls: list[dict[str, object]] = []

    async def fake_submit(**kwargs: object) -> QueuedGeneration:
        calls.append(dict(kwargs))
        return QueuedGeneration(
            generation_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            status="queued",
            replayed=False,
        )

    monkeypatch.setattr(
        "foxgen.bot.suno_upload_extend_flow.submit_suno_upload_extend",
        fake_submit,
    )
    submit = callback("music:upload-extend:confirm")
    await confirm_upload_extend(submit, state)  # type: ignore[arg-type]

    assert len(calls) == 1
    call = calls[0]
    assert call["user_id"] == 515
    assert call["idempotency_key"] == "upload-extend:515:stable"
    payload = call["input_data"]
    assert isinstance(payload, dict)
    assert payload["input_storage_key"] == "inputs/515/extend.mp3"
    assert payload["continue_at"] == 45.0
    assert "upload_url" not in payload
    assert "uploadUrl" not in payload
    assert state.current is None
