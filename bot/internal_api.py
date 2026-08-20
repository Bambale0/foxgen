"""
Internal API для административной панели (read-only).

Использует timestamped HMAC-аутентификацию, совместимую с
backend/app/channels/internal.py (InternalChannelClient).

Эндпоинты:
  GET  /internal/v1/health  — детальный статус бота
  GET  /internal/v1/stats   — агрегированная read-only статистика
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
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
    """Проверяет HMAC-подпись из InternalChannelClient._signed_headers."""
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
    """Детальный статус бота — версия, аптайм, база данных."""
    from bot.internal_api_db import simple_db_query_ok

    db_ok = False
    db_error: str | None = None
    try:
        db_ok = await simple_db_query_ok()
    except Exception as exc:  # noqa: BLE001 - health endpoint reports any DB failure
        db_error = str(exc)

    payload: dict[str, Any] = {
        "service": "tanya-telegram",
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
    """Агрегированная read-only статистика: пользователи, генерации, транзакции, доход."""
    from bot.internal_api_db import get_db_aggregates

    try:
        stats = await get_db_aggregates()
    except Exception as exc:
        logger.exception("Failed to fetch internal stats")
        return web.json_response({"error": str(exc)}, status=500)

    return web.json_response(stats)


def setup_internal_api(app: web.Application, secret: str, version: str = "") -> None:
    """Регистрирует internal API, а также автономные payment routes."""
    app["internal_api_secret"] = secret
    app["bot_version"] = version

    app.middlewares.append(internal_auth_middleware)

    router = app.router
    router.add_get(f"{_INTERNAL_PREFIX}/health", handle_internal_health)
    router.add_get(f"{_INTERNAL_PREFIX}/stats", handle_internal_stats)

    from bot.handlers.freekassa_payments import setup_freekassa_routes

    setup_freekassa_routes(app)

    logger.info(
        "Internal API registered: prefix=%s, routes=health, stats",
        _INTERNAL_PREFIX,
    )
