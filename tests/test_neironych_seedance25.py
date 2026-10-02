from __future__ import annotations

from bot.services.neironych_entrypoints import seedance25_native_options


def _payload(**changes):
    value = {
        "scenario": "text",
        "duration": 5,
        "ratio": "16:9",
        "resolution": "720p",
        "first_frame": None,
        "last_frame": None,
        "image_urls": [],
        "video_urls": [],
        "audio_urls": [],
        "return_last_frame": False,
        "generate_audio": True,
        "output_format": "mp4",
        "web_search": False,
        "nsfw_checker": False,
    }
    value.update(changes)
    return value


def test_seedance25_native_text_and_multimodal_contracts():
    text = seedance25_native_options(_payload())
    assert text is not None
    assert text["ratio"] == "16:9"
    assert text["generate_audio"] is True

    refs = seedance25_native_options(
        _payload(
            scenario="multimodal",
            image_urls=["https://media.example/a.jpg"],
            video_urls=["https://media.example/a.mp4"],
            audio_urls=["https://media.example/a.mp3"],
        )
    )
    assert refs is not None
    assert refs["mode"] == "reference"
    assert refs["images"] == ["https://media.example/a.jpg"]


def test_seedance25_native_frame_contract_forces_adaptive():
    result = seedance25_native_options(
        _payload(
            scenario="first_last",
            ratio="16:9",
            first_frame="https://media.example/start.jpg",
            last_frame="https://media.example/end.jpg",
        )
    )
    assert result is not None
    assert result["ratio"] == "adaptive"
    assert result["start_image"] == "https://media.example/start.jpg"
    assert result["end_image"] == "https://media.example/end.jpg"


def test_seedance25_features_not_in_partner_contract_keep_existing_provider():
    assert seedance25_native_options(_payload(return_last_frame=True)) is None
    assert seedance25_native_options(_payload(output_format="mov")) is None
    assert seedance25_native_options(_payload(web_search=True)) is None
    assert seedance25_native_options(_payload(nsfw_checker=True)) is None
    assert seedance25_native_options(_payload(generate_audio=False)) is None
    assert seedance25_native_options(_payload(ratio="adaptive")) is None
