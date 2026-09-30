from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from typing import Any, Awaitable, Callable

from aiogram import Bot, types
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.methods import TelegramMethod
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.types.base import TelegramType

logger = logging.getLogger(__name__)

TELEGRAM_MENU_EMOJI_IDS_ENV = "HAPPYFOX_TELEGRAM_MENU_EMOJI_IDS"
TELEGRAM_DANGER_BUTTON_TERMS = (
    "отмена",
    "отменить",
    "удалить",
    "удалить всё",
    "убрать",
    "отклонить",
    "заблокировать",
    "выключить",
)


@lru_cache(maxsize=8)
def _parse_telegram_menu_emoji_ids(raw: str) -> dict[str, str]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning(
            "telegram_menu_custom_emoji_config_invalid",
            extra={"event": "telegram_menu_custom_emoji_config_invalid"},
        )
        return {}
    if not isinstance(payload, dict):
        logger.warning(
            "telegram_menu_custom_emoji_config_invalid_type",
            extra={"event": "telegram_menu_custom_emoji_config_invalid_type"},
        )
        return {}

    result: dict[str, str] = {}
    for key, value in payload.items():
        emoji_id = str(value or "").strip()
        if emoji_id.isdigit():
            result[str(key)] = emoji_id
    return result


def telegram_menu_emoji_ids() -> dict[str, str]:
    raw = str(os.getenv(TELEGRAM_MENU_EMOJI_IDS_ENV, "")).strip()
    return _parse_telegram_menu_emoji_ids(raw)


def style_telegram_markup(markup: InlineKeyboardMarkup) -> InlineKeyboardMarkup:
    """Apply native Telegram colors and configured custom-emoji icons.

    Regular navigation/actions are green. Explicitly destructive/cancel actions
    are red. Existing styles/icons are preserved. A configured non-ASCII key is
    treated as a literal Unicode prefix, for example {"🏠": "123..."}.
    """
    emoji_ids = telegram_menu_emoji_ids()
    emoji_prefixes = sorted(
        (
            (prefix, emoji_id)
            for prefix, emoji_id in emoji_ids.items()
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
            updates: dict[str, Any] = {}

            if not button.style:
                normalized = text.casefold()
                updates["style"] = (
                    "danger"
                    if any(term in normalized for term in TELEGRAM_DANGER_BUTTON_TERMS)
                    else "success"
                )

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
            themed = style_telegram_markup(reply_markup)
            if themed is not reply_markup:
                method = method.model_copy(update={"reply_markup": themed})
        return await make_request(bot, method)


def install_telegram_button_theme(bot: Bot) -> None:
    bot.session.middleware(TelegramButtonThemeMiddleware())
