from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from foxgen.application.media import DownloadedMedia
from foxgen.core.errors import ErrorCode, ProviderError
from foxgen.providers.kie.client import KieClient, TaskCreated, TaskRecord


SUNO_API_FAMILY = "suno"
SUNO_EXTEND_API_FAMILY = "suno_extend"
SUNO_UPLOAD_COVER_API_FAMILY = "suno_upload_cover"


class InputMediaResolver(Protocol):
    async def describe(self, storage_key: str) -> DownloadedMedia: ...

    async def presigned_url(self, storage_key: str) -> str: ...


class SunoClient:
    """Typed adapter for KIE's dedicated Suno generation API family."""

    def __init__(self, transport: KieClient) -> None:
        self._transport = transport

    async def create_task(
        self,
        *,
        model: str,
        input_data: Mapping[str, object],
        callback_url: str | None = None,
    ) -> TaskCreated:
        del callback_url
        payload = _generate_payload(model=model, input_data=input_data)
        data = await self._transport.request_data("POST", "/api/v1/generate", json=payload)
        return _task_created(data)

    async def get_task(self, task_id: str) -> TaskRecord:
        return await _get_suno_task(self._transport, task_id)


class SunoExtendClient:
    """Typed adapter for extending an existing generated Suno track."""

    def __init__(self, transport: KieClient) -> None:
        self._transport = transport

    async def create_task(
        self,
        *,
        model: str,
        input_data: Mapping[str, object],
        callback_url: str | None = None,
    ) -> TaskCreated:
        del callback_url
        payload = _extend_payload(model=model, input_data=input_data)
        data = await self._transport.request_data(
            "POST",
            "/api/v1/generate/extend",
            json=payload,
        )
        return _task_created(data)

    async def get_task(self, task_id: str) -> TaskRecord:
        return await _get_suno_task(self._transport, task_id)


