from __future__ import annotations

import asyncio

from bot.max_api import MaxClient, MaxSettings


async def check() -> None:
    settings = MaxSettings.from_env()
    if not settings.enabled:
        raise RuntimeError("MAX must be enabled in HappyFox production")
    settings.validate_enabled()

    client = MaxClient(settings)
    try:
        payload = await client.get_subscriptions()
    finally:
        await client.close()

    if not isinstance(payload, dict):
        raise RuntimeError("MAX API connectivity check returned an invalid payload")
    subscriptions = payload.get("subscriptions")
    if subscriptions is not None and not isinstance(subscriptions, list):
        raise RuntimeError("MAX subscriptions payload is not a list")

    print(f"max_api_ok=1 subscriptions={len(subscriptions or [])}")


if __name__ == "__main__":
    asyncio.run(check())
