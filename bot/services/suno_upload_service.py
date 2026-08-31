from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

import aiohttp

from bot.services.suno_service import SunoApiError

logger = logging.getLogger(__name__)


class SunoUploadService:
    ENDPOINT = "https://kieai.redpandaai.co/api/file-stream-upload"
    MAX_BYTES = 256 * 1024 * 1024

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = str(api_key or os.getenv("KIE_AI_API_KEY") or "").strip()

    async def upload_bytes(
        self,
        content: bytes,
        *,
        filename: str,
        content_type: str = "audio/mpeg",
    ) -> str:
        if not self.api_key:
            raise SunoApiError("KIE_AI_API_KEY не настроен")
        if not content:
            raise ValueError("Пустой аудиофайл")
        if len(content) > self.MAX_BYTES:
            raise ValueError("Аудиофайл слишком большой")
        clean_name = Path(str(filename or "audio.mp3")).name[:160] or "audio.mp3"

        form = aiohttp.FormData()
        form.add_field(
            "file",
            content,
            filename=clean_name,
            content_type=str(content_type or "application/octet-stream"),
        )
        form.add_field("uploadPath", "suno-inputs")

        timeout = aiohttp.ClientTimeout(total=180)
        try:
            async with aiohttp.ClientSession(trust_env=False, timeout=timeout) as session:
                async with session.post(
                    self.ENDPOINT,
                    data=form,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                ) as response:
                    text = await response.text()
                    try:
                        payload: Any = json.loads(text)
                    except json.JSONDecodeError:
                        payload = {"message": text[:500]}
                    if response.status < 200 or response.status >= 300:
                        raise SunoApiError(
                            str(
                                (payload.get("message") if isinstance(payload, dict) else "")
                                or f"Audio upload HTTP {response.status}"
                            )[:500]
                        )
        except asyncio.TimeoutError as exc:
            raise SunoApiError("Загрузка аудио в KIE превысила лимит времени") from exc
        except aiohttp.ClientError as exc:
            raise SunoApiError(f"Не удалось загрузить аудио в KIE: {exc}") from exc

        if not isinstance(payload, dict):
            raise SunoApiError("KIE upload вернул неожиданный ответ")
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        for key in ("downloadUrl", "download_url", "url", "fileUrl", "file_url"):
            value = data.get(key) if isinstance(data, dict) else None
            if isinstance(value, str) and value.strip().startswith("https://"):
                return value.strip()
        raise SunoApiError("KIE upload не вернул публичную ссылку на аудио")


suno_upload_service = SunoUploadService()
