import pytest
from pydantic import ValidationError

from foxgen.providers.kie.contracts import InputContract, contract_schema, validate_input


def test_seedance_text_to_video_applies_documented_defaults() -> None:
    payload = validate_input(
        InputContract.SEEDANCE_2,
        {"prompt": "A fox runs through a rainy neon city"},
    )

    assert payload["resolution"] == "720p"
    assert payload["aspect_ratio"] == "16:9"
    assert payload["duration"] == 5
    assert payload["reference_image_urls"] == []


def test_seedance_rejects_frame_and_reference_modes_together() -> None:
    with pytest.raises(ValidationError, match="mutually exclusive"):
        validate_input(
            InputContract.SEEDANCE_2,
            {
                "prompt": "Animate the character",
                "first_frame_url": "https://example.com/frame.png",
                "reference_video_urls": ["https://example.com/reference.mp4"],
            },
        )


def test_seedance_last_frame_requires_first_frame() -> None:
    with pytest.raises(ValidationError, match="requires first_frame_url"):
        validate_input(
            InputContract.SEEDANCE_2,
            {
                "prompt": "Transition to the final frame",
                "last_frame_url": "https://example.com/end.png",
            },
        )


def test_seedream_45_text_applies_exact_documented_defaults() -> None:
    payload = validate_input(
        InputContract.SEEDREAM_45_TEXT,
        {"prompt": "Premium editorial portrait"},
    )

    assert payload == {
        "prompt": "Premium editorial portrait",
        "aspect_ratio": "1:1",
        "quality": "basic",
        "nsfw_checker": False,
    }


def test_seedream_45_edit_requires_an_input_image() -> None:
    with pytest.raises(ValidationError):
        validate_input(
            InputContract.SEEDREAM_45_EDIT,
            {"prompt": "Replace the background"},
        )


def test_seedream_5_edit_requires_an_input_image() -> None:
    with pytest.raises(ValidationError):
        validate_input(
            InputContract.SEEDREAM_5_IMAGE,
            {"prompt": "Replace the background"},
        )


def test_nano_banana_supports_text_and_image_modes() -> None:
    text_payload = validate_input(InputContract.NANO_BANANA, {"prompt": "A fox mascot"})
    edit_payload = validate_input(
        InputContract.NANO_BANANA,
        {
            "prompt": "Put the mascot in a black hoodie",
            "image_input": ["https://example.com/fox.png"],
        },
    )

    assert text_payload["image_input"] == []
    assert edit_payload["image_input"] == ["https://example.com/fox.png"]


def test_contract_exposes_json_schema_for_ui() -> None:
    schema = contract_schema(InputContract.SEEDANCE_2)

    assert "prompt" in schema["properties"]
    assert "first_frame_url" in schema["properties"]
