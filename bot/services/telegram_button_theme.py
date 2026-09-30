from __future__ import annotations

import json
import logging
import os
import time
from functools import lru_cache
from typing import Any, Awaitable, Callable, Mapping

from aiogram import Bot
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.methods import TelegramMethod
from aiogram.methods.base import TelegramType
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

TELEGRAM_MENU_EMOJI_IDS_ENV = "HAPPYFOX_TELEGRAM_MENU_EMOJI_IDS"
TELEGRAM_BUTTON_EMOJI_SETTING_KEY = "telegram_button_emoji_ids"
TELEGRAM_BUTTON_EMOJI_MAX_ENTRIES = 64
TELEGRAM_BUTTON_EMOJI_CACHE_SECONDS = 5.0

TELEGRAM_DANGER_BUTTON_TERMS = (
    "отмена",
    "отменить",
    "удалить",
    "удалить всё",
    "убрать",
    "отклонить",
    "заблокировать",
    "выключить",
    "очистить",
    "сбросить",
)
TELEGRAM_DANGER_CALLBACK_TERMS = (
    "cancel",
    "delete",
    "remove",
    "reject",
    "ban",
    "disable",
    "clear",
    "reset",
)

_persisted_cache_until = 0.0
_persisted_cache_present = False
_persisted_cache: dict[str, str] = {}


@lru_cache(maxsize=8)
def _parse_telegram_emoji_ids(raw: str) -> dict[str, str]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning(
            "telegram_button_custom_emoji_config_invalid",
            extra={"event": "telegram_button_custom_emoji_config_invalid"},
        )
        return {}
    if not isinstance(payload, dict):
        logger.warning(
            "telegram_button_custom_emoji_config_invalid_type",
            extra={"event": "telegram_button_custom_emoji_config_invalid_type"},
        )
        return {}

    result: dict[str, str] = {}
    for key, value in payload.items():
        prefix = str(key or "").strip()
        emoji_id = str(value or "").strip()
        if prefix and len(prefix) <= 32 and emoji_id.isdigit():
            result[prefix] = emoji_id
    return result


