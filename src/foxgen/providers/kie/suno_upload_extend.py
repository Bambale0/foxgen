from __future__ import annotations

from collections.abc import Mapping

from foxgen.core.errors import ErrorCode, ProviderError
from foxgen.providers.kie.client import KieClient, TaskCreated, TaskRecord
from foxgen.providers.kie.contracts import InputContract, validate_input
from foxgen.providers.kie.suno import InputMediaResolver, _get_suno_task, _task_created

SUNO_UPLOAD_EXTEND_API_FAMILY = "suno_upload_extend"


class SunoUploadExtendClient:
    """Extend one FoxGen-owned uploaded audio input through KIE Suno V5."""

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
        del callback_url
        try:
            normalized = validate_input(
                InputContract.SUNO_V5_UPLOAD_EXTEND,
                dict(input_data),
            )
        except Exception as exc:
            raise ProviderError(
                ErrorCode.VALIDATION,
                "Параметры Suno Upload & Extend не прошли проверку.",
                retryable=False,
            ) from exc

        storage_key = normalized.get("input_storage_key")
        if not isinstance(storage_key, str) or not storage_key.startswith("inputs/"):
            raise ProviderError(
                ErrorCode.PROVIDER_PROTOCOL,
                "Suno Upload & Extend не получил проверенный приватный аудиофайл.",
                retryable=False,
            )
        try:
            media = await self._input_media.describe(storage_key)
        except Exception as exc:
            raise ProviderError(
                ErrorCode.INPUT_DOWNLOAD_FAILED,
                "Исходный аудиофайл для Suno Upload & Extend больше недоступен.",
                retryable=False,
            ) from exc
        if media.size_bytes <= 0 or not media.content_type.lower().startswith("audio/"):
            raise ProviderError(
                ErrorCode.VALIDATION,
                "Suno Upload & Extend принимает только непустой аудиофайл.",
                retryable=False,
            )
        try:
            upload_url = await self._input_media.presigned_url(storage_key)
        except Exception as exc:
            raise ProviderError(
                ErrorCode.INPUT_STORAGE_FAILED,
                "Не удалось подготовить безопасную ссылку исходного аудио.",
                retryable=False,
            ) from exc

        payload = _upload_extend_payload(
            model=model,
            input_data=normalized,
            upload_url=upload_url,
        )
        data = await self._transport.request_data(
            "POST",
            "/api/v1/generate/upload-extend",
            json=payload,
        )
        return _task_created(data)

    async def get_task(self, task_id: str) -> TaskRecord:
        return await _get_suno_task(self._transport, task_id)


def _upload_extend_payload(
    *,
    model: str,
    input_data: Mapping[str, object],
    upload_url: str,
) -> dict[str, object]:
    custom = bool(input_data.get("default_param_flag", False))
    instrumental = bool(input_data.get("instrumental", False)) if custom else False
    payload: dict[str, object] = {
        "uploadUrl": upload_url,
        "defaultParamFlag": custom,
        "instrumental": instrumental,
        "model": model,
    }

    prompt = input_data.get("prompt")
    if isinstance(prompt, str) and prompt:
        payload["prompt"] = prompt

    if not custom:
        return payload

    field_map = (
        ("style", "style"),
        ("title", "title"),
        ("continue_at", "continueAt"),
        ("negative_tags", "negativeTags"),
        ("vocal_gender", "vocalGender"),
        ("style_weight", "styleWeight"),
        ("weirdness_constraint", "weirdnessConstraint"),
        ("audio_weight", "audioWeight"),
        ("persona_id", "personaId"),
    )
    for source_key, target_key in field_map:
        value = input_data.get(source_key)
        if value is not None and value != "":
            payload[target_key] = value
    return payload
