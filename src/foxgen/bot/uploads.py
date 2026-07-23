import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from aiogram import Bot
from aiogram.types import Message

from foxgen.application.media import DownloadedMedia
from foxgen.core.errors import ErrorCode, SubmissionError
from foxgen.infra.media import S3MediaStorage


@dataclass(frozen=True, slots=True)
class UploadedInput:
    kind: str
    url: str
    storage_key: str


class TelegramInputMediaStorage:
    def __init__(self, *, storage: S3MediaStorage, max_bytes: int) -> None:
        self._storage = storage
        self._max_bytes = max_bytes

    async def upload(
        self,
        *,
        bot: Bot,
        message: Message,
        user_id: int,
    ) -> UploadedInput:
        file_id, file_size, filename, content_type, kind = _message_file(message)
        if file_size is not None and file_size > self._max_bytes:
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "Файл превышает допустимый размер.",
                details={"file_size": file_size, "max_bytes": self._max_bytes},
            )

        temporary = tempfile.NamedTemporaryFile(prefix="foxgen-input-", delete=False)
        path = Path(temporary.name)
        temporary.close()
        try:
            await bot.download(file_id, destination=path)
            size_bytes = path.stat().st_size
            if size_bytes > self._max_bytes:
                raise SubmissionError(
                    ErrorCode.VALIDATION,
                    "Файл превышает допустимый размер.",
                    details={"file_size": size_bytes, "max_bytes": self._max_bytes},
                )
            checksum = await _checksum(path)
            media = DownloadedMedia(
                path=path,
                filename=filename,
                content_type=content_type,
                size_bytes=size_bytes,
                checksum_sha256=checksum,
            )
            suffix = Path(filename).suffix.lower()[:16] or ".bin"
            storage_key = (
                f"inputs/{user_id}/{uuid4().hex[:16]}-"
                f"{checksum[:24]}{suffix}"
            )
            stored = await self._storage.store(key=storage_key, media=media)
            url = await self._storage.presigned_url(stored.storage_key)
            return UploadedInput(kind=kind, url=url, storage_key=stored.storage_key)
        finally:
            path.unlink(missing_ok=True)


async def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _message_file(message: Message) -> tuple[str, int | None, str, str, str]:
    if message.photo:
        photo = message.photo[-1]
        return photo.file_id, photo.file_size, "photo.jpg", "image/jpeg", "image"
    if message.video:
        video = message.video
        return (
            video.file_id,
            video.file_size,
            video.file_name or "video.mp4",
            video.mime_type or "video/mp4",
            "video",
        )
    if message.animation:
        animation = message.animation
        return (
            animation.file_id,
            animation.file_size,
            animation.file_name or "animation.mp4",
            animation.mime_type or "video/mp4",
            "video",
        )
    if message.audio:
        audio = message.audio
        return (
            audio.file_id,
            audio.file_size,
            audio.file_name or "audio.mp3",
            audio.mime_type or "audio/mpeg",
            "audio",
        )
    if message.voice:
        voice = message.voice
        return voice.file_id, voice.file_size, "voice.ogg", voice.mime_type, "audio"
    if message.document:
        document = message.document
        mime_type = document.mime_type or "application/octet-stream"
        if mime_type.startswith("image/"):
            kind = "image"
        elif mime_type.startswith("video/"):
            kind = "video"
        elif mime_type.startswith("audio/"):
            kind = "audio"
        else:
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "Документ должен быть изображением, видео или аудио.",
            )
        return (
            document.file_id,
            document.file_size,
            document.file_name or f"input-{kind}",
            mime_type,
            kind,
        )
    raise SubmissionError(
        ErrorCode.VALIDATION,
        "Отправьте изображение, видео или аудио одним сообщением.",
    )