def _normalize_telegram_emoji_ids(mapping: Mapping[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in mapping.items():
        prefix = str(key or "").strip()
        emoji_id = str(value or "").strip()
        if prefix and len(prefix) <= 32 and emoji_id.isdigit():
            result[prefix] = emoji_id
    if len(result) > TELEGRAM_BUTTON_EMOJI_MAX_ENTRIES:
        raise ValueError(
            f"Telegram button emoji mapping supports at most "
            f"{TELEGRAM_BUTTON_EMOJI_MAX_ENTRIES} entries"
        )
    return result


def telegram_menu_emoji_ids() -> dict[str, str]:
    """Return the environment fallback for Telegram custom-emoji prefixes."""
    raw = str(os.getenv(TELEGRAM_MENU_EMOJI_IDS_ENV, "")).strip()
    return _parse_telegram_emoji_ids(raw)


def invalidate_telegram_button_emoji_cache() -> None:
    global _persisted_cache_until, _persisted_cache_present, _persisted_cache
    _persisted_cache_until = 0.0
    _persisted_cache_present = False
    _persisted_cache = {}


async def get_configured_telegram_emoji_ids() -> dict[str, str]:
    """Return DB-backed custom-emoji prefixes, falling back to environment.

    Once an admin saves the setting, the database becomes authoritative,
    including an intentionally empty mapping.
    """
    global _persisted_cache_until, _persisted_cache_present, _persisted_cache

    now = time.monotonic()
    if _persisted_cache_until > now:
        if _persisted_cache_present:
            return dict(_persisted_cache)
        return telegram_menu_emoji_ids()

    try:
        from bot.database import get_bot_setting

        raw = await get_bot_setting(TELEGRAM_BUTTON_EMOJI_SETTING_KEY, None)
    except Exception:
        logger.exception(
            "telegram_button_custom_emoji_setting_read_failed",
            extra={"event": "telegram_button_custom_emoji_setting_read_failed"},
        )
        _persisted_cache_until = now + TELEGRAM_BUTTON_EMOJI_CACHE_SECONDS
        _persisted_cache_present = False
        _persisted_cache = {}
        return telegram_menu_emoji_ids()

    _persisted_cache_until = now + TELEGRAM_BUTTON_EMOJI_CACHE_SECONDS
    _persisted_cache_present = raw is not None
    _persisted_cache = _parse_telegram_emoji_ids(str(raw or "")) if raw is not None else {}

    if _persisted_cache_present:
        return dict(_persisted_cache)
    return telegram_menu_emoji_ids()


async def set_configured_telegram_emoji_ids(
    mapping: Mapping[str, Any],
    *,
    updated_by_telegram_id: int,
) -> dict[str, str]:
    """Persist the authoritative Telegram custom-emoji prefix mapping."""
    clean = _normalize_telegram_emoji_ids(mapping)
    payload = json.dumps(clean, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    from bot.database import set_bot_setting

    saved = await set_bot_setting(
        TELEGRAM_BUTTON_EMOJI_SETTING_KEY,
        payload,
        updated_by_telegram_id=updated_by_telegram_id,
    )
    if not saved:
        raise RuntimeError("Failed to persist Telegram button emoji mapping")

    global _persisted_cache_until, _persisted_cache_present, _persisted_cache
    _persisted_cache_until = time.monotonic() + TELEGRAM_BUTTON_EMOJI_CACHE_SECONDS
    _persisted_cache_present = True
    _persisted_cache = dict(clean)
    return clean


def style_telegram_markup(
    markup: InlineKeyboardMarkup,
    *,
    emoji_ids: Mapping[str, str] | None = None,
) -> InlineKeyboardMarkup:
    """Apply native Telegram colors and configured custom-emoji icons.

    Regular navigation/actions are green. Explicitly destructive/cancel actions
    are red. Existing explicit styles/icons are preserved. Custom emoji are
    configured by literal Unicode prefix, for example {"🏠": "123..."}.
    """
    configured = (
        _normalize_telegram_emoji_ids(emoji_ids)
        if emoji_ids is not None
        else telegram_menu_emoji_ids()
    )
    emoji_prefixes = sorted(
        (
            (prefix, emoji_id)
            for prefix, emoji_id in configured.items()
            if prefix and not prefix.isascii()
        ),
        key=lambda item: len(item[0]),
        reverse=True,
    )

    rows: list[list[InlineKeyboardButton]] = []
    changed = False
    for row in markup.inline_keyboard:
        styled_row: list[InlineKeyboardButton] = []
        for button in row:
            text = str(button.text or "")
            callback_data = str(button.callback_data or "")
            updates: dict[str, Any] = {}

            if not button.style:
                normalized_text = text.casefold()
                normalized_callback = callback_data.casefold()
                is_danger = any(
                    term in normalized_text for term in TELEGRAM_DANGER_BUTTON_TERMS
                ) or any(
                    term in normalized_callback
                    for term in TELEGRAM_DANGER_CALLBACK_TERMS
                )
                updates["style"] = "danger" if is_danger else "success"

            if not button.icon_custom_emoji_id:
                for prefix, emoji_id in emoji_prefixes:
                    if text.startswith(f"{prefix} "):
                        remainder = text[len(prefix) :].lstrip()
                        if remainder:
                            updates["text"] = remainder
                            updates["icon_custom_emoji_id"] = emoji_id
                        break

            if updates:
                changed = True
                styled_row.append(button.model_copy(update=updates))
            else:
                styled_row.append(button)
        rows.append(styled_row)

    if not changed:
        return markup
    return InlineKeyboardMarkup(inline_keyboard=rows)


class TelegramButtonThemeMiddleware(BaseRequestMiddleware):
    async def __call__(
        self,
        make_request: Callable[[Bot, TelegramMethod[TelegramType]], Awaitable[Any]],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Any:
        reply_markup = getattr(method, "reply_markup", None)
        if isinstance(reply_markup, InlineKeyboardMarkup):
            emoji_ids = await get_configured_telegram_emoji_ids()
            themed = style_telegram_markup(reply_markup, emoji_ids=emoji_ids)
            if themed is not reply_markup:
                method = method.model_copy(update={"reply_markup": themed})
        return await make_request(bot, method)


def install_telegram_button_theme(bot: Bot) -> None:
    bot.session.middleware(TelegramButtonThemeMiddleware())
