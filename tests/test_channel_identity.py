import asyncio

from bot import database
from bot.channel_identity import ensure_channel_identity, get_channel_identity


def test_instagram_identity_exists_without_fake_telegram_user(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "identity.db"
    monkeypatch.setattr(database, "DATABASE_PATH", str(database_path))

    identity = asyncio.run(
        ensure_channel_identity(
            channel="instagram",
            account_id="ig-business-1",
            external_user_id="igsid-42",
            username="creator42",
            display_name="Creator 42",
        )
    )
    again = asyncio.run(
        get_channel_identity(
            channel="instagram",
            account_id="ig-business-1",
            external_user_id="igsid-42",
        )
    )

    assert identity.id > 0
    assert identity.channel == "instagram"
    assert identity.external_user_id == "igsid-42"
    assert identity.user_id is None
    assert again is not None
    assert again.id == identity.id
    assert again.user_id is None


def test_identity_upsert_refreshes_profile_without_creating_duplicate(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "identity-upsert.db"
    monkeypatch.setattr(database, "DATABASE_PATH", str(database_path))

    first = asyncio.run(
        ensure_channel_identity(
            channel="instagram",
            account_id="ig-business-1",
            external_user_id="igsid-7",
            username="old_name",
        )
    )
    second = asyncio.run(
        ensure_channel_identity(
            channel="instagram",
            account_id="ig-business-1",
            external_user_id="igsid-7",
            username="new_name",
            display_name="New Name",
        )
    )

    assert second.id == first.id
    assert second.username == "new_name"
    assert second.display_name == "New Name"
    assert second.user_id is None
