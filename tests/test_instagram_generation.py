import asyncio

from bot import database
from bot import db as db_backend
from bot import instagram_generation
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
    def __init__(self, *, fail_first_media: bool = False) -> None:
        self.messages: list[tuple[str, str, str]] = []
        self.media: list[tuple[str, str, str, str]] = []
        self.fail_first_media = fail_first_media
        self.media_attempts = 0

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
        self.media_attempts += 1
        if self.fail_first_media and self.media_attempts == 1:
            raise RuntimeError("temporary Meta delivery failure")
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


def _image_event(sender_id: str = "igsid-1") -> InstagramEvent:
    return InstagramEvent(
        event_id="message:image-1",
        kind="message",
        account_id="ig-business-1",
        sender_id=sender_id,
        payload={
            "message": {
                "mid": "image-1",
                "attachments": [
                    {
                        "type": "image",
                        "payload": {
                            "url": "https://cdn.example/reference.jpg"
                        },
                    }
                ],
            }
        },
    )


def _text_event(
    text: str,
    sender_id: str = "igsid-1",
    *,
    event_id: str = "text-1",
) -> InstagramEvent:
    return InstagramEvent(
        event_id=f"message:{event_id}",
        kind="message",
        account_id="ig-business-1",
        sender_id=sender_id,
        text=text,
        payload={"message": {"mid": event_id, "text": text}},
    )


def _prepare_identity(
    tmp_path,
    monkeypatch,
    *,
    external_user_id: str = "igsid-1",
):
    database_path = tmp_path / f"{external_user_id}.db"
    monkeypatch.setattr(database, "DATABASE_PATH", str(database_path))
    asyncio.run(database.init_db())
    return asyncio.run(
        ensure_channel_identity(
            channel="instagram",
            account_id="ig-business-1",
            external_user_id=external_user_id,
        )
    )


async def _make_job_retry_ready(job_id: str) -> None:
    async with db_backend.connect() as db:
        await db.execute(
            """
            UPDATE instagram_generation_jobs
            SET next_attempt_at_epoch = 0
            WHERE id = ?
            """,
            (job_id,),
        )
        await db.commit()


def test_first_instagram_image_runs_free_without_telegram_link(
    tmp_path,
    monkeypatch,
) -> None:
    identity = _prepare_identity(tmp_path, monkeypatch)
    client = _FakeClient()
    generator_calls: list[tuple[str, str]] = []

    async def generator(prompt: str, image_url: str) -> str:
        generator_calls.append((prompt, image_url))
        return "https://cdn.example/result-free.jpg"

    service = InstagramGenerationService(
        settings=_settings(),
        client=client,
        generator=generator,
    )

    assert asyncio.run(service.handle_message(identity, _image_event())) is True
    draft = asyncio.run(get_instagram_draft(identity.id))
    assert draft is not None
    assert draft.state == "waiting_prompt"

    assert (
        asyncio.run(
            service.handle_message(
                identity,
                _text_event("Сделай стильную аватарку"),
            )
        )
        is True
    )
    queued = asyncio.run(_claim_next_job())
    assert queued is not None
    assert queued.billing_mode == "free"
    assert queued.cost == 0

    asyncio.run(service._process_job(queued))

    assert generator_calls == [
        ("Сделай стильную аватарку", "https://cdn.example/reference.jpg")
    ]
    assert client.media == [
        (
            "ig-business-1",
            "igsid-1",
            "image",
            "https://cdn.example/result-free.jpg",
        )
    ]
    promotion = asyncio.run(ensure_instagram_first_image_promotion(identity.id))
    assert promotion.status == "consumed"
    final_draft = asyncio.run(get_instagram_draft(identity.id))
    assert final_draft is not None
    assert final_draft.state == "idle"
    assert final_draft.image_url == ""


