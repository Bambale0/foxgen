import asyncio
import hashlib
import hmac
import json

import pytest

from bot.instagram_api import (
    InstagramClient,
    InstagramSettings,
    handle_instagram_webhook,
    normalize_instagram_events,
    verify_instagram_signature,
    verify_instagram_webhook,
)


class _WebhookRequest:
    def __init__(
        self,
        *,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
        query: dict[str, str] | None = None,
        app: dict | None = None,
    ) -> None:
        self._body = body
        self.headers = headers or {}
        self.query = query or {}
        self.app = app or {}

    async def read(self) -> bytes:
        return self._body


def _signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_verify_instagram_signature_uses_raw_body_hmac_sha256() -> None:
    body = b'{"object":"instagram"}'
    secret = "app-secret"

    assert verify_instagram_signature(body, _signature(secret, body), secret)
    assert not verify_instagram_signature(body + b" ", _signature(secret, body), secret)
    assert not verify_instagram_signature(body, "sha256=bad", secret)
    assert not verify_instagram_signature(body, "", secret)


def test_normalize_instagram_message_comment_and_postback_events() -> None:
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "ig-business-1",
                "time": 123456,
                "messaging": [
                    {
                        "sender": {"id": "igsid-1"},
                        "recipient": {"id": "ig-business-1"},
                        "timestamp": 123400,
                        "message": {"mid": "mid-1", "text": "Хочу"},
                    },
                    {
                        "sender": {"id": "igsid-1"},
                        "recipient": {"id": "ig-business-1"},
                        "timestamp": 123401,
                        "postback": {"mid": "mid-2", "payload": "CREATE_IMAGE"},
                    },
                ],
            },
            {
                "id": "ig-business-1",
                "time": 123500,
                "field": "comments",
                "value": {
                    "id": "comment-1",
                    "from": {"id": "igsid-2", "username": "creator"},
                    "text": "ХОЧУ",
                    "media": {"id": "media-1", "media_product_type": "REELS"},
                },
            },
        ],
    }

    events = normalize_instagram_events(payload)

    assert [event.kind for event in events] == ["message", "postback", "comments"]
    assert events[0].event_id == "message:mid-1"
    assert events[0].sender_id == "igsid-1"
    assert events[0].text == "Хочу"
    assert events[1].payload["postback"]["payload"] == "CREATE_IMAGE"
    assert events[2].event_id == "comments:comment-1"
    assert events[2].sender_id == "igsid-2"
    assert events[2].media_id == "media-1"


def test_normalize_marks_explicit_meta_echo_as_echo() -> None:
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "ig-business-1",
                "messaging": [
                    {
                        "sender": {"id": "some-id"},
                        "recipient": {"id": "igsid-1"},
                        "message": {"mid": "mid-echo", "is_echo": True},
                    }
                ],
            }
        ],
    }

    events = normalize_instagram_events(payload)

    assert len(events) == 1
    assert events[0].is_echo is True


def test_webhook_verification_returns_challenge_only_for_matching_token() -> None:
    settings = InstagramSettings(
        enabled=True,
        app_id="app",
        app_secret="secret",
        verify_token="verify-me",
        access_token="token",
        ig_user_id="ig-business-1",
    )
    valid = _WebhookRequest(
        query={
            "hub.mode": "subscribe",
            "hub.verify_token": "verify-me",
            "hub.challenge": "challenge-123",
        },
        app={"instagram_settings": settings},
    )
    invalid = _WebhookRequest(
        query={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong",
            "hub.challenge": "challenge-123",
        },
        app={"instagram_settings": settings},
    )

    valid_response = asyncio.run(verify_instagram_webhook(valid))
    invalid_response = asyncio.run(verify_instagram_webhook(invalid))

    assert valid_response.status == 200
    assert valid_response.text == "challenge-123"
    assert invalid_response.status == 403


