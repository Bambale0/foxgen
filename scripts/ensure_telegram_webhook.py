from __future__ import annotations

import asyncio
import os
from urllib.parse import urljoin

from aiogram import Bot
from aiogram.types import MenuButtonWebApp, WebAppInfo


def _webhook_url() -> str:
    host = str(os.getenv("WEBHOOK_HOST", "")).strip().rstrip("/")
    path = str(os.getenv("WEBHOOK_PATH", "/webhook")).strip() or "/webhook"
    if not path.startswith("/"):
        path = "/" + path
    if not host.startswith("https://"):
        raise RuntimeError("WEBHOOK_HOST must be an HTTPS origin")
    return urljoin(host + "/", path.lstrip("/"))


async def ensure() -> None:
    token = str(os.getenv("BOT_TOKEN", "")).strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is required")

    target = _webhook_url()
    mini_app_url = str(os.getenv("MINI_APP_URL", "")).strip()
    bot = Bot(token=token)
    try:
        await bot.set_webhook(url=target, drop_pending_updates=False)
        info = await bot.get_webhook_info()
        if str(info.url or "").rstrip("/") != target.rstrip("/"):
            raise RuntimeError(
                f"Telegram webhook mismatch: expected={target} actual={info.url or ''}"
            )
        if info.last_error_message:
            raise RuntimeError(f"Telegram webhook reports error: {info.last_error_message}")

        if mini_app_url.startswith("https://"):
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="Открыть HappyFox",
                    web_app=WebAppInfo(url=mini_app_url),
                )
            )
    finally:
        await bot.session.close()

    print(f"telegram_webhook_ok={target}")


if __name__ == "__main__":
    asyncio.run(ensure())
