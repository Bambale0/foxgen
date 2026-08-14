from uuid import UUID

import pytest

from foxgen.infra.reference_media import ReferenceMediaUrlSigner


@pytest.mark.asyncio
async def test_reference_media_url_uses_public_foxgen_origin() -> None:
    asset_id = UUID("12345678-1234-5678-1234-567812345678")
    signer = ReferenceMediaUrlSigner(
        public_base_url="https://foxgen.example",
        secret="reference-media-secret",
        ttl_seconds=600,
    )

    url = await signer.url(asset_id)

    assert url.startswith(f"https://foxgen.example/v1/reference-media/{asset_id}?")
    assert "expires=" in url
    assert "signature=" in url
    assert "minio" not in url
