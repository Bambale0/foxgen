from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from foxgen.core.errors import ErrorCode, ProviderError
from foxgen.providers.kie.client import KieClient, TaskCreated, TaskRecord


SUNO_API_FAMILY = "suno"


class SunoClient:
    """Typed adapter for KIE's dedicated Suno API family.

    The first production slice intentionally covers only `/api/v1/generate` and
    `/api/v1/generate/record-info`. Callback handling remains polling-only until
    the dedicated Suno callback contract is reviewed in a later #15 slice.
    """

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
        task_id = data.get("taskId")
        if not isinstance(task_id, str) or not task_id:
            raise ProviderError(
                ErrorCode.PROVIDER_PROTOCOL,
                "Suno вернул некорректный идентификатор задачи.",
                retryable=False,
                details={"data": data},
            )
        return TaskCreated(task_id=task_id)

    async def get_task(self, task_id: str) -> TaskRecord:
        data = await self._transport.request_data(
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

    for source, target in (
        ("prompt", "prompt"),
        ("style", "style"),
        ("title", "title"),
        ("negative_tags", "negativeTags"),
        ("vocal_gender", "vocalGender"),
        ("style_weight", "styleWeight"),
        ("weirdness_constraint", "weirdnessConstraint"),
        ("audio_weight", "audioWeight"),
    ):
        value = input_data.get(source)
        if value is not None and value != "":
            payload[target] = value
    return payload


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
                if key not in {"audioUrl", "streamAudioUrl", "imageUrl"}
            }
        )

    return {
        "audioUrls": list(dict.fromkeys(audio_urls)),
        "tracks": metadata,
        "task_type": data.get("type"),
    }
