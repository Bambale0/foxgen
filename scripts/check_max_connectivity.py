from __future__ import annotations

import asyncio
import os

from bot.max_api import MaxClient, MaxSettings
from bot.max_commands import MAX_QUICK_COMMANDS


async def check() -> None:
    settings = MaxSettings.from_env()
    if not settings.enabled:
        raise RuntimeError("MAX must be enabled in HappyFox production")
    settings.validate_enabled()

    client = MaxClient(settings)
    try:
        payload = await client.get_subscriptions()
        bot_info = await client.get_bot_info()
    finally:
        await client.close()

    if not isinstance(payload, dict) or not isinstance(bot_info, dict):
        raise TypeError("MAX API connectivity check returned an invalid payload")
    subscriptions = payload.get("subscriptions")
    if subscriptions is not None and not isinstance(subscriptions, list):
        raise TypeError("MAX subscriptions payload is not a list")

    expected_url = os.getenv("MAX_WEBHOOK_URL", "").strip()
    if not expected_url:
        raise RuntimeError("MAX_WEBHOOK_URL is required for the production check")
    if (
        not isinstance(subscriptions, list)
        or len(subscriptions) != 1
        or not isinstance(subscriptions[0], dict)
        or subscriptions[0].get("url") != expected_url
    ):
        raise RuntimeError("MAX must have exactly one canonical webhook subscription")

    commands = bot_info.get("commands")
    if not isinstance(commands, list):
        raise TypeError("MAX bot info commands payload is not a list")
    actual_commands = [
        (
            str(command.get("name") or "").strip().lstrip("/"),
            str(command.get("description") or "").strip(),
        )
        for command in commands
        if isinstance(command, dict)
    ]
    if actual_commands != list(MAX_QUICK_COMMANDS):
        raise RuntimeError(
            "MAX quick commands drifted from the HappyFox contract: "
            f"{actual_commands!r}"
        )

    print(
        "max_api_ok=1 "
        f"subscriptions={len(subscriptions or [])} commands={len(commands)}"
    )


if __name__ == "__main__":
    asyncio.run(check())
