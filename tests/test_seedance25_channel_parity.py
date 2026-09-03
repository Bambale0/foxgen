from pathlib import Path

from bot.instagram_model_contract import instagram_video_cost
from bot.instagram_seedance25_official import (
    _decode_config,
    _scenario_from_text,
)
from bot.instagram_seedance25_official import (
    _default_config as instagram_default_config,
)
from bot.max_catalog import MAX_VIDEO_TYPES, max_preset_manager
from bot.max_omni_audio import MaxOmniGenerationService
from bot.max_seedance25 import (
    MODEL_KEY,
    MaxSeedance25ChannelService,
    MaxSeedance25GenerationService,
)
from bot.max_seedance25 import (
    _default_config as max_default_config,
)
from bot.max_suno_full_channel import MaxSunoFullChannelService


def test_max_catalog_exposes_seedance25_for_all_video_entry_types():
    assert all(MODEL_KEY in MAX_VIDEO_TYPES[kind] for kind in ("text", "imgtxt", "video"))
    assert MODEL_KEY in max_preset_manager.video_models("text")
    assert MODEL_KEY in max_preset_manager.video_models("imgtxt")
    assert MODEL_KEY in max_preset_manager.video_models("video")


def test_max_seedance25_uses_quality_seconds_pricing():
    assert max_preset_manager.video_cost(MODEL_KEY, duration=5, quality="480p") == 20
    assert max_preset_manager.video_cost(MODEL_KEY, duration=5, quality="720p") == 30
    assert max_preset_manager.video_cost(MODEL_KEY, duration=30, quality="720p") == 180


def test_max_seedance25_preserves_existing_suno_and_omni_layers():
    assert issubclass(MaxSeedance25ChannelService, MaxSunoFullChannelService)
    assert issubclass(MaxSeedance25GenerationService, MaxOmniGenerationService)


def test_max_seedance25_defaults_cover_full_provider_controls():
    data = max_default_config("video")
    assert data["seedance25_scenario"] == "multimodal"
    assert data["duration"] == 5
    assert data["resolution"] == "720p"
    assert data["aspect_ratio"] == "adaptive"
    assert data["generate_audio"] is True
    assert data["return_last_frame"] is False
    assert set(data) >= {"image_urls", "video_urls", "audio_urls"}


def test_instagram_seedance25_accepts_all_four_scenarios():
    assert _scenario_from_text("1") == "text"
    assert _scenario_from_text("оживить фото") == "first_frame"
    assert _scenario_from_text("2 кадра") == "first_last"
    assert _scenario_from_text("multimodal") == "multimodal"


def test_instagram_seedance25_draft_round_trip_keeps_full_contract():
    data = instagram_default_config()
    data.update(
        scenario="multimodal",
        duration=17,
        resolution="480p",
        aspect_ratio="21:9",
        generate_audio=False,
        return_last_frame=True,
        image_urls=["https://example.com/a.png"],
        video_urls=["https://example.com/a.mp4"],
        audio_urls=["https://example.com/a.mp3"],
    )
    import json

    restored = _decode_config(json.dumps(data))
    assert restored == data


def test_instagram_seedance25_price_changes_with_duration_and_resolution():
    assert instagram_video_cost(duration=5, resolution="480p") == 20
    assert instagram_video_cost(duration=5, resolution="720p") == 30
    assert instagram_video_cost(duration=30, resolution="720p") == 180


def test_all_channel_runtime_sources_use_seedance25_provider_contract():
    max_source = Path("bot/max_seedance25.py").read_text(encoding="utf-8")
    instagram_source = Path("bot/instagram_seedance25_official.py").read_text(encoding="utf-8")
    telegram_source = Path("bot/handlers/seedance_25_official_contract.py").read_text(encoding="utf-8")
    for source in (max_source, instagram_source, telegram_source):
        assert "seedance_25_service.generate_video" in source
        assert "reference_audio_urls" in source
        assert "return_last_frame" in source
        assert "generate_audio" in source
    assert "first_frame_url" in max_source and "last_frame_url" in max_source
    assert "first_frame_url" in instagram_source and "last_frame_url" in instagram_source
