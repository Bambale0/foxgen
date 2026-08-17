from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from foxgen.core.errors import ErrorCode, ProviderError
from foxgen.providers.kie.client import KieClient, TaskCreated, TaskRecord


KLING_MOTION_API_FAMILY = "kling_motion"
KLING_MOTION_IMAGE_MAX_BYTES = 10 * 1024 * 1024
KLING_MOTION_VIDEO_MAX_BYTES = 100 * 1024 * 1024


class InputMediaDescription(Protocol):
    content_type: str
    size_bytes: int


class InputMediaResolver(Protocol):
    async def describe(self, storage_key: str) -> InputMediaDescription: ...

    async def presigned_url(self, storage_key: str) -> str: ...


class KlingMotionClient:
    """Resolve FoxGen-owned inputs immediately before KIE Motion Control submission."""

    def __init__(self, transport: KieClient, input_media: InputMediaResolver) -> None:
        self._transport = transport
        self._input_media = input_media

    async def create_task(
        self,
        *,
        model: str,
        input_data: Mapping[str, object],
        callback_url: str | None = None,
    ) -> TaskCreated:
        image_key = _storage_key(input_data, "image_storage_key")
        video_key = _storage_key(input_data, "video_storage_key")

        try:
            image = await self._input_media.describe(image_key)
            video = await self._input_media.describe(video_key)
        except Exception as exc:
            raise ProviderError(
                ErrorCode.INPUT_DOWNLOAD_FAILED,
                "Исходные файлы Motion Control больше недоступны.",
                retryable=False,
            ) from exc

        _validate_image(image)
        _validate_video(video)

        try:
            image_url = await self._input_media.presigned_url(image_key)
            video_url = await self._input_media.presigned_url(video_key)
        except Exception as exc:
            raise ProviderError(
                ErrorCode.INPUT_STORAGE_FAILED,
                "Не удалось подготовить безопасные ссылки Motion Control.",
                retryable=False,
            ) from exc

        provider_input = {
            key: value
            for key, value in input_data.items()
            if key not in {"image_storage_key", "video_storage_key"}
        }
        provider_input["input_urls"] = [image_url]
        provider_input["video_urls"] = [video_url]
        return await self._transport.create_task(
            model=model,
            input_data=provider_input,
            callback_url=callback_url,
        )

    async def get_task(self, task_id: str) -> TaskRecord:
        return await self._transport.get_task(task_id)


def _storage_key(input_data: Mapping[str, object], field: str) -> str:
    value = input_data.get(field)
    if (
        not isinstance(value, str)
        or not value.startswith("inputs/")
        or ".." in value
        or "://" in value
    ):
        raise ProviderError(
            ErrorCode.PROVIDER_PROTOCOL,
            "Motion Control не получил проверенные приватные файлы.",
            retryable=False,
        )
    return value


def _validate_image(media: InputMediaDescription) -> None:
    if media.size_bytes <= 0 or media.size_bytes > KLING_MOTION_IMAGE_MAX_BYTES:
        raise ProviderError(
            ErrorCode.VALIDATION,
            "Изображение Motion Control должно быть непустым и не больше 10 MB.",
            retryable=False,
        )
    if media.content_type.lower() not in {"image/jpeg", "image/png"}:
        raise ProviderError(
            ErrorCode.VALIDATION,
            "Motion Control принимает JPEG или PNG изображение.",
            retryable=False,
        )


def _validate_video(media: InputMediaDescription) -> None:
    if media.size_bytes <= 0 or media.size_bytes > KLING_MOTION_VIDEO_MAX_BYTES:
        raise ProviderError(
            ErrorCode.VALIDATION,
            "Видео Motion Control должно быть непустым и не больше 100 MB.",
            retryable=False,
        )
    if media.content_type.lower() not in {"video/mp4", "video/quicktime"}:
        raise ProviderError(
            ErrorCode.VALIDATION,
            "Motion Control принимает MP4 или QuickTime видео.",
            retryable=False,
        )
