import asyncio

import pytest

from bot import database
from bot.max_api import MaxApiError, MaxSettings
from bot.max_creator_channel import MaxCreatorChannelService
from bot.max_creator_client import MaxCreatorClient, MaxResolvedVideo
from bot.max_creator_generation import (
    MaxCreatorGenerationService,
    enqueue_max_motion_generation,
    motion_cost,
)
from bot.max_generation import get_max_generation_job
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
    def __init__(self, *, duration: int = 5) -> None:
        self.duration = duration
        self.tokens = []

    async def resolve_video_attachment(self, token: str) -> MaxResolvedVideo:
        self.tokens.append(token)
        return MaxResolvedVideo(
            url=f"https://cdn.example.invalid/{token}.mp4",
            duration_seconds=self.duration,
        )


class FakeVideoApi:
    def __init__(self, payload) -> None:
        self.payload = payload
        self.calls = []

    async def _request_json(self, method, path):
        self.calls.append((method, path))
        return self.payload


def _prepare_database(database_path, monkeypatch) -> None:
    monkeypatch.setattr(database, "DATABASE_PATH", str(database_path))
    asyncio.run(database.init_db())


def _service(*, creator=None):
    client = FakeTransport()
    service = MaxCreatorChannelService(
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
        creator_client=creator or FakeCreator(),
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


def _message(user_id: int, text: str, attachments=None) -> dict:
    return {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": user_id, "name": "Creator"},
            "body": {"text": text, "attachments": attachments or []},
        },
    }


def test_max_creator_client_resolves_https_video_and_duration() -> None:
    api = FakeVideoApi(
        {
            "urls": {
                "hls": "http://unsafe.invalid/index.m3u8",
                "mp4_720": "https://cdn.example.invalid/video.mp4",
            },
            "duration": 5.6,
        }
    )
    creator = MaxCreatorClient(api)

    result = asyncio.run(creator.resolve_video_attachment("video-token"))

    assert result.url == "https://cdn.example.invalid/video.mp4"
    assert result.duration_seconds == 6
    assert api.calls == [("GET", "/videos/video-token")]

    with pytest.raises(MaxApiError, match="token is required"):
        asyncio.run(creator.resolve_video_attachment(""))


def test_generic_max_video_flow_resolves_attachment_token(tmp_path, monkeypatch) -> None:
    _prepare_database(tmp_path / "max-token-video.db", monkeypatch)
    creator = FakeCreator(duration=7)
    service, _ = _service(creator=creator)

    asyncio.run(
        service.handle_update(
            _callback(101, "cb-model", "max:video:video:seedance_2")
        )
    )
    asyncio.run(
        service.handle_update(
            _message(
                101,
                "keep the movement, change the style",
                [{"type": "video", "payload": {"token": "max-video-1"}}],
            )
        )
    )

    session = asyncio.run(get_max_session(101))
    assert creator.tokens == ["max-video-1"]
    assert session.state == "video:confirm"
    assert session.data["input_data"]["video_urls"] == [
        "https://cdn.example.invalid/max-video-1.mp4"
    ]


def test_motion_control_fsm_uses_real_duration_and_quality_price(
    tmp_path,
    monkeypatch,
) -> None:
    _prepare_database(tmp_path / "max-motion-fsm.db", monkeypatch)
    creator = FakeCreator(duration=5)
    service, _ = _service(creator=creator)

    asyncio.run(service.handle_update(_callback(202, "cb0", "max:motion_control")))
    asyncio.run(
        service.handle_update(
            _callback(202, "cb1", "max:motion:model:motion_control_v30")
        )
    )
    asyncio.run(
        service.handle_update(
            _message(
                202,
                "cinematic lighting",
                [
                    {
                        "type": "image",
                        "payload": {"url": "https://cdn.example.invalid/person.jpg"},
                    }
                ],
            )
        )
    )
    asyncio.run(
        service.handle_update(
            _message(
                202,
                "",
                [{"type": "video", "payload": {"token": "motion-video"}}],
            )
        )
    )
    asyncio.run(
        service.handle_update(_callback(202, "cb2", "max:motion:orientation:video"))
    )
    asyncio.run(
        service.handle_update(_callback(202, "cb3", "max:motion:quality:720p"))
    )

    session = asyncio.run(get_max_session(202))
    assert session.state == "motion:confirm"
    assert session.data["duration"] == 5
    assert session.data["quality"] == "720p"
    assert session.data["prompt"] == "cinematic lighting"
    assert session.data["cost"] == 30
    assert motion_cost(
        "motion_control_v30",
        duration=5,
        quality="1080p",
    ) == 40


def test_motion_control_enqueue_and_worker_are_durable(
    tmp_path,
    monkeypatch,
) -> None:
    _prepare_database(tmp_path / "max-motion-worker.db", monkeypatch)

    async def seed_user():
        await ensure_max_user(303, first_name="Creator")
        await apply_max_balance_delta(
            303,
            100,
            tx_type="test_credit",
            idempotency_key="test:max-motion:credit",
        )
        return await enqueue_max_motion_generation(
            303,
            model="motion_control_v30",
            image_url="https://cdn.example.invalid/person.jpg",
            video_url="https://cdn.example.invalid/motion.mp4",
            duration=5,
            quality="1080p",
            orientation="video",
            prompt="keep face identity",
        )

    job = asyncio.run(seed_user())
    assert job.cost == 40
    assert asyncio.run(get_max_balance(303)) == 100 - job.cost

    captured = {}

    async def fake_generate_motion_control(**kwargs):
        captured.update(kwargs)
        return {"data": {"taskId": "kie-motion-task"}}

    async def fake_poll(_job):
        return "https://cdn.example.invalid/result.mp4"

    monkeypatch.setattr(
        "bot.max_creator_generation.kling_service.generate_motion_control",
        fake_generate_motion_control,
    )
    monkeypatch.setattr("bot.max_creator_generation._poll_provider", fake_poll)

    transport = FakeTransport()
    service = MaxCreatorGenerationService(transport)
    asyncio.run(service._process(job))

    stored = asyncio.run(get_max_generation_job(job.id))
    assert stored is not None
    assert stored.status == "succeeded"
    assert stored.provider_task_id == "kie-motion-task"
    assert stored.result_url == "https://cdn.example.invalid/result.mp4"
    assert captured["motion_model"] == "kling-3.0/motion-control"
    assert captured["mode"] == "1080p"
    assert captured["motion_direction"] == "video"
    assert transport.media[0]["media_type"] == "video"
