from pathlib import Path

import pytest

from bot.services.seedance_25_service import Seedance25Service


@pytest.mark.asyncio
async def test_seedance25_text_payload_matches_kie_contract(monkeypatch):
    service = Seedance25Service(kie_key="test")
    captured = {}

    async def fake_post(endpoint, payload):
        captured["endpoint"] = endpoint
        captured["payload"] = payload
        return {"task_id": "task-1", "status": "pending"}

    monkeypatch.setattr(service, "_kie_post", fake_post)

    result = await service.generate_video(
        "cinematic city at night",
        duration=15,
        aspect_ratio="16:9",
        resolution="720p",
        generate_audio=True,
        return_last_frame=True,
        callBackUrl="https://example.com/webhook/kie_seedance25",
    )

    assert result["success"] is True
    assert captured["endpoint"] == "/api/v1/jobs/createTask"
    assert captured["payload"] == {
        "model": "bytedance/seedance-2-5",
        "callBackUrl": "https://example.com/webhook/kie_seedance25",
        "input": {
            "prompt": "cinematic city at night",
            "return_last_frame": True,
            "generate_audio": True,
            "resolution": "720p",
            "aspect_ratio": "16:9",
            "duration": 15,
        },
    }


@pytest.mark.asyncio
async def test_seedance25_first_frame_forces_adaptive_ratio(monkeypatch):
    service = Seedance25Service(kie_key="test")
    captured = {}

    async def fake_post(_endpoint, payload):
        captured.update(payload)
        return {"task_id": "task-frame"}

    monkeypatch.setattr(service, "_kie_post", fake_post)

    result = await service.generate_video(
        "subtle natural motion",
        first_frame_url="https://example.com/start.png",
        aspect_ratio="16:9",
        duration=5,
    )

    assert result["scenario"] == "first_frame"
    assert captured["input"]["first_frame_url"] == "https://example.com/start.png"
    assert captured["input"]["aspect_ratio"] == "adaptive"
    assert "reference_image_urls" not in captured["input"]


@pytest.mark.asyncio
async def test_seedance25_rejects_mixed_frame_and_multimodal_modes(monkeypatch):
    service = Seedance25Service(kie_key="test")
    called = False

    async def fake_post(_endpoint, _payload):
        nonlocal called
        called = True
        return {"task_id": "unexpected"}

    monkeypatch.setattr(service, "_kie_post", fake_post)

    result = await service.generate_video(
        "move",
        first_frame_url="https://example.com/start.png",
        reference_video_urls=["https://example.com/ref.mp4"],
    )

    assert result["success"] is False
    assert "cannot be combined" in result["error"]
    assert called is False


@pytest.mark.asyncio
async def test_seedance25_multimodal_payload_includes_all_reference_types(monkeypatch):
    service = Seedance25Service(kie_key="test")
    captured = {}

    async def fake_post(_endpoint, payload):
        captured.update(payload)
        return {"task_id": "task-refs"}

    monkeypatch.setattr(service, "_kie_post", fake_post)

    result = await service.generate_video(
        "use the character, motion and soundtrack references",
        duration=12,
        aspect_ratio="9:16",
        reference_image_urls=["https://example.com/character.png"],
        reference_video_urls=["https://example.com/motion.mp4"],
        reference_audio_urls=["https://example.com/audio.mp3"],
    )

    assert result["scenario"] == "multimodal"
    assert captured["input"]["reference_image_urls"] == ["https://example.com/character.png"]
    assert captured["input"]["reference_video_urls"] == ["https://example.com/motion.mp4"]
    assert captured["input"]["reference_audio_urls"] == ["https://example.com/audio.mp3"]
    assert captured["input"]["aspect_ratio"] == "9:16"


@pytest.mark.asyncio
@pytest.mark.parametrize("duration", [-1, 0, 3, 31])
async def test_seedance25_rejects_undocumented_durations(duration):
    service = Seedance25Service(kie_key="test")
    result = await service.generate_video("test", duration=duration)
    assert result["success"] is False
    assert "4-30" in result["error"]


def test_seedance25_frontend_does_not_send_stale_provider_fields():
    source = Path("frontend/miniapp-v0/lib/seedance25-api.ts").read_text(encoding="utf-8")
    for field in (
        "seedance25_output_format",
        "seedance25_web_search",
        "seedance25_nsfw_checker",
    ):
        assert field not in source


def test_seedance25_official_form_replaces_legacy_public_form():
    bridge = Path("frontend/miniapp-v0/components/forms/seedance25-public-form.tsx").read_text(
        encoding="utf-8"
    )
    official = Path("frontend/miniapp-v0/components/forms/seedance25-official-form.tsx").read_text(
        encoding="utf-8"
    )
    assert "Seedance25OfficialForm as Seedance25PublicForm" in bridge
    assert "webSearch" not in official
    assert "nsfwChecker" not in official
    assert "outputFormat" not in official
    assert "min={4}" in official and "max={30}" in official
