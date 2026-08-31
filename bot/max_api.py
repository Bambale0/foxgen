from __future__ import annotations

import asyncio
import hmac
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import aiohttp
from aiohttp import web

from bot.max_store import (
    claim_max_event,
    mark_max_event_processed,
    max_event_key,
    release_max_event,
)

logger = logging.getLogger(__name__)

MAX_DEFAULT_API_BASE = "https://platform-api2.max.ru"
MAX_DEFAULT_WEBHOOK_PATH = "/max/webhook"
MAX_UPDATE_TYPES = ("bot_started", "message_created", "message_callback")
MAX_WEBHOOK_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{5,256}$")
MAX_MEDIA_TYPES = frozenset({"image", "video", "audio", "file"})


class MaxApiError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class MaxSettings:
    enabled: bool
    access_token: str
    webhook_secret: str
    api_base: str = MAX_DEFAULT_API_BASE
    webhook_path: str = MAX_DEFAULT_WEBHOOK_PATH
    mini_app_url: str = ""

    @classmethod
    def from_env(cls) -> "MaxSettings":
        enabled = str(os.getenv("MAX_ENABLED", "0")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        return cls(
            enabled=enabled,
            access_token=str(os.getenv("MAX_ACCESS_TOKEN", "")).strip(),
            webhook_secret=str(os.getenv("MAX_WEBHOOK_SECRET", "")).strip(),
            api_base=str(os.getenv("MAX_API_BASE", MAX_DEFAULT_API_BASE)).strip().rstrip("/"),
            webhook_path=str(os.getenv("MAX_WEBHOOK_PATH", MAX_DEFAULT_WEBHOOK_PATH)).strip()
            or MAX_DEFAULT_WEBHOOK_PATH,
            mini_app_url=str(os.getenv("MAX_MINI_APP_URL", "")).strip(),
        )

    def validate_enabled(self) -> None:
        if not self.enabled:
            return
        if not self.access_token:
            raise RuntimeError("MAX_ACCESS_TOKEN is required when MAX_ENABLED=1")
        if not MAX_WEBHOOK_SECRET_RE.fullmatch(self.webhook_secret):
            raise RuntimeError(
                "MAX_WEBHOOK_SECRET must match ^[A-Za-z0-9_-]{5,256}$"
            )
        if not self.webhook_path.startswith("/"):
            raise RuntimeError("MAX_WEBHOOK_PATH must start with /")
        if not self.api_base.startswith("https://"):
            raise RuntimeError("MAX_API_BASE must use HTTPS")


class MaxClient:
    """Production HTTP client for the official MAX Bot API."""

    def __init__(
        self,
        settings: MaxSettings,
        *,
        session: aiohttp.ClientSession | None = None,
    ):
        self.settings = settings
        self._session = session
        self._own_session = session is None
        self._send_locks: dict[int, asyncio.Lock] = {}
        self._last_send: dict[int, float] = {}

    async def close(self) -> None:
        if self._own_session and self._session is not None and not self._session.closed:
            await self._session.close()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=60, connect=10)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = await self._get_session()
        url = f"{self.settings.api_base}{path}"
        headers = {"Authorization": self.settings.access_token}
        try:
            async with session.request(
                method,
                url,
                params=params,
                json=json_body,
                headers=headers,
            ) as response:
                raw = await response.text()
                try:
                    payload = await response.json(content_type=None)
                except (ValueError, aiohttp.ContentTypeError):
                    payload = {}
                if response.status < 200 or response.status >= 300:
                    message = str(payload.get("message") or raw or f"HTTP {response.status}")[:500]
                    raise MaxApiError(message, status=response.status)
                if not isinstance(payload, dict):
                    raise MaxApiError(
                        "MAX API returned a non-object JSON response",
                        status=response.status,
                    )
                return payload
        except asyncio.TimeoutError as exc:
            raise MaxApiError("MAX API request timed out") from exc
        except aiohttp.ClientError as exc:
            raise MaxApiError(f"MAX API transport error: {exc}") from exc

    async def _rate_limit_dialog(self, user_id: int) -> None:
        lock = self._send_locks.setdefault(int(user_id), asyncio.Lock())
        await lock.acquire()
        last = self._last_send.get(int(user_id), 0.0)
        wait = 0.5 - (time.monotonic() - last)
        if wait > 0:
            await asyncio.sleep(wait)

    def _release_dialog(self, user_id: int) -> None:
        self._last_send[int(user_id)] = time.monotonic()
        lock = self._send_locks.get(int(user_id))
        if lock is not None and lock.locked():
            lock.release()

    async def send_message(
        self,
        user_id: int,
        text: str,
        *,
        attachments: list[dict[str, Any]] | None = None,
        format: str = "html",
        notify: bool = True,
    ) -> dict[str, Any]:
        await self._rate_limit_dialog(user_id)
        try:
            body: dict[str, Any] = {"text": str(text)[:4000], "notify": bool(notify)}
            if format:
                body["format"] = format
            if attachments:
                body["attachments"] = attachments
            return await self._request_json(
                "POST",
                "/messages",
                params={"user_id": int(user_id)},
                json_body=body,
            )
        finally:
            self._release_dialog(user_id)

    async def answer_callback(
        self,
        callback_id: str,
        *,
        message: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = await self._request_json(
            "POST",
            "/answers",
            params={"callback_id": callback_id},
            json_body={"message": message} if message is not None else {},
        )
        if payload.get("success") is False:
            raise MaxApiError(str(payload.get("message") or "MAX callback answer failed"))
        return payload

    async def create_subscription(self, webhook_url: str) -> dict[str, Any]:
        if not webhook_url.startswith("https://"):
            raise ValueError("MAX webhook URL must use HTTPS")
        payload = await self._request_json(
            "POST",
            "/subscriptions",
            json_body={
                "url": webhook_url,
                "update_types": list(MAX_UPDATE_TYPES),
                "secret": self.settings.webhook_secret,
            },
        )
        if payload.get("success") is not True:
            raise MaxApiError(str(payload.get("message") or "MAX subscription failed"))
        return payload

    async def get_subscriptions(self) -> dict[str, Any]:
        return await self._request_json("GET", "/subscriptions")

    async def get_upload_slot(self, media_type: str) -> dict[str, Any]:
        if media_type not in MAX_MEDIA_TYPES:
            raise ValueError("Unsupported MAX media type")
        return await self._request_json("POST", "/uploads", params={"type": media_type})

    async def upload_media_bytes(
        self,
        media_type: str,
        content: bytes,
        *,
        filename: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload one MAX media object and return its attachment token."""
        slot = await self.get_upload_slot(media_type)
        upload_url = str(slot.get("url") or "")
        if not upload_url.startswith("https://"):
            raise MaxApiError("MAX upload slot did not contain an HTTPS URL")

        session = await self._get_session()
        form = aiohttp.FormData()
        form.add_field(
            "data",
            content,
            filename=filename,
            content_type=content_type,
        )
        try:
            async with session.post(upload_url, data=form) as response:
                raw = await response.text()
                try:
                    uploaded = await response.json(content_type=None)
                except (ValueError, aiohttp.ContentTypeError):
                    uploaded = {}
                if response.status < 200 or response.status >= 300:
                    raise MaxApiError(
                        str(uploaded.get("message") or raw or "MAX media upload failed")[:500],
                        status=response.status,
                    )
        except asyncio.TimeoutError as exc:
            raise MaxApiError("MAX media upload timed out") from exc
        except aiohttp.ClientError as exc:
            raise MaxApiError(f"MAX media upload transport error: {exc}") from exc

        token = str(uploaded.get("token") or slot.get("token") or "").strip()
        if not token:
            raise MaxApiError("MAX media upload did not return a token")
        return token

    async def upload_media_from_url(
        self,
        media_type: str,
        source_url: str,
        *,
        filename: str,
    ) -> str:
        """Download a provider result and upload it to MAX.

        MAX supports direct external URLs only for images. Video/audio/file results
        therefore pass through the official upload endpoint before delivery.
        """
        if media_type not in MAX_MEDIA_TYPES:
            raise ValueError("Unsupported MAX media type")
        session = await self._get_session()
        try:
            async with session.get(source_url) as response:
                if response.status < 200 or response.status >= 300:
                    raise MaxApiError(
                        f"Provider media download failed with HTTP {response.status}",
                        status=response.status,
                    )
                content = await response.read()
                content_type = str(response.headers.get("Content-Type") or "application/octet-stream")
        except asyncio.TimeoutError as exc:
            raise MaxApiError("Provider media download timed out") from exc
        except aiohttp.ClientError as exc:
            raise MaxApiError(f"Provider media download failed: {exc}") from exc
        return await self.upload_media_bytes(
            media_type,
            content,
            filename=filename,
            content_type=content_type,
        )

    async def send_media_url(
        self,
        user_id: int,
        *,
        media_type: str,
        url: str,
        text: str = "",
        filename: str = "result.bin",
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        extra = list(attachments or [])
        if media_type == "image":
            media = image_url_attachment(url)
        else:
            token = await self.upload_media_from_url(
                media_type,
                url,
                filename=filename,
            )
            media = token_attachment(media_type, token)
        return await self.send_message(
            user_id,
            text,
            attachments=[media, *extra],
        )


def callback_button(text: str, payload: str) -> dict[str, str]:
    return {"type": "callback", "text": text, "payload": payload}


def link_button(text: str, url: str) -> dict[str, str]:
    return {"type": "link", "text": text, "url": url}


def open_app_button(text: str, url: str) -> dict[str, str]:
    return {"type": "open_app", "text": text, "web_app": url}


def inline_keyboard(rows: list[list[dict[str, Any]]]) -> dict[str, Any]:
    if len(rows) > 30 or any(len(row) > 7 for row in rows):
        raise ValueError("MAX inline keyboard exceeds platform limits")
    if sum(len(row) for row in rows) > 210:
        raise ValueError("MAX inline keyboard exceeds 210 buttons")
    return {"type": "inline_keyboard", "payload": {"buttons": rows}}


def image_url_attachment(url: str) -> dict[str, Any]:
    return {"type": "image", "payload": {"url": url}}


def token_attachment(media_type: str, token: str) -> dict[str, Any]:
    if media_type not in MAX_MEDIA_TYPES:
        raise ValueError("Unsupported MAX media type")
    return {"type": media_type, "payload": {"token": token}}


def verify_max_webhook_secret(request: web.Request, secret: str) -> bool:
    provided = str(request.headers.get("X-Max-Bot-Api-Secret", ""))
    return bool(secret and provided and hmac.compare_digest(provided, secret))


MaxEventHandler = Callable[[dict[str, Any]], Awaitable[None]]


def setup_max_routes(
    app: web.Application,
    *,
    settings: MaxSettings,
    event_handler: MaxEventHandler,
) -> None:
    settings.validate_enabled()

    async def webhook(request: web.Request) -> web.Response:
        if not verify_max_webhook_secret(request, settings.webhook_secret):
            return web.json_response({"error": "unauthorized"}, status=401)
        try:
            update = await request.json()
        except (ValueError, TypeError):
            return web.json_response({"error": "invalid_json"}, status=400)
        if not isinstance(update, dict):
            return web.json_response({"error": "invalid_update"}, status=400)

        event_key = max_event_key(update)
        if not await claim_max_event(event_key):
            return web.json_response({"ok": True, "duplicate": True})
        try:
            await event_handler(update)
        except Exception:
            await release_max_event(event_key)
            logger.exception("MAX event handling failed: type=%s", update.get("update_type"))
            return web.json_response({"error": "handler_failed"}, status=500)
        await mark_max_event_processed(event_key)
        return web.json_response({"ok": True})

    app.router.add_post(settings.webhook_path, webhook)