def test_webhook_rejects_tampered_payload_and_dispatches_unique_events() -> None:
    body = json.dumps(
        {
            "object": "instagram",
            "entry": [
                {
                    "id": "ig-business-1",
                    "messaging": [
                        {
                            "sender": {"id": "igsid-1"},
                            "recipient": {"id": "ig-business-1"},
                            "timestamp": 123400,
                            "message": {"mid": "mid-1", "text": "Привет"},
                        }
                    ],
                }
            ],
        },
        separators=(",", ":"),
    ).encode()
    settings = InstagramSettings(
        enabled=True,
        app_id="app",
        app_secret="secret",
        verify_token="verify-me",
        access_token="token",
        ig_user_id="ig-business-1",
    )
    seen: list[str] = []
    claimed: set[str] = set()

    async def claim_once(event_id: str) -> bool:
        if event_id in claimed:
            return False
        claimed.add(event_id)
        return True

    async def dispatch(event) -> None:
        seen.append(event.event_id)

    app = {
        "instagram_settings": settings,
        "instagram_claim_once": claim_once,
        "instagram_event_handler": dispatch,
    }
    valid_request = _WebhookRequest(
        body=body,
        headers={"X-Hub-Signature-256": _signature("secret", body)},
        app=app,
    )
    duplicate_request = _WebhookRequest(
        body=body,
        headers={"X-Hub-Signature-256": _signature("secret", body)},
        app=app,
    )
    tampered_request = _WebhookRequest(
        body=body + b" ",
        headers={"X-Hub-Signature-256": _signature("secret", body)},
        app=app,
    )

    assert asyncio.run(handle_instagram_webhook(valid_request)).status == 200
    assert asyncio.run(handle_instagram_webhook(duplicate_request)).status == 200
    assert asyncio.run(handle_instagram_webhook(tampered_request)).status == 401
    assert seen == ["message:mid-1"]


def test_instagram_client_builds_official_login_api_requests(monkeypatch) -> None:
    calls: list[tuple[str, str, dict]] = []
    client = InstagramClient(access_token="token", api_version="v24.0")

    async def fake_request(method: str, path: str, **kwargs):
        calls.append((method, path, kwargs))
        return {"success": True, "id": "result-id"}

    monkeypatch.setattr(client, "_request", fake_request)

    asyncio.run(client.subscribe_webhooks("ig-1", ["messages", "comments"]))
    asyncio.run(client.send_text("ig-1", "igsid-1", "Привет"))
    asyncio.run(
        client.send_media(
            "ig-1",
            "igsid-1",
            "image",
            "https://example.com/a.jpg",
        )
    )
    asyncio.run(client.private_reply("ig-1", "comment-1", "Пришли фото в Direct"))
    asyncio.run(
        client.create_image_container(
            "ig-1",
            "https://example.com/a.jpg",
            "caption",
        )
    )
    asyncio.run(
        client.create_reel_container(
            "ig-1",
            "https://example.com/a.mp4",
            "caption",
        )
    )
    asyncio.run(client.get_container_status("container-1"))
    asyncio.run(client.publish_container("ig-1", "container-1"))

    assert calls[0] == (
        "POST",
        "ig-1/subscribed_apps",
        {"params": {"subscribed_fields": "messages,comments"}},
    )
    assert calls[1][1] == "ig-1/messages"
    assert calls[1][2]["json_body"] == {
        "recipient": {"id": "igsid-1"},
        "message": {"text": "Привет"},
    }
    assert calls[2][2]["json_body"]["message"]["attachment"]["type"] == "image"
    assert calls[3][2]["json_body"]["recipient"] == {"comment_id": "comment-1"}
    assert calls[4][2]["form_body"]["image_url"] == "https://example.com/a.jpg"
    assert calls[5][2]["form_body"]["media_type"] == "REELS"
    assert calls[6] == (
        "GET",
        "container-1",
        {"params": {"fields": "status_code,status"}},
    )
    assert calls[7] == (
        "POST",
        "ig-1/media_publish",
        {"form_body": {"creation_id": "container-1"}},
    )


def test_instagram_client_rejects_non_public_media_urls() -> None:
    client = InstagramClient(access_token="token")

    with pytest.raises(ValueError, match="public https"):
        asyncio.run(
            client.send_media(
                "ig-1",
                "igsid-1",
                "image",
                "file:///tmp/a.jpg",
            )
        )
    with pytest.raises(ValueError, match="public https"):
        asyncio.run(client.create_reel_container("ig-1", "http://localhost/a.mp4"))
