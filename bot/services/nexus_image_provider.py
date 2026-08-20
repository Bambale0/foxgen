from __future__ import annotations

import asyncio
import base64
import logging
import uuid
from collections.abc import Iterable
from typing import Any

import aiohttp

from bot.services.media_input_utils import image_sources_to_data_uris

logger = logging.getLogger(__name__)

_SUPPORTED_ASPECT_RATIOS = {
    "auto",
    "1:1",
    "16:9",
    "9:16",
    "4:3",
    "3:4",
    "3:2",
    "2:3",
    "5:4",
    "4:5",
    "21:9",
}
_TERMINAL_STATUSES = {"completed", "failed"}
_MAX_RESULT_BYTES = 25 * 1024 * 1024
_SUPPORTED_IMAGE_SIZES = {"1K", "2K", "4K"}


def _normalize_image_size(resolution: str) -> str:
    raw = str(resolution or "2K").strip().upper()
    if raw in {"BASIC", "HIGH"}:
        raw = {"BASIC": "2K", "HIGH": "4K"}[raw]
    if raw not in _SUPPORTED_IMAGE_SIZES:
        logger.warning("Nexus %s unsupported image_size=%s; fallback to 2K", "adapter", resolution)
        return "2K"
    return raw


def build_nexus_image_params(
    *,
    model_name: str,
    prompt: str,
    aspect_ratio: str,
    image_size: str | None = None,
    image_input: Iterable[str | bytes | bytearray] | None = None,
    max_references: int = 4,
) -> dict[str, Any]:
    """Build the documented Nexus image-generation params payload.

    Nexus' public Nano Banana schema exposes model_name, prompt, image_urls and,
    for Nano Banana 2 / Pro, supports image_size and aspect_ratio.
    """

    params: dict[str, Any] = {
        "model_name": str(model_name).strip(),
        "prompt": str(prompt or "").strip(),
    }

    ratio = str(aspect_ratio or "").strip()
    if ratio and ratio in _SUPPORTED_ASPECT_RATIOS:
        params["aspect_ratio"] = ratio

    references = [
        value
        for value in image_sources_to_data_uris(image_input)
        if isinstance(value, str) and value.strip()
    ][: max(0, int(max_references))]

    if references:
        params["image_urls"] = references

    normalized_size = str(image_size or "").strip().upper()
    if normalized_size in _SUPPORTED_IMAGE_SIZES:
        params["image_size"] = normalized_size

    return params