def test_failed_free_generation_keeps_the_gift_for_retry(
    tmp_path,
    monkeypatch,
) -> None:
    identity = _prepare_identity(
        tmp_path,
        monkeypatch,
        external_user_id="igsid-fail",
    )
    client = _FakeClient()

    async def failing_generator(_prompt: str, _image_url: str) -> str:
        raise RuntimeError("provider failed")

    service = InstagramGenerationService(
        settings=_settings(),
        client=client,
        generator=failing_generator,
    )

    asyncio.run(service.handle_message(identity, _image_event("igsid-fail")))
    asyncio.run(
        service.handle_message(
            identity,
            _text_event(
                "Сделай портрет",
                "igsid-fail",
                event_id="fail-text",
            ),
        )
    )
    job = asyncio.run(_claim_next_job())
    assert job is not None
    asyncio.run(service._process_job(job))

    promotion = asyncio.run(ensure_instagram_first_image_promotion(identity.id))
    assert promotion.status == "available"
    assert any(
        "Бесплатная попытка сохранена" in message[2]
        for message in client.messages
    )


def test_second_instagram_image_requires_confirmation_and_charges_normal_price(
    tmp_path,
    monkeypatch,
) -> None:
    identity = _prepare_identity(
        tmp_path,
        monkeypatch,
        external_user_id="igsid-paid",
    )
    user = asyncio.run(database.get_or_create_user(700020))
    identity = asyncio.run(
        link_channel_identity_to_user(identity_id=identity.id, user_id=user.id)
    )
    assert (
        asyncio.run(
            reserve_instagram_first_image(identity.id, "already-free")
        )
        is True
    )
    assert asyncio.run(consume_instagram_first_image("already-free")) is True

    client = _FakeClient()

    async def generator(_prompt: str, _image_url: str) -> str:
        return "https://cdn.example/result-paid.jpg"

    service = InstagramGenerationService(
        settings=_settings(),
        client=client,
        generator=generator,
    )
    before = float(asyncio.run(database.get_user_credits(700020)))

    asyncio.run(service.handle_message(identity, _image_event("igsid-paid")))
    asyncio.run(
        service.handle_message(
            identity,
            _text_event(
                "Сделай fashion-портрет",
                "igsid-paid",
                event_id="paid-prompt",
            ),
        )
    )
    draft = asyncio.run(get_instagram_draft(identity.id))
    assert draft is not None
    assert draft.state == "awaiting_confirmation"
    assert any(
        "2.5" in message[2] and "ДА" in message[2]
        for message in client.messages
    )

    asyncio.run(
        service.handle_message(
            identity,
            _text_event("ДА", "igsid-paid", event_id="paid-confirm"),
        )
    )
    after_charge = float(asyncio.run(database.get_user_credits(700020)))
    assert after_charge == before - 2.5

    job = asyncio.run(_claim_next_job())
    assert job is not None
    assert job.billing_mode == "credits"
    assert job.cost == 2.5
    asyncio.run(service._process_job(job))

    assert client.media[-1][-1] == "https://cdn.example/result-paid.jpg"
    after_success = float(asyncio.run(database.get_user_credits(700020)))
    assert after_success == after_charge


def test_paid_generation_failure_refunds_credits(tmp_path, monkeypatch) -> None:
    identity = _prepare_identity(
        tmp_path,
        monkeypatch,
        external_user_id="igsid-refund",
    )
    user = asyncio.run(database.get_or_create_user(700030))
    identity = asyncio.run(
        link_channel_identity_to_user(identity_id=identity.id, user_id=user.id)
    )
    assert (
        asyncio.run(reserve_instagram_first_image(identity.id, "used-free"))
        is True
    )
    assert asyncio.run(consume_instagram_first_image("used-free")) is True

    client = _FakeClient()

    async def failing_generator(_prompt: str, _image_url: str) -> str:
        raise RuntimeError("provider failed")

    service = InstagramGenerationService(
        settings=_settings(),
        client=client,
        generator=failing_generator,
    )
    before = float(asyncio.run(database.get_user_credits(700030)))
    asyncio.run(service.handle_message(identity, _image_event("igsid-refund")))
    asyncio.run(
        service.handle_message(
            identity,
            _text_event(
                "Убери фон",
                "igsid-refund",
                event_id="refund-prompt",
            ),
        )
    )
    asyncio.run(
        service.handle_message(
            identity,
            _text_event("да", "igsid-refund", event_id="refund-confirm"),
        )
    )
    assert float(asyncio.run(database.get_user_credits(700030))) == before - 2.5
    job = asyncio.run(_claim_next_job())
    assert job is not None
    asyncio.run(service._process_job(job))

    assert float(asyncio.run(database.get_user_credits(700030))) == before
    assert any("возвращены" in message[2].lower() for message in client.messages)


