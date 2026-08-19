"""
Unified KIE Market adapter for Nano Banana 2 Lite and future Market models.

Covers:
- createTask / recordInfo (generation lifecycle)
- File upload (stream / base64 / URL)
- Credit balance
- Direct download URL
- Webhook HMAC verification
- Result parsing
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import mimetypes
import os
import time
from typing import Any, Dict, Iterable, List, Optional

import aiohttp

from bot.config import config

logger = logging.getLogger(__name__)

KIE_MARKET_API_BASE = "https://api.kie.ai"
KIE_UPLOAD_BASE = "https://kieai.redpandaai.co"

# ── valid aspect ratios for nano-banana-2-lite ──────────────────────
VALID_ASPECT_RATIOS = frozenset({
    "1:1", "1:4", "1:8", "2:3", "3:2", "3:4", "4:1",
    "4:3", "4:5", "5:4", "8:1", "9:16", "16:9", "21:9", "auto",
})

# ── task states ─────────────────────────────────────────────────────
TASK_STATE_WAITING = "waiting"
TASK_STATE_QUEUING = "queuing"
TASK_STATE_GENERATING = "generating"
TASK_STATE_SUCCESS = "success"
TASK_STATE_FAIL = "fail"
TERMINAL_STATES = {TASK_STATE_SUCCESS, TASK_STATE_FAIL}


class KieMarketError(Exception):
    """KIE Market API error."""

    def __init__(self, message: str, data: dict | None = None):
        super().__init__(message)
        self.data = data or {}


class KieMarketService:
    """Unified service for KIE Market generation models (nano-banana-2-lite, etc.)."""

    def __init__(
        self,
        api_key: str = "",
        callback_base_url: str = "",
        webhook_hmac_key: str = "",
    ):
        self.api_key = api_key or config.KIE_AI_API_KEY or ""
        self.callback_base_url = (callback_base_url or config.kie_notification_url).rstrip("/")
        self.webhook_hmac_key = webhook_hmac_key or getattr(config, "KIE_WEBHOOK_HMAC_KEY", "") or ""
        self._session: Optional[aiohttp.ClientSession] = None
        # Upload URL cache: local_path -> (remote_url, cached_at)
        self._upload_cache: dict[str, tuple[str, float]] = {}

    # ── session management ──────────────────────────────────────────

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=120)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    # ── low-level HTTP helpers ──────────────────────────────────────

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def _post_json(
        self, url: str, payload: dict, timeout: int = 60
    ) -> dict:
        session = await self._get_session()
        headers = {**self._auth_headers(), "Content-Type": "application/json"}
        logger.debug("KIE Market POST %s ← %s", url, _safe_log_payload(payload))
        try:
            async with session.post(
                url, headers=headers, json=payload,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                data = await resp.json(content_type=None)
                logger.debug("KIE Market POST %s → code=%s", url, data.get("code"))
                return data
        except Exception as exc:
            logger.exception("KIE Market POST failed: %s", url)
            raise KieMarketError(str(exc)) from exc

    async def _get_json(
        self, url: str, params: dict | None = None, timeout: int = 30
    ) -> dict:
        session = await self._get_session()
        headers = self._auth_headers()
        logger.debug("KIE Market GET %s params=%s", url, params)
        try:
            async with session.get(
                url, headers=headers, params=params,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                data = await resp.json(content_type=None)
                logger.debug("KIE Market GET %s → code=%s", url, data.get("code"))
                return data
        except Exception as exc:
            logger.exception("KIE Market GET failed: %s", url)
            raise KieMarketError(str(exc)) from exc

    # ═════════════════════════════════════════════════════════════════
    #  1. Create task (nano-banana-2-lite)
    # ═════════════════════════════════════════════════════════════════

    async def create_nano_banana_2_lite_task(
        self,
        prompt: str,
        image_urls: list[str] | None = None,
        aspect_ratio: str = "auto",
        callback_url: str | None = None,
    ) -> str:
        """Create a nano-banana-2-lite generation task.

        Returns the ``taskId`` string on success.
        """
        if aspect_ratio not in VALID_ASPECT_RATIOS:
            logger.warning(
                "nano-banana-2-lite: unknown aspect_ratio=%s, falling back to auto",
                aspect_ratio,
            )
            aspect_ratio = "auto"

        payload: dict[str, Any] = {
            "model": "nano-banana-2-lite",
            "callBackUrl": callback_url or self.callback_base_url,
            "input": {
                "prompt": prompt,
                "image_urls": image_urls or [],
                "aspect_ratio": aspect_ratio,
            },
        }

        logger.info(
            "KIE Market createTask nano-banana-2-lite: prompt_len=%d refs=%d ratio=%s",
            len(prompt), len(image_urls or []), aspect_ratio,
        )

        data = await self._post_json(
            f"{KIE_MARKET_API_BASE}/api/v1/jobs/createTask", payload,
        )

        code = data.get("code")
        if code != 200:
            raise KieMarketError(
                f"createTask failed with code={code}: {data.get('msg', '')}", data,
            )

        task_id = data.get("data", {}).get("taskId")
        if not task_id:
            raise KieMarketError(
                f"createTask response missing taskId: {data}", data,
            )

        logger.info("KIE Market task created: %s", task_id)
        return task_id

    # ═════════════════════════════════════════════════════════════════
    #  2. Get task details / status
    # ═════════════════════════════════════════════════════════════════

    async def get_task_details(self, task_id: str) -> dict:
        """Return the full task record from KIE Market recordInfo endpoint."""
        data = await self._get_json(
            f"{KIE_MARKET_API_BASE}/api/v1/jobs/recordInfo",
            params={"taskId": task_id},
        )
        if data.get("code") != 200:
            raise KieMarketError(
                f"recordInfo failed with code={data.get('code')}: {data.get('msg', '')}",
                data,
            )
        return data

    async def get_task_status(self, task_id: str) -> dict | None:
        """Convenience: return the inner ``data`` block or None on failure."""
        try:
            details = await self.get_task_details(task_id)
        except KieMarketError:
            return None
        inner = details.get("data")
        if not isinstance(inner, dict):
            return None
        return inner

    # ═════════════════════════════════════════════════════════════════
    #  3. Result parsing
    # ═════════════════════════════════════════════════════════════════

    @staticmethod
    def parse_result_urls(task_data: dict) -> list[str]:
        """Extract ``resultUrls`` from a task ``data`` block."""
        result_json = task_data.get("resultJson")
        if not result_json:
            return []
        try:
            parsed = json.loads(result_json) if isinstance(result_json, str) else result_json
        except (json.JSONDecodeError, TypeError):
            logger.warning("KIE Market: invalid resultJson: %s", result_json)
            return []
        urls = parsed.get("resultUrls", []) if isinstance(parsed, dict) else []
        return urls if isinstance(urls, list) else []

    # ═════════════════════════════════════════════════════════════════
    #  4. File upload (stream primary; also base64 + URL helpers)
    # ═════════════════════════════════════════════════════════════════

    def _upload_cache_key(self, local_path: str) -> str:
        try:
            stat = os.stat(local_path)
            return f"{local_path}:{stat.st_size}:{stat.st_mtime_ns}"
        except OSError:
            return local_path

    async def upload_file_stream(
        self,
        file_path: str,
        file_name: str | None = None,
        upload_path: str = "images/telegram",
    ) -> str:
        """Upload a local file via KIE stream upload. Returns the download URL."""
        if not os.path.isfile(file_path):
            raise KieMarketError(f"File not found: {file_path}")

        cache_key = self._upload_cache_key(file_path)
        cached = self._upload_cache.get(cache_key)
        if cached and time.time() - cached[1] < 48 * 3600:
            logger.debug("KIE Market upload cache hit: %s", file_path)
            return cached[0]

        fname = file_name or os.path.basename(file_path)
        mime_type = mimetypes.guess_type(file_path)[0] or "image/png"

        session = await self._get_session()
        form = aiohttp.FormData()
        with open(file_path, "rb") as fh:
            form.add_field("file", fh, filename=fname, content_type=mime_type)
            form.add_field("uploadPath", upload_path)
            form.add_field("fileName", fname)

            headers = self._auth_headers()
            try:
                async with session.post(
                    f"{KIE_UPLOAD_BASE}/api/file-stream-upload",
                    headers=headers,
                    data=form,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    data = await resp.json(content_type=None)
            except Exception as exc:
                logger.exception("KIE Market stream upload failed: %s", file_path)
                raise KieMarketError(str(exc)) from exc

        if not isinstance(data, dict) or not data.get("success"):
            raise KieMarketError(f"Upload rejected: {data}", data)

        url = (data.get("data", {}).get("fileUrl")
               or data.get("data", {}).get("downloadUrl", "")).strip()
        if not url:
            raise KieMarketError(f"Upload returned no URL: {data}", data)

        self._upload_cache[cache_key] = (url, time.time())
        logger.info("KIE Market uploaded: %s → %s", file_path, url)
        return url

    async def upload_file_base64(
        self,
        file_path: str,
        file_name: str | None = None,
        upload_path: str = "images/telegram",
    ) -> str:
        """Upload via base64 (for small files < 10 MB)."""
        if not os.path.isfile(file_path):
            raise KieMarketError(f"File not found: {file_path}")

        cache_key = self._upload_cache_key(file_path) + ":b64"
        cached = self._upload_cache.get(cache_key)
        if cached and time.time() - cached[1] < 48 * 3600:
            return cached[0]

        fname = file_name or os.path.basename(file_path)
        mime_type = mimetypes.guess_type(file_path)[0] or "image/png"
        with open(file_path, "rb") as fh:
            raw = fh.read()
        b64_data = base64.b64encode(raw).decode("ascii")

        payload = {
            "file": f"data:{mime_type};base64,{b64_data}",
            "fileName": fname,
            "uploadPath": upload_path,
        }

        data = await self._post_json(
            f"{KIE_UPLOAD_BASE}/api/file-base64-upload", payload, timeout=90,
        )
        if not isinstance(data, dict) or not data.get("success"):
            raise KieMarketError(f"Base64 upload rejected: {data}", data)

        url = (data.get("data", {}).get("fileUrl")
               or data.get("data", {}).get("downloadUrl", "")).strip()
        if not url:
            raise KieMarketError(f"Base64 upload returned no URL: {data}", data)

        self._upload_cache[cache_key] = (url, time.time())
        logger.info("KIE Market base64 uploaded: %s → %s", file_path, url)
        return url

    async def upload_file_url(self, public_url: str) -> str:
        """Register a publicly-accessible URL with KIE (no local file needed)."""
        payload = {"url": public_url}
        data = await self._post_json(
            f"{KIE_UPLOAD_BASE}/api/file-url-upload", payload, timeout=30,
        )
        if not isinstance(data, dict) or not data.get("success"):
            raise KieMarketError(f"URL upload rejected: {data}", data)
        url = (data.get("data", {}).get("fileUrl")
               or data.get("data", {}).get("downloadUrl", "")).strip()
        if not url:
            raise KieMarketError(f"URL upload returned no URL: {data}", data)
        logger.info("KIE Market URL uploaded: %s → %s", public_url, url)
        return url

    async def upload_local_refs(self, sources: Iterable[str] | None) -> list[str]:
        """Upload a batch of local file paths → KIE temporary URLs.

        Falls back to the existing ``kie_file_upload_service`` for files
        that may already have stable public URLs.
        """
        if not sources:
            return []
        from bot.services.kie_file_upload_service import kie_file_upload_service
        return await kie_file_upload_service.upload_local_image_sources(sources)

    # ═════════════════════════════════════════════════════════════════
    #  5. Credit balance
    # ═════════════════════════════════════════════════════════════════

    async def get_remaining_credits(self) -> int | float:
        """Return current credit balance."""
        data = await self._get_json(f"{KIE_MARKET_API_BASE}/api/v1/chat/credit")
        credits = data.get("data", 0)
        logger.debug("KIE Market credits: %s", credits)
        return credits

    # ═════════════════════════════════════════════════════════════════
    #  6. Direct download URL (20-min temporary link)
    # ═════════════════════════════════════════════════════════════════

    async def get_download_url(self, generated_url: str) -> str:
        """Get a 20-minute direct download URL for a KIE-generated file."""
        data = await self._post_json(
            f"{KIE_MARKET_API_BASE}/api/v1/common/download-url",
            {"url": generated_url},
        )
        url = data.get("data", "")
        if not url:
            raise KieMarketError(f"download-url returned no data: {data}", data)
        logger.debug("KIE Market download-url: %s → %s", generated_url, url)
        return url

    # ═════════════════════════════════════════════════════════════════
    #  7. Webhook HMAC verification
    # ═════════════════════════════════════════════════════════════════

    def verify_webhook_signature(
        self,
        payload: dict,
        headers: Any,
    ) -> bool:
        """Validate KIE Market webhook using HMAC-SHA256.

        Headers required: ``X-Webhook-Timestamp``, ``X-Webhook-Signature``.
        Message format: ``taskId + "." + timestamp``.
        """
        if not self.webhook_hmac_key:
            logger.warning("KIE Market: webhook HMAC key not configured, skipping verification")
            return True  # tolerate missing key in dev

        timestamp = _get_header(headers, "X-Webhook-Timestamp")
        signature = _get_header(headers, "X-Webhook-Signature")

        task_id = (
            payload.get("taskId")
            or (payload.get("data") or {}).get("taskId")
            or ""
        )

        if not timestamp or not signature or not task_id:
            logger.warning(
                "KIE Market webhook: missing fields ts=%s sig=%s tid=%s",
                bool(timestamp), bool(signature), bool(task_id),
            )
            return False

        message = f"{task_id}.{timestamp}".encode()
        secret = self.webhook_hmac_key.encode()
        digest = hmac.new(secret, message, hashlib.sha256).digest()
        expected = base64.b64encode(digest).decode()

        ok = hmac.compare_digest(expected, signature)
        if not ok:
            logger.warning(
                "KIE Market webhook: signature mismatch for task %s", task_id,
            )
        return ok

    # ═════════════════════════════════════════════════════════════════
    #  8. High-level: generate image (task → store → return)
    # ═════════════════════════════════════════════════════════════════

    async def generate_nano_banana_2_lite(
        self,
        prompt: str,
        image_urls: list[str] | None = None,
        aspect_ratio: str = "auto",
        callback_url: str | None = None,
    ) -> dict | None:
        """Create a task and return ``{"task_id": str}`` for async processing."""
        try:
            task_id = await self.create_nano_banana_2_lite_task(
                prompt=prompt,
                image_urls=image_urls,
                aspect_ratio=aspect_ratio,
                callback_url=callback_url,
            )
            return {"task_id": task_id}
        except KieMarketError as exc:
            logger.error("KIE Market generate failed: %s", exc)
            return None


# ── helpers ──────────────────────────────────────────────────────────

def _get_header(headers: Any, name: str) -> str:
    """Extract header value case-insensitively from various header types."""
    if headers is None:
        return ""
    if isinstance(headers, dict):
        for key, val in headers.items():
            if isinstance(key, str) and key.lower() == name.lower():
                return str(val) if val else ""
        return ""
    # aiohttp CIMultiDict / multidict
    return str(headers.get(name, "") or "")


def _safe_log_payload(payload: dict) -> dict:
    """Return a copy safe for logging (redact large binary fields)."""
    if not isinstance(payload, dict):
        return payload
    safe = dict(payload)
    inp = safe.get("input")
    if isinstance(inp, dict) and "image_urls" in inp:
        safe["input"] = {**inp, "image_urls": f"[{len(inp['image_urls'])} urls]"}
    return safe


# ── singleton ────────────────────────────────────────────────────────

kie_market_service = KieMarketService(
    api_key=config.KIE_AI_API_KEY or "",
    callback_base_url=config.kie_market_notification_url,
    webhook_hmac_key=getattr(config, "KIE_WEBHOOK_HMAC_KEY", "") or "",
)
