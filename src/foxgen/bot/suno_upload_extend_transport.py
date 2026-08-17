from __future__ import annotations

from typing import Any

import httpx

from foxgen.bot.api_client import QueuedGeneration
from foxgen.core.config import get_settings


class SunoUploadExtendTransportError(RuntimeError):
    pass


async def submit_suno_upload_extend(
    *,
    user_id: int,
    username: str | None,
    input_data: dict[str, object],
    idempotency_key: str,
) -> QueuedGeneration:
    settings = get_settings()
    token = settings.internal_api_token
    if token is None:
        raise SunoUploadExtendTransportError("Внутренний API FoxGen не настроен.")
    headers = {
        "Authorization": f"Bearer {token.get_secret_value()}",
        "X-FoxGen-User-Id": str(user_id),
        "Idempotency-Key": idempotency_key,
        "Content-Type": "application/json",
    }
    if username:
        headers["X-FoxGen-Username"] = username
    try:
        async with httpx.AsyncClient(
            base_url=str(settings.internal_api_base_url).rstrip("/"),
            timeout=settings.internal_api_timeout_seconds,
        ) as client:
            response = await client.post(
                "/v1/user-portal/music/suno/upload-extend",
                headers=headers,
                json=input_data,
            )
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise SunoUploadExtendTransportError(
            "Backend временно недоступен. Повторите попытку позже."
        ) from exc
    try:
        payload: Any = response.json()
    except ValueError as exc:
        raise SunoUploadExtendTransportError("Backend вернул повреждённый ответ.") from exc
    if response.is_error:
        detail = payload.get("detail") if isinstance(payload, dict) else None
        raise SunoUploadExtendTransportError(str(detail or f"HTTP {response.status_code}"))
    if not isinstance(payload, dict):
        raise SunoUploadExtendTransportError("Backend вернул ответ неизвестного формата.")
    generation_id = payload.get("generation_id")
    task_status = payload.get("status")
    if not isinstance(generation_id, str) or not generation_id:
        raise SunoUploadExtendTransportError(
            "Backend не вернул generation_id для Suno Upload & Extend."
        )
    if not isinstance(task_status, str):
        raise SunoUploadExtendTransportError("Backend не вернул status для Suno Upload & Extend.")
    return QueuedGeneration(
        generation_id=generation_id,
        status=task_status,
        replayed=bool(payload.get("replayed", False)),
    )
