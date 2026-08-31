import asyncio

from bot import database, instagram_video_generation
from bot.channel_identity import ensure_channel_identity
from bot.instagram_api import InstagramEvent, InstagramSettings
from bot.instagram_creator_generation import InstagramCreatorGenerationService
from bot.instagram_generation import get_instagram_draft
from bot.instagram_i18n import (
    detect_instagram_language,
    get_instagram_language,
)


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


async def _account_link(_identity) -> str:
    return "https://t.me/HappyFoxBot?start=iglink_test-token"


def test_language_detector_supports_ru_en_and_explicit_switches() -> None:
    assert detect_instagram_language("Хочу фото") == "ru"
    assert detect_instagram_language("I want a photo") == "en"
    assert detect_instagram_language("English") == "en"
    assert detect_instagram_language("Русский") == "ru"
    assert detect_instagram_language("🔥 123") == ""


def test_attachment_first_uses_bilingual_choice_until_language_is_known(
    tmp_path,
    monkeypatch,
) -> None:
    identity = asyncio.run(_identity(tmp_path, monkeypatch, "igsid-bilingual"))
    client = _FakeClient()
    service = InstagramCreatorGenerationService(settings=_settings(), client=client)

    assert asyncio.run(
        service.handle_message(identity, _image_event("igsid-bilingual"))
    ) is True

    assert asyncio.run(get_instagram_language(identity.id)) == ""
    text = client.messages[-1][2].lower()
    assert "что хочешь создать" in text
    assert "what do you want to create" in text
    assert "фото / photo" in text
    assert "видео / video" in text


def test_english_photo_choice_persists_language_and_localizes_followups(
    tmp_path,
    monkeypatch,
) -> None:
    identity = asyncio.run(_identity(tmp_path, monkeypatch, "igsid-en-photo"))
    client = _FakeClient()
    service = InstagramCreatorGenerationService(settings=_settings(), client=client)

    assert asyncio.run(
        service.handle_message(identity, _text_event("Photo", "igsid-en-photo"))
    ) is True
    assert asyncio.run(get_instagram_language(identity.id)) == "en"
    assert "photo selected" in client.messages[-1][2].lower()
    assert "first photo generation is free" in client.messages[-1][2].lower()

    assert asyncio.run(
        service.handle_message(identity, _image_event("igsid-en-photo"))
    ) is True
    assert "photo received" in client.messages[-1][2].lower()
    assert "describe the result" in client.messages[-1][2].lower()


def test_english_video_continue_resumes_paid_flow(tmp_path, monkeypatch) -> None:
    identity = asyncio.run(_identity(tmp_path, monkeypatch, "igsid-en-video"))
    client = _FakeClient()
    service = InstagramCreatorGenerationService(
        settings=_settings(),
        client=client,
        account_link_factory=_account_link,
    )

    async def fake_linked_billing_user(_identity_id: int):
        return 77, 700010, 999.0

    monkeypatch.setattr(
        instagram_video_generation.generation,
        "_linked_billing_user",
        fake_linked_billing_user,
    )

    assert asyncio.run(
        service.handle_message(identity, _text_event("Video", "igsid-en-video"))
    ) is True
    assert asyncio.run(get_instagram_language(identity.id)) == "en"
    paywall = client.messages[-1][2].lower()
    assert "instagram video is paid" in paywall
    assert "yookassa or lava top" in paywall
    assert "continue" in paywall

    assert asyncio.run(
        service.handle_message(identity, _text_event("Continue", "igsid-en-video"))
    ) is True
    draft = asyncio.run(get_instagram_draft(identity.id))
    assert draft is not None
    assert draft.state == "video:waiting_source:"
    assert "now send a photo or video reference" in client.messages[-1][2].lower()


def test_explicit_language_command_switches_existing_session(tmp_path, monkeypatch) -> None:
    identity = asyncio.run(_identity(tmp_path, monkeypatch, "igsid-switch"))
    client = _FakeClient()
    service = InstagramCreatorGenerationService(settings=_settings(), client=client)

    assert asyncio.run(
        service.handle_message(identity, _text_event("Фото", "igsid-switch"))
    ) is True
    assert asyncio.run(get_instagram_language(identity.id)) == "ru"

    assert asyncio.run(
        service.handle_message(identity, _text_event("English", "igsid-switch"))
    ) is True
    assert asyncio.run(get_instagram_language(identity.id)) == "en"
    assert "send a photo first" in client.messages[-1][2].lower()
