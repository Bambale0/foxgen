from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import aiohttp
from aiohttp import web

from bot.services.redis_service import redis_service

logger = logging.getLogger(__name__)

_GRAPH_HOST = "https://graph.instagram.com"
_DEFAULT_API_VERSION = "v24.0"
_DEFAULT_WEBHOOK_PATH = "/instagram/webhook"
_DEFAULT_IDEMPOTENCY_TTL_SECONDS = 7 * 24 * 60 * 60
_DEFAULT_SUBSCRIBED_FIELDS = ("messages", "messaging_postbacks", "comments")
_TRUE_VALUES = {"1", "true", "yes", "on"}


class InstagramApiError(RuntimeError):
    """Stable exception exposed by the Instagram infrastructure adapter."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: Any = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class InstagramDeliveryUnavailable(RuntimeError):
    """Raised when a webhook cannot be processed with exactly-once safety."""


@dataclass(frozen=True)
class InstagramSettings:
    enabled: bool = False
    app_id: str = ""
    app_secret: str = ""
    verify_token: str = ""
    access_token: str = ""
    ig_user_id: str = ""
    api_version: str = _DEFAULT_API_VERSION
    webhook_path: str = _DEFAULT_WEBHOOK_PATH
    request_timeout_seconds: int = 30
    idempotency_ttl_seconds: int = _DEFAULT_IDEMPOTENCY_TTL_SECONDS
    subscribed_fields: tuple[str, ...] = _DEFAULT_SUBSCRIBED_FIELDS

    @classmethod
    def from_env(cls) -> InstagramSettings:
        raw_fields = os.getenv(
            "INSTAGRAM_SUBSCRIBED_FIELDS",
            ",".join(_DEFAULT_SUBSCRIBED_FIELDS),
        )
        fields = tuple(
            item.strip() for item in raw_fields.split(",") if item.strip()
        ) or _DEFAULT_SUBSCRIBED_FIELDS
        return cls(
            enabled=os.getenv("INSTAGRAM_ENABLED", "0").strip().lower()
            in _TRUE_VALUES,
            app_id=os.getenv("INSTAGRAM_APP_ID", "").strip(),
            app_secret=os.getenv("INSTAGRAM_APP_SECRET", "").strip(),
            verify_token=os.getenv("INSTAGRAM_VERIFY_TOKEN", "").strip(),
            access_token=os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip(),
            ig_user_id=os.getenv("INSTAGRAM_IG_USER_ID", "").strip(),
            api_version=(
                os.getenv("INSTAGRAM_API_VERSION", _DEFAULT_API_VERSION).strip()
                or _DEFAULT_API_VERSION
            ),
            webhook_path=(
                os.getenv("INSTAGRAM_WEBHOOK_PATH", _DEFAULT_WEBHOOK_PATH).strip()
                or _DEFAULT_WEBHOOK_PATH
            ),
            request_timeout_seconds=max(
                1,
                int(os.getenv("INSTAGRAM_REQUEST_TIMEOUT_SECONDS", "30")),
            ),
            idempotency_ttl_seconds=max(
                60,
                int(
                    os.getenv(
                        "INSTAGRAM_IDEMPOTENCY_TTL_SECONDS",
                        str(_DEFAULT_IDEMPOTENCY_TTL_SECONDS),
                    )
                ),
            ),
            subscribed_fields=fields,
        )

    def route_validation_errors(self) -> list[str]:
        errors: list[str] = []
        for key, value in (
            ("INSTAGRAM_APP_SECRET", self.app_secret),
            ("INSTAGRAM_VERIFY_TOKEN", self.verify_token),
        ):
            if not value:
                errors.append(f"{key} is required when Instagram webhooks are enabled")
        if not self.webhook_path.startswith("/"):
            errors.append("INSTAGRAM_WEBHOOK_PATH must start with /")
        return errors


@dataclass(frozen=True)
class InstagramEvent:
    event_id: str
    kind: str
    account_id: str
    sender_id: str = ""
    recipient_id: str = ""
    timestamp: int = 0
    text: str = ""
    media_id: str = ""
    is_echo: bool = False
    payload: dict[str, Any] = field(default_factory=dict)


InstagramEventHandler = Callable[[InstagramEvent], Awaitable[None]]
InstagramClaimOnce = Callable[[str], Awaitable[bool]]
InstagramReleaseClaim = Callable[[str], Awaitable[None]]


def verify_instagram_signature(body: bytes, signature: str, app_secret: str) -> bool:
    """Validate Meta's X-Hub-Signature-256 against the raw request body."""
    if not body or not signature or not app_secret:
        return False
    prefix = "sha256="
    if not signature.startswith(prefix):
        return False
    received = signature[len(prefix) :].strip().lower()
    if not received:
        return False
    expected = hmac.new(
        app_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, received)


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _stable_event_id(kind: str, explicit_id: Any, payload: dict[str, Any]) -> str:
    explicit = str(explicit_id or "").strip()
    if explicit:
        return f"{kind}:{explicit}"
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()[:32]
    return f"{kind}:sha256:{digest}"


