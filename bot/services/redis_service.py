import logging
from typing import Optional
from urllib.parse import urlparse

from bot.config import config

logger = logging.getLogger(__name__)

try:
    import redis.asyncio as redis
except Exception:  # pragma: no cover - optional dependency fallback
    redis = None


def _safe_redis_url(value: str) -> str:
    parsed = urlparse(str(value or ""))
    if not parsed.scheme:
        return "[not configured]"
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return f"{parsed.scheme}://{host}{parsed.path or ''}"


class RedisService:
    """Small async Redis wrapper with graceful fallback when Redis is unavailable."""

    def __init__(self):
        self._client = None
        self._is_disabled = False
        self._warned_unavailable = False

    def build_key(self, suffix: str) -> str:
        return f"{config.REDIS_PREFIX}:{suffix}"

    async def get_client(self):
        if self._is_disabled or redis is None:
            if redis is None and not self._warned_unavailable:
                logger.warning("redis package is unavailable, Redis cache disabled")
                self._warned_unavailable = True
            return None

        if self._client is None:
            try:
                self._client = redis.from_url(
                    config.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                    health_check_interval=30,
                )
                await self._client.ping()
                logger.info("Redis connected: %s", _safe_redis_url(config.redis_url))
            except Exception:
                logger.exception("Failed to connect to Redis at %s", _safe_redis_url(config.redis_url))
                self._is_disabled = True
                self._client = None
                return None

        return self._client

    async def get(self, key: str) -> Optional[str]:
        client = await self.get_client()
        if client is None:
            return None
        try:
            value = await client.get(key)
            return value if isinstance(value, str) and value else None
        except Exception:
            logger.exception("Redis GET failed for key=%s", key)
            return None

    async def set(self, key: str, value: str, ttl_seconds: int | None = None) -> bool:
        client = await self.get_client()
        if client is None:
            return False
        try:
            await client.set(key, value, ex=ttl_seconds)
            return True
        except Exception:
            logger.exception("Redis SET failed for key=%s", key)
            return False

    async def delete(self, key: str) -> bool:
        client = await self.get_client()
        if client is None:
            return False
        try:
            await client.delete(key)
            return True
        except Exception:
            logger.exception("Redis DELETE failed for key=%s", key)
            return False

    async def close(self):
        if self._client is None:
            return
        try:
            await self._client.aclose()
        except Exception:
            logger.exception("Failed to close Redis client")
        finally:
            self._client = None


redis_service = RedisService()
