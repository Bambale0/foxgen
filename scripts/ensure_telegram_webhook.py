from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import os
import sys
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import MenuButtonDefault, MenuButtonWebApp, WebAppInfo

# The production deploy executes this file directly as
# /app/scripts/ensure_telegram_webhook.py. In that mode Python puts /app/scripts
# on sys.path, not the repository root, so make the project package importable
# explicitly before importing bot.*.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from bot import db as db_backend  # noqa: E402
from bot.config import config  # noqa: E402


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


def _mini_app_url_with_release() -> str:
    base_url = str(config.mini_app_url or "").strip()
    if not base_url:
        return ""
    parts = urlsplit(base_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    release = str(os.getenv("HAPPYFOX_RELEASE", "")).strip()
    if release and release.lower() not in {"unknown", "local"}:
        query["release"] = release
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _normalise_allowed_updates(values) -> tuple[str, ...]:
    if not values:
        return ()
    result: set[str] = set()
    for value in values:
        raw = getattr(value, "value", value)
        text = str(raw or "").strip()
        if text:
            result.add(text)
    return tuple(sorted(result))


async def _resolve_allowed_updates() -> list[str]:
    """Resolve the exact update types from the production dispatcher wiring."""
    from bot.main import setup_dispatcher

    dispatcher = setup_dispatcher()
    try:
        return list(dispatcher.resolve_used_update_types())
    finally:
        await dispatcher.storage.close()


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


async def _reconcile_miniapp_menu(bot: Bot) -> dict[str, int]:
    """Set the default menu to Mini App and clear stale per-chat overrides."""
    mini_app_url = _mini_app_url_with_release()
    if not mini_app_url:
        raise RuntimeError("Telegram Mini App URL is unavailable")
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(text="🚀 Mini App", web_app=WebAppInfo(url=mini_app_url))
    )

    checked = 0
    reset = 0
    skipped = 0
    for chat_id in await _telegram_user_ids():
        checked += 1
        try:
            current = await bot.get_chat_menu_button(chat_id=chat_id)
            if str(getattr(current, "type", "")) == "default":
                continue
            await bot.set_chat_menu_button(
                chat_id=chat_id,
                menu_button=MenuButtonDefault(),
            )
            reset += 1
        except (TelegramBadRequest, TelegramForbiddenError):
            # Historical users may have deleted the chat or blocked the bot.
            # That must not make a production deploy fail.
            skipped += 1

    return {"checked": checked, "reset": reset, "skipped": skipped}


async def ensure(
    *,
    repair: bool = True,
    require_empty_queue: bool = False,
) -> None:
    token = str(os.getenv("BOT_TOKEN", "")).strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is required")

    target = _webhook_url()
    secret = _webhook_secret()
    fixed_ip = str(os.getenv("TELEGRAM_WEBHOOK_IP_ADDRESS", "")).strip()
    allowed_updates = await _resolve_allowed_updates()
    started_at = int(time.time())
    bot = Bot(token=token)
    menu_result: dict[str, int] | None = None
    try:
        if repair:
            kwargs: dict[str, object] = {
                "url": target,
                "drop_pending_updates": False,
                "allowed_updates": allowed_updates,
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

        actual_updates = _normalise_allowed_updates(info.allowed_updates)
        expected_updates = _normalise_allowed_updates(allowed_updates)
        if actual_updates != expected_updates:
            raise RuntimeError(
                "Telegram allowed_updates mismatch: "
                f"expected={','.join(expected_updates)} "
                f"actual={','.join(actual_updates)}"
            )

        pending = int(info.pending_update_count or 0)
        if require_empty_queue and pending != 0:
            raise RuntimeError(
                f"Telegram webhook queue is not empty: pending_update_count={pending}"
            )

        error_date = int(info.last_error_date.timestamp()) if info.last_error_date else 0
        if info.last_error_message and error_date >= started_at:
            raise RuntimeError(f"Telegram webhook reports new error: {info.last_error_message}")

        if repair:
            # Telegram can retain stale per-chat menu overrides even after the
            # default button is updated. Reconcile both levels.
            menu_result = await _reconcile_miniapp_menu(bot)
    finally:
        await bot.session.close()

    mode = "repair" if repair else "check"
    print(
        f"telegram_webhook_{mode}_ok={target} "
        f"allowed_updates={','.join(_normalise_allowed_updates(allowed_updates))}"
    )
    if menu_result is not None:
        print(
            "telegram_miniapp_menu_ok="
            f"checked:{menu_result['checked']},"
            f"reset:{menu_result['reset']},"
            f"skipped:{menu_result['skipped']}"
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reconcile or verify the HappyFox Telegram webhook registration."
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Verify live registration without mutating Telegram state.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(
        ensure(
            repair=not args.check_only,
            require_empty_queue=args.check_only,
        )
    )
