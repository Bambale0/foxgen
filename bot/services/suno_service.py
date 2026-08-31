from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


class SunoApiError(RuntimeError):
    pass


class SunoService:
    BASE_URL = "https://api.kie.ai"
    MODELS = frozenset({"V5_5", "V5", "V4_5PLUS", "V4_5", "V4_5ALL", "V4"})
    CREATE_ENDPOINTS = {
        "generate": "/api/v1/generate",
        "extend": "/api/v1/generate/extend",
        "upload_extend": "/api/v1/generate/upload-extend",
        "upload_cover": "/api/v1/generate/upload-cover",
        "add_vocals": "/api/v1/generate/add-vocals",
        "add_instrumental": "/api/v1/generate/add-instrumental",
        "lyrics": "/api/v1/lyrics",
        "separate_vocal": "/api/v1/vocal-removal/generate",
        "split_stem": "/api/v1/vocal-removal/generate",
        "split_stem_advanced": "/api/v1/vocal-removal/generate",
        "wav": "/api/v1/wav/generate",
        "music_video": "/api/v1/mp4/generate",
        "midi": "/api/v1/midi/generate",
        "sounds": "/api/v1/generate/sounds",
        "voice_validate": "/api/v1/voice/validate",
        "voice_generate": "/api/v1/voice/generate",
    }
    RECORD_ENDPOINTS = {
        "generate": "/api/v1/generate/record-info",
        "extend": "/api/v1/generate/record-info",
        "upload_extend": "/api/v1/generate/record-info",
        "upload_cover": "/api/v1/generate/record-info",
        "add_vocals": "/api/v1/generate/record-info",
        "add_instrumental": "/api/v1/generate/record-info",
        "lyrics": "/api/v1/lyrics/record-info",
        "separate_vocal": "/api/v1/vocal-removal/record-info",
        "split_stem": "/api/v1/vocal-removal/record-info",
        "split_stem_advanced": "/api/v1/vocal-removal/record-info",
        "wav": "/api/v1/wav/record-info",
        "music_video": "/api/v1/mp4/record-info",
        "midi": "/api/v1/midi/record-info",
        "sounds": "/api/v1/generate/record-info",
        "voice_validate": "/api/v1/voice/validate-info",
        "voice_generate": "/api/v1/voice/record-info",
    }
    SYNC_OPERATIONS = frozenset({"persona", "timestamped_lyrics", "voice_check"})
    TRANSIENT_HTTP = frozenset({408, 425, 429, 500, 502, 503, 504})
    REQUEST_TIMEOUT = 90
    RETRIES = 3

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = str(api_key or os.getenv("KIE_AI_API_KEY") or "").strip()

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _callback_url(self) -> str:
        explicit = str(os.getenv("SUNO_CALLBACK_URL") or "").strip()
        if explicit.startswith("https://"):
            return explicit
        host = str(os.getenv("WEBHOOK_HOST") or "").strip().rstrip("/")
        if host.startswith("https://"):
            return f"{host}/webhook/suno"
        return ""

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise SunoApiError("KIE_AI_API_KEY не настроен")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = self._headers()
        url = f"{self.BASE_URL}{path}"
        timeout = aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT)
        last_error = ""
        for attempt in range(self.RETRIES):
            try:
                async with aiohttp.ClientSession(trust_env=False, timeout=timeout) as session:
                    async with session.request(
                        method,
                        url,
                        headers=headers,
                        json=json_body,
                        params=params,
                    ) as response:
                        text = await response.text()
                        try:
                            payload = json.loads(text)
                        except json.JSONDecodeError:
                            payload = {"message": text[:1000]}
                        if response.status in self.TRANSIENT_HTTP and attempt < self.RETRIES - 1:
                            last_error = self.error_message(payload) or f"HTTP {response.status}"
                            await asyncio.sleep(1.5 * (attempt + 1))
                            continue
                        if response.status < 200 or response.status >= 300:
                            raise SunoApiError(
                                self.error_message(payload) or f"Suno HTTP {response.status}"
                            )
                        if not isinstance(payload, dict):
                            raise SunoApiError("Suno вернул неожиданный ответ")
                        code = payload.get("code")
                        if code not in (None, 0, 200, "0", "200"):
                            raise SunoApiError(self.error_message(payload) or f"Suno code={code}")
                        return payload
            except asyncio.TimeoutError as exc:
                last_error = "Suno request timeout"
                if attempt >= self.RETRIES - 1:
                    raise SunoApiError(last_error) from exc
            except aiohttp.ClientError as exc:
                last_error = f"Suno transport error: {exc}"
                if attempt >= self.RETRIES - 1:
                    raise SunoApiError(last_error) from exc
            if attempt < self.RETRIES - 1:
                await asyncio.sleep(1.5 * (attempt + 1))
        raise SunoApiError(last_error or "Suno request failed")

    @staticmethod
    def error_message(payload: Any) -> str:
        if isinstance(payload, dict):
            for key in ("errorMessage", "error_message", "msg", "message", "detail", "error"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
                if isinstance(value, dict):
                    nested = SunoService.error_message(value)
                    if nested:
                        return nested
            for value in payload.values():
                if isinstance(value, (dict, list)):
                    nested = SunoService.error_message(value)
                    if nested:
                        return nested
        elif isinstance(payload, list):
            for value in payload:
                nested = SunoService.error_message(value)
                if nested:
                    return nested
        return ""

    @staticmethod
    def task_id(payload: Any) -> str:
        if isinstance(payload, dict):
            for key in ("taskId", "task_id"):
                value = payload.get(key)
                if value not in (None, ""):
                    return str(value)
            for value in payload.values():
                found = SunoService.task_id(value)
                if found:
                    return found
        elif isinstance(payload, list):
            for value in payload:
                found = SunoService.task_id(value)
                if found:
                    return found
        return ""

    @staticmethod
    def _model(value: Any) -> str:
        model = str(value or "V5_5").strip().upper()
        if model not in SunoService.MODELS:
            raise ValueError("Unsupported Suno model")
        return model

    async def submit(self, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        op = str(operation or "").strip().lower()
        body = dict(request or {})

        if op == "persona":
            return await self._request(
                "POST",
                "/api/v1/generate/generate-persona",
                json_body=body,
            )
        if op == "timestamped_lyrics":
            return await self._request(
                "POST",
                "/api/v1/generate/get-timestamped-lyrics",
                json_body=body,
            )
        if op == "voice_check":
            return await self._request(
                "POST",
                "/api/v1/voice/check-voice",
                json_body=body,
            )
        if op not in self.CREATE_ENDPOINTS:
            raise ValueError(f"Unsupported Suno operation: {op}")

        callback_url = self._callback_url()
        if callback_url and "callBackUrl" not in body:
            body["callBackUrl"] = callback_url

        if op in {
            "generate",
            "extend",
            "upload_extend",
            "upload_cover",
            "add_vocals",
            "add_instrumental",
        }:
            body["model"] = self._model(body.get("model"))
        if op in {"separate_vocal", "split_stem", "split_stem_advanced"}:
            body["type"] = op
        return await self._request(
            "POST",
            self.CREATE_ENDPOINTS[op],
            json_body=body,
        )

    async def get_task(self, operation: str, task_id: str) -> dict[str, Any]:
        op = str(operation or "").strip().lower()
        path = self.RECORD_ENDPOINTS.get(op)
        if not path:
            raise ValueError(f"Suno operation has no polling endpoint: {op}")
        return await self._request(
            "GET",
            path,
            params={"taskId": str(task_id)},
        )

    @staticmethod
    def _data(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {}
        data = payload.get("data")
        return data if isinstance(data, dict) else payload

    @classmethod
    def task_state(cls, operation: str, payload: dict[str, Any]) -> str:
        data = cls._data(payload)
        candidates = (
            data.get("successFlag"),
            data.get("status"),
            data.get("state"),
            payload.get("status"),
        )
        for raw in candidates:
            if raw in (None, ""):
                continue
            value = str(raw).strip().lower()
            if value in {"success", "succeeded", "done", "completed", "complete", "1"}:
                return "success"
            if value in {
                "fail",
                "failed",
                "error",
                "create_task_failed",
                "generate_audio_failed",
                "generate_wav_failed",
                "generate_mp4_failed",
                "processing_validate_fail",
                "2",
                "3",
            }:
                return "failed"
            if value in {
                "pending",
                "processing",
                "queued",
                "running",
                "wait_processing",
                "processing_validate",
                "wait_validating",
                "0",
            }:
                if operation == "voice_validate" and value == "wait_validating":
                    return "success"
                return "pending"

        if operation in {
            "generate",
            "extend",
            "upload_extend",
            "upload_cover",
            "add_vocals",
            "add_instrumental",
        }:
            response = data.get("response")
            if isinstance(response, dict) and response.get("sunoData"):
                return "success"
        if operation == "lyrics":
            response = data.get("response")
            if response:
                return "success"
        if operation == "voice_validate" and data.get("validateInfo"):
            return "success"
        if operation == "voice_generate" and data.get("voiceId"):
            return "success"
        return "pending"

    @staticmethod
    def _https_urls(value: Any, *, prefix: str = "") -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("https://"):
                results.append({"label": prefix or "result", "url": text})
        elif isinstance(value, list):
            for index, item in enumerate(value):
                results.extend(
                    SunoService._https_urls(
                        item,
                        prefix=f"{prefix}[{index}]" if prefix else str(index),
                    )
                )
        elif isinstance(value, dict):
            for key, item in value.items():
                results.extend(
                    SunoService._https_urls(
                        item,
                        prefix=f"{prefix}.{key}" if prefix else str(key),
                    )
                )
        return results

    @classmethod
    def normalize_result(cls, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = cls._data(payload)
        result: dict[str, Any] = {
            "operation": operation,
            "provider_task_id": cls.task_id(payload),
            "tracks": [],
            "urls": [],
        }

        response = data.get("response")
        if isinstance(response, dict):
            suno_data = response.get("sunoData") or response.get("suno_data")
            if isinstance(suno_data, list):
                tracks: list[dict[str, Any]] = []
                for item in suno_data:
                    if not isinstance(item, dict):
                        continue
                    audio_url = str(item.get("audioUrl") or item.get("audio_url") or "").strip()
                    track = {
                        "audio_id": str(item.get("id") or item.get("audioId") or "").strip(),
                        "audio_url": audio_url,
                        "stream_audio_url": str(
                            item.get("streamAudioUrl") or item.get("stream_audio_url") or ""
                        ).strip(),
                        "image_url": str(item.get("imageUrl") or item.get("image_url") or "").strip(),
                        "title": str(item.get("title") or "Suno").strip(),
                        "duration": item.get("duration"),
                        "tags": str(item.get("tags") or "").strip(),
                        "prompt": str(item.get("prompt") or "").strip(),
                    }
                    if track["audio_id"] or audio_url:
                        tracks.append(track)
                result["tracks"] = tracks

        if operation == "lyrics":
            result["lyrics"] = response if response not in (None, "") else data.get("lyrics")
        elif operation == "voice_validate":
            result["validate_info"] = str(data.get("validateInfo") or "").strip()
        elif operation == "voice_generate":
            result["voice_id"] = str(data.get("voiceId") or "").strip()
        elif operation == "midi":
            result["midi_data"] = data.get("midiData") or data.get("response")
        elif operation == "timestamped_lyrics":
            result["aligned_words"] = data.get("alignedWords") or []
            result["waveform_data"] = data.get("waveformData") or []
        elif operation == "persona":
            result["persona_id"] = str(
                data.get("personaId")
                or cls._data(data.get("response") or {}).get("personaId")
                or ""
            ).strip()

        result["urls"] = cls._https_urls(data)
        return result

    @classmethod
    def immediate_result(cls, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        return cls.normalize_result(operation, payload)


suno_service = SunoService()
