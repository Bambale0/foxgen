"""
In-memory sliding-window rate limiter for aiohttp webhooks and API routes.

Usage:
    from bot.services.rate_limiter import rate_limiter_middleware
    app.middlewares.append(rate_limiter_middleware)

Config:
    RATE_LIMIT_RPM (env, default=120) — max requests per minute per IP
    RATE_LIMIT_WHITELIST (env, comma-separated IPs) — exempted IPs
"""

import asyncio
import logging
import os
import time
from collections import defaultdict

from aiohttp import web

logger = logging.getLogger(__name__)

DEFAULT_RPM = 120
WINDOW_SEC = 60
CLEANUP_INTERVAL = 300  # 5 min

_whitelist = {
    ip.strip()
    for ip in os.environ.get("RATE_LIMIT_WHITELIST", "").split(",")
    if ip.strip()
}


class _SlidingWindowCounter:
    """Sliding-window rate counter per key."""

    __slots__ = ("timestamps",)

    def __init__(self) -> None:
        self.timestamps: list[float] = []

    def prune(self, now: float) -> None:
        cutoff = now - WINDOW_SEC
        # fast path: most recent is within window
        if self.timestamps and self.timestamps[-1] < cutoff:
            self.timestamps.clear()
            return
        # remove expired entries (batch pop from left)
        i = 0
        while i < len(self.timestamps) and self.timestamps[i] < cutoff:
            i += 1
        if i > 0:
            del self.timestamps[:i]

    def count(self) -> int:
        now = time.monotonic()
        self.prune(now)
        return len(self.timestamps)

    def hit(self) -> int:
        now = time.monotonic()
        self.prune(now)
        self.timestamps.append(now)
        return len(self.timestamps)


_counters: dict[str, _SlidingWindowCounter] = defaultdict(_SlidingWindowCounter)
_rate_limit = int(os.environ.get("RATE_LIMIT_RPM", str(DEFAULT_RPM)))


def _client_ip(request: web.Request) -> str:
    """Resolve the client IP from the trusted HappyFox reverse proxy.

    Production exposes the backend only on loopback and nginx always overwrites
    X-Real-IP with ``$remote_addr``.  A client-controlled X-Forwarded-For value
    must therefore never win over X-Real-IP, otherwise an attacker can rotate
    the first XFF item and bypass the per-IP limiter.
    """

    real_ip = request.headers.get("X-Real-IP", "").strip()
    if real_ip:
        return real_ip

    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()

    transport = request.transport
    if transport is not None:
        peername = transport.get_extra_info("peername")
        if peername:
            return str(peername[0])
    return str(request.remote or "unknown")


@web.middleware
async def rate_limiter_middleware(
    request: web.Request,
    handler,
) -> web.StreamResponse:
    """Rate-limit incoming HTTP requests per IP using a sliding window.

    Exempts:
    - Health endpoint (GET /health)
    - HMAC-protected internal admin API (it has its own network allowlist)
    - IPs in RATE_LIMIT_WHITELIST
    """
    if request.path.startswith("/internal/admin/"):
        from bot.internal_admin_dispatch import dispatch_internal_admin_request

        return await dispatch_internal_admin_request(request)

    client_ip = _client_ip(request)

    # Exempt health check and whitelisted IPs
    if request.method == "GET" and request.path == "/health":
        return await handler(request)
    if client_ip in _whitelist:
        return await handler(request)

    counter = _counters[client_ip]
    current_count = counter.hit()

    if current_count > _rate_limit:
        logger.warning(
            "Rate limit exceeded for %s: %d requests in %ds window (limit=%d)",
            client_ip,
            current_count,
            WINDOW_SEC,
            _rate_limit,
        )
        return web.json_response(
            {"error": "Too many requests. Please slow down."},
            status=429,
            headers={
                "Retry-After": str(WINDOW_SEC),
                "X-RateLimit-Limit": str(_rate_limit),
            },
        )

    response = await handler(request)
    return response


async def _cleanup_loop() -> None:
    """Periodically evict stale counter entries to prevent memory leak."""
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL)
        now = time.monotonic()
        cutoff = now - WINDOW_SEC * 2  # keep 2 windows for safety
        stale_keys = [
            ip
            for ip, c in _counters.items()
            if c.timestamps and c.timestamps[-1] < cutoff
        ]
        for ip in stale_keys:
            del _counters[ip]
        if stale_keys:
            logger.debug("Rate limiter cleanup: evicted %d stale IPs", len(stale_keys))


def start_cleanup_task() -> None:
    """Start background cleanup asyncio task."""
    loop = asyncio.get_event_loop()
    loop.create_task(_cleanup_loop())
