from __future__ import annotations

from foxgen.bot.generation_capabilities import (
    IMAGE_MODELS,
    VIDEO_MODELS,
    VideoGenerationType,
    wizard_submission_slugs,
)
from foxgen.bot.generation_keyboards import image_settings_keyboard, video_settings_keyboard
from foxgen.bot.generation_wizard import (
    _submission_payload,
    _video_media_complete,
    default_image_flow_data,
    default_video_flow_data,
)
from foxgen.providers.kie.registry import ModelRegistry


def _callbacks(markup: object) -> set[str]:
    keyboard = getattr(markup, "inline_keyboard")
    return {
        button.callback_data
        for row in keyboard
        for button in row
        if button.callback_data is not None
    }


def test_wizard_covers_every_paid_submission_model() -> None:
    production = {item.slug for item in ModelRegistry().submission_models()}
    assert wizard_submission_slugs() == production


def test_image_default_draft_matches_screen_contract() -> None:
    data = default_image_flow_data(42)
    assert data["entrypoint"] == "wizard"
    assert data["generation_type"] == "image"
    assert data["image_flow_step"] == "select_model"
    assert data["image_model_key"] == "seedream-5-pro"
    assert data["media"] == []
    assert data["can_submit"] is False
    assert str(data["idempotency_key"]).startswith("generation:42:")


def test_video_default_draft_matches_screen_contract() -> None:
    data = default_video_flow_data(42)
    assert data["entrypoint"] == "wizard"
    assert data["generation_type"] == "video"
    assert data["video_flow_step"] == "select_model"
    assert data["video_type"] == VideoGenerationType.TEXT.value
    assert data["media"] == []
    assert data["can_submit"] is False


def test_seedream_ui_model_selects_edit_slug_only_when_references_exist() -> None:
    capability = IMAGE_MODELS["seedream-5-pro"]
    assert capability.submission_slug(has_references=False) == "seedream-5-pro"
    assert capability.submission_slug(has_references=True) == "seedream-5-pro-edit"


def test_image_settings_are_model_specific() -> None:
    seedream = IMAGE_MODELS["seedream-5-pro"]
    seedream_callbacks = _callbacks(
        image_settings_keyboard(
            seedream,
            {
                "aspect_ratio": "1:1",
                "quality": "basic",
                "output_format": "png",
            },
        )
    )
    assert "gw:i:quality:high" in seedream_callbacks
    assert "gw:i:resolution:4K" not in seedream_callbacks

    banana = IMAGE_MODELS["nano-banana-2"]
    banana_callbacks = _callbacks(
        image_settings_keyboard(
            banana,
            {
                "aspect_ratio": "auto",
                "resolution": "1K",
                "output_format": "png",
            },
        )
    )
    assert "gw:i:resolution:4K" in banana_callbacks
    assert "gw:i:quality:high" not in banana_callbacks


def test_video_settings_expose_only_verified_seedance_options() -> None:
    capability = VIDEO_MODELS["seedance-2"]
    callbacks = _callbacks(
        video_settings_keyboard(
            capability,
            {
                "aspect_ratio": "16:9",
                "duration": 5,
                "resolution": "720p",
                "generate_audio": False,
                "return_last_frame": False,
                "web_search": False,
            },
        )
    )
    assert "gw:v:duration:15" in callbacks
    assert "gw:v:toggle:audio" in callbacks
    assert "gw:v:toggle:last" in callbacks
    assert "gw:v:toggle:web" in callbacks
    assert not any(value and value.startswith("gw:v:resolution:") for value in callbacks)


def test_first_last_video_payload_preserves_media_order() -> None:
    data = default_video_flow_data(42)
    data.update(
        {
            "video_type": VideoGenerationType.FIRST_LAST.value,
            "prompt": "Camera moves through the scene",
            "media": [
                {"kind": "image", "storage_key": "inputs/42/first.png"},
                {"kind": "image", "storage_key": "inputs/42/last.png"},
            ],
        }
    )
    slug, payload = _submission_payload(
        data,
        [
            {"kind": "image", "url": "https://media.example/first.png"},
            {"kind": "image", "url": "https://media.example/last.png"},
        ],
    )
    assert slug == "seedance-2"
    assert payload["first_frame_url"] == "https://media.example/first.png"
    assert payload["last_frame_url"] == "https://media.example/last.png"


def test_multimodal_video_payload_separates_reference_types() -> None:
    data = default_video_flow_data(42)
    data.update(
        {
            "video_type": VideoGenerationType.REFERENCES.value,
            "prompt": "Use the supplied references",
            "media": [
                {"kind": "image", "storage_key": "inputs/42/image.png"},
                {"kind": "video", "storage_key": "inputs/42/video.mp4"},
                {"kind": "audio", "storage_key": "inputs/42/audio.mp3"},
            ],
        }
    )
    slug, payload = _submission_payload(
        data,
        [
            {"kind": "image", "url": "https://media.example/image.png"},
            {"kind": "video", "url": "https://media.example/video.mp4"},
            {"kind": "audio", "url": "https://media.example/audio.mp3"},
        ],
    )
    assert slug == "seedance-2"
    assert payload["reference_image_urls"] == ["https://media.example/image.png"]
    assert payload["reference_video_urls"] == ["https://media.example/video.mp4"]
    assert payload["reference_audio_urls"] == ["https://media.example/audio.mp3"]


def test_video_media_completion_is_screen_specific() -> None:
    one_image = [{"kind": "image", "storage_key": "inputs/one.png"}]
    two_images = [
        {"kind": "image", "storage_key": "inputs/one.png"},
        {"kind": "image", "storage_key": "inputs/two.png"},
    ]
    assert _video_media_complete(VideoGenerationType.FIRST_FRAME, one_image) is True
    assert _video_media_complete(VideoGenerationType.FIRST_LAST, one_image) is False
    assert _video_media_complete(VideoGenerationType.FIRST_LAST, two_images) is True
    assert _video_media_complete(VideoGenerationType.REFERENCES, one_image) is True
