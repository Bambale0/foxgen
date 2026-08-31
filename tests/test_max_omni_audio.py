import asyncio

import pytest

from bot import database
from bot.max_api import MaxSettings
from bot.max_generation import (
    MaxGenerationRetry,
    enqueue_max_generation,
    get_max_generation_job,
)
from bot.max_omni_audio import (
    MaxOmniGenerationService,
    enqueue_max_omni_audio,
    omni_audio_cost,
)
from bot.max_omni_channel import MaxOmniChannelService
from bot.max_store import (
    apply_max_balance_delta,
    ensure_max_user,
    get_max_balance,
    get_max_session,
)


class FakeTransport:
    def __init__(self) -> None:
        self.sent = []
        self.answers = []
        self.media = []

    async def send_message(
        self,
        user_id,
        text,
        *,
        attachments=None,
        format="html",
        notify=True,
    ):
        self.sent.append(
            {
                "user_id": user_id,
                "text": text,
                "attachments": attachments,
                "format": format,
                "notify": notify,
            }
        )
        return {"ok": True}

    async def answer_callback(self, callback_id, *, message=None):
        self.answers.append({"callback_id": callback_id, "message": message})
        return {"success": True}

    async def send_media_url(
        self,
        user_id,
        *,
        media_type,
        url,
        text="",
        filename=None,
    ):
        self.media.append(
            {
                "user_id": user_id,
                "media_type": media_type,
                "url": url,
                "text": text,
                "filename": filename,
            }
        )
        return {"ok": True}


class FakePayments:
    enabled = True


class FakeCreator:
    async def resolve_video_attachment(self, token):
        raise AssertionError(f"unexpected video token resolution: {token}")


def _prepare_database(database_path, monkeypatch) -> None:
    monkeypatch.setattr(database, "DATABASE_PATH", str(database_path))
    asyncio.run(database.init_db())


def _service():
    client = FakeTransport()
    service = MaxOmniChannelService(
        settings=MaxSettings(
            enabled=True,
            access_token="token",
            webhook_secret="valid_secret",
            mini_app_url="https://example.invalid/mini-app/",
        ),
        client=client,
        payments=FakePayments(),
        bot_name="happyfox_bot",
        support_contact="HappyFox support",
        creator_client=FakeCreator(),
    )
    return service, client


def _callback(user_id: int, callback_id: str, payload: str) -> dict:
    return {
        "update_type": "message_callback",
        "callback": {
            "callback_id": callback_id,
            "payload": payload,
            "user": {"user_id": user_id, "name": "Creator"},
        },
    }


def _message(user_id: int, text: str) -> dict:
    return {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": user_id, "name": "Creator"},
            "body": {"text": text, "attachments": []},
        },
    }


def test_audio_profile_fsm_prepares_approved_max_price(tmp_path, monkeypatch) -> None:
    _prepare_database(tmp_path / "max-audio-fsm.db", monkeypatch)
    service, _ = _service()

    asyncio.run(service.handle_update(_callback(401, "cb0", "max:omni_audio")))
    asyncio.run(
        service.handle_update(_callback(401, "cb1", "max:audio:voice:achernar"))
    )
    asyncio.run(
        service.handle_update(
            _message(401, "Studio Voice\nWarm, clear creator narration")
        )
    )

    session = asyncio.run(get_max_session(401))
    assert session.state == "audio:confirm"
    assert session.data["base_voice"] == "achernar"
    assert session.data["name"] == "Studio Voice"
    assert session.data["voice_description"] == "Warm, clear creator narration"
    assert session.data["cost"] == 3
    assert omni_audio_cost() == 3


