from __future__ import annotations

import asyncio
from typing import Any

_cache: dict[int, Any] = {}
_locks: dict[int, asyncio.Lock] = {}


def _bot_cache_key(bot: Any) -> int:
    bot_id = getattr(bot, "id", None)
    try:
        return int(bot_id) if bot_id is not None else id(bot)
    except (TypeError, ValueError):
        return id(bot)


async def get_bot_me_cached(bot: Any) -> Any:
    """Return Telegram bot identity without repeated Bot API calls."""
    key = _bot_cache_key(bot)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock

    async with lock:
        cached = _cache.get(key)
        if cached is not None:
            return cached
        me = await bot.get_me()
        _cache[key] = me
        return me


async def get_bot_username_cached(bot: Any) -> str:
    me = await get_bot_me_cached(bot)
    return str(getattr(me, "username", "") or "").strip().lstrip("@")


def clear_bot_identity_cache(bot: Any | None = None) -> None:
    if bot is None:
        _cache.clear()
        _locks.clear()
        return
    key = _bot_cache_key(bot)
    _cache.pop(key, None)
    _locks.pop(key, None)
