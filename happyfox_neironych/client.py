"""Finite, single-attempt HTTP transport. The caller owns durable reconciliation."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import logging
import math
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from PIL import Image, UnidentifiedImageError

from .contracts import PreparedRequest

logger = logging.getLogger(__name__)
DEFAULT_ORIGIN = "https://api.xn--e1aikcel5c5a.online"
_MIB = 1024 * 1024


class ProviderError(RuntimeError):
    def __init__(self, code: str, *, status: int = 0, uncertain: bool = False,
                 retryable: bool = False, retry_after: float = 0, request_id: str = ""):
        # Only internal or allowlisted codes are passed here, never response prose.
        super().__init__(code)
        self.code = code
        self.status = status
        self.uncertain = uncertain
        self.retryable = retryable
        self.retry_after = retry_after
        self.request_id = request_id


def setting(suffix: str, default: str = "") -> str:
    for prefix in ("NEURONYCH_", "NEIRONYCH_"):
        value = os.getenv(prefix + suffix, "").strip()
        if value:
            return value
    return default


@dataclass(frozen=True, slots=True)
class Settings:
    api_key: str = field(default="", repr=False)
    enabled: bool = False
    base_url: str = DEFAULT_ORIGIN
    timeout: float = 120.0
    poll_interval: float = 15.0
    max_json_bytes: int = 96 * _MIB
    max_image_bytes: int = 32 * _MIB
    max_video_bytes: int = 750 * _MIB

    def __post_init__(self) -> None:
        try:
            parts = urlsplit(self.base_url)
            valid = parts.scheme == "https" and parts.hostname and not any((parts.username, parts.password, parts.query, parts.fragment, parts.path)) and parts.port in (None, 443)
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("Neironych base URL must be an HTTPS origin without path or credentials")
        if not math.isfinite(self.timeout) or not 1 <= self.timeout <= 1800:
            raise ValueError("Neironych timeout must be finite in 1..1800 seconds")
        if not math.isfinite(self.poll_interval) or not 10 <= self.poll_interval <= 300:
            raise ValueError("Neironych poll interval must be 10..300 seconds")
        if any(type(value) is not int or value < 1 for value in (self.max_json_bytes, self.max_image_bytes, self.max_video_bytes)):
            raise ValueError("Media byte limits must be positive integers")

    @property
    def ready(self) -> bool:
        return bool(self.enabled and self.api_key)

    @classmethod
    def from_env(cls) -> Settings:
        enabled = setting("API_ENABLED", "false").casefold() in ("true", "yes", "on", "1")
        key = ""
        if enabled:
            for prefix in ("NEURONYCH_", "NEIRONYCH_"):
                key = os.getenv(prefix + "API_KEY", "").strip()
                filename = os.getenv(prefix + "API_KEY_FILE", "").strip()
                if key:
                    break
                if filename:
                    try:
                        with open(filename, encoding="utf-8") as source:
                            key = source.read(16385).strip()
                    except (OSError, UnicodeError):
                        raise ValueError("Configured Neironych secret file cannot be read") from None
                    if not key or len(key) > 16384:
                        raise ValueError("Invalid Neironych secret file")
                    break
        return cls(api_key=key, enabled=enabled,
                   base_url=setting("API_BASE_URL", DEFAULT_ORIGIN).rstrip("/"),
                   timeout=float(setting("API_TIMEOUT", "120")),
                   poll_interval=float(setting("API_POLL_INTERVAL", "15")),
                   max_json_bytes=int(setting("MAX_JSON_BYTES", str(96 * _MIB))),
                   max_image_bytes=int(setting("MAX_IMAGE_BYTES", str(32 * _MIB))),
                   max_video_bytes=int(setting("MAX_VIDEO_BYTES", str(750 * _MIB))))


@dataclass(frozen=True, slots=True)
class ImageAsset:
    data: bytes = field(repr=False)
    content_type: str
    extension: str


@dataclass(frozen=True, slots=True)
class Outcome:
    request_id: str = ""
    text: str | None = field(default=None, repr=False)
    images: tuple[ImageAsset, ...] = field(default=(), repr=False)
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VideoStatus:
    request_id: str
    status: str
    billed_seconds: int | None = None


def request_id(value: Any, *, required: bool = True) -> str:
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,160}", value):
        return value
    if not required:
        return ""
    raise ProviderError("invalid_request_id", uncertain=True)


_ERROR_CODES = frozenset({
    "api_key_required", "invalid_api_key", "insufficient_balance", "partner_not_active",
    "model_not_available", "generation_not_found", "content_not_available", "idempotency_conflict",
    "request_already_submitted", "capability_mismatch", "media_asset_not_ready", "invalid_request_contract",
    "invalid_idempotency_key", "invalid_previous_response", "unknown_model_contract", "upload_rejected",
    "provider_rejected_request", "provider_rate_limited", "provider_temporarily_unavailable",
    "submission_outcome_unknown", "provider_response_invalid", "unexpected_provider_stream",
})


def response_error(response: httpx.Response, body: Any, *, is_post: bool) -> ProviderError:
    code = "provider_http_error"
    rid = request_id(response.headers.get("X-Request-Id"), required=False)
    if isinstance(body, dict):
        error = body.get("error")
        raw = error.get("type") if isinstance(error, dict) else body.get("detail")
        if isinstance(raw, str) and raw in _ERROR_CODES:
            code = raw
        rid = request_id(body.get("request_id"), required=False) or rid
    try:
        retry_after = float(response.headers.get("Retry-After", "0"))
        if not math.isfinite(retry_after) or retry_after < 0:
            retry_after = 0
    except ValueError:
        retry_after = 0
    uncertain = is_post and (response.status_code >= 500 or code in {"request_already_submitted", "idempotency_conflict"})
    return ProviderError(code, status=response.status_code, uncertain=uncertain,
                         retryable=response.status_code == 429 or response.status_code >= 500,
                         retry_after=retry_after, request_id=rid)


class Client:
    def __init__(self, settings: Settings | None = None, *, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings or Settings.from_env()
        self.transport = transport

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=httpx.Timeout(self.settings.timeout, connect=min(10, self.settings.timeout)),
                                 follow_redirects=False, transport=self.transport)

    def _headers(self) -> dict[str, str]:
        if not self.settings.ready:
            raise ProviderError("provider_not_configured", retryable=True)
        return {"Authorization": "Bearer " + self.settings.api_key}

    async def _json(self, method: str, endpoint: str, *, req: PreparedRequest | None = None,
                    public: bool = False, expected: int = 200) -> tuple[dict[str, Any], str]:
        started = time.monotonic()
        headers = {} if public else self._headers()
        if req:
            headers.update({"Content-Type": "application/json", "Idempotency-Key": req.key})
        rid = ""
        http_status = 0
        try:
            async with asyncio.timeout(self.settings.timeout):
                async with self._http() as client:
                    async with client.stream(method, self.settings.base_url + endpoint,
                                             headers=headers, content=req.body.encode() if req else None) as response:
                        http_status = response.status_code
                        data = bytearray()
                        async for chunk in response.aiter_bytes():
                            data.extend(chunk)
                            if len(data) > self.settings.max_json_bytes:
                                raise ProviderError("provider_response_too_large", uncertain=bool(req))
                        try:
                            body = json.loads(data)
                        except (ValueError, UnicodeError):
                            body = None
                        if not 200 <= http_status < 300:
                            raise response_error(response, body, is_post=bool(req))
                        if http_status != expected:
                            raise ProviderError("unexpected_http_status", status=http_status, uncertain=bool(req))
                        if not isinstance(body, dict):
                            raise ProviderError("provider_response_invalid", uncertain=bool(req))
                        rid = request_id(response.headers.get("X-Request-Id"), required=False)
                        return body, rid
        except (httpx.RequestError, TimeoutError):
            raise ProviderError("submission_outcome_unknown" if req else "transport_unavailable",
                                uncertain=bool(req), retryable=True) from None
        finally:
            logger.info("neironych_request operation=%s method=%s model=%s correlation=%s http_status=%s request_id=%s duration_ms=%s",
                        endpoint.split("/")[2] if endpoint.startswith("/v1/") else "unknown", method,
                        req.model.id if req else "", hashlib.sha256(req.key.encode()).hexdigest()[:16] if req else "",
                        http_status, rid, round((time.monotonic() - started) * 1000))

    async def list_models(self) -> set[str]:
        body, _ = await self._json("GET", "/v1/models", public=True)
        if not isinstance(body.get("data"), list) or any(not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in body["data"]):
            raise ProviderError("invalid_model_catalog")
        return {row["id"] for row in body["data"]}

    async def submit(self, req: PreparedRequest) -> Outcome:
        body, rid = await self._json("POST", req.endpoint, req=req, expected=202 if req.model.kind == "video" else 200)
        if req.model.kind == "video":
            return Outcome(request_id=request_id(body.get("request_id")))
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        if req.model.kind == "text":
            parts = []
            if req.endpoint == "/v1/responses":
                if body.get("status") not in (None, "completed"):
                    raise ProviderError("text_incomplete", uncertain=True, request_id=rid)
                for item in body.get("output", []) or []:
                    if not isinstance(item, dict) or item.get("type") != "message":
                        continue
                    for chunk in item.get("content", []) or []:
                        if isinstance(chunk, dict) and chunk.get("type") == "output_text" and isinstance(chunk.get("text"), str):
                            parts.append(chunk["text"])
            else:
                for choice in body.get("choices", []) or []:
                    if not isinstance(choice, dict):
                        continue
                    if choice.get("finish_reason") not in (None, "stop"):
                        raise ProviderError("text_incomplete", uncertain=True, request_id=rid)
                    message = choice.get("message")
                    if isinstance(message, dict) and isinstance(message.get("content"), str):
                        parts.append(message["content"])
            text = "\n".join(parts).strip()
            if not text:
                raise ProviderError("text_output_missing", uncertain=True, request_id=rid)
            return Outcome(request_id=rid or request_id(body.get("id"), required=False), text=text, usage=usage)
        images = body.get("data")
        if not isinstance(images, list) or len(images) != req.payload["n"]:
            raise ProviderError("image_count_mismatch", uncertain=True, request_id=rid)
        assets = []
        for item in images:
            encoded = item.get("b64_json") if isinstance(item, dict) else None
            if not isinstance(encoded, str) or len(encoded) > ((self.settings.max_image_bytes + 2) // 3) * 4:
                raise ProviderError("invalid_image_payload", uncertain=True, request_id=rid)
            try:
                data = base64.b64decode(encoded, validate=True)
                if not data or len(data) > self.settings.max_image_bytes:
                    raise ValueError("size")
                with Image.open(io.BytesIO(data)) as image:
                    mime = Image.MIME.get(image.format or "")
                    extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(mime or "")
                    if not extension or image.width * image.height > 64000000:
                        raise ValueError("format")
                    image.verify()
            except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError):
                raise ProviderError("invalid_image_payload", uncertain=True, request_id=rid) from None
            assets.append(ImageAsset(data, str(mime), extension))
        return Outcome(request_id=rid, images=tuple(assets), usage=usage)

    async def video_status(self, external_id: str) -> VideoStatus:
        rid = request_id(external_id)
        body, _ = await self._json("GET", f"/v1/videos/{rid}")
        if body.get("request_id", rid) != rid:
            raise ProviderError("status_identity_mismatch", retryable=True)
        state = body.get("status")
        if state not in ("pending", "done", "failed", "expired"):
            raise ProviderError("unknown_video_status", retryable=True)
        seconds = None
        usage = body.get("usage")
        if isinstance(usage, dict) and usage.get("billed_seconds") is not None:
            seconds = usage["billed_seconds"]
            if type(seconds) is not int or seconds <= 0:
                raise ProviderError("invalid_billed_seconds", retryable=True)
        return VideoStatus(rid, state, seconds)

    async def download_video(self, external_id: str, destination: Path) -> Path:
        rid = request_id(external_id)
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary: str | None = None
        try:
            async with asyncio.timeout(self.settings.timeout):
                async with self._http() as client:
                    async with client.stream("GET", f"{self.settings.base_url}/v1/videos/{rid}/content", headers=self._headers()) as response:
                        if response.status_code != 200:
                            raise response_error(response, {}, is_post=False)
                        if response.headers.get("content-type", "").split(";", 1)[0].lower() != "video/mp4":
                            raise ProviderError("invalid_video_content_type", retryable=True)
                        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".neironych-", delete=False) as output:
                            temporary = output.name
                            total = 0
                            prefix = bytearray()
                            async for chunk in response.aiter_bytes(chunk_size=1024 * 1024):
                                total += len(chunk)
                                if total > self.settings.max_video_bytes:
                                    raise ProviderError("video_too_large")
                                if len(prefix) < 32:
                                    prefix.extend(chunk[:32 - len(prefix)])
                                output.write(chunk)
                            if total < 12 or bytes(prefix[4:8]) != b"ftyp":
                                raise ProviderError("invalid_mp4", retryable=True)
                            output.flush()
                            os.fsync(output.fileno())
                        os.replace(temporary, destination)
                        temporary = None
            return destination
        except (httpx.RequestError, TimeoutError):
            raise ProviderError("video_download_unavailable", retryable=True) from None
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)