def _extract_result_source(payload: dict[str, Any]) -> tuple[str, str] | None:
    result = payload.get("result")
    if isinstance(result, str) and result.strip():
        value = result.strip()
        return ("url", value) if value.startswith(("http://", "https://")) else ("base64", value)
    if not isinstance(result, dict):
        return None

    for key in ("image_url", "url"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return "url", value.strip()

    for key in ("images", "image_urls"):
        values = result.get(key)
        if not isinstance(values, list) or not values:
            continue
        first = values[0]
        if isinstance(first, str) and first.strip():
            value = first.strip()
            return ("url", value) if value.startswith(("http://", "https://")) else ("base64", value)
        if isinstance(first, dict):
            for nested_key in ("image_url", "url", "base64", "b64_json"):
                value = first.get(nested_key)
                if isinstance(value, str) and value.strip():
                    normalized = value.strip()
                    return (
                        ("url", normalized)
                        if normalized.startswith(("http://", "https://"))
                        else ("base64", normalized)
                    )

    for key in ("base64", "b64_json", "image_base64"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return "base64", value.strip()
    return None


def _decode_base64_image(value: str) -> tuple[bytes, str]:
    normalized = str(value or "").strip()
    mime_type = "image/png"
    encoded = normalized
    if normalized.startswith("data:") and "," in normalized:
        header, encoded = normalized.split(",", 1)
        if ";base64" in header:
            mime_type = header.removeprefix("data:").split(";", 1)[0] or mime_type

    raw = base64.b64decode(encoded, validate=False)
    if not raw:
        raise ValueError("empty image result")
    if len(raw) > _MAX_RESULT_BYTES:
        raise ValueError("image result exceeds 25 MB")
    return raw, mime_type


class NexusImageProvider:
    """Async adapter over Nexus' /generate + /tasks flow."""

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        base_url: str = "https://nexusapi.dev",
        timeout_seconds: int = 180,
        poll_interval_seconds: float = 1.0,
        max_references: int = 4,
    ) -> None:
        self.api_key = str(api_key or "").strip()
        self.model_name = str(model_name or "").strip()
        self.base_url = str(base_url or "https://nexusapi.dev").strip().rstrip("/")
        self.timeout_seconds = max(30, int(timeout_seconds))
        self.poll_interval_seconds = max(0.5, float(poll_interval_seconds))
        self.max_references = max(1, int(max_references))
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout_seconds + 60)
            )
        return self._session

    async def _start_task(self, session: aiohttp.ClientSession, params: dict[str, Any]) -> str | None:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Idempotency-Key": str(uuid.uuid4()),
        }
        try:
            async with session.post(
                f"{self.base_url}/generate",
                headers=headers,
                json={"params": params},
            ) as response:
                body = await response.text()
                if response.status not in {200, 202}:
                    logger.warning(
                        "Nexus %s start failed: HTTP %s body=%s",
                        self.model_name,
                        response.status,
                        body[:1000],
                    )
                    return None
                try:
                    payload = await response.json(content_type=None)
                except (ValueError, UnicodeDecodeError):
                    logger.warning("Nexus %s start response is not JSON", self.model_name)
                    return None
                task_id = str(payload.get("task_id") or "").strip() if isinstance(payload, dict) else ""
                if not task_id:
                    logger.warning("Nexus %s did not return task_id", self.model_name)
                    return None
                return task_id
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.warning("Nexus %s start transport failure: %s", self.model_name, exc)
            return None

    async def get_task_status(self, task_id: str) -> dict[str, Any] | None:
        session = await self._get_session()
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with session.get(
                f"{self.base_url}/tasks/{task_id}",
                headers=headers,
            ) as response:
                if response.status != 200:
                    body = await response.text()
                    if response.status != 404:
                        logger.warning(
                            "Nexus %s task %s status failed: HTTP %s body=%s",
                            self.model_name,
                            task_id,
                            response.status,
                            body[:1000],
                        )
                    return None
                payload = await response.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            logger.warning(
                "Nexus %s task %s polling failure: %s",
                self.model_name,
                task_id,
                exc,
            )
            return None

        return payload if isinstance(payload, dict) else None

    async def _wait_for_result(
        self,
        session: aiohttp.ClientSession,
        task_id: str,
    ) -> dict[str, Any] | None:
        deadline = asyncio.get_running_loop().time() + self.timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            payload = await self.get_task_status(task_id)
            if not payload:
                return None
            status = str(payload.get("status") or "").strip().lower()
            if status == "completed":
                return payload
            if status == "failed":
                logger.warning(
                    "Nexus %s task %s failed: %s",
                    self.model_name,
                    task_id,
                    str(payload.get("error") or "unknown provider failure")[:1000],
                )
                return None
            if status not in _TERMINAL_STATUSES:
                await asyncio.sleep(self.poll_interval_seconds)

        logger.warning(
            "Nexus %s task %s timed out after %ss",
            self.model_name,
            task_id,
            self.timeout_seconds,
        )
        return None

    async def _download_image(
        self,
        session: aiohttp.ClientSession,
        url: str,
    ) -> tuple[bytes, str] | None:
        try:
            async with session.get(
                url,
                headers={"Accept": "image/avif,image/webp,image/png,image/jpeg,*/*;q=0.8"},
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "Nexus %s result download failed: HTTP %s",
                        self.model_name,
                        response.status,
                    )
                    return None
                if response.content_length is not None and response.content_length > _MAX_RESULT_BYTES:
                    logger.warning("Nexus %s result exceeds 25 MB", self.model_name)
                    return None
                raw = await response.read()
                if not raw or len(raw) > _MAX_RESULT_BYTES:
                    return None
                return raw, response.headers.get("Content-Type", "image/png").split(";", 1)[0]
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.warning("Nexus %s result download failure: %s", self.model_name, exc)
            return None

    async def get_completed_result(
        self,
        task_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        completed_payload = payload or await self.get_task_status(task_id)
        if not isinstance(completed_payload, dict):
            return None

        status = str(completed_payload.get("status") or "").strip().lower()
        if status != "completed":
            return None

        source = _extract_result_source(completed_payload)
        if source is None:
            logger.warning(
                "Nexus %s task %s completed without image result",
                self.model_name,
                task_id,
            )
            return None

        source_type, value = source
        if source_type == "url":
            return {
                "result_url": value,
                "provider": "nexus",
                "provider_model": self.model_name,
                "provider_task_id": task_id,
                "status": status,
            }

        try:
            image_bytes, mime_type = _decode_base64_image(value)
        except (ValueError, TypeError, base64.binascii.Error) as exc:
            logger.warning("Nexus %s returned invalid image data: %s", self.model_name, exc)
            return None

        return {
            "image_bytes": image_bytes,
            "mime_type": mime_type,
            "provider": "nexus",
            "provider_model": self.model_name,
            "provider_task_id": task_id,
            "status": status,
        }

    async def generate_image(
        self,
        prompt: str,
        aspect_ratio: str = "1:1",
        resolution: str = "4K",
        image_input: list[str] | None = None,
        output_format: str = "png",
    ) -> dict[str, Any] | None:
        if not self.api_key:
            return None

        clean_prompt = str(prompt or "").strip()
        if not clean_prompt:
            # Nexus' published Nano Banana schema requires prompt. Keep image-only
            # legacy requests on the existing Kie fallback instead of sending 422.
            logger.info("Nexus %s skipped: prompt is empty; using fallback", self.model_name)
            return None

        ratio = str(aspect_ratio or "").strip()
        if ratio and ratio not in _SUPPORTED_ASPECT_RATIOS:
            logger.info(
                "Nexus %s skipped unsupported aspect_ratio=%s; using fallback",
                self.model_name,
                ratio,
            )
            return None
        reference_count = len(image_input or [])
        if reference_count > self.max_references:
            logger.info(
                "Nexus %s skipped: refs=%s exceed provider max=%s; using fallback",
                self.model_name,
                reference_count,
                self.max_references,
            )
            return None

        normalized_resolution = _normalize_image_size(resolution)

        params = build_nexus_image_params(
            model_name=self.model_name,
            prompt=clean_prompt,
            aspect_ratio=ratio,
            image_size=normalized_resolution,
            image_input=image_input,
            max_references=self.max_references,
        )
        logger.info(
            "Nexus image request: model=%s refs=%s aspect_ratio=%s requested_resolution=%s requested_format=%s",
            self.model_name,
            len(params.get("image_urls") or []),
            params.get("aspect_ratio", "provider_default"),
            params.get("image_size", normalized_resolution),
            output_format,
        )

        session = await self._get_session()
        task_id = await self._start_task(session, params)
        if not task_id:
            return None

        return {
            "task_id": task_id,
            "provider": "nexus",
            "provider_model": self.model_name,
            "provider_task_id": task_id,
            "retryable": False,
        }

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
