from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from foxgen.bot.api_client import QueuedGeneration
from foxgen.core.config import get_settings


@dataclass(frozen=True, slots=True)
class SunoSourceView:
    generation_id: str
    model_slug: str
    audio_id: str
    title: str
    duration_seconds: float | None
    preview_url: str


class SunoExtendTransportError(RuntimeError):
    pass


async def list_suno_sources(*, user_id: int) -> tuple[SunoSourceView, ...]:
    data = await _request(
        "GET",
        "/v1/user-portal/music/suno/sources",
        user_id=user_id,
    )
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        raise SunoExtendTransportError("Некорректный список Suno-треков от backend.")
    items: list[SunoSourceView] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        try:
            generation_id = str(raw["generation_id"])
            model_slug = str(raw["model_slug"])
            audio_id = str(raw["audio_id"])
            title = str(raw["title"])
            preview_url = str(raw["preview_url"])
        except KeyError:
            continue
        duration_raw = raw.get("duration_seconds")
        duration = (
            float(duration_raw)
            if isinstance(duration_raw, (int, float)) and not isinstance(duration_raw, bool)
            else None
        )
        items.append(
            SunoSourceView(
                generation_id=generation_id,
                model_slug=model_slug,
                audio_id=audio_id,
                title=title,
                duration_seconds=duration,
                preview_url=preview_url,
            )
        )
    return tuple(items)


async def submit_suno_extend(
    *,
    user_id: int,
    username: str | None,
    source_generation_id: str,
    audio_id: str,
    input_data: dict[str, object],
    idempotency_key: str,
) -> QueuedGeneration:
    payload = dict(input_data)
    payload["source_generation_id"] = source_generation_id
    payload["audio_id"] = audio_id
    data = await _request(
        "POST",
        "/v1/user-portal/music/suno/extend",
        user_id=user_id,
        username=username,
        idempotency_key=idempotency_key,
        json=payload,
    )
    generation_id = data.get("generation_id")
    status = data.get("status")
    if not isinstance(generation_id, str) or not generation_id:
        raise SunoExtendTransportError("Backend не вернул generation_id для Suno Extend.")
    if not isinstance(status, str):
        raise SunoExtendTransportError("Backend не вернул status для Suno Extend.")
    return QueuedGeneration(
        generation_id=generation_id,
        status=status,
        replayed=bool(data.get("replayed", False)),
    )


async def _request(
    method: str,
    path: str,
    *,
    user_id: int,
    username: str | None = None,
    idempotency_key: str | None = None,
    json: dict[str, object] | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    token = settings.internal_api_token
    if token is None:
        raise SunoExtendTransportError("Внутренний API FoxGen не настроен.")
    headers = {
        "Authorization": f"Bearer {token.get_secret_value()}",
        "X-FoxGen-User-Id": str(user_id),
    }
    if username:
        headers["X-FoxGen-Username"] = username
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key

    try:
        async with httpx.AsyncClient(
            base_url=str(settings.internal_api_base_url).rstrip("/"),
            timeout=settings.internal_api_timeout_seconds,
        ) as client:
            response = await client.request(method, path, headers=headers, json=json)
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise SunoExtendTransportError(
            "Backend временно недоступен. Повторите попытку позже."
        ) from exc

    try:
        payload: Any = response.json()
    except ValueError as exc:
        raise SunoExtendTransportError("Backend вернул повреждённый ответ.") from exc
    if response.is_error:
        detail = payload.get("detail") if isinstance(payload, dict) else None
        raise SunoExtendTransportError(str(detail or f"HTTP {response.status_code}"))
    if not isinstance(payload, dict):
        raise SunoExtendTransportError("Backend вернул ответ неизвестного формата.")
    return payload
