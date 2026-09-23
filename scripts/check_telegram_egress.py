from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

# The production deploy executes files in this directory inside the runtime
# image (/app/scripts), where Python puts /app/scripts on sys.path instead of
# the repository root. Make the project package importable explicitly.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from bot.config import config  # noqa: E402

# Outbound Bot API traffic on the dedicated host is carried by
# happyfox-telegram-egress.service, and the silent failure mode is a hung
# request: the webhook route stays healthy while every reply times out. A
# bounded timeout turns that into a loud deploy failure instead of a silent one.
EGRESS_TIMEOUT_SECONDS = 20


async def check() -> None:
    token = str(getattr(config, "BOT_TOKEN", "") or "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is required for the Telegram egress check")

    session = AiohttpSession(timeout=EGRESS_TIMEOUT_SECONDS)
    bot = Bot(
        token=token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    started = time.perf_counter()
    try:
        me = await bot.get_me()
    finally:
        await bot.session.close()
    duration_ms = round((time.perf_counter() - started) * 1000, 1)

    if not getattr(me, "id", None):
        raise RuntimeError("Telegram getMe returned an invalid payload")

    print(
        "telegram_egress_ok=1 "
        f"method=getMe bot_id={me.id} "
        f"username={me.username or '-'} duration_ms={duration_ms}"
    )


def main() -> None:
    asyncio.run(check())


if __name__ == "__main__":
    main()
