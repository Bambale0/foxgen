import pytest

from foxgen.core.errors import SubmissionError
from foxgen.infra.reference_media import ReferenceMediaUrlSigner, sign_reference_media_url


ASSET_ID = "12345678-1234-5678-1234-567812345678"


def _signer() -> ReferenceMediaUrlSigner:
    return ReferenceMediaUrlSigner(
        public_base_url="https://foxgen.example",
        secret="reference-media-secret",
        ttl_seconds=600,
    )


def test_reference_media_capability_rejects_expired_signature() -> None:
    from uuid import UUID

    asset_id = UUID(ASSET_ID)
    signature = sign_reference_media_url(asset_id, 1, "reference-media-secret")

    with pytest.raises(SubmissionError):
        _signer().verify(asset_id=asset_id, expires_at=1, signature=signature)


def test_reference_media_capability_binds_signature_to_asset() -> None:
    from uuid import UUID

    asset_id = UUID(ASSET_ID)
    other_asset_id = UUID("87654321-4321-8765-4321-876543218765")
    expires = 2_000_000_000
    signature = sign_reference_media_url(asset_id, expires, "reference-media-secret")

    with pytest.raises(SubmissionError):
        _signer().verify(
            asset_id=other_asset_id,
            expires_at=expires,
            signature=signature,
        )
