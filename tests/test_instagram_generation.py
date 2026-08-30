import asyncio

from bot import database
from bot.channel_identity import ensure_channel_identity, link_channel_identity_to_user
from bot.channel_promotions import (
    consume_instagram_first_image,
    ensure_instagram_first_image_promotion,
    reserve_instagram_first_image,
)
from bot.instagram_api import InstagramEvent, InstagramSettings
from bot.instagram_generation import (
    InstagramGenerationService,
    _claim_next_job,
    get_instagram_draft,
)


class _FakeClient:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, str]] = []
        self.media: list[tuple[str, str, str, str]] = []

    async def send_text(self, account_id: str, recipient_id: str, text: str):
        self.messages.append((account_id, recipient_id, text))
        return {"message_id": f"text-{len(self.messages)}"}

    async def send_media(
        self,
        account_id: str,
        recipient_id: str,
        media_type: str,
        media_url: str,
    ):
        self.media.append((account_id, recipient_id, media_type, media_url))
        return {"message_id": f"media-{len(self.media)}"}


def _settings() -> InstagramSettings:
    return InstagramSettings(
        enabled=True,
        app_id="app",
        app_secret="secret",
        verify_token="verify",
        access_token="token",
        ig_user_id="ig-business-1",
    )


async def _prepare_identity(tmp_path, monkeypatch, external_user_id: str):
    database_path = tmp_path / f"{external_user_id}.db"
    monkeypatch.setattr(database, "DATABASE_PATH", str(database_path))
    await database.init_db()
    return await ensure_channel_identity(
        channel="instagram",
        account_id="ig-business-1",
        external_user_id=external_user_id,
    )


def _image_event(sender_id: str) -> InstagramEvent:
    return InstagramEvent(
        event_id=f"message:{sender_id}:image",
        kind="message",
        account_id="ig-business-1",
        sender_id=sender_id,
        payload={
            "message": {
                "mid": f"image-{sender_id}",
                "attachments": [
                    {
                        "type": "image",
                        "payload": {"url": "https://cdn.example/reference.jpg"},
                    }
                ],
            }
        },
    )


def _text_event(text: str, sender_id: str) -> InstagramEvent:
    return InstagramEvent(
        event_id=f"message:{sender_id}:{text}",
        kind="message",
        account_id="ig-business-1",
        sender_id=sender_id,
        text=text,
        payload={"message": {"mid": f"text-{sender_id}", "text": text}},
    )


def test_first_instagram_generation_is_free_and_consumed_on_success(
    tmp_path,
    monkeypatch,
) -> None:
    identity = asyncio.run(_prepare_identity(tmp_path, monkeypatch, "igsid-free"))
    client = _FakeClient()

    async def generator(_prompt: str, _image_url: str) -> str:
        return "https://cdn.example/result-free.jpg"

    service = InstagramGenerationService(
        settings=_settings(),
        client=client,
        generator=generator,
    )

    assert asyncio.run(service.handle_message(identity, _image_event("igsid-free")))
    assert asyncio.run(
        service.handle_message(
            identity,
            _text_event("Сделай стильный портрет", "igsid-free"),
        )
    )

    job = asyncio.run(_claim_next_job())
    assert job is not None
    assert job.billing_mode == "free"
    assert job.cost == 0
    asyncio.run(service._process_job(job))

    promotion = asyncio.run(ensure_instagram_first_image_promotion(identity.id))
    assert promotion.status == "consumed"
    assert client.media[-1][-1] == "https://cdn.example/result-free.jpg"
    draft = asyncio.run(get_instagram_draft(identity.id))
    assert draft is not None
    assert draft.state == "idle"
    assert draft.image_url == ""


def test_failed_free_generation_does_not_burn_entitlement(tmp_path, monkeypatch) -> None:
    identity = asyncio.run(_prepare_identity(tmp_path, monkeypatch, "igsid-free-fail"))
    client = _FakeClient()

    async def generator(_prompt: str, _image_url: str) -> str:
        raise RuntimeError("provider failed")

    service = InstagramGenerationService(
        settings=_settings(),
        client=client,
        generator=generator,
    )

    asyncio.run(service.handle_message(identity, _image_event("igsid-free-fail")))
    asyncio.run(
        service.handle_message(
            identity,
            _text_event("Сделай арт", "igsid-free-fail"),
        )
    )
    job = asyncio.run(_claim_next_job())
    assert job is not None
    asyncio.run(service._process_job(job))

    promotion = asyncio.run(ensure_instagram_first_image_promotion(identity.id))
    assert promotion.status == "available"
    assert any("Бесплатная попытка сохранена" in item[2] for item in client.messages)


def test_paid_generation_failure_refunds_same_happyfox_balance(
    tmp_path,
    monkeypatch,
) -> None:
    identity = asyncio.run(_prepare_identity(tmp_path, monkeypatch, "igsid-paid-fail"))
    user = asyncio.run(database.get_or_create_user(700030))
    identity = asyncio.run(
        link_channel_identity_to_user(identity_id=identity.id, user_id=user.id)
    )
    assert asyncio.run(reserve_instagram_first_image(identity.id, "used-free")) is True
    assert asyncio.run(consume_instagram_first_image("used-free")) is True

    client = _FakeClient()

    async def generator(_prompt: str, _image_url: str) -> str:
        raise RuntimeError("provider failed")

    service = InstagramGenerationService(
        settings=_settings(),
        client=client,
        generator=generator,
    )
    before = float(asyncio.run(database.get_user_credits(700030)))

    asyncio.run(service.handle_message(identity, _image_event("igsid-paid-fail")))
    asyncio.run(
        service.handle_message(
            identity,
            _text_event("Убери фон", "igsid-paid-fail"),
        )
    )
    asyncio.run(
        service.handle_message(
            identity,
            _text_event("да", "igsid-paid-fail"),
        )
    )
    charged = float(asyncio.run(database.get_user_credits(700030)))
    assert charged < before

    job = asyncio.run(_claim_next_job())
    assert job is not None
    assert job.billing_mode == "credits"
    asyncio.run(service._process_job(job))

    after = float(asyncio.run(database.get_user_credits(700030)))
    assert after == before
    assert any("возвращены" in item[2].lower() for item in client.messages)
