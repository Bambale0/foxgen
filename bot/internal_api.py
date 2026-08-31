"""
Internal API for the HappyFox admin surface and autonomous external routes.

Uses timestamped HMAC authentication compatible with
backend/app/channels/internal.py (InternalChannelClient).

Endpoints:
  GET  /internal/v1/health  — detailed HappyFox backend status
  GET  /internal/v1/stats   — aggregated read-only statistics
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from functools import partial
from typing import Any

from aiohttp import web

logger = logging.getLogger(__name__)

_INTERNAL_PREFIX = "/internal/v1"
_DISABLED_LEGACY_PAYMENT_PATHS = frozenset(
    {
        "/yookassa/webhook",
        "/webhook/yookassa",
    }
)


def _verify_hmac(request: web.Request, secret: str) -> bool:
    """Validate a signature created by InternalChannelClient._signed_headers."""
    if not secret:
        return False
    timestamp_str = request.headers.get("X-Internal-Timestamp", "")
    signature = request.headers.get("X-Internal-Signature", "")
    if not timestamp_str or not signature:
        return False
    try:
        timestamp = int(timestamp_str)
    except (ValueError, TypeError):
        return False
    if abs(time.time() - timestamp) > 30:
        return False
    method = request.method.upper()
    path = str(request.rel_url.path)
    body = b""
    message = b"\n".join(
        [
            timestamp_str.encode("ascii"),
            method.encode("ascii"),
            path.encode("utf-8"),
            body,
        ]
    )
    expected = hmac.new(
        secret.encode("utf-8"), message, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@web.middleware
async def internal_auth_middleware(request: web.Request, handler: Any) -> web.Response:
    """Protect internal API and permanently retire old payment endpoints."""
    if request.path in _DISABLED_LEGACY_PAYMENT_PATHS:
        return web.json_response(
            {
                "error": "payment_provider_removed",
                "provider": "lava",
                "webhook": "/lava/webhook",
            },
            status=410,
        )
    if not request.path.startswith(_INTERNAL_PREFIX):
        return await handler(request)
    secret = request.app.get("internal_api_secret", "")
    if not _verify_hmac(request, secret):
        return web.json_response({"error": "unauthorized"}, status=401)
    return await handler(request)


async def handle_internal_health(request: web.Request) -> web.Response:
    """Report HappyFox backend version and database connectivity."""
    from bot.internal_api_db import simple_db_query_ok

    db_ok = False
    db_error: str | None = None
    try:
        db_ok = await simple_db_query_ok()
    except Exception as exc:  # noqa: BLE001 - health endpoint reports any DB failure
        db_error = str(exc)

    payload: dict[str, Any] = {
        "service": "happyfox-backend",
        "status": "ok" if db_ok else "degraded",
        "version": request.app.get("bot_version", "unknown"),
        "database": (
            "connected"
            if db_ok
            else f"error: {db_error}"
            if db_error
            else "unknown"
        ),
    }
    status_code = 200 if db_ok else 503
    return web.json_response(payload, status=status_code)


async def handle_internal_stats(request: web.Request) -> web.Response:
    """Return aggregated read-only users, generation and billing statistics."""
    from bot.internal_api_db import get_db_aggregates

    try:
        stats = await get_db_aggregates()
    except Exception as exc:
        logger.exception("Failed to fetch internal stats")
        return web.json_response({"error": str(exc)}, status=500)

    return web.json_response(stats)


async def _instagram_bot_username(app: web.Application) -> str:
    bot = app.get("bot")
    if bot is None:
        raise RuntimeError("Telegram bot is unavailable for Instagram account linking")

    username = str(app.get("instagram_link_bot_username") or "").strip().lstrip("@")
    if username:
        return username

    me = await bot.get_me()
    username = str(getattr(me, "username", "") or "").strip().lstrip("@")
    if not username:
        raise RuntimeError("Telegram bot username is unavailable")
    app["instagram_link_bot_username"] = username
    return username


async def _build_instagram_account_link_url(app: web.Application, identity: Any) -> str:
    from bot.channel_link import create_channel_link_token

    username = await _instagram_bot_username(app)
    token = await create_channel_link_token(int(identity.id))
    return f"https://t.me/{username}?start=iglink_{token}"


def _setup_instagram_channel(app: web.Application) -> None:
    """Register Instagram only when the channel is explicitly enabled."""
    from bot.instagram_api import (
        InstagramClient,
        InstagramSettings,
        setup_instagram_routes,
    )
    from bot.instagram_channel import build_instagram_event_handler
    from bot.instagram_creator_generation import InstagramCreatorGenerationService
    from bot.instagram_generation import install_instagram_generation_worker

    settings = InstagramSettings.from_env()
    if not settings.enabled:
        logger.info("Instagram channel disabled")
        return

    account_link_factory = partial(_build_instagram_account_link_url, app)
    client = InstagramClient.from_settings(settings)
    generation_service = InstagramCreatorGenerationService(
        settings=settings,
        client=client,
        account_link_factory=account_link_factory,
    )
    install_instagram_generation_worker(app, generation_service)

    setup_instagram_routes(
        app,
        settings=settings,
        event_handler=build_instagram_event_handler(
            settings,
            client=client,
            account_link_factory=account_link_factory,
            generation_service=generation_service,
        ),
    )


def setup_internal_api(app: web.Application, secret: str, version: str = "") -> None:
    """Register internal API plus isolated payment and channel HTTP routes."""
    app["internal_api_secret"] = secret
    app["bot_version"] = version

    app.middlewares.append(internal_auth_middleware)

    router = app.router
    router.add_get(f"{_INTERNAL_PREFIX}/health", handle_internal_health)
    router.add_get(f"{_INTERNAL_PREFIX}/stats", handle_internal_stats)

    from bot.handlers.freekassa_payments import setup_freekassa_routes
    from bot.max_runtime import setup_max_runtime

    setup_freekassa_routes(app)
    _setup_instagram_channel(app)
    setup_max_runtime(app)

    logger.info(
        "Internal API registered: prefix=%s, routes=health, stats",
        _INTERNAL_PREFIX,
    )
