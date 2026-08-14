import asyncio
import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from uuid import uuid4

from aiogram import Bot
from aiogram.types import Message, PhotoSize

from foxgen.application.media import DownloadedMedia
from foxgen.core.errors import ErrorCode, SubmissionError
from foxgen.infra.media import S3MediaStorage


@dataclass(frozen=True, slots=True)
class UploadedInput:
    kind: str
    storage_key: str


@dataclass(frozen=True, slots=True)
class InputCleanupResult:
    deleted: tuple[str, ...]
    failed: tuple[str, ...]


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
        if message.media_group_id is not None:
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "Альбомы пока не поддерживаются. Отправьте один файл отдельным сообщением.",
            )
        file_id, file_size, filename, content_type, kind = _message_file(message)
        return await self._download_and_store(
            bot=bot,
            file_id=file_id,
            file_size=file_size,
            filename=filename,
            content_type=content_type,
            kind=kind,
            user_id=user_id,
        )

    async def upload_photo_size(
        self,
        *,
        bot: Bot,
        photo: PhotoSize,
        user_id: int,
        filename: str = "video-reference.jpg",
    ) -> UploadedInput:
        """Store a Telegram-generated video thumbnail as an explicit image reference."""

        return await self._download_and_store(
            bot=bot,
            file_id=photo.file_id,
            file_size=photo.file_size,
            filename=filename,
            content_type="image/jpeg",
            kind="image",
            user_id=user_id,
        )

    async def _download_and_store(
        self,
        *,
        bot: Bot,
        file_id: str,
        file_size: int | None,
        filename: str,
        content_type: str,
        kind: str,
        user_id: int,
    ) -> UploadedInput:
        if user_id <= 0:
            raise SubmissionError(ErrorCode.VALIDATION, "Не удалось определить пользователя.")
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
            try:
                await bot.download(file_id, destination=path)
            except Exception as exc:
                raise SubmissionError(
                    ErrorCode.INPUT_DOWNLOAD_FAILED,
                    "Не удалось скачать файл из Telegram. Отправьте его ещё раз.",
                    retryable=True,
                ) from exc
            size_bytes = path.stat().st_size
            if size_bytes <= 0:
                raise SubmissionError(ErrorCode.VALIDATION, "Получен пустой файл.")
            if size_bytes > self._max_bytes:
                raise SubmissionError(
                    ErrorCode.VALIDATION,
                    "Файл превышает допустимый размер.",
                    details={"file_size": size_bytes, "max_bytes": self._max_bytes},
                )
            checksum = await asyncio.to_thread(_checksum, path)
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
            try:
                stored = await self._storage.store(key=storage_key, media=media)
            except SubmissionError:
                raise
            except Exception as exc:
                raise SubmissionError(
                    ErrorCode.INPUT_STORAGE_FAILED,
                    "Не удалось сохранить файл. Повторите попытку позже.",
                    retryable=True,
                ) from exc
            return UploadedInput(kind=kind, storage_key=stored.storage_key)
        finally:
            path.unlink(missing_ok=True)

    async def presign(self, storage_key: str) -> str:
        normalized = storage_key.strip()
        if not normalized.startswith(("inputs/", "generations/")):
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "Черновик содержит некорректную ссылку на входной файл.",
            )
        # inputs/ are temporary user uploads; generations/ are durable archived
        # results reused read-only as remix references. Cleanup below remains
        # intentionally restricted to inputs/ and cannot delete durable results.
        return await self._storage.presigned_url(normalized)

    async def delete_many(self, storage_keys: tuple[str, ...]) -> InputCleanupResult:
        deleted: list[str] = []
        failed: list[str] = []
        for storage_key in dict.fromkeys(storage_keys):
            normalized = storage_key.strip()
            if not normalized.startswith("inputs/"):
                continue
            try:
                await self._storage.delete(normalized)
            except Exception:
                failed.append(normalized)
            else:
                deleted.append(normalized)
        return InputCleanupResult(deleted=tuple(deleted), failed=tuple(failed))


def stored_input_keys(data: Mapping[str, object]) -> tuple[str, ...]:
    keys: list[str] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            storage_key = value.get("storage_key")
            if isinstance(storage_key, str) and storage_key.startswith("inputs/"):
                keys.append(storage_key)
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    for field in ("media", "reference_original", "reference_preview"):
        visit(data.get(field))
    return tuple(dict.fromkeys(keys))


def message_media_kind(message: Message) -> str:
    return _message_file(message)[4]


def _checksum(path: Path) -> str:
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