def test_delivery_retry_does_not_generate_or_charge_twice(
    tmp_path,
    monkeypatch,
) -> None:
    identity = _prepare_identity(
        tmp_path,
        monkeypatch,
        external_user_id="igsid-delivery",
    )
    client = _FakeClient(fail_first_media=True)
    calls = 0

    async def generator(_prompt: str, _image_url: str) -> str:
        nonlocal calls
        calls += 1
        return "https://cdn.example/result-retry.jpg"

    service = InstagramGenerationService(
        settings=_settings(),
        client=client,
        generator=generator,
    )
    asyncio.run(service.handle_message(identity, _image_event("igsid-delivery")))
    asyncio.run(
        service.handle_message(
            identity,
            _text_event(
                "Сделай арт",
                "igsid-delivery",
                event_id="delivery-prompt",
            ),
        )
    )
    first_job = asyncio.run(_claim_next_job())
    assert first_job is not None
    asyncio.run(service._process_job(first_job))
    assert calls == 1

    asyncio.run(_make_job_retry_ready(first_job.id))
    retry_job = asyncio.run(_claim_next_job())
    assert retry_job is not None
    assert retry_job.result_url == "https://cdn.example/result-retry.jpg"
    assert retry_job.delivered_at_epoch is None
    asyncio.run(service._process_job(retry_job))

    assert calls == 1
    assert client.media_attempts == 2
    promotion = asyncio.run(ensure_instagram_first_image_promotion(identity.id))
    assert promotion.status == "consumed"


def test_finalization_retry_does_not_resend_already_delivered_image(
    tmp_path,
    monkeypatch,
) -> None:
    identity = _prepare_identity(
        tmp_path,
        monkeypatch,
        external_user_id="igsid-finalize",
    )
    client = _FakeClient()
    calls = 0
    consume_calls = 0
    real_consume = instagram_generation.consume_instagram_first_image

    async def generator(_prompt: str, _image_url: str) -> str:
        nonlocal calls
        calls += 1
        return "https://cdn.example/result-finalize.jpg"

    async def flaky_consume(reservation_key: str) -> bool:
        nonlocal consume_calls
        consume_calls += 1
        if consume_calls == 1:
            raise RuntimeError("temporary promotion DB failure")
        return await real_consume(reservation_key)

    monkeypatch.setattr(
        instagram_generation,
        "consume_instagram_first_image",
        flaky_consume,
    )
    service = InstagramGenerationService(
        settings=_settings(),
        client=client,
        generator=generator,
    )
    asyncio.run(service.handle_message(identity, _image_event("igsid-finalize")))
    asyncio.run(
        service.handle_message(
            identity,
            _text_event(
                "Сделай киношный портрет",
                "igsid-finalize",
                event_id="finalize-prompt",
            ),
        )
    )
    first_job = asyncio.run(_claim_next_job())
    assert first_job is not None
    asyncio.run(service._process_job(first_job))

    assert calls == 1
    assert client.media_attempts == 1
    asyncio.run(_make_job_retry_ready(first_job.id))
    retry_job = asyncio.run(_claim_next_job())
    assert retry_job is not None
    assert retry_job.delivered_at_epoch is not None
    asyncio.run(service._process_job(retry_job))

    assert calls == 1
    assert client.media_attempts == 1
    assert consume_calls == 2
    promotion = asyncio.run(ensure_instagram_first_image_promotion(identity.id))
    assert promotion.status == "consumed"
