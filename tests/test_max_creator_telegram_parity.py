import asyncio

from bot import database
from bot.max_api import MaxSettings
from bot.max_creation_parity import MaxCreationParityChannelService
from bot.max_store import get_max_session


class FakeMaxClient:
    def __init__(self) -> None:
        self.sent = []
        self.answers = []

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

    async def _request_json(self, *args, **kwargs):
        return {}


class FakePayments:
    enabled = True


def _prepare_database(database_path, monkeypatch) -> None:
    monkeypatch.setattr(database, "DATABASE_PATH", str(database_path))
    asyncio.run(database.init_db())


def _service() -> tuple[MaxCreationParityChannelService, FakeMaxClient]:
    client = FakeMaxClient()
    service = MaxCreationParityChannelService(
        settings=MaxSettings(
            enabled=True,
            access_token="token",
            webhook_secret="valid_secret",
            mini_app_url="https://example.invalid/mini-app/",
        ),
        client=client,
        payments=FakePayments(),
        bot_name="happyfox_bot",
        support_contact="https://max.ru/happyfox-support",
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


def _message(
    user_id: int,
    text: str = "",
    *,
    image_url: str = "",
    video_url: str = "",
) -> dict:
    attachments = []
    if image_url:
        attachments.append({"type": "image", "payload": {"url": image_url}})
    if video_url:
        attachments.append({"type": "video", "payload": {"url": video_url}})
    return {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": user_id, "name": "Creator"},
            "body": {"text": text, "attachments": attachments},
        },
    }


def _callbacks(message: dict) -> set[str]:
    result: set[str] = set()
    for attachment in message.get("attachments") or []:
        for row in attachment.get("payload", {}).get("buttons", []):
            for button in row:
                if button.get("type") == "callback":
                    result.add(str(button.get("payload") or ""))
    return result


def test_max_photo_follows_model_refs_settings_prompt_confirm(
    tmp_path,
    monkeypatch,
) -> None:
    _prepare_database(tmp_path / "max-photo-parity.db", monkeypatch)
    service, client = _service()

    asyncio.run(service.handle_update(_callback(801, "photo", "max:create_image")))
    assert "max:image:banana_2" in _callbacks(client.answers[-1]["message"])

    asyncio.run(service.handle_update(_callback(801, "model", "max:image:banana_2")))
    session = asyncio.run(get_max_session(801))
    assert session.state == "parity:image:refs"
    assert "max:image:refs:skip" in _callbacks(client.answers[-1]["message"])
    assert "max:image:refs:continue" in _callbacks(client.answers[-1]["message"])

    asyncio.run(service.handle_update(_callback(801, "skip", "max:image:refs:skip")))
    session = asyncio.run(get_max_session(801))
    assert session.state == "parity:image:settings_prompt"

    settings_callbacks = _callbacks(client.answers[-1]["message"])
    assert "max:image:ratio:9x16" in settings_callbacks
    assert "max:image:quality:4k" in settings_callbacks
    assert "max:image:count:4" in settings_callbacks

    asyncio.run(service.handle_update(_callback(801, "ratio", "max:image:ratio:9x16")))
    asyncio.run(service.handle_update(_callback(801, "quality", "max:image:quality:4k")))
    asyncio.run(service.handle_update(_callback(801, "count", "max:image:count:4")))
    session = asyncio.run(get_max_session(801))
    assert session.data["aspect_ratio"] == "9:16"
    assert session.data["quality"] == "4K"
    assert session.data["count"] == 4

    asyncio.run(service.handle_update(_message(801, "cinematic portrait")))
    session = asyncio.run(get_max_session(801))
    assert session.state == "parity:image:confirm"
    assert session.data["prompt"] == "cinematic portrait"
    assert session.data["options"]["aspect_ratio"] == "9:16"
    assert session.data["options"]["quality"] == "4K"
    assert session.data["count"] == 4
    assert "max:generate" in _callbacks(client.sent[-1])
    assert "max:cancel" in _callbacks(client.sent[-1])


