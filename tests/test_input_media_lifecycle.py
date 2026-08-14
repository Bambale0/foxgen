from typing import Any, cast

import pytest
from aiogram import Bot
from aiogram.types import Message

from foxgen.application.media import DownloadedMedia, MediaStorage, StoredMedia
from foxgen.bot.uploads import TelegramInputMediaStorage, stored_input_keys
from foxgen.core.errors import ErrorCode, SubmissionError


class StubStorage:
    def __init__(self, *, fail: set[str] | None = None) -> None:
        self.deleted: list[str] = []
        self.fail = fail or set()

    async def store(self, *, key: str, media: DownloadedMedia) -> StoredMedia:
        return StoredMedia(
            storage_key=key,
            content_type=media.content_type,
            size_bytes=media.size_bytes,
            checksum_sha256=media.checksum_sha256,
        )

    async def delete(self, storage_key: str) -> None:
        if storage_key in self.fail:
            raise RuntimeError("temporary S3 failure")
        self.deleted.append(storage_key)

    async def presigned_url(self, storage_key: str) -> str:
        return f"https://example.test/{storage_key}"


class AlbumMessage:
    media_group_id = "album-1"


async def test_album_is_rejected_before_any_telegram_download() -> None:
    storage = StubStorage()
    service = TelegramInputMediaStorage(
        storage=cast(MediaStorage, storage),
        max_bytes=10_000,
    )

    with pytest.raises(SubmissionError) as captured:
        await service.upload(
            bot=cast(Bot, object()),
            message=cast(Message, AlbumMessage()),
            user_id=7,
        )

    assert captured.value.code == ErrorCode.VALIDATION
    assert "Альбомы" in captured.value.public_message


async def test_delete_many_is_idempotent_scoped_and_reports_failures() -> None:
    storage = StubStorage(fail={"inputs/7/b.jpg"})
    service = TelegramInputMediaStorage(
        storage=cast(MediaStorage, storage),
        max_bytes=10_000,
    )

    result = await service.delete_many(
        (
            "inputs/7/a.jpg",
            "inputs/7/a.jpg",
            "generations/result.jpg",
            "inputs/7/b.jpg",
        )
    )

    assert result.deleted == ("inputs/7/a.jpg",)
    assert result.failed == ("inputs/7/b.jpg",)
    assert storage.deleted == ["inputs/7/a.jpg"]


def test_stored_input_keys_collects_all_reference_fields_once() -> None:
    data: dict[str, Any] = {
        "media": [
            {"kind": "image", "storage_key": "inputs/7/a.jpg"},
            {"kind": "image", "storage_key": "inputs/7/a.jpg"},
        ],
        "reference_original": {"kind": "video", "storage_key": "inputs/7/b.mp4"},
        "reference_preview": {"kind": "image", "storage_key": "inputs/7/c.jpg"},
        "result": {"storage_key": "generations/7/result.jpg"},
    }

    assert stored_input_keys(data) == (
        "inputs/7/a.jpg",
        "inputs/7/b.mp4",
        "inputs/7/c.jpg",
    )
