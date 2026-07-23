from typing import Any

import pytest

from foxgen.bot.catalog import GenerationMode, MODELS_BY_MODE
from foxgen.bot.flows import ResolvedInput, _provider_payload
from foxgen.providers.kie.contracts import validate_input
from foxgen.providers.kie.registry import ModelRegistry


@pytest.mark.parametrize(
    ("model_slug", "mode", "extra", "media"),
    [
        (
            "seedream-5-pro",
            GenerationMode.IMAGE_TEXT,
            {"quality": "high"},
            [],
        ),
        (
            "seedream-5-pro-edit",
            GenerationMode.IMAGE_EDIT,
            {"quality": "basic"},
            [{"kind": "image", "url": "https://cdn.example/input.png"}],
        ),
        (
            "nano-banana-2",
            GenerationMode.IMAGE_TEXT,
            {"resolution": "1K"},
            [],
        ),
        (
            "nano-banana-pro",
            GenerationMode.IMAGE_EDIT,
            {"resolution": "1K"},
            [{"kind": "image", "url": "https://cdn.example/input.png"}],
        ),
        (
            "seedance-2",
            GenerationMode.VIDEO_TEXT,
            {"duration": 5, "resolution": "720p", "generate_audio": True},
            [],
        ),
        (
            "seedance-2-mini",
            GenerationMode.VIDEO_IMAGE,
            {"duration": 10, "resolution": "720p", "generate_audio": False},
            [{"kind": "image", "url": "https://cdn.example/frame.png"}],
        ),
        (
            "seedance-2",
            GenerationMode.VIDEO_REFERENCE,
            {"duration": 5, "resolution": "720p", "generate_audio": True},
            [
                {"kind": "image", "url": "https://cdn.example/reference.png"},
                {"kind": "video", "url": "https://cdn.example/reference.mp4"},
                {"kind": "audio", "url": "https://cdn.example/reference.mp3"},
            ],
        ),
    ],
)
def test_telegram_payloads_pass_the_registered_model_contract(
    model_slug: str,
    mode: GenerationMode,
    extra: dict[str, object],
    media: list[ResolvedInput],
) -> None:
    data: dict[str, Any] = {
        "mode": mode.value,
        "model_slug": model_slug,
        "prompt": "A cinematic fox in soft studio light",
        "aspect_ratio": "16:9" if mode.value.startswith("video_") else "1:1",
        **extra,
    }

    payload = _provider_payload(data, media)
    contract = ModelRegistry().get(model_slug).contract
    normalized = validate_input(contract, payload)

    for key, value in payload.items():
        assert normalized[key] == value


def test_every_fsm_model_exists_in_the_production_registry() -> None:
    registry = ModelRegistry()

    for choices in MODELS_BY_MODE.values():
        for choice in choices:
            assert registry.get(choice.slug).slug == choice.slug


def test_reference_video_payload_keeps_reference_modes_separate() -> None:
    payload = _provider_payload(
        {
            "mode": GenerationMode.VIDEO_REFERENCE.value,
            "model_slug": "seedance-2",
            "prompt": "Follow the references",
            "aspect_ratio": "16:9",
            "duration": 5,
        },
        [
            {"kind": "image", "url": "https://cdn.example/reference.png"},
            {"kind": "audio", "url": "https://cdn.example/reference.mp3"},
        ],
    )

    assert "first_frame_url" not in payload
    assert payload["reference_image_urls"] == ["https://cdn.example/reference.png"]
    assert payload["reference_audio_urls"] == ["https://cdn.example/reference.mp3"]
