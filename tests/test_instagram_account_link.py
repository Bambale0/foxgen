import asyncio
import hashlib
import sqlite3

import pytest

from bot import database
from bot.channel_identity import ensure_channel_identity
from bot.channel_link import (
    ChannelLinkError,
    consume_channel_link_token,
    create_channel_link_token,
)


def _prepare_database(database_path, monkeypatch) -> None:
    monkeypatch.setattr(database, "DATABASE_PATH", str(database_path))
    asyncio.run(database.init_db())


def test_link_token_is_hashed_one_time_and_reuses_existing_user(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "link.db"
    _prepare_database(database_path, monkeypatch)
    user = asyncio.run(database.get_or_create_user(700001))
    identity = asyncio.run(
        ensure_channel_identity(
            channel="instagram",
            account_id="ig-business-1",
            external_user_id="igsid-1",
            username="creator",
        )
    )

    token = asyncio.run(create_channel_link_token(identity.id, ttl_seconds=900))

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT token_hash FROM channel_link_tokens WHERE identity_id = ?",
            (identity.id,),
        ).fetchone()
    assert row is not None
    assert token not in row[0]
    assert row[0] == hashlib.sha256(token.encode("utf-8")).hexdigest()

    linked = asyncio.run(consume_channel_link_token(token, user.id))
    assert linked.id == identity.id
    assert linked.user_id == user.id

    with pytest.raises(ChannelLinkError) as error:
        asyncio.run(consume_channel_link_token(token, user.id))
    assert error.value.code == "used"


def test_expired_link_token_cannot_attach_identity(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "expired.db"
    _prepare_database(database_path, monkeypatch)
    user = asyncio.run(database.get_or_create_user(700002))
    identity = asyncio.run(
        ensure_channel_identity(
            channel="instagram",
            account_id="ig-business-1",
            external_user_id="igsid-expired",
        )
    )

    monkeypatch.setattr("bot.channel_link.time.time", lambda: 1_000.0)
    token = asyncio.run(create_channel_link_token(identity.id, ttl_seconds=60))
    monkeypatch.setattr("bot.channel_link.time.time", lambda: 1_061.0)

    with pytest.raises(ChannelLinkError) as error:
        asyncio.run(consume_channel_link_token(token, user.id))
    assert error.value.code == "expired"


def test_identity_cannot_be_silently_relinked_to_another_user(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "conflict.db"
    _prepare_database(database_path, monkeypatch)
    first_user = asyncio.run(database.get_or_create_user(700003))
    second_user = asyncio.run(database.get_or_create_user(700004))
    identity = asyncio.run(
        ensure_channel_identity(
            channel="instagram",
            account_id="ig-business-1",
            external_user_id="igsid-conflict",
        )
    )

    first_token = asyncio.run(create_channel_link_token(identity.id))
    asyncio.run(consume_channel_link_token(first_token, first_user.id))
    second_token = asyncio.run(create_channel_link_token(identity.id))

    with pytest.raises(ChannelLinkError) as error:
        asyncio.run(consume_channel_link_token(second_token, second_user.id))
    assert error.value.code == "conflict"


def test_new_token_invalidates_previous_unconsumed_token(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "replace.db"
    _prepare_database(database_path, monkeypatch)
    user = asyncio.run(database.get_or_create_user(700005))
    identity = asyncio.run(
        ensure_channel_identity(
            channel="instagram",
            account_id="ig-business-1",
            external_user_id="igsid-replace",
        )
    )

    old_token = asyncio.run(create_channel_link_token(identity.id))
    new_token = asyncio.run(create_channel_link_token(identity.id))

    with pytest.raises(ChannelLinkError) as error:
        asyncio.run(consume_channel_link_token(old_token, user.id))
    assert error.value.code == "used"

    linked = asyncio.run(consume_channel_link_token(new_token, user.id))
    assert linked.user_id == user.id
