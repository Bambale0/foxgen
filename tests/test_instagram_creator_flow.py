import asyncio

from bot import database
from bot.channel_identity import ensure_channel_identity
from bot.instagram_api import InstagramEvent, InstagramSettings
from bot.instagram_creation_mode import get_instagram_creation_kind
from bot.instagram_creator_generation import InstagramCreatorGenerationService
from bot.instagram_generation import get_instagram_draft


class _FakeClient:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, str]] = []

    async def send_text(self, account_id: str, recipient_id: str, text: str):
        self.messages.append((account_id, recipient_id, text))
        return {"message_id": f"msg-{len(self.messages)}"}


async def _identity(tmp_path, monkeypatch, external_user_id: str):
    db_path = tmp_path / f"{external_user_id}.db"
    monkeypatch.setattr(database, "DATABASE_PATH", str(db_path))
    await database.init_db()
    return await ensure_channel_identity(
        channel="instagram",
        account_id="ig-business-1",
        external_user_id=external_user_id,
    )


def _settings() -> InstagramSettings:
    return InstagramSettings(
        enabled=True,
        app_id="app",
        app_secret="secret",
        verify_token="verify",
        access_token="token",
        ig_user_id="ig-business-1",
    )


def _text_event(text: str, sender_id: str) -> InstagramEvent:
    return InstagramEvent(
        event_id=f"message:{sender_id}:{text}",
        kind="message",
        account_id="ig-business-1",
        sender_id=sender_id,
        text=text,
        payload={"message": {"mid": f"mid-{sender_id}", "text": text}},
    )


def _image_event(sender_id: str) -> InstagramEvent:
    return InstagramEvent(
        event_id=f"message:{sender_id}:image",
        kind="message",
        account_id="ig-business-1",
        sender_id=sender_id,
        payload={
            "message": {
                "mid": f"img-{sender_id}",
                "attachments": [
                    {
                        "type": "image",
                        "payload": {"url": "https://cdn.example/source.jpg"},
                    }
                ],
            }
        },
    )


def test_first_instagram_step_always_asks_photo_or_video(tmp_path, monkeypatch) -> None:
    identity = asyncio.run(_identity(tmp_path, monkeypatch, "igsid-choice"))
    client = _FakeClient()
    service = InstagramCreatorGenerationService(settings=_settings(), client=client)

    handled = asyncio.run(service.handle_message(identity, _image_event("igsid-choice")))

    assert handled is True
    assert asyncio.run(get_instagram_creation_kind(identity.id)) == ""
    assert asyncio.run(get_instagram_draft(identity.id)) is None
    assert len(client.messages) == 1
    text = client.messages[0][2].lower()
    assert "что хочешь создать" in text
    assert "фото" in text
    assert "видео" in text
    assert "seedream 5 pro" in text
    assert "seedance 2.5" in text


def test_photo_choice_is_persisted_before_accepting_media(tmp_path, monkeypatch) -> None:
    identity = asyncio.run(_identity(tmp_path, monkeypatch, "igsid-photo"))
    client = _FakeClient()
    service = InstagramCreatorGenerationService(settings=_settings(), client=client)

    assert asyncio.run(
        service.handle_message(identity, _text_event("Фото", "igsid-photo"))
    ) is True

    assert asyncio.run(get_instagram_creation_kind(identity.id)) == "photo"
    assert "seedream 5 pro" in client.messages[-1][2].lower()

    assert asyncio.run(service.handle_message(identity, _image_event("igsid-photo"))) is True
    draft = asyncio.run(get_instagram_draft(identity.id))
    assert draft is not None
    assert draft.image_url == "https://cdn.example/source.jpg"
    assert draft.state == "waiting_prompt"


def test_video_choice_is_persisted_and_accepts_image_reference(tmp_path, monkeypatch) -> None:
    identity = asyncio.run(_identity(tmp_path, monkeypatch, "igsid-video"))
    client = _FakeClient()
    service = InstagramCreatorGenerationService(settings=_settings(), client=client)

    assert asyncio.run(
        service.handle_message(identity, _text_event("Видео", "igsid-video"))
    ) is True

    assert asyncio.run(get_instagram_creation_kind(identity.id)) == "video"
    assert "seedance 2.5" in client.messages[-1][2].lower()

    assert asyncio.run(service.handle_message(identity, _image_event("igsid-video"))) is True
    draft = asyncio.run(get_instagram_draft(identity.id))
    assert draft is not None
    assert draft.image_url == "https://cdn.example/source.jpg"
    assert draft.state == "video:waiting_prompt:image"
