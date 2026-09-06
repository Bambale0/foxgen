from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import time
from urllib.parse import urljoin

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import MenuButtonCommands

from bot import db as db_backend


def _webhook_url() -> str:
    override = str(os.getenv("TELEGRAM_WEBHOOK_URL", "")).strip()
    if override:
        if not override.startswith("https://"):
            raise RuntimeError("TELEGRAM_WEBHOOK_URL must be an HTTPS URL")
        return override

    host = str(os.getenv("WEBHOOK_HOST", "")).strip().rstrip("/")
    path = str(os.getenv("WEBHOOK_PATH", "/webhook")).strip() or "/webhook"
    if not path.startswith("/"):
        path = "/" + path
    if not host.startswith("https://"):
        raise RuntimeError("WEBHOOK_HOST must be an HTTPS origin")
    return urljoin(host + "/", path.lstrip("/"))


def _webhook_secret() -> str:
    explicit = str(os.getenv("WEBHOOK_SECRET_TOKEN", "")).strip()
    if explicit:
        return explicit
    internal = str(os.getenv("INTERNAL_API_SECRET", "")).strip()
    if not internal:
        return ""
    return hmac.new(
        internal.encode("utf-8"),
        b"happyfox:telegram-webhook:v1",
        hashlib.sha256,
    ).hexdigest()


async def _telegram_user_ids() -> list[int]:
    """Return known Telegram private-chat ids from the HappyFox user table."""
    async with db_backend.connect() as db:
        cursor = await db.execute(
            "SELECT DISTINCT telegram_id FROM users WHERE telegram_id IS NOT NULL"
        )
        rows = await cursor.fetchall()

    result: list[int] = []
    for row in rows:
        try:
            telegram_id = int(row[0])
        except (TypeError, ValueError, IndexError):
            continue
        if telegram_id > 0:
            result.append(telegram_id)
    return result


async def _reconcile_command_menu(bot: Bot) -> dict[str, int]:
    """Clear stale per-chat WebApp overrides and keep native quick commands."""
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())

    checked = 0
    reset = 0
    skipped = 0
    for chat_id in await _telegram_user_ids():
        checked += 1
        try:
            current = await bot.get_chat_menu_button(chat_id=chat_id)
            if str(getattr(current, "type", "")) == "commands":
                continue
            await bot.set_chat_menu_button(
                chat_id=chat_id,
                menu_button=MenuButtonCommands(),
            )
            reset += 1
        except (TelegramBadRequest, TelegramForbiddenError):
            # Historical users may have deleted the chat or blocked the bot.
            # That must not make a production deploy fail.
            skipped += 1

    return {"checked": checked, "reset": reset, "skipped": skipped}


async def ensure() -> None:
    token = str(os.getenv("BOT_TOKEN", "")).strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is required")

    target = _webhook_url()
    secret = _webhook_secret()
    fixed_ip = str(os.getenv("TELEGRAM_WEBHOOK_IP_ADDRESS", "")).strip()
    started_at = int(time.time())
    bot = Bot(token=token)
    menu_result: dict[str, int] | None = None
    try:
        kwargs: dict[str, object] = {
            "url": target,
            "drop_pending_updates": False,
        }
        if secret:
            kwargs["secret_token"] = secret
        if fixed_ip:
            kwargs["ip_address"] = fixed_ip
        await bot.set_webhook(**kwargs)

        info = await bot.get_webhook_info()
        if str(info.url or "").rstrip("/") != target.rstrip("/"):
            raise RuntimeError(
                f"Telegram webhook mismatch: expected={target} actual={info.url or ''}"
            )
        if fixed_ip and str(info.ip_address or "") != fixed_ip:
            raise RuntimeError(
                f"Telegram webhook IP mismatch: expected={fixed_ip} actual={info.ip_address or ''}"
            )
        error_date = int(info.last_error_date.timestamp()) if info.last_error_date else 0
        if info.last_error_message and error_date >= started_at:
            raise RuntimeError(f"Telegram webhook reports new error: {info.last_error_message}")

        # Telegram can retain a per-chat WebApp menu override even after the
        # default button is returned to commands. Reconcile both levels.
        menu_result = await _reconcile_command_menu(bot)
    finally:
        await bot.session.close()

    print(f"telegram_webhook_ok={target}")
    if menu_result is not None:
        print(
            "telegram_command_menu_ok="
            f"checked:{menu_result['checked']},"
            f"reset:{menu_result['reset']},"
            f"skipped:{menu_result['skipped']}"
        )


if __name__ == "__main__":
    asyncio.run(ensure())
