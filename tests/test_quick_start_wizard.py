from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from foxgen.bot.generation_capabilities import VideoGenerationType
from foxgen.bot.quick_start_wizard import bridge_reference_to_wizard
from foxgen.bot.states import GenerationStates
from foxgen.bot.uploads import TelegramInputMediaStorage


class StubState:
    def __init__(self, data: dict[str, object]) -> None:
        self.data = dict(data)
        self.current: str | None = GenerationStates.reference_choosing_product.state

    async def get_data(self) -> dict[str, object]:
        return dict(self.data)

    async def clear(self) -> None:
        self.data = {}
        self.current = None

    async def update_data(self, **kwargs: object) -> dict[str, object]:
        self.data.update(kwargs)
        return dict(self.data)

    async def set_state(self, state: object) -> None:
        self.current = getattr(state, "state", state) if state is not None else None


def _callback(data: str) -> SimpleNamespace:
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=42),
        message=SimpleNamespace(edit_text=AsyncMock(), answer=AsyncMock()),
        answer=AsyncMock(),
    )


def _input_media() -> TelegramInputMediaStorage:
    return cast(TelegramInputMediaStorage, SimpleNamespace())


async def test_image_quick_start_keeps_reference_and_enters_image_model_screen() -> None:
    state = StubState(
        {
            "reference_kind": "image",
            "reference_original": {
                "kind": "image",
                "storage_key": "inputs/42/reference.jpg",
            },
            "reference_preview": None,
            "reference_caption": "Use the reference lighting",
            "idempotency_key": "quick-start-idempotency",
        }
    )
    callback = _callback("reference:product:image")

    await bridge_reference_to_wizard(
        cast(CallbackQuery, callback),
        cast(FSMContext, state),
        _input_media(),
    )

    assert state.current == GenerationStates.image_selecting_model.state
    assert state.data["entrypoint"] == "wizard"
    assert state.data["wizard_origin"] == "quick_start"
    assert state.data["media"] == [{"kind": "image", "storage_key": "inputs/42/reference.jpg"}]
    assert state.data["reference_caption"] == "Use the reference lighting"
    assert state.data["idempotency_key"] == "quick-start-idempotency"


async def test_video_quick_start_prefers_multimodal_references_for_video_source() -> None:
    state = StubState(
        {
            "reference_kind": "video",
            "reference_original": {
                "kind": "video",
                "storage_key": "inputs/42/reference.mp4",
            },
            "reference_preview": {
                "kind": "image",
                "storage_key": "inputs/42/preview.jpg",
            },
            "reference_caption": "Animate in the same mood",
            "idempotency_key": "quick-video-idempotency",
        }
    )
    callback = _callback("reference:product:video")

    await bridge_reference_to_wizard(
        cast(CallbackQuery, callback),
        cast(FSMContext, state),
        _input_media(),
    )

    assert state.current == GenerationStates.video_selecting_model.state
    assert state.data["entrypoint"] == "wizard"
    assert state.data["wizard_origin"] == "quick_start"
    assert state.data["video_type"] == VideoGenerationType.REFERENCES.value
    assert state.data["media"] == [{"kind": "video", "storage_key": "inputs/42/reference.mp4"}]
    assert state.data["idempotency_key"] == "quick-video-idempotency"
