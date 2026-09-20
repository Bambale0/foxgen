"""Contract tests for Bot API rich_message prompt normalization.

Telegram clients send rich formatted content as ``Message.rich_message`` without
``text``/``caption``/``entities``. Prompt handlers are ``F.text`` based, so an
unnormalized rich message is silently dropped (no handler, no reply, no task).
These tests pin the normalization seam that restores prompt delivery.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram.types import Update

from bot.services import telegram_rich_message as rich

ADMIN_USER_ID = 962098909


def _update(**message_fields) -> Update:
    payload = {
        "update_id": 944770145,
        "message": {
            "message_id": 7001,
            "date": 1_789_915_044,
            "chat": {"id": ADMIN_USER_ID, "type": "private", "first_name": "Admin"},
            "from": {"id": ADMIN_USER_ID, "is_bot": False, "first_name": "Admin"},
            **message_fields,
        },
    }
    return Update.model_validate(payload)


def _photo_size() -> list[dict]:
    return [{"file_id": "file", "file_unique_id": "unique", "width": 10, "height": 10}]


def test_reported_rich_prompt_payload_is_extracted() -> None:
    update = _update(
        rich_message={
            "blocks": [
                {"type": "paragraph", "text": "Сделай постер"},
                {
                    "type": "paragraph",
                    "text": {"type": "bold", "text": "с неоновым котом"},
                },
                {
                    "type": "list",
                    "items": [
                        {
                            "label": "•",
                            "blocks": [{"type": "paragraph", "text": "первый"}],
                        },
                        {
                            "label": "•",
                            "blocks": [{"type": "paragraph", "text": "второй"}],
                        },
                    ],
                },
            ]
        }
    )

    message = update.message

    assert message.text is None
    assert message.rich_message is not None
    assert rich.extract_rich_message_text(message.rich_message) == (
        "Сделай постер\nс неоновым котом\n• первый\n• второй"
    )


def test_nested_rich_text_leaves_are_extracted() -> None:
    rich_message = _update(
        rich_message={
            "blocks": [
                {
                    "type": "paragraph",
                    "text": {
                        "type": "italic",
                        "text": {"type": "code", "text": "стиль"},
                    },
                },
                {
                    "type": "paragraph",
                    "text": {
                        "type": "url",
                        "text": "ссылка",
                        "url": "https://example.com",
                    },
                },
                {
                    "type": "paragraph",
                    "text": {
                        "type": "custom_emoji",
                        "custom_emoji_id": "5368324170671202286",
                        "alternative_text": "🦊",
                    },
                },
                {"type": "mathematical_expression", "expression": "E=mc^2"},
                {"type": "pre", "text": "print(1)", "language": "python"},
            ]
        }
    ).message.rich_message

    assert rich.extract_rich_message_text(rich_message) == (
        "стиль\nссылка\n🦊\nE=mc^2\nprint(1)"
    )


def test_container_blocks_lists_tables_and_details_are_extracted() -> None:
    rich_message = _update(
        rich_message={
            "blocks": [
                {
                    "type": "table",
                    "cells": [
                        [
                            {"text": "модель", "align": "left", "valign": "middle"},
                            {"text": "цена", "align": "left", "valign": "middle"},
                        ],
                        [
                            {"text": "banana_pro", "align": "left", "valign": "middle"},
                            {"text": "10", "align": "left", "valign": "middle"},
                        ],
                    ],
                },
                {
                    "type": "details",
                    "summary": "детали",
                    "blocks": [{"type": "paragraph", "text": "внутри"}],
                },
                {
                    "type": "blockquote",
                    "blocks": [{"type": "paragraph", "text": "цитата"}],
                    "credit": "автор",
                },
                {"type": "divider"},
                {"type": "thinking", "text": "размышление"},
            ]
        }
    ).message.rich_message

    assert rich.extract_rich_message_text(rich_message) == (
        "модель | цена\nbanana_pro | 10\nдетали\nвнутри\nцитата\n— автор\nразмышление"
    )


def test_media_only_rich_message_has_no_prompt_text() -> None:
    message = _update(
        rich_message={"blocks": [{"type": "photo", "photo": _photo_size()}]}
    ).message

    assert rich.extract_rich_message_text(message.rich_message) == ""
    assert "photo" in rich.rich_message_block_types(message.rich_message)


def test_media_caption_is_used_as_text() -> None:
    message = _update(
        rich_message={
            "blocks": [
                {
                    "type": "photo",
                    "photo": _photo_size(),
                    "caption": {"text": "подпись"},
                }
            ]
        }
    ).message

    assert rich.extract_rich_message_text(message.rich_message) == "подпись"


def test_normalizer_fills_text_so_prompt_handlers_match(caplog) -> None:
    async def scenario() -> None:
        update = _update(
            rich_message={"blocks": [{"type": "paragraph", "text": "промпт кота"}]}
        )
        seen: dict[str, object] = {}

        async def handler(event, data):
            seen["text"] = event.message.text
            seen["data"] = data
            return "handled"

        with caplog.at_level(logging.INFO, logger="bot.telemetry.telegram"):
            result = await rich.RichMessageNormalizerMiddleware()(handler, update, {})

        assert result == "handled"
        assert seen["data"] == {}
        assert seen["text"] == "промпт кота"
        assert update.message.text == "промпт кота"
        assert update.message.content_type == "text"
        # Raw blocks stay available for incident forensics.
        assert update.message.rich_message is not None
        assert any(
            "telegram_rich_message_normalized" in record.message
            and f"update_id={update.update_id}" in record.message
            for record in caplog.records
        )

    asyncio.run(scenario())


def test_normalizer_keeps_plain_text_untouched(caplog) -> None:
    async def scenario() -> None:
        update = _update(text="обычный промпт")

        async def handler(event, data):
            return event.message.text

        with caplog.at_level(logging.INFO, logger="bot.telemetry.telegram"):
            result = await rich.RichMessageNormalizerMiddleware()(handler, update, {})

        assert result == "обычный промпт"
        assert not any(
            "telegram_rich_message" in record.message for record in caplog.records
        )

    asyncio.run(scenario())


def test_normalizer_logs_media_only_rich_message_without_text(caplog) -> None:
    async def scenario() -> None:
        update = _update(
            rich_message={"blocks": [{"type": "photo", "photo": _photo_size()}]}
        )

        async def handler(event, data):
            return event.message.text

        with caplog.at_level(logging.WARNING, logger="bot.telemetry.telegram"):
            result = await rich.RichMessageNormalizerMiddleware()(handler, update, {})

        assert result is None
        assert update.message.text is None
        assert any(
            "telegram_rich_message_without_text" in record.message
            for record in caplog.records
        )

    asyncio.run(scenario())


def test_normalizer_never_breaks_update_on_extraction_failure(
    caplog, monkeypatch
) -> None:
    def boom(_rich_message):
        raise ValueError("unexpected shape")

    monkeypatch.setattr(rich, "extract_rich_message_text", boom)

    async def scenario() -> None:
        update = _update(
            rich_message={"blocks": [{"type": "paragraph", "text": "промпт"}]}
        )

        async def handler(event, data):
            return "still handled"

        with caplog.at_level(logging.ERROR, logger="bot.telemetry.telegram"):
            result = await rich.RichMessageNormalizerMiddleware()(handler, update, {})

        assert result == "still handled"
        assert any(
            "telegram_rich_message_normalization_failed" in record.message
            for record in caplog.records
        )

    asyncio.run(scenario())


def test_normalizer_passes_non_message_updates_through() -> None:
    async def scenario() -> None:
        update = Update.model_validate(
            {
                "update_id": 944770146,
                "callback_query": {
                    "id": "cb",
                    "from": {
                        "id": ADMIN_USER_ID,
                        "is_bot": False,
                        "first_name": "Admin",
                    },
                    "chat_instance": "ci",
                    "data": "create_image_text_new",
                },
            }
        )

        async def handler(event, data):
            return "callback handled"

        result = await rich.RichMessageNormalizerMiddleware()(handler, update, {})

        assert result == "callback handled"

    asyncio.run(scenario())


def test_main_registers_normalizer_before_routers_after_telemetry() -> None:
    main_text = Path("bot/main.py").read_text(encoding="utf-8")

    telemetry_pos = main_text.index(
        "dp.update.outer_middleware(TelegramUpdateTelemetryMiddleware())"
    )
    normalizer_pos = main_text.index(
        "dp.update.outer_middleware(RichMessageNormalizerMiddleware())"
    )
    router_pos = main_text.index("dp.include_router(fast_start_router)")

    # Telemetry keeps the raw content type for forensics; normalization then runs
    # before any router so existing F.text prompt handlers match rich messages.
    assert telemetry_pos < normalizer_pos < router_pos
    assert "from bot.services.telegram_rich_message import" in main_text