def _message_event(account_id: str, item: dict[str, Any]) -> InstagramEvent | None:
    sender_id = str((item.get("sender") or {}).get("id") or "")
    recipient_id = str((item.get("recipient") or {}).get("id") or "")
    timestamp = _int_or_zero(item.get("timestamp"))

    message = item.get("message")
    if isinstance(message, dict):
        return InstagramEvent(
            event_id=_stable_event_id("message", message.get("mid"), item),
            kind="message",
            account_id=account_id,
            sender_id=sender_id,
            recipient_id=recipient_id,
            timestamp=timestamp,
            text=str(message.get("text") or ""),
            is_echo=bool(
                message.get("is_echo") or (sender_id and sender_id == account_id)
            ),
            payload={"message": message},
        )

    postback = item.get("postback")
    if isinstance(postback, dict):
        return InstagramEvent(
            event_id=_stable_event_id("postback", postback.get("mid"), item),
            kind="postback",
            account_id=account_id,
            sender_id=sender_id,
            recipient_id=recipient_id,
            timestamp=timestamp,
            text=str(postback.get("title") or ""),
            is_echo=bool(sender_id and sender_id == account_id),
            payload={"postback": postback},
        )

    return None


def _field_event(entry: dict[str, Any]) -> InstagramEvent | None:
    kind = str(entry.get("field") or "").strip()
    value = entry.get("value")
    if not kind or not isinstance(value, dict):
        return None

    account_id = str(entry.get("id") or "")
    sender = value.get("from") if isinstance(value.get("from"), dict) else {}
    media = value.get("media") if isinstance(value.get("media"), dict) else {}
    explicit_id = value.get("id") or value.get("message_id")
    return InstagramEvent(
        event_id=_stable_event_id(kind, explicit_id, entry),
        kind=kind,
        account_id=account_id,
        sender_id=str(sender.get("id") or ""),
        recipient_id=account_id,
        timestamp=_int_or_zero(entry.get("time")),
        text=str(value.get("text") or ""),
        media_id=str(media.get("id") or value.get("media_id") or ""),
        payload=value,
    )


def normalize_instagram_events(payload: dict[str, Any]) -> list[InstagramEvent]:
    """Translate Meta webhook payloads into channel-neutral event envelopes."""
    if payload.get("object") != "instagram":
        return []

    entries = payload.get("entry")
    if not isinstance(entries, list):
        return []

    normalized: list[InstagramEvent] = []
    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            continue
        account_id = str(raw_entry.get("id") or "")
        messaging = raw_entry.get("messaging")
        if isinstance(messaging, list):
            for raw_item in messaging:
                if not isinstance(raw_item, dict):
                    continue
                event = _message_event(account_id, raw_item)
                if event is not None:
                    normalized.append(event)

        field_event = _field_event(raw_entry)
        if field_event is not None:
            normalized.append(field_event)

    return normalized


def _event_key(event_id: str) -> str:
    digest = hashlib.sha256(event_id.encode("utf-8")).hexdigest()
    return redis_service.build_key(f"instagram:event:{digest}")


async def _claim_event_once(event_id: str, ttl_seconds: int) -> bool:
    client = await redis_service.get_client()
    if client is None:
        raise InstagramDeliveryUnavailable(
            "Redis is required for Instagram webhook idempotency"
        )
    try:
        claimed = await client.set(
            _event_key(event_id),
            "processing",
            ex=ttl_seconds,
            nx=True,
        )
    except Exception as exc:
        raise InstagramDeliveryUnavailable(
            "Instagram webhook idempotency storage is unavailable"
        ) from exc
    return bool(claimed)


async def _release_event_claim(event_id: str) -> None:
    client = await redis_service.get_client()
    if client is None:
        return
    try:
        await client.delete(_event_key(event_id))
    except Exception:
        logger.exception("Failed to release Instagram event claim: %s", event_id)


