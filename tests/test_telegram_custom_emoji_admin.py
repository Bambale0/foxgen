from pathlib import Path
from types import SimpleNamespace

from bot.services.telegram_custom_emoji import extract_custom_emoji_ids


def _entity(custom_emoji_id: str | None = None, entity_type: str = "custom_emoji"):
    return SimpleNamespace(type=entity_type, custom_emoji_id=custom_emoji_id)


def _message(*, entities=None, caption_entities=None, reply_to_message=None, rich_message=None):
    return SimpleNamespace(
        entities=entities,
        caption_entities=caption_entities,
        reply_to_message=reply_to_message,
        rich_message=rich_message,
    )


def test_extracts_custom_emoji_from_command_message_entities():
    message = _message(
        entities=[
            _entity(entity_type="bot_command"),
            _entity("5368324170671202286"),
        ]
    )

    assert extract_custom_emoji_ids(message) == ["5368324170671202286"]


def test_extracts_custom_emoji_from_replied_message():
    replied = _message(entities=[_entity("5774022692642492953")])
    message = _message(reply_to_message=replied)

    assert extract_custom_emoji_ids(message) == ["5774022692642492953"]


def test_extracts_and_deduplicates_rich_message_custom_emoji():
    message = _message(
        entities=[_entity("111")],
        rich_message={
            "type": "paragraph",
            "children": [
                {"type": "custom_emoji", "custom_emoji_id": "111"},
                {"type": "custom_emoji", "custom_emoji_id": "222"},
            ],
        },
    )

    assert extract_custom_emoji_ids(message) == ["111", "222"]


def test_ignores_plain_unicode_emoji_without_custom_emoji_id():
    message = _message(entities=[_entity(None), _entity(entity_type="bold")])

    assert extract_custom_emoji_ids(message) == []


def test_admin_router_exposes_emoji_id_command_with_access_check():
    source = Path("bot/handlers/admin.py").read_text(encoding="utf-8")

    assert '@router.message(Command("emoji_id"))' in source
    handler = source.split('@router.message(Command("emoji_id"))', 1)[1].split(
        '@router.message(Command("admin"))',
        1,
    )[0]
    assert "is_admin(message.from_user.id)" in handler
    assert "extract_custom_emoji_ids(message)" in handler
