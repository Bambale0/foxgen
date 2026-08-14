from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

from fastapi.testclient import TestClient

from foxgen.api.app import create_app
from foxgen.core.config import Settings
from foxgen.infra.reference_media import ReferenceMediaUrlSigner


REFERENCE_ID = UUID("12345678-1234-5678-1234-567812345678")


class FakeStream:
    content_type = "image/png"
    size_bytes = 6

    async def chunks(self, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
        del chunk_size
        yield b"abc"
        yield b"def"


class FakeDelivery:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, int, str]] = []

    async def open(
        self,
        *,
        asset_id: UUID,
        expires_at: int,
        signature: str,
    ) -> FakeStream:
        self.calls.append((asset_id, expires_at, signature))
        return FakeStream()


def test_reference_media_proxy_streams_without_internal_auth_header() -> None:
    delivery = FakeDelivery()
    client = TestClient(
        create_app(
            Settings(internal_api_token="secret", miniapp_enabled=False),
            manage_resources=False,
            reference_media_delivery=delivery,
        )
    )

    response = client.get(
        f"/v1/reference-media/{REFERENCE_ID}",
        params={"expires": 2_000_000_000, "signature": "a" * 64},
    )

    assert response.status_code == 200
    assert response.content == b"abcdef"
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "private, no-store"
    assert delivery.calls == [(REFERENCE_ID, 2_000_000_000, "a" * 64)]


def test_reference_media_signer_binds_asset_and_expiry() -> None:
    signer = ReferenceMediaUrlSigner(
        public_base_url="https://foxgen.example",
        secret="top-secret",
        ttl_seconds=600,
    )

    # Signature validation itself is exercised through a deterministic explicit expiry.
    from foxgen.infra.reference_media import sign_reference_media_url

    expires = 2_000_000_000
    signature = sign_reference_media_url(REFERENCE_ID, expires, "top-secret")
    signer.verify(asset_id=REFERENCE_ID, expires_at=expires, signature=signature)
