from __future__ import annotations

import asyncio
from functools import wraps
from typing import Any

_CACHE_STATE_ATTR = "_happyfox_bot_identity_cache_state"
_INSTALLED_ATTR = "_happyfox_bot_identity_cache_installed"


def install_bot_identity_cache(bot: Any) -> None:
    """Cache Bot.get_me() on one long-lived bot instance."""
    if bool(getattr(bot, _INSTALLED_ATTR, False)):
        return

    original_get_me = bot.get_me
    lock = asyncio.Lock()
    state: dict[str, Any] = {"value": None}

    @wraps(original_get_me)
    async def cached_get_me(*args: Any, **kwargs: Any) -> Any:
        cached = state["value"]
        if cached is not None:
            return cached

        async with lock:
            cached = state["value"]
            if cached is not None:
                return cached
            identity = await original_get_me(*args, **kwargs)
            state["value"] = identity
            return identity

    bot.get_me = cached_get_me
    setattr(bot, _CACHE_STATE_ATTR, state)
    setattr(bot, _INSTALLED_ATTR, True)


def clear_bot_identity_cache(bot: Any) -> None:
    state = getattr(bot, _CACHE_STATE_ATTR, None)
    if isinstance(state, dict):
        state["value"] = None
