from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _entity_custom_emoji_id(entity: Any) -> str | None:
    entity_type = getattr(entity, "type", None)
    type_value = getattr(entity_type, "value", entity_type)
    if str(type_value or "") != "custom_emoji":
        return None
    emoji_id = str(getattr(entity, "custom_emoji_id", "") or "").strip()
    return emoji_id if emoji_id.isdigit() else None


def _walk_rich_message(value: Any):
    if value is None:
        return

    if hasattr(value, "model_dump"):
        try:
            value = value.model_dump(mode="python")
        except TypeError:
            value = value.model_dump()

    if isinstance(value, Mapping):
        type_value = value.get("type")
        if type_value == "custom_emoji":
            emoji_id = str(value.get("custom_emoji_id") or "").strip()
            if emoji_id.isdigit():
                yield emoji_id
        for child in value.values():
            yield from _walk_rich_message(child)
        return

    if isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk_rich_message(child)


def extract_custom_emoji_ids(message: Any) -> list[str]:
    """Extract Telegram custom-emoji document IDs from a message or its reply."""
    seen: set[str] = set()
    result: list[str] = []

    def add(emoji_id: str | None) -> None:
        if emoji_id and emoji_id not in seen:
            seen.add(emoji_id)
            result.append(emoji_id)

    for candidate in (message, getattr(message, "reply_to_message", None)):
        if candidate is None:
            continue

        for attr_name in ("entities", "caption_entities"):
            for entity in getattr(candidate, attr_name, None) or ():
                add(_entity_custom_emoji_id(entity))

        for emoji_id in _walk_rich_message(getattr(candidate, "rich_message", None)):
            add(emoji_id)

    return result