async def verify_instagram_webhook(request: web.Request) -> web.Response:
    settings = request.app.get("instagram_settings") or InstagramSettings.from_env()
    mode = str(request.query.get("hub.mode") or "")
    verify_token = str(request.query.get("hub.verify_token") or "")
    challenge = str(request.query.get("hub.challenge") or "")
    is_valid = (
        settings.enabled
        and mode == "subscribe"
        and bool(challenge)
        and bool(settings.verify_token)
        and hmac.compare_digest(verify_token, settings.verify_token)
    )
    if not is_valid:
        return web.Response(text="Forbidden", status=403)
    return web.Response(text=challenge, status=200)


async def handle_instagram_webhook(request: web.Request) -> web.Response:
    settings = request.app.get("instagram_settings") or InstagramSettings.from_env()
    if not settings.enabled:
        return web.json_response({"error": "instagram_disabled"}, status=404)

    raw_body = await request.read()
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not verify_instagram_signature(raw_body, signature, settings.app_secret):
        return web.json_response({"error": "invalid_signature"}, status=401)

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return web.json_response({"error": "invalid_json"}, status=400)
    if not isinstance(payload, dict) or payload.get("object") != "instagram":
        return web.json_response({"error": "invalid_object"}, status=400)

    event_handler: InstagramEventHandler | None = request.app.get(
        "instagram_event_handler"
    )
    if event_handler is None:
        return web.json_response(
            {"error": "instagram_handler_unavailable"},
            status=503,
        )

    claim_once: InstagramClaimOnce | None = request.app.get("instagram_claim_once")
    release_claim: InstagramReleaseClaim | None = request.app.get(
        "instagram_release_claim"
    )
    processed = 0
    duplicates = 0
    echoes = 0

    try:
        for event in normalize_instagram_events(payload):
            if event.is_echo:
                echoes += 1
                continue

            claimed = (
                await claim_once(event.event_id)
                if claim_once is not None
                else await _claim_event_once(
                    event.event_id,
                    settings.idempotency_ttl_seconds,
                )
            )
            if not claimed:
                duplicates += 1
                continue

            try:
                await event_handler(event)
            except Exception:
                if release_claim is not None:
                    await release_claim(event.event_id)
                else:
                    await _release_event_claim(event.event_id)
                raise
            processed += 1
    except InstagramDeliveryUnavailable:
        logger.exception("Instagram webhook delivery unavailable")
        return web.json_response({"error": "delivery_unavailable"}, status=503)
    except Exception:
        logger.exception("Instagram webhook event handler failed")
        return web.json_response({"error": "event_processing_failed"}, status=503)

    return web.json_response(
        {
            "ok": True,
            "processed": processed,
            "duplicates": duplicates,
            "echoes": echoes,
        }
    )


def _require_public_https_url(value: str) -> str:
    candidate = str(value or "").strip()
    parsed = urlparse(candidate)
    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or not hostname
        or hostname in {"localhost", "127.0.0.1", "::1"}
        or hostname.endswith(".local")
    ):
        raise ValueError("Instagram media URL must be a public https URL")
    return candidate


