"""Normalize incoming Bot API rich messages into plain prompt text.

Telegram clients deliver rich formatted content (for example, formatted text
pasted from a web page) as ``Message.rich_message``. Such an update carries no
``text``, no ``caption`` and no ``entities``: everything lives in
``rich_message.blocks``. Prompt and menu handlers in this project are ``F.text``
based, so an unnormalized rich message is silently dropped - the user gets no
reply and no generation task is created.

The middleware below runs once per update, before any router, extracts plain
text from the rich blocks and writes it back into ``Message.text`` so every
existing handler keeps working. Raw ``rich_message`` is intentionally preserved
for incident forensics and each normalization is logged with stable identifiers.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.enums import RichBlockType
from aiogram.types import Update

logger = logging.getLogger("bot.telemetry.telegram")

RELEASE = str(os.getenv("HAPPYFOX_RELEASE", "unknown")).strip() or "unknown"

_MESSAGE_FIELDS = (
    "message",
    "edited_message",
    "channel_post",
    "edited_channel_post",
    "business_message",
    "edited_business_message",
    "guest_message",
)

# Rich block kinds come from the aiogram enum so a Bot API rename fails the
# contract tests loudly instead of silently dropping prompts again.
_DIVIDER_KIND = RichBlockType.DIVIDER.value
# Blocks whose plain text is carried by ``text``.
_TEXT_BLOCKS = frozenset(
    kind.value
    for kind in (
        RichBlockType.PARAGRAPH,
        RichBlockType.HEADING,
        RichBlockType.PRE,
        RichBlockType.FOOTER,
        RichBlockType.THINKING,
    )
)
# Quotation blocks carry ``text`` plus an optional ``credit``.
_QUOTE_BLOCKS = frozenset(
    kind.value
    for kind in (RichBlockType.PULLQUOTE, RichBlockType.EXPANDABLE_BLOCKQUOTE)
)
_MATH_KIND = RichBlockType.MATHEMATICAL_EXPRESSION.value
_LIST_KIND = RichBlockType.LIST.value
_TABLE_KIND = RichBlockType.TABLE.value
_DETAILS_KIND = RichBlockType.DETAILS.value
_BLOCKQUOTE_KIND = RichBlockType.BLOCKQUOTE.value
# Blocks that only nest other blocks and may add a caption.
_COLLECTION_BLOCKS = frozenset(
    kind.value for kind in (RichBlockType.COLLAGE, RichBlockType.SLIDESHOW)
)


def _block_kind(block: Any) -> str:
    """Return the normalized rich block type value."""
    kind = _field(block, "type")
    if kind is None:
        return ""
    return str(getattr(kind, "value", kind))


def _field(value: Any, name: str, default: Any = None) -> Any:
    """Read one field from an aiogram model or from a raw mapping."""
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _plain(value: Any) -> str:
    """Flatten a RichText union member into plain text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    text = _field(value, "text")
    if text is not None:
        return _plain(text)
    for key in ("alternative_text", "expression", "name"):
        nested = _field(value, key)
        if nested:
            return str(nested)
    return ""


def _join(parts: Any) -> str:
    cleaned = [part.strip() for part in parts if isinstance(part, str) and part.strip()]
    return "\n".join(cleaned)


def extract_rich_message_text(rich_message: Any) -> str:
    """Return the plain text of a ``RichMessage`` payload."""
    return blocks_text(_field(rich_message, "blocks") or ())


def blocks_text(blocks: Any) -> str:
    """Return plain text for a list of rich blocks, joined by newlines."""
    if not blocks:
        return ""
    return _join(block_text(block) for block in blocks)


def rich_message_block_types(rich_message: Any) -> tuple[str, ...]:
    """Return the block type names of a ``RichMessage`` for safe logging."""
    blocks = _field(rich_message, "blocks") or ()
    kinds: list[str] = []
    for block in blocks:
        kind = _block_kind(block)
        kinds.append(kind or type(block).__name__)
    return tuple(kinds)


def _credit_text(block: Any) -> str:
    credit = _plain(_field(block, "credit"))
    return f"— {credit.strip()}" if credit.strip() else ""


def block_text(block: Any) -> str:
    """Return plain text for one rich block."""
    kind = _block_kind(block)
    if kind == _DIVIDER_KIND:
        return ""
    if kind in _TEXT_BLOCKS:
        return _plain(_field(block, "text"))
    if kind in _QUOTE_BLOCKS:
        return _join([_plain(_field(block, "text")), _credit_text(block)])
    if kind == _MATH_KIND:
        return _plain(_field(block, "expression"))
    if kind == _LIST_KIND:
        items: list[str] = []
        for item in _field(block, "items") or ():
            label = str(_field(item, "label", "") or "").strip()
            body = blocks_text(_field(item, "blocks"))
            items.append(f"{label} {body}".strip())
        return _join(items)
    if kind == _TABLE_KIND:
        rows: list[str] = []
        for row in _field(block, "cells") or ():
            cells = [_plain(_field(cell, "text")).strip() for cell in row]
            rows.append(" | ".join(cell for cell in cells if cell))
        return _join(rows)
    if kind == _DETAILS_KIND:
        return _join(
            [_plain(_field(block, "summary")), blocks_text(_field(block, "blocks"))]
        )
    if kind == _BLOCKQUOTE_KIND:
        return _join([blocks_text(_field(block, "blocks")), _credit_text(block)])
    if kind in _COLLECTION_BLOCKS:
        return _join(
            [blocks_text(_field(block, "blocks")), _plain(_field(block, "caption"))]
        )
    # Media blocks and any future block type: keep the caption if there is one.
    return _plain(_field(block, "caption"))


class RichMessageNormalizerMiddleware(BaseMiddleware):
    """Restore ``Message.text`` for rich messages before routing runs."""

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Update):
            message = _first_message(event)
            if (
                message is not None
                and not _field(message, "text")
                and _field(message, "rich_message") is not None
            ):
                self._normalize(event, message)
        return await handler(event, data)

    @staticmethod
    def _normalize(update: Update, message: Any) -> None:
        rich_message = _field(message, "rich_message")
        kinds = ",".join(rich_message_block_types(rich_message)) or "-"
        try:
            text = extract_rich_message_text(rich_message)
        except Exception:
            logger.exception(
                "telegram_rich_message_normalization_failed update_id=%s "
                "blocks=%s release=%s",
                update.update_id,
                kinds,
                RELEASE,
            )
            return
        if not text:
            logger.warning(
                "telegram_rich_message_without_text update_id=%s blocks=%s release=%s",
                update.update_id,
                kinds,
                RELEASE,
            )
            return
        object.__setattr__(message, "text", text)
        logger.info(
            "telegram_rich_message_normalized update_id=%s chars=%s blocks=%s release=%s",
            update.update_id,
            len(text),
            kinds,
            RELEASE,
        )


def _first_message(update: Update) -> Any:
    for name in _MESSAGE_FIELDS:
        message = getattr(update, name, None)
        if message is not None:
            return message
    return None
