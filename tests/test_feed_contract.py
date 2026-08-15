from uuid import uuid4

import pytest

from foxgen.bot.feed import parse_start_payload, telegram_deep_link
from foxgen.bot.feed_remix import _resolved_publication_media
from foxgen.bot.keyboards import main_menu
from foxgen.core.errors import SubmissionError


def _callbacks(markup: object) -> set[str]:
    keyboard = getattr(markup, "inline_keyboard")
    return {
        button.callback_data
        for row in keyboard
        for button in row
        if button.callback_data is not None
    }


def test_main_menu_exposes_feed_profile_and_publish() -> None:
    callbacks = _callbacks(main_menu())
    assert {"feed:open", "feed:profile:me", "feed:publish:start"}.issubset(callbacks)


def test_deep_link_parser_accepts_post_profile_and_remix() -> None:
    publication_id = str(uuid4())
    assert parse_start_payload(f"post_{publication_id}") == ("post", publication_id)
    assert parse_start_payload(f"remix_{publication_id}") == ("remix", publication_id)
    assert parse_start_payload("profile_creator-42") == ("profile", "creator-42")


def test_deep_link_parser_rejects_malformed_or_oversized_profile() -> None:
    assert parse_start_payload("post_not-a-uuid") is None
    assert parse_start_payload("remix_not-a-uuid") is None
    assert parse_start_payload("profile_AB C") is None
    assert parse_start_payload("profile_" + "a" * 57) is None


def test_telegram_deep_link_stays_within_start_payload_contract() -> None:
    publication_id = str(uuid4())
    assert telegram_deep_link("@foxgen_bot", f"post_{publication_id}") == (
        f"https://t.me/foxgen_bot?start=post_{publication_id}"
    )
    with pytest.raises(ValueError, match="64"):
        telegram_deep_link("foxgen_bot", "profile_" + "a" * 57)


def test_remix_media_accepts_only_signed_https_supported_media() -> None:
    result = _resolved_publication_media(
        {
            "items": [
                {"url": "https://storage.example/image", "content_type": "image/png"},
                {"url": "https://storage.example/video", "content_type": "video/mp4"},
                {"url": "http://unsafe.example/file", "content_type": "image/png"},
                {"url": "https://storage.example/text", "content_type": "text/plain"},
            ]
        }
    )
    assert result == [
        {"kind": "image", "url": "https://storage.example/image"},
        {"kind": "video", "url": "https://storage.example/video"},
    ]


def test_remix_media_fails_closed_when_no_compatible_media() -> None:
    with pytest.raises(SubmissionError):
        _resolved_publication_media({"items": []})