class InstagramClient:
    """Official Instagram Login API client for messaging and publishing."""

    def __init__(
        self,
        *,
        access_token: str,
        api_version: str = _DEFAULT_API_VERSION,
        timeout_seconds: int = 30,
        graph_host: str = _GRAPH_HOST,
    ) -> None:
        self.access_token = str(access_token or "").strip()
        self.api_version = str(api_version or _DEFAULT_API_VERSION).strip().lstrip("/")
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.graph_host = str(graph_host or _GRAPH_HOST).rstrip("/")

    @classmethod
    def from_settings(cls, settings: InstagramSettings) -> InstagramClient:
        return cls(
            access_token=settings.access_token,
            api_version=settings.api_version,
            timeout_seconds=settings.request_timeout_seconds,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        form_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.access_token:
            raise InstagramApiError("Instagram access token is not configured")

        url = f"{self.graph_host}/{self.api_version}/{path.lstrip('/')}"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        try:
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json_body,
                    data=form_body,
                ) as response,
            ):
                try:
                    payload = await response.json(content_type=None)
                except (aiohttp.ContentTypeError, json.JSONDecodeError):
                    payload = {"raw": await response.text()}
                status = response.status
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise InstagramApiError("Instagram API request failed") from exc

        if not isinstance(payload, dict):
            payload = {"data": payload}
        error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        if status >= 400 or error:
            raise InstagramApiError(
                str(error.get("message") or "Instagram API request failed"),
                status=status,
                code=error.get("code"),
            )
        return payload

    async def get_webhook_subscriptions(self, ig_user_id: str) -> dict[str, Any]:
        return await self._request("GET", f"{ig_user_id}/subscribed_apps")

    async def subscribe_webhooks(
        self,
        ig_user_id: str,
        fields: Iterable[str] = _DEFAULT_SUBSCRIBED_FIELDS,
    ) -> dict[str, Any]:
        normalized = ",".join(
            dict.fromkeys(str(item).strip() for item in fields if str(item).strip())
        )
        if not normalized:
            raise ValueError("At least one Instagram webhook field is required")
        return await self._request(
            "POST",
            f"{ig_user_id}/subscribed_apps",
            params={"subscribed_fields": normalized},
        )

    async def unsubscribe_webhooks(self, ig_user_id: str) -> dict[str, Any]:
        return await self._request("DELETE", f"{ig_user_id}/subscribed_apps")

    async def send_text(
        self,
        ig_user_id: str,
        recipient_id: str,
        text: str,
    ) -> dict[str, Any]:
        message = str(text or "").strip()
        if not message:
            raise ValueError("Instagram message text cannot be empty")
        return await self._request(
            "POST",
            f"{ig_user_id}/messages",
            json_body={
                "recipient": {"id": str(recipient_id)},
                "message": {"text": message},
            },
        )

    async def send_media(
        self,
        ig_user_id: str,
        recipient_id: str,
        media_type: str,
        media_url: str,
    ) -> dict[str, Any]:
        normalized_type = str(media_type or "").strip().lower()
        if normalized_type not in {"image", "video"}:
            raise ValueError("Instagram media message type must be image or video")
        public_url = _require_public_https_url(media_url)
        return await self._request(
            "POST",
            f"{ig_user_id}/messages",
            json_body={
                "recipient": {"id": str(recipient_id)},
                "message": {
                    "attachment": {
                        "type": normalized_type,
                        "payload": {"url": public_url},
                    }
                },
            },
        )

    async def private_reply(
        self,
        ig_user_id: str,
        comment_id: str,
        text: str,
    ) -> dict[str, Any]:
        message = str(text or "").strip()
        if not message:
            raise ValueError("Instagram private reply text cannot be empty")
        return await self._request(
            "POST",
            f"{ig_user_id}/messages",
            json_body={
                "recipient": {"comment_id": str(comment_id)},
                "message": {"text": message},
            },
        )

    async def create_image_container(
        self,
        ig_user_id: str,
        image_url: str,
        caption: str = "",
    ) -> dict[str, Any]:
        form_body: dict[str, Any] = {
            "image_url": _require_public_https_url(image_url)
        }
        if caption:
            form_body["caption"] = str(caption)
        return await self._request(
            "POST",
            f"{ig_user_id}/media",
            form_body=form_body,
        )

    async def create_reel_container(
        self,
        ig_user_id: str,
        video_url: str,
        caption: str = "",
        *,
        share_to_feed: bool = True,
    ) -> dict[str, Any]:
        form_body: dict[str, Any] = {
            "media_type": "REELS",
            "video_url": _require_public_https_url(video_url),
            "share_to_feed": "true" if share_to_feed else "false",
        }
        if caption:
            form_body["caption"] = str(caption)
        return await self._request(
            "POST",
            f"{ig_user_id}/media",
            form_body=form_body,
        )

    async def get_container_status(self, container_id: str) -> dict[str, Any]:
        return await self._request(
            "GET",
            str(container_id),
            params={"fields": "status_code,status"},
        )

    async def publish_container(
        self,
        ig_user_id: str,
        creation_id: str,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"{ig_user_id}/media_publish",
            form_body={"creation_id": str(creation_id)},
        )

    async def get_content_publishing_limit(self, ig_user_id: str) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"{ig_user_id}/content_publishing_limit",
        )


def setup_instagram_routes(
    app: web.Application,
    *,
    event_handler: InstagramEventHandler | None = None,
    settings: InstagramSettings | None = None,
) -> bool:
    """Register webhook routes only after explicit Instagram enablement."""
    resolved = settings or InstagramSettings.from_env()
    if not resolved.enabled:
        logger.info("Instagram transport disabled")
        return False

    errors = resolved.route_validation_errors()
    if errors:
        raise RuntimeError(
            "Invalid Instagram webhook configuration: " + "; ".join(errors)
        )

    app["instagram_settings"] = resolved
    if event_handler is not None:
        app["instagram_event_handler"] = event_handler
    app.router.add_get(resolved.webhook_path, verify_instagram_webhook)
    app.router.add_post(resolved.webhook_path, handle_instagram_webhook)
    logger.info(
        "Instagram webhook transport registered: path=%s api=%s",
        resolved.webhook_path,
        resolved.api_version,
    )
    return True
