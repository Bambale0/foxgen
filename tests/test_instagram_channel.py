import asyncio
from dataclasses import dataclass

from bot.channel_promotions import ChannelPromotionStatus
from bot.instagram_api import InstagramEvent, InstagramSettings
from bot.instagram_channel import InstagramChannelAdapter


@dataclass
class _Identity:
    id: int = 1
    user_id: int | None = 42


class _FakeClient:
    def __init__(self) -> None:
        self.private_replies: list[tuple[str, str, str]] = []
        self.messages: list[tuple[str, str, str]] = []

    async def private_reply(self, account_id: str, comment_id: str, text: str):
        self.private_replies.append((account_id, comment_id, text))
        return {"recipient_id": "igsid-1", "message_id": "reply-1"}

    async def send_text(self, account_id: str, recipient_id: str, text: str):
        self.messages.append((account_id, recipient_id, text))
        return {"recipient_id": recipient_id, "message_id": "message-1"}


async def _identity_resolver(**_kwargs):
    return _Identity()


async def _available_promotion(_identity_id: int):
    return ChannelPromotionStatus(
        promotion_code="instagram_first_image",
        status="available",
        reservation_key=None,
    )


def _adapter(
    client: _FakeClient,
    *,
    identity_resolver=_identity_resolver,
    promotion_resolver=_available_promotion,
    account_link_factory=None,
) -> InstagramChannelAdapter:
    settings = InstagramSettings(
        enabled=True,
        app_id="app",
        app_secret="secret",
        verify_token="verify",
        access_token="token",
        ig_user_id="ig-business-1",
    )
    return InstagramChannelAdapter(
        settings=settings,
        client=client,
        identity_resolver=identity_resolver,
        promotion_resolver=promotion_resolver,
        account_link_factory=account_link_factory,
    )


def test_comment_keyword_starts_private_reply_acquisition_flow() -> None:
    client = _FakeClient()
    adapter = _adapter(client)
    event = InstagramEvent(
        event_id="comments:comment-1",
        kind="comments",
        account_id="ig-business-1",
        sender_id="igsid-1",
        text="ХОЧУ!",
        payload={"id": "comment-1", "from": {"id": "igsid-1", "username": "creator"}},
    )

    asyncio.run(adapter.handle_event(event))

    assert len(client.private_replies) == 1
    account_id, comment_id, text = client.private_replies[0]
    assert account_id == "ig-business-1"
    assert comment_id == "comment-1"
    assert "Direct" in text
    assert "фото" in text.lower()
    assert "бесплат" in text.lower()
    assert "видео" in text.lower()
    assert "плат" in text.lower()


def test_unrelated_comment_is_not_auto_dm_trigger() -> None:
    client = _FakeClient()
    adapter = _adapter(client)
    event = InstagramEvent(
        event_id="comments:comment-2",
        kind="comments",
        account_id="ig-business-1",
        sender_id="igsid-2",
        text="Очень красиво",
        payload={"id": "comment-2", "from": {"id": "igsid-2"}},
    )

    asyncio.run(adapter.handle_event(event))

    assert client.private_replies == []
    assert client.messages == []


def test_unlinked_user_can_start_free_first_image_without_telegram_link() -> None:
    client = _FakeClient()

    async def unlinked_identity(**_kwargs):
        return _Identity(id=7, user_id=None)

    link_calls: list[int] = []

    async def account_link_factory(identity: _Identity) -> str:
        link_calls.append(identity.id)
        return "https://t.me/HappyFoxBot?start=iglink_token123"

    adapter = _adapter(
        client,
        identity_resolver=unlinked_identity,
        account_link_factory=account_link_factory,
    )
    event = InstagramEvent(
        event_id="message:unlinked-free",
        kind="message",
        account_id="ig-business-1",
        sender_id="igsid-unlinked",
        payload={
            "message": {
                "mid": "unlinked-free",
                "attachments": [
                    {"type": "image", "payload": {"url": "https://cdn.example/photo.jpg"}}
                ],
            }
        },
    )

    asyncio.run(adapter.handle_event(event))

    assert link_calls == []
    assert len(client.messages) == 1
    reply = client.messages[0][2]
    assert "фото получил" in reply.lower()
    assert "бесплат" in reply.lower()


def test_unlinked_user_is_sent_to_payment_link_only_after_free_image_is_consumed() -> None:
    client = _FakeClient()

    async def unlinked_identity(**_kwargs):
        return _Identity(id=7, user_id=None)

    async def consumed_promotion(_identity_id: int):
        return ChannelPromotionStatus(
            promotion_code="instagram_first_image",
            status="consumed",
            reservation_key="done-task",
        )

    link_calls: list[int] = []

    async def account_link_factory(identity: _Identity) -> str:
        link_calls.append(identity.id)
        return "https://t.me/HappyFoxBot?start=iglink_token123"

    adapter = _adapter(
        client,
        identity_resolver=unlinked_identity,
        promotion_resolver=consumed_promotion,
        account_link_factory=account_link_factory,
    )
    event = InstagramEvent(
        event_id="message:unlinked-paid",
        kind="message",
        account_id="ig-business-1",
        sender_id="igsid-unlinked",
        text="Ещё одну",
        payload={"message": {"mid": "unlinked-paid", "text": "Ещё одну"}},
    )

    asyncio.run(adapter.handle_event(event))

    assert link_calls == [7]
    assert len(client.messages) == 1
    reply = client.messages[0][2]
    assert "бесплатная первая фото-генерация уже использована" in reply.lower()
    assert "обычным ценам" in reply.lower()
    assert "https://t.me/HappyFoxBot?start=iglink_token123" in reply


def test_incoming_photo_dm_is_acknowledged_and_asks_for_prompt() -> None:
    client = _FakeClient()
    adapter = _adapter(client)
    event = InstagramEvent(
        event_id="message:mid-photo",
        kind="message",
        account_id="ig-business-1",
        sender_id="igsid-3",
        payload={
            "message": {
                "mid": "mid-photo",
                "attachments": [
                    {"type": "image", "payload": {"url": "https://cdn.example/photo.jpg"}}
                ],
            }
        },
    )

    asyncio.run(adapter.handle_event(event))

    assert len(client.messages) == 1
    assert client.messages[0][0:2] == ("ig-business-1", "igsid-3")
    assert "Фото получил" in client.messages[0][2]
    assert "что" in client.messages[0][2].lower()


def test_first_text_dm_explains_the_two_step_creator_flow() -> None:
    client = _FakeClient()
    adapter = _adapter(client)
    event = InstagramEvent(
        event_id="message:mid-text",
        kind="message",
        account_id="ig-business-1",
        sender_id="igsid-4",
        text="Привет, хочу попробовать",
        payload={"message": {"mid": "mid-text", "text": "Привет, хочу попробовать"}},
    )

    asyncio.run(adapter.handle_event(event))

    assert len(client.messages) == 1
    reply = client.messages[0][2]
    assert "фото" in reply.lower()
    assert "бесплат" in reply.lower()
    assert "видео" in reply.lower()
    assert "плат" in reply.lower()
    assert "опис" in reply.lower() or "напиши" in reply.lower()
