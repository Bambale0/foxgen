from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from foxgen.bot.api_client import BalanceView, PriceQuote, QueuedGeneration
from foxgen.bot.states import MusicCoverStates, MusicExtendStates
from foxgen.bot.suno_upload_cover_contract import COVER_STATE_NAMES, is_cover_state
from foxgen.bot.suno_upload_cover_flow import (
    MODEL_SLUG,
    begin_cover,
    choose_cover_mode,
    choose_cover_vocal,
    confirm_cover,
    receive_cover_audio,
    receive_cover_prompt,
    receive_cover_style,
    receive_cover_title,
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
        return SimpleNamespace(kind="audio", storage_key=f"inputs/{user_id}/cover.mp3")


def callback(data: str) -> SimpleNamespace:
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=515, username="cover_user"),
        message=SimpleNamespace(edit_text=AsyncMock(), answer=AsyncMock()),
        answer=AsyncMock(),
    )


def message(text: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        from_user=SimpleNamespace(id=515, username="cover_user"),
        answer=AsyncMock(),
    )


def test_every_cover_state_is_recognized_by_shell_contract() -> None:
    declared = {state.state for state in MusicCoverStates.__all_states__}
    assert COVER_STATE_NAMES == declared
    assert all(is_cover_state(state) for state in declared)
    assert is_cover_state(None) is False
    assert is_cover_state("MusicCoverStates:removed") is False


@pytest.mark.asyncio
async def test_cover_entry_from_music_hub_waits_for_audio() -> None:
    state = FakeState()
    await state.set_state(MusicExtendStates.choosing_action)
    start = callback("music:cover:start")

    await begin_cover(start, state)  # type: ignore[arg-type]

    assert state.current == MusicCoverStates.waiting_audio.state
    assert str(state.data["idempotency_key"]).startswith("suno-cover:515:")
    assert state.data["media"] == []


@pytest.mark.asyncio
async def test_cover_audio_is_stored_in_media_for_global_cancel_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = FakeState()
    await state.set_state(MusicCoverStates.waiting_audio)
    storage = FakeInputMedia()
    incoming = message()
    monkeypatch.setattr("foxgen.bot.suno_upload_cover_flow.message_media_kind", lambda _message: "audio")

    await receive_cover_audio(  # type: ignore[arg-type]
        incoming,
        state,
        SimpleNamespace(),
        storage,
    )

    assert state.current == MusicCoverStates.choosing_mode.state
    assert state.data["input_storage_key"] == "inputs/515/cover.mp3"
    assert state.data["media"] == [{"kind": "audio", "storage_key": "inputs/515/cover.mp3"}]
    assert storage.calls == [515]


@pytest.mark.asyncio
async def test_simple_cover_quotes_price_after_prompt() -> None:
    state = FakeState()
    api = FakeApi(price=25, balance=100)
    await state.update_data(input_storage_key="inputs/515/cover.mp3")
    await state.set_state(MusicCoverStates.choosing_mode)

    await choose_cover_mode(callback("music:cover:mode:simple"), state)  # type: ignore[arg-type]
    await choose_cover_vocal(callback("music:cover:vocal:yes"), state)  # type: ignore[arg-type]
    prompt = message("Make this a dreamy indie-pop cover")
    await receive_cover_prompt(prompt, state, api)  # type: ignore[arg-type]

    assert state.current == MusicCoverStates.confirming.state
    assert state.data["custom_mode"] is False
    assert state.data["instrumental"] is False
    assert state.data["can_submit"] is True
    rendered = prompt.answer.await_args.args[0]
    assert "25 CREDIT" in rendered


@pytest.mark.asyncio
async def test_custom_instrumental_skips_prompt_and_requires_style_title() -> None:
    state = FakeState()
    api = FakeApi()
    await state.update_data(input_storage_key="inputs/515/cover.mp3")
    await state.set_state(MusicCoverStates.choosing_mode)

    await choose_cover_mode(callback("music:cover:mode:custom"), state)  # type: ignore[arg-type]
    await choose_cover_vocal(callback("music:cover:vocal:no"), state)  # type: ignore[arg-type]
    assert state.current == MusicCoverStates.waiting_style.state

    await receive_cover_style(message("cinematic orchestral"), state)  # type: ignore[arg-type]
    assert state.current == MusicCoverStates.waiting_title.state

    title = message("Orchestral Cover")
    await receive_cover_title(title, state, api)  # type: ignore[arg-type]
    assert state.current == MusicCoverStates.confirming.state
    assert state.data["prompt"] == ""
    assert state.data["can_submit"] is True


@pytest.mark.asyncio
async def test_cover_missing_price_fails_closed() -> None:
    state = FakeState()
    api = FakeApi(price=None, balance=100)
    await state.update_data(
        input_storage_key="inputs/515/cover.mp3",
        custom_mode=False,
        instrumental=False,
    )
    await state.set_state(MusicCoverStates.waiting_prompt)

    prompt = message("Acoustic cover")
    await receive_cover_prompt(prompt, state, api)  # type: ignore[arg-type]

    assert state.data["can_submit"] is False
    assert "не опубликована активная цена" in prompt.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_cover_submit_uses_owner_transport_and_never_provider_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = FakeState()
    await state.update_data(
        input_storage_key="inputs/515/cover.mp3",
        custom_mode=True,
        instrumental=False,
        prompt="[Verse] New words",
        style="dream pop",
        title="Night Cover",
        negative_tags="",
        idempotency_key="cover:515:stable",
        can_submit=True,
        media=[{"kind": "audio", "storage_key": "inputs/515/cover.mp3"}],
    )
    await state.set_state(MusicCoverStates.confirming)
    calls: list[dict[str, object]] = []

    async def fake_submit(**kwargs: object) -> QueuedGeneration:
        calls.append(dict(kwargs))
        return QueuedGeneration(
            generation_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            status="queued",
            replayed=False,
        )

    monkeypatch.setattr("foxgen.bot.suno_upload_cover_flow.submit_suno_upload_cover", fake_submit)
    submit = callback("music:cover:confirm")
    await confirm_cover(submit, state)  # type: ignore[arg-type]

    assert len(calls) == 1
    call = calls[0]
    assert call["user_id"] == 515
    assert call["idempotency_key"] == "cover:515:stable"
    payload = call["input_data"]
    assert isinstance(payload, dict)
    assert payload["input_storage_key"] == "inputs/515/cover.mp3"
    assert "upload_url" not in payload
    assert "uploadUrl" not in payload
    assert state.current is None
