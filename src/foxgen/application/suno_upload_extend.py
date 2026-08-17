from __future__ import annotations

from typing import Protocol

from foxgen.application.media import DownloadedMedia
from foxgen.application.submissions import SubmissionReceipt
from foxgen.application.suno_upload_cover import _owned_input_key
from foxgen.core.errors import ErrorCode, SubmissionError
from foxgen.providers.kie.contracts import InputContract, validate_input

SUNO_UPLOAD_EXTEND_MODEL_SLUG = "suno-v5-upload-extend"


class InputMediaInspector(Protocol):
    async def describe(self, storage_key: str) -> DownloadedMedia: ...


class UploadExtendSubmissionService(Protocol):
    async def submit(
        self,
        *,
        user_id: int,
        username: str | None,
        model_slug: str,
        input_data: dict[str, object],
        idempotency_key: str,
    ) -> SubmissionReceipt: ...


class SunoUploadExtendService:
    def __init__(
        self,
        *,
        input_media: InputMediaInspector,
        submission: UploadExtendSubmissionService,
        max_bytes: int,
    ) -> None:
        self._input_media = input_media
        self._submission = submission
        self._max_bytes = max_bytes

    async def submit(
        self,
        *,
        user_id: int,
        username: str | None,
        input_data: dict[str, object],
        idempotency_key: str,
    ) -> SubmissionReceipt:
        normalized = validate_input(InputContract.SUNO_V5_UPLOAD_EXTEND, input_data)
        storage_key = normalized.get("input_storage_key")
        if not isinstance(storage_key, str) or not _owned_input_key(user_id, storage_key):
            raise SubmissionError(
                ErrorCode.TASK_NOT_FOUND,
                "Исходный аудиофайл не найден.",
                retryable=False,
            )
        try:
            media = await self._input_media.describe(storage_key)
        except SubmissionError:
            raise
        except Exception as exc:
            raise SubmissionError(
                ErrorCode.INPUT_DOWNLOAD_FAILED,
                "Не удалось проверить исходный аудиофайл.",
                retryable=True,
            ) from exc
        if media.size_bytes <= 0:
            raise SubmissionError(ErrorCode.VALIDATION, "Получен пустой аудиофайл.")
        if media.size_bytes > self._max_bytes:
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "Аудиофайл превышает допустимый размер.",
                details={"file_size": media.size_bytes, "max_bytes": self._max_bytes},
            )
        if not media.content_type.lower().startswith("audio/"):
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "Для Suno Upload & Extend нужен аудиофайл.",
            )
        return await self._submission.submit(
            user_id=user_id,
            username=username,
            model_slug=SUNO_UPLOAD_EXTEND_MODEL_SLUG,
            input_data=normalized,
            idempotency_key=idempotency_key,
        )
