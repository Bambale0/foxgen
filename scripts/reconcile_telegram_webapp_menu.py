from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import MenuButtonWebApp, WebAppInfo

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from bot import db as db_backend  # noqa: E402
from bot.config import config  # noqa: E402
from bot.keyboards import _mini_app_url_with_start_param  # noqa: E402


async def _telegram_user_ids() -> list[int]:
    async with db_backend.connect() as db:
        cursor = await db.execute(
            "SELECT DISTINCT telegram_id FROM users WHERE telegram_id IS NOT NULL"
        )
        rows = await cursor.fetchall()

    user_ids: list[int] = []
    for row in rows:
        try:
            telegram_id = int(row[0])
        except (TypeError, ValueError, IndexError):
            continue
        if telegram_id > 0:
            user_ids.append(telegram_id)
    return user_ids


def _menu_button(launch_url: str) -> MenuButtonWebApp:
    return MenuButtonWebApp(
        text="Открыть HappyFox",
        web_app=WebAppInfo(url=launch_url),
    )


async def reconcile() -> dict[str, int]:
    launch_url = _mini_app_url_with_start_param()
    if not launch_url:
        raise RuntimeError("HappyFox Mini App URL is unavailable")
    if not config.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is required")

    bot = Bot(token=config.BOT_TOKEN)
    checked = 0
    reset = 0
    skipped = 0
    try:
        await bot.set_chat_menu_button(menu_button=_menu_button(launch_url))
        for chat_id in await _telegram_user_ids():
            checked += 1
            try:
                current = await bot.get_chat_menu_button(chat_id=chat_id)
                current_web_app = getattr(current, "web_app", None)
                current_url = str(getattr(current_web_app, "url", "") or "")
                if (
                    str(getattr(current, "type", "")) == "web_app"
                    and current_url == launch_url
                ):
                    continue
                await bot.set_chat_menu_button(
                    chat_id=chat_id,
                    menu_button=_menu_button(launch_url),
                )
                reset += 1
            except (TelegramBadRequest, TelegramForbiddenError):
                skipped += 1
    finally:
        await bot.session.close()

    result = {"checked": checked, "reset": reset, "skipped": skipped}
    print(
        "telegram_webapp_menu_ok="
        f"checked:{checked},reset:{reset},skipped:{skipped}"
    )
    return result


if __name__ == "__main__":
    asyncio.run(reconcile())
