from pathlib import Path

import pytest

from foxgen.application.media import DownloadedMedia, StoredMedia
from foxgen.application.reference_memory import ReferenceMemoryService
from foxgen.core.errors import SubmissionError
from tests.test_reference_memory import FakeRepository, FakeStorage, FakeUrlSigner


class RecordingInputSource:
    def __init__(self, media: DownloadedMedia) -> None:
        self.media = media
        self.keys: list[str] = []

    async def describe(self, storage_key: str) -> DownloadedMedia:
        self.keys.append(storage_key)
        return self.media


def media(tmp_path: Path) -> DownloadedMedia:
    path = tmp_path / "miniapp.png"
    path.write_bytes(b"miniapp-reference")
    return DownloadedMedia(
        path=path,
        filename="miniapp.png",
        content_type="image/png",
        size_bytes=17,
        checksum_sha256="b" * 64,
    )


def service(source: RecordingInputSource) -> ReferenceMemoryService:
    return ReferenceMemoryService(
        repository=FakeRepository(),
        input_source=source,
        storage=FakeStorage(),
        url_signer=FakeUrlSigner(),
        max_items=50,
        max_bytes=1024,
    )


@pytest.mark.asyncio
async def test_owner_miniapp_input_can_be_promoted_to_reference_memory(tmp_path: Path) -> None:
    source = RecordingInputSource(media(tmp_path))

    result = await service(source).save_from_temporary_input(
        user_id=42,
        username="fox",
        storage_key="inputs/miniapp/42/source.png",
    )

    assert result.duplicate is False
    assert source.keys == ["inputs/miniapp/42/source.png"]


@pytest.mark.asyncio
async def test_foreign_miniapp_input_is_rejected_before_read(tmp_path: Path) -> None:
    source = RecordingInputSource(media(tmp_path))

    with pytest.raises(SubmissionError):
        await service(source).save_from_temporary_input(
            user_id=42,
            username="fox",
            storage_key="inputs/miniapp/99/private.png",
        )

    assert source.keys == []