def test_max_required_image_reference_cannot_be_skipped(tmp_path, monkeypatch) -> None:
    _prepare_database(tmp_path / "max-photo-required-ref.db", monkeypatch)
    service, client = _service()

    asyncio.run(service.handle_update(_callback(802, "photo", "max:create_image")))
    asyncio.run(service.handle_update(_callback(802, "model", "max:image:seedream_edit")))
    asyncio.run(service.handle_update(_callback(802, "skip", "max:image:refs:skip")))

    session = asyncio.run(get_max_session(802))
    assert session.state == "parity:image:refs"
    assert "нужен хотя бы один референс" in client.answers[-1]["message"]["text"]

    asyncio.run(
        service.handle_update(
            _message(802, image_url="https://example.invalid/reference.jpg")
        )
    )
    asyncio.run(
        service.handle_update(_callback(802, "continue", "max:image:refs:continue"))
    )
    assert asyncio.run(get_max_session(802)).state == "parity:image:settings_prompt"


def test_max_video_follows_model_type_media_settings_prompt_confirm(
    tmp_path,
    monkeypatch,
) -> None:
    _prepare_database(tmp_path / "max-video-parity.db", monkeypatch)
    service, client = _service()

    asyncio.run(service.handle_update(_callback(803, "video", "max:create_video")))
    assert any(
        payload.startswith("max:video_model:")
        for payload in _callbacks(client.answers[-1]["message"])
    )

    asyncio.run(
        service.handle_update(_callback(803, "model", "max:video_model:v3_pro"))
    )
    assert asyncio.run(get_max_session(803)).state == "video:select_type"

    asyncio.run(service.handle_update(_callback(803, "type", "max:vtype:imgtxt")))
    session = asyncio.run(get_max_session(803))
    assert session.state == "parity:video:media"
    assert session.data["generation_type"] == "imgtxt"

    asyncio.run(
        service.handle_update(
            _message(803, image_url="https://example.invalid/start.jpg")
        )
    )
    session = asyncio.run(get_max_session(803))
    assert session.data["image_urls"] == ["https://example.invalid/start.jpg"]

    asyncio.run(
        service.handle_update(
            _callback(803, "media-continue", "max:video:media:continue")
        )
    )
    assert asyncio.run(get_max_session(803)).state == "parity:video:settings_prompt"

    asyncio.run(
        service.handle_update(_callback(803, "duration", "max:video:duration:10"))
    )
    asyncio.run(
        service.handle_update(_callback(803, "ratio", "max:video:ratio:9x16"))
    )
    session = asyncio.run(get_max_session(803))
    assert session.data["options"]["duration"] == 10
    assert session.data["options"]["aspect_ratio"] == "9:16"

    asyncio.run(service.handle_update(_message(803, "camera moves forward")))
    session = asyncio.run(get_max_session(803))
    assert session.state == "video:confirm"
    assert session.data["input_data"]["image_urls"] == [
        "https://example.invalid/start.jpg"
    ]
    assert session.data["options"]["duration"] == 10
    assert session.data["options"]["aspect_ratio"] == "9:16"
    assert "max:generate" in _callbacks(client.sent[-1])


def test_seedance25_model_first_entry_keeps_dedicated_full_wizard(
    tmp_path,
    monkeypatch,
) -> None:
    _prepare_database(tmp_path / "max-seedance25-parity.db", monkeypatch)
    service, client = _service()

    asyncio.run(service.handle_update(_callback(804, "video", "max:create_video")))
    asyncio.run(
        service.handle_update(
            _callback(804, "model", "max:video_model:seedance_2_5")
        )
    )
    assert asyncio.run(get_max_session(804)).state == "video:select_type"

    asyncio.run(service.handle_update(_callback(804, "type", "max:vtype:text")))
    session = asyncio.run(get_max_session(804))
    assert session.state == "seedance25:configure"
    callbacks = _callbacks(client.answers[-1]["message"])
    assert "max:s25:res:480p" in callbacks
    assert "max:s25:res:720p" in callbacks
    assert "max:s25:dur:plus" in callbacks
    assert "max:s25:audio" in callbacks
    assert "max:s25:continue" in callbacks
