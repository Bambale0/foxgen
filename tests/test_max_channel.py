import asyncio
from types import SimpleNamespace

from bot import database
from bot.max_api import MaxSettings
from bot.max_channel import MaxChannelService
from bot.max_store import get_max_session


class FakeMaxClient:
    def __init__(self) -> None:
        self.sent = []
        self.answers = []

    async def send_message(self, user_id, text, *, attachments=None, format="html", notify=True):
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


class FakePayments:
    enabled = True


def _prepare_database(database_path, monkeypatch) -> None:
    monkeypatch.setattr(database, "DATABASE_PATH", str(database_path))
    asyncio.run(database.init_db())


def _service() -> tuple[MaxChannelService, FakeMaxClient]:
    client = FakeMaxClient()
    service = MaxChannelService(
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


def test_max_photo_fsm_prepares_and_enqueues_generation(tmp_path, monkeypatch) -> None:
    _prepare_database(tmp_path / "max-channel-photo.db", monkeypatch)
    service, client = _service()
    captured = {}

    async def fake_enqueue(max_user_id, **kwargs):
        captured["max_user_id"] = max_user_id
        captured.update(kwargs)
        return SimpleNamespace(id="maxjob123456789", cost=2.5)

    monkeypatch.setattr("bot.max_channel.enqueue_max_generation", fake_enqueue)

    asyncio.run(service.handle_update(_callback(42, "cb1", "max:create_image")))
    asyncio.run(service.handle_update(_callback(42, "cb2", "max:image:banana_2")))
    waiting = asyncio.run(get_max_session(42))
    assert waiting.state == "image:waiting_input"
    assert waiting.data["model"] == "banana_2"

    asyncio.run(
        service.handle_update(
            _message(
                42,
                "cinematic fox portrait",
                [
                    {
                        "type": "image",
                        "payload": {"url": "https://cdn.example.invalid/ref.jpg"},
                    }
                ],
            )
        )
    )
    prepared = asyncio.run(get_max_session(42))
    assert prepared.state == "image:confirm"
    assert prepared.data["prompt"] == "cinematic fox portrait"
    assert prepared.data["input_data"]["image_urls"] == [
        "https://cdn.example.invalid/ref.jpg"
    ]

    asyncio.run(service.handle_update(_callback(42, "cb3", "max:generate")))
    assert captured["max_user_id"] == 42
    assert captured["kind"] == "image"
    assert captured["model"] == "banana_2"
    assert captured["prompt"] == "cinematic fox portrait"
    assert captured["input_data"]["image_urls"]
    assert asyncio.run(get_max_session(42)).state == ""
    assert client.answers[-1]["callback_id"] == "cb3"
    assert "Генерация запущена" in client.answers[-1]["message"]["text"]


def test_max_video_fsm_requires_reference_for_image_to_video(tmp_path, monkeypatch) -> None:
    _prepare_database(tmp_path / "max-channel-video.db", monkeypatch)
    service, client = _service()

    asyncio.run(
        service.handle_update(
            _callback(99, "cb-video", "max:video:imgtxt:grok_imagine")
        )
    )
    assert asyncio.run(get_max_session(99)).state == "video:waiting_input"

    asyncio.run(service.handle_update(_message(99, "animate this portrait")))
    still_waiting = asyncio.run(get_max_session(99))
    assert still_waiting.state == "video:waiting_input"
    assert "приложите изображение" in client.sent[-1]["text"]

    asyncio.run(
        service.handle_update(
            _message(
                99,
                "animate this portrait",
                [
                    {
                        "type": "image",
                        "payload": {
                            "photos": {
                                "large": {"url": "https://cdn.example.invalid/portrait.jpg"}
                            }
                        },
                    }
                ],
            )
        )
    )
    prepared = asyncio.run(get_max_session(99))
    assert prepared.state == "video:confirm"
    assert prepared.data["generation_type"] == "imgtxt"
    assert prepared.data["input_data"]["image_urls"] == [
        "https://cdn.example.invalid/portrait.jpg"
    ]


def test_max_bot_started_referral_is_max_only(tmp_path, monkeypatch) -> None:
    _prepare_database(tmp_path / "max-channel-ref.db", monkeypatch)
    service, client = _service()

    asyncio.run(
        service.handle_update(
            {
                "update_type": "bot_started",
                "user": {"user_id": 500, "name": "New Creator"},
                "payload": "ref_400",
            }
        )
    )

    assert any("Реферальный бонус MAX начислен" in item["text"] for item in client.sent)
    assert asyncio.run(get_max_session(500)).state == ""

    async def _assert_no_telegram_user() -> None:
        from bot import db as db_backend

        async with db_backend.connect() as db:
            db.row_factory = db_backend.Row
            cursor = await db.execute("SELECT id FROM users WHERE telegram_id = ?", (500,))
            assert await cursor.fetchone() is None

    asyncio.run(_assert_no_telegram_user())
