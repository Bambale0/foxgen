from __future__ import annotations

from typing import Protocol

from pydantic import ValidationError

from foxgen.application.media import DownloadedMedia
from foxgen.application.media_probe import VisualMediaProbe, probe_image, probe_iso_video
from foxgen.application.submissions import SubmissionReceipt
from foxgen.core.errors import ErrorCode, SubmissionError
from foxgen.providers.kie.contracts import InputContract, validate_input
from foxgen.providers.kie.motion import (
    KLING_MOTION_IMAGE_MAX_BYTES,
    KLING_MOTION_VIDEO_MAX_BYTES,
)


KLING_MOTION_MODEL_SLUG = "kling-3-motion-control"
_MIN_SIDE = 341
_MIN_RATIO = 2 / 5
_MAX_RATIO = 5 / 2
_MIN_DURATION_SECONDS = 3.0
_MAX_DURATION_SECONDS = 30.0


class InputMediaInspector(Protocol):
    async def describe(self, storage_key: str) -> DownloadedMedia: ...


class MotionSubmissionService(Protocol):
    async def submit(
        self,
        *,
        user_id: int,
        username: str | None,
        model_slug: str,
        input_data: dict[str, object],
        idempotency_key: str,
    ) -> SubmissionReceipt: ...


class KlingMotionService:
    """Validate owner-bound image/video metadata before billing or provider submission."""

    def __init__(
        self,
        *,
        input_media: InputMediaInspector,
        submission: MotionSubmissionService,
    ) -> None:
        self._input_media = input_media
        self._submission = submission

    async def submit(
        self,
        *,
        user_id: int,
        username: str | None,
        input_data: dict[str, object],
        idempotency_key: str,
    ) -> SubmissionReceipt:
        try:
            normalized = validate_input(InputContract.KLING_3_MOTION_CONTROL, input_data)
        except ValidationError as exc:
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "Некорректные параметры Motion Control.",
                retryable=False,
                details={"errors": exc.errors(include_url=False)},
            ) from exc
        image_key = self._owned_key(user_id, normalized, "image_storage_key")
        video_key = self._owned_key(user_id, normalized, "video_storage_key")

        image = await self._describe(image_key, "изображение")
        video = await self._describe(video_key, "видео")
        self._validate_image(image)
        self._validate_video(video)

        return await self._submission.submit(
            user_id=user_id,
            username=username,
            model_slug=KLING_MOTION_MODEL_SLUG,
            input_data=normalized,
            idempotency_key=idempotency_key,
        )

    @staticmethod
    def _owned_key(user_id: int, payload: dict[str, object], field: str) -> str:
        value = payload.get(field)
        prefixes = (f"inputs/{user_id}/", f"inputs/miniapp/{user_id}/")
        if (
            not isinstance(value, str)
            or ".." in value
            or "://" in value
            or not value.startswith(prefixes)
        ):
            raise SubmissionError(
                ErrorCode.TASK_NOT_FOUND,
                "Исходный файл Motion Control не найден.",
                retryable=False,
            )
        return value

    async def _describe(self, storage_key: str, label: str) -> DownloadedMedia:
        try:
            return await self._input_media.describe(storage_key)
        except SubmissionError:
            raise
        except Exception as exc:
            raise SubmissionError(
                ErrorCode.INPUT_DOWNLOAD_FAILED,
                f"Не удалось проверить {label} Motion Control.",
                retryable=True,
            ) from exc

    @staticmethod
    def _validate_image(media: DownloadedMedia) -> None:
        if media.size_bytes <= 0 or media.size_bytes > KLING_MOTION_IMAGE_MAX_BYTES:
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "Изображение Motion Control должно быть не больше 10 MB.",
            )
        if media.content_type.lower() not in {"image/jpeg", "image/png"}:
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "Для Motion Control используйте JPEG или PNG изображение.",
            )
        KlingMotionService._validate_visual_probe(
            probe_image(media.path, media.content_type),
            label="Изображение",
            require_duration=False,
        )

    @staticmethod
    def _validate_video(media: DownloadedMedia) -> None:
        if media.size_bytes <= 0 or media.size_bytes > KLING_MOTION_VIDEO_MAX_BYTES:
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "Видео Motion Control должно быть не больше 100 MB.",
            )
        if media.content_type.lower() not in {"video/mp4", "video/quicktime"}:
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "Для Motion Control используйте MP4 или QuickTime видео.",
            )
        KlingMotionService._validate_visual_probe(
            probe_iso_video(media.path),
            label="Видео",
            require_duration=True,
        )

    @staticmethod
    def _validate_visual_probe(
        probe: VisualMediaProbe,
        *,
        label: str,
        require_duration: bool,
    ) -> None:
        if probe.width < _MIN_SIDE or probe.height < _MIN_SIDE:
            raise SubmissionError(
                ErrorCode.VALIDATION,
                f"{label} должно быть больше 340 px по каждой стороне.",
            )
        ratio = probe.aspect_ratio
        if ratio < _MIN_RATIO or ratio > _MAX_RATIO:
            raise SubmissionError(
                ErrorCode.VALIDATION,
                f"Соотношение сторон {label.lower()} должно быть от 2:5 до 5:2.",
            )
        if require_duration:
            duration = probe.duration_seconds
            if duration is None or not _MIN_DURATION_SECONDS <= duration <= _MAX_DURATION_SECONDS:
                raise SubmissionError(
                    ErrorCode.VALIDATION,
                    "Видео движения должно длиться от 3 до 30 секунд.",
                )
