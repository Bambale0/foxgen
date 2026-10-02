from __future__ import annotations


import pytest

from bot.max_generation import MaxGenerationJob


def _job(*, kind="image", model="banana_2", generation_type="text"):
    return MaxGenerationJob(
        id="maxjob-12345678",
        max_user_id=7,
        kind=kind,
        generation_type=generation_type,
        model=model,
        prompt="prompt",
        cost=3,
        input_data={"image_urls": ["https://media.example/a.png"]},
        options={
            "aspect_ratio": "16:9",
            "quality": "2K",
            "duration": 5,
            "resolution": "720p",
            "generate_audio": True,
        },
        status="processing",
        provider_kind=None,
        provider_task_id=None,
        result_url=None,
        delivered_at_epoch=None,
        attempt_count=1,
    )


@pytest.mark.asyncio
async def test_max_native_image_request_uses_stable_job_idempotency(monkeypatch):
    import bot.max_generation as mod

    async def route(product):
        assert product == "banana_2"
        return "nano-banana-2"

    monkeypatch.setattr(mod.neironych_routing, "media_model", route)
    request = await mod._native_request_for_job(_job())

    assert request is not None
    assert request.model.id == "nano-banana-2"
    assert request.key == "happyfox-max-maxjob-12345678"
    assert request.payload["images"] == [
        {"image_url": "https://media.example/a.png"}
    ]


@pytest.mark.asyncio
async def test_max_seedance25_frame_request_uses_adaptive_ratio(monkeypatch):
    import bot.max_generation as mod

    async def route(product):
        assert product == "seedance_2_5"
        return "seedance-2.5"

    monkeypatch.setattr(mod.neironych_routing, "media_model", route)
    request = await mod._native_request_for_job(
        _job(kind="video", model="seedance_2_5", generation_type="imgtxt")
    )

    assert request is not None
    assert request.payload["start_image"] == {
        "url": "https://media.example/a.png"
    }
    assert request.payload["aspect_ratio"] == "adaptive"
    assert request.key == "happyfox-max-maxjob-12345678"


@pytest.mark.asyncio
async def test_max_native_route_disabled_keeps_existing_provider(monkeypatch):
    import bot.max_generation as mod

    async def route(product):
        return None

    monkeypatch.setattr(mod.neironych_routing, "media_model", route)
    assert await mod._native_request_for_job(_job()) is None


@pytest.mark.asyncio
async def test_max_held_native_outcome_refunds_without_second_submit(monkeypatch):
    import bot.max_generation as mod

    job = _job()

    async def native_request(_job):
        return object()

    async def advance(_job_id, _request):
        return {"phase": "held", "error": "submission_outcome_unknown"}

    refunded = []
    failed = []
    messages = []

    monkeypatch.setattr(mod, "_native_request_for_job", native_request)
    monkeypatch.setattr(mod.neironych_jobs, "advance_max_operation", advance)
    monkeypatch.setattr(mod, "get_max_generation_job", lambda _job_id: _async(job))
    monkeypatch.setattr(mod, "_refund_job", lambda current, reason: _record_async(refunded, reason))
    monkeypatch.setattr(mod, "_mark_job_failed", lambda _job_id, reason: _record_async(failed, reason))
    monkeypatch.setattr(mod, "record_max_generation", _noop_async)

    class Client:
        async def send_message(self, user_id, text):
            messages.append((user_id, text))

    service = mod.MaxGenerationService(Client())
    await service._handle_job(job)

    assert refunded
    assert failed
    assert len(messages) == 1


async def _async(value):
    return value


async def _record_async(target, value):
    target.append(value)


async def _noop_async(*args, **kwargs):
    return None
