from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from bot.max_api import MaxClient, MaxSettings, _extract_upload_token


def _client() -> MaxClient:
    return MaxClient(
        MaxSettings(
            enabled=True,
            access_token="test-token",
            webhook_secret="secret",
        )
    )


def test_extract_upload_token_supports_max_image_response() -> None:
    uploaded = {
        "photos": {
            "photo-id": {
                "token": "image-token",
            }
        }
    }

    assert _extract_upload_token(uploaded, {}) == "image-token"


def test_extract_upload_token_preserves_generic_media_contract() -> None:
    assert _extract_upload_token({"token": "uploaded-token"}, {}) == "uploaded-token"
    assert _extract_upload_token({}, {"token": "slot-token"}) == "slot-token"


@pytest.mark.asyncio
async def test_send_media_url_reuploads_image_before_message(monkeypatch) -> None:
    client = _client()
    upload = AsyncMock(return_value="image-token")
    send = AsyncMock(return_value={"success": True})
    monkeypatch.setattr(client, "upload_media_from_url", upload)
    monkeypatch.setattr(client, "send_message", send)

    result = await client.send_media_url(
        42,
        media_type="image",
        url="https://provider.example/result.png",
        text="done",
        filename="result.jpg",
    )

    assert result == {"success": True}
    upload.assert_awaited_once_with(
        "image",
        "https://provider.example/result.png",
        filename="result.jpg",
    )
    send.assert_awaited_once_with(
        42,
        "done",
        attachments=[
            {
                "type": "image",
                "payload": {"token": "image-token"},
            }
        ],
    )
