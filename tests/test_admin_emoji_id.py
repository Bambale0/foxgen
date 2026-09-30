from types import SimpleNamespace

import pytest
from aiogram.types import MessageEntity

from bot.handlers import admin
from bot.services.telegram_custom_emoji import extract_custom_emoji_ids


def _message(*, entities=None, caption_entities=None, rich_message=None, reply_to_message=None):
    return SimpleNamespace(
        entities=entities or [],
        caption_entities=caption_entities or [],
        rich_message=rich_message,
        reply_to_message=reply_to_message,
    )


def test_extract_custom_emoji_ids_from_text_entities_and_reply():
    direct = MessageEntity(
        type="custom_emoji",
        offset=0,
        length=2,
        custom_emoji_id="5368324170671202286",
    )
    replied = MessageEntity(
        type="custom_emoji",
        offset=0,
        length=2,
        custom_emoji_id="5774022692642492953",
    )
    message = _message(
        entities=[direct],
        reply_to_message=_message(entities=[replied]),
    )

    assert extract_custom_emoji_ids(message) == [
        "5368324170671202286",
        "5774022692642492953",
    ]


def test_extract_custom_emoji_ids_from_rich_message_and_deduplicates():
    message = _message(
        rich_message={
            "type": "paragraph",
            "text": {
                "type": "custom_emoji",
                "custom_emoji_id": "5368324170671202286",
                "alternative_text": "🦊",
            },
        },
        entities=[
            MessageEntity(
                type="custom_emoji",
                offset=0,
                length=2,
                custom_emoji_id="5368324170671202286",
            )
        ],
    )

    assert extract_custom_emoji_ids(message) == ["5368324170671202286"]


@pytest.mark.asyncio
async def test_cmd_emoji_id_returns_ids_for_admin(monkeypatch):
    answers = []

    class FakeMessage:
        from_user = SimpleNamespace(id=123)
        entities = [
            MessageEntity(
                type="custom_emoji",
                offset=10,
                length=2,
                custom_emoji_id="5368324170671202286",
            )
        ]
        caption_entities = []
        rich_message = None
        reply_to_message = None

        async def answer(self, text, **kwargs):
            answers.append((text, kwargs))

    monkeypatch.setattr(admin, "is_admin", lambda user_id: user_id == 123)

    await admin.cmd_emoji_id(FakeMessage())

    assert len(answers) == 1
    assert "<code>5368324170671202286</code>" in answers[0][0]
    assert answers[0][1]["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_cmd_emoji_id_is_admin_only(monkeypatch):
    answers = []

    class FakeMessage:
        from_user = SimpleNamespace(id=321)
        entities = []
        caption_entities = []
        rich_message = None
        reply_to_message = None

        async def answer(self, text, **kwargs):
            answers.append((text, kwargs))

    monkeypatch.setattr(admin, "is_admin", lambda _user_id: False)

    await admin.cmd_emoji_id(FakeMessage())

    assert answers == [("⛔ У вас нет доступа к этой команде.", {})]