class SunoUploadCoverClient:
    """Generate a V5 cover from one FoxGen-owned temporary audio input."""

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
        storage_key = input_data.get("input_storage_key")
        if not isinstance(storage_key, str) or not storage_key.startswith("inputs/"):
            raise ProviderError(
                ErrorCode.PROVIDER_PROTOCOL,
                "Suno Cover не получил проверенный приватный аудиофайл.",
                retryable=False,
            )
        try:
            media = await self._input_media.describe(storage_key)
        except Exception as exc:
            raise ProviderError(
                ErrorCode.INPUT_DOWNLOAD_FAILED,
                "Исходный аудиофайл для Suno Cover больше недоступен.",
                retryable=False,
            ) from exc
        if media.size_bytes <= 0 or not media.content_type.lower().startswith("audio/"):
            raise ProviderError(
                ErrorCode.VALIDATION,
                "Suno Cover принимает только непустой аудиофайл.",
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
        payload = _upload_cover_payload(
            model=model,
            input_data=input_data,
            upload_url=upload_url,
        )
        data = await self._transport.request_data(
            "POST",
            "/api/v1/generate/upload-cover",
            json=payload,
        )
        return _task_created(data)

    async def get_task(self, task_id: str) -> TaskRecord:
        return await _get_suno_task(self._transport, task_id)


def _task_created(data: Mapping[str, Any]) -> TaskCreated:
    task_id = data.get("taskId")
    if not isinstance(task_id, str) or not task_id:
        raise ProviderError(
            ErrorCode.PROVIDER_PROTOCOL,
            "Suno вернул некорректный идентификатор задачи.",
            retryable=False,
            details={"data": dict(data)},
        )
    return TaskCreated(task_id=task_id)


async def _get_suno_task(transport: KieClient, task_id: str) -> TaskRecord:
    data = await transport.request_data(
        "GET",
        "/api/v1/generate/record-info",
        params={"taskId": task_id},
    )
    normalized_id = data.get("taskId", task_id)
    if not isinstance(normalized_id, str) or not normalized_id:
        normalized_id = task_id
    status = data.get("status")
    result = _normalize_suno_result(data)
    return TaskRecord(
        task_id=normalized_id,
        state=status if isinstance(status, str) else None,
        result=result,
        errorCode=data.get("errorCode"),
        errorMessage=data.get("errorMessage"),
        type=data.get("type"),
    )


def _generate_payload(*, model: str, input_data: Mapping[str, object]) -> dict[str, object]:
    custom_mode = bool(input_data.get("custom_mode", False))
    instrumental = bool(input_data.get("instrumental", False))
    payload: dict[str, object] = {
        "customMode": custom_mode,
        "instrumental": instrumental,
        "model": model,
    }

    _copy_optional_fields(
        payload,
        input_data,
        (
            ("prompt", "prompt"),
            ("style", "style"),
            ("title", "title"),
            ("negative_tags", "negativeTags"),
            ("vocal_gender", "vocalGender"),
            ("style_weight", "styleWeight"),
            ("weirdness_constraint", "weirdnessConstraint"),
            ("audio_weight", "audioWeight"),
        ),
    )
    return payload


def _extend_payload(*, model: str, input_data: Mapping[str, object]) -> dict[str, object]:
    audio_id = input_data.get("audio_id")
    if not isinstance(audio_id, str) or not audio_id:
        raise ProviderError(
            ErrorCode.PROVIDER_PROTOCOL,
            "Suno Extend не получил проверенный audioId.",
            retryable=False,
        )
    default_param_flag = bool(input_data.get("default_param_flag", False))
    payload: dict[str, object] = {
        "defaultParamFlag": default_param_flag,
        "audioId": audio_id,
        "model": model,
    }
    if default_param_flag:
        _copy_optional_fields(
            payload,
            input_data,
            (
                ("prompt", "prompt"),
                ("style", "style"),
                ("title", "title"),
                ("continue_at", "continueAt"),
                ("negative_tags", "negativeTags"),
                ("vocal_gender", "vocalGender"),
                ("style_weight", "styleWeight"),
                ("weirdness_constraint", "weirdnessConstraint"),
                ("audio_weight", "audioWeight"),
            ),
        )
    return payload


def _upload_cover_payload(
    *,
    model: str,
    input_data: Mapping[str, object],
    upload_url: str,
) -> dict[str, object]:
    custom_mode = bool(input_data.get("custom_mode", False))
    instrumental = bool(input_data.get("instrumental", False)) if custom_mode else False
    payload: dict[str, object] = {
        "uploadUrl": upload_url,
        "customMode": custom_mode,
        "instrumental": instrumental,
        "model": model,
    }
    _copy_optional_fields(payload, input_data, (("prompt", "prompt"),))
    if custom_mode:
        _copy_optional_fields(
            payload,
            input_data,
            (
                ("style", "style"),
                ("title", "title"),
                ("negative_tags", "negativeTags"),
                ("vocal_gender", "vocalGender"),
                ("style_weight", "styleWeight"),
                ("weirdness_constraint", "weirdnessConstraint"),
                ("audio_weight", "audioWeight"),
                ("persona_id", "personaId"),
            ),
        )
    return payload


def _copy_optional_fields(
    target: dict[str, object],
    source: Mapping[str, object],
    fields: tuple[tuple[str, str], ...],
) -> None:
    for source_key, target_key in fields:
        value = source.get(source_key)
        if value is not None and value != "":
            target[target_key] = value


def _normalize_suno_result(data: Mapping[str, Any]) -> dict[str, object]:
    response = data.get("response")
    response_map = response if isinstance(response, Mapping) else {}
    raw_tracks = response_map.get("sunoData")
    tracks = raw_tracks if isinstance(raw_tracks, list) else []

    audio_urls: list[str] = []
    metadata: list[dict[str, object]] = []
    for item in tracks:
        if not isinstance(item, Mapping):
            continue
        audio_url = item.get("audioUrl")
        if isinstance(audio_url, str) and audio_url.startswith("https://"):
            audio_urls.append(audio_url)
        metadata.append(
            {
                key: value
                for key, value in item.items()
                if key
                not in {
                    "audioUrl",
                    "streamAudioUrl",
                    "imageUrl",
                    "sourceAudioUrl",
                    "sourceStreamAudioUrl",
                    "sourceImageUrl",
                }
            }
        )

    return {
        "audioUrls": list(dict.fromkeys(audio_urls)),
        "tracks": metadata,
        "task_type": data.get("type"),
    }
