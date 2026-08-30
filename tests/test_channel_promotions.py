import asyncio
from pathlib import Path

from bot import database
from bot.channel_identity import ensure_channel_identity
from bot.channel_promotions import (
    consume_instagram_first_image,
    ensure_instagram_first_image_promotion,
    release_instagram_first_image,
    reserve_instagram_first_image,
)


def _prepare_identity(database_path, monkeypatch, *, external_user_id: str = "igsid-free"):
    monkeypatch.setattr(database, "DATABASE_PATH", str(database_path))
    asyncio.run(database.init_db())
    return asyncio.run(
        ensure_channel_identity(
            channel="instagram",
            account_id="ig-business-1",
            external_user_id=external_user_id,
        )
    )


def test_first_instagram_image_is_available_then_consumed_once(tmp_path, monkeypatch) -> None:
    identity = _prepare_identity(tmp_path / "free-image.db", monkeypatch)

    initial = asyncio.run(ensure_instagram_first_image_promotion(identity.id))
    reserved = asyncio.run(reserve_instagram_first_image(identity.id, "task-1"))
    consumed = asyncio.run(consume_instagram_first_image("task-1"))
    second = asyncio.run(reserve_instagram_first_image(identity.id, "task-2"))
    final = asyncio.run(ensure_instagram_first_image_promotion(identity.id))

    assert initial.status == "available"
    assert reserved is True
    assert consumed is True
    assert second is False
    assert final.status == "consumed"


def test_failed_generation_releases_free_image_for_retry(tmp_path, monkeypatch) -> None:
    identity = _prepare_identity(tmp_path / "free-image-retry.db", monkeypatch)

    assert asyncio.run(reserve_instagram_first_image(identity.id, "failed-task")) is True
    assert asyncio.run(release_instagram_first_image("failed-task")) is True
    assert asyncio.run(reserve_instagram_first_image(identity.id, "retry-task")) is True
    assert asyncio.run(consume_instagram_first_image("retry-task")) is True


def test_same_reservation_key_is_idempotent_but_second_key_cannot_double_claim(
    tmp_path,
    monkeypatch,
) -> None:
    identity = _prepare_identity(tmp_path / "free-image-idempotent.db", monkeypatch)

    assert asyncio.run(reserve_instagram_first_image(identity.id, "same-task")) is True
    assert asyncio.run(reserve_instagram_first_image(identity.id, "same-task")) is True
    assert asyncio.run(reserve_instagram_first_image(identity.id, "other-task")) is False


def test_promotion_is_keyed_to_instagram_external_user_not_account_link(tmp_path, monkeypatch) -> None:
    first = _prepare_identity(
        tmp_path / "free-image-multi-account.db",
        monkeypatch,
        external_user_id="igsid-one-person",
    )
    second = asyncio.run(
        ensure_channel_identity(
            channel="instagram",
            account_id="ig-business-2",
            external_user_id="igsid-one-person",
        )
    )

    assert first.id != second.id
    assert asyncio.run(reserve_instagram_first_image(first.id, "task-one")) is True
    assert asyncio.run(consume_instagram_first_image("task-one")) is True
    assert asyncio.run(reserve_instagram_first_image(second.id, "task-two")) is False


def test_postgres_promotion_schema_uses_native_ddl_path() -> None:
    source = Path("bot/channel_promotions.py").read_text(encoding="utf-8")

    assert "id BIGSERIAL PRIMARY KEY" in source
    assert "raw_connection.cursor()" in source
    assert "UNIQUE(channel, external_user_id, promotion_code)" in source
    assert "status = 'consumed'" in source