def test_audio_id_enqueue_and_worker_deliver_real_asset_id(tmp_path, monkeypatch) -> None:
    _prepare_database(tmp_path / "max-audio-worker.db", monkeypatch)

    async def seed():
        await ensure_max_user(402, first_name="Creator")
        await apply_max_balance_delta(
            402,
            20,
            tx_type="test_credit",
            idempotency_key="test:max-audio:credit",
        )
        return await enqueue_max_omni_audio(
            402,
            base_voice="achernar",
            name="Studio Voice",
            voice_description="Warm narrator",
        )

    job = asyncio.run(seed())
    assert job.cost == 3
    assert asyncio.run(get_max_balance(402)) == 17

    async def fake_create_audio(**kwargs):
        assert kwargs["audio_id"] == "achernar"
        assert kwargs["name"] == "Studio Voice"
        return {
            "status": "done",
            "task_id": "audio-asset-123",
            "asset_id": "audio-asset-123",
            "asset_kind": "audio",
        }

    monkeypatch.setattr(
        "bot.max_omni_audio.gemini_omni_service.create_audio",
        fake_create_audio,
    )
    transport = FakeTransport()
    worker = MaxOmniGenerationService(transport)
    asyncio.run(worker._process(job))

    stored = asyncio.run(get_max_generation_job(job.id))
    assert stored is not None
    assert stored.status == "succeeded"
    assert stored.result_url == "audio-asset-123"
    assert "audio-asset-123" in transport.sent[0]["text"]
    assert transport.sent[0]["attachments"]


def test_pending_audio_id_resumes_without_duplicate_create(tmp_path, monkeypatch) -> None:
    _prepare_database(tmp_path / "max-audio-resume.db", monkeypatch)

    async def seed():
        await ensure_max_user(403, first_name="Creator")
        await apply_max_balance_delta(
            403,
            20,
            tx_type="test_credit",
            idempotency_key="test:max-audio-resume:credit",
        )
        return await enqueue_max_omni_audio(
            403,
            base_voice="puck",
            name="Puck Voice",
        )

    job = asyncio.run(seed())
    create_calls = 0

    async def fake_create_audio(**kwargs):
        nonlocal create_calls
        create_calls += 1
        return {
            "status": "pending",
            "task_id": "provider-audio-task",
            "asset_kind": "audio",
        }

    monkeypatch.setattr(
        "bot.max_omni_audio.gemini_omni_service.create_audio",
        fake_create_audio,
    )
    transport = FakeTransport()
    worker = MaxOmniGenerationService(transport)

    with pytest.raises(MaxGenerationRetry):
        asyncio.run(worker._process(job))

    pending = asyncio.run(get_max_generation_job(job.id))
    assert pending is not None
    assert pending.provider_task_id == "provider-audio-task"

    async def fake_get(endpoint, *, params=None):
        assert endpoint == "/api/v1/jobs/recordInfo"
        assert params == {"taskId": "provider-audio-task"}
        return {
            "code": 200,
            "data": {"status": "success", "kieAudioId": "audio-resolved-456"},
        }

    monkeypatch.setattr(
        "bot.max_omni_audio.gemini_omni_service._kie_get",
        fake_get,
    )
    asyncio.run(worker._process(pending))

    stored = asyncio.run(get_max_generation_job(job.id))
    assert stored is not None
    assert stored.status == "succeeded"
    assert stored.result_url == "audio-resolved-456"
    assert create_calls == 1


def test_gemini_omni_video_receives_selected_audio_id(tmp_path, monkeypatch) -> None:
    _prepare_database(tmp_path / "max-audio-video.db", monkeypatch)

    async def seed():
        await ensure_max_user(404, first_name="Creator")
        await apply_max_balance_delta(
            404,
            100,
            tx_type="test_credit",
            idempotency_key="test:max-audio-video:credit",
        )
        return await enqueue_max_generation(
            404,
            kind="video",
            generation_type="text",
            model="gemini_omni",
            prompt="A creator speaking to camera",
            input_data={
                "image_urls": [],
                "video_urls": [],
                "audio_ids": ["audio-selected-789"],
            },
            options={
                "duration": 6,
                "aspect_ratio": "16:9",
                "resolution": "720p",
                "generate_audio": True,
            },
        )

    job = asyncio.run(seed())
    captured = {}

    async def fake_generate_video(**kwargs):
        captured.update(kwargs)
        return {"data": {"taskId": "gemini-video-task"}}

    async def fake_poll(_job):
        return "https://cdn.example.invalid/omni-audio-video.mp4"

    monkeypatch.setattr(
        "bot.max_omni_audio.gemini_omni_service.generate_video",
        fake_generate_video,
    )
    monkeypatch.setattr("bot.max_omni_audio._poll_provider", fake_poll)

    transport = FakeTransport()
    worker = MaxOmniGenerationService(transport)
    asyncio.run(worker._process(job))

    assert captured["audio_ids"] == ["audio-selected-789"]
    assert transport.media[0]["media_type"] == "video"
