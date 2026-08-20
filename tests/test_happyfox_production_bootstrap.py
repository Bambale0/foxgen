from scripts.prepare_happyfox_production import (
    build_runtime_values,
    mini_app_url_for_origin,
    postgres_url_for_database,
    redis_url_for_db,
)
from scripts.validate_happyfox_env import validate


def _legacy() -> dict[str, str]:
    return {
        "FOXGEN_TELEGRAM_BOT_TOKEN": "123456:token",
        "FOXGEN_DATABASE_URL": "postgresql+asyncpg://foxgen:secret@postgres:5432/foxgen",
        "FOXGEN_REDIS_URL": "redis://:secret@redis:6379/0",
        "FOXGEN_KIE_API_KEY": "kie-key",
        "FOXGEN_KIE_CALLBACK_BASE_URL": "https://alena.chillcreative.ru",
        "FOXGEN_KIE_WEBHOOK_HMAC_KEY": "kie-hook",
        "FOXGEN_INTERNAL_API_TOKEN": "internal-token",
    }


def test_bootstrap_derives_separate_database_and_redis_namespace() -> None:
    values = build_runtime_values(
        _legacy(),
        {},
        database_name="happyfox",
        redis_db=3,
    )

    assert values["DATABASE_URL"].endswith("@postgres:5432/happyfox")
    assert values["REDIS_URL"].endswith("@redis:6379/3")
    assert values["REDIS_PREFIX"] == "foxgen_happyfox"
    assert values["PRODUCT_ID"] == "happyfox"
    assert values["PAYMENT_PROVIDER"] == "telegram_stars"
    assert values["MINI_APP_URL"] == "https://alena.chillcreative.ru/mini-app/"
    assert values["WEBHOOK_PORT"] == "8080"
    assert validate(values) == []


def test_bootstrap_preserves_existing_current_runtime_values() -> None:
    values = build_runtime_values(
        _legacy(),
        {
            "PAYMENT_PROVIDER": "cryptobot",
            "ADMIN_IDS": "123,456",
            "REDIS_URL": "redis://:secret@redis:6379/7",
        },
        database_name="happyfox",
        redis_db=2,
    )

    assert values["PAYMENT_PROVIDER"] == "cryptobot"
    assert values["ADMIN_IDS"] == "123,456"
    assert values["REDIS_URL"].endswith("/7")


def test_database_url_normalizes_asyncpg_and_changes_database_only() -> None:
    result = postgres_url_for_database(
        "postgresql+asyncpg://foxgen:p%40ss@postgres:5432/foxgen?connect_timeout=5",
        "happyfox",
    )

    assert result == (
        "postgresql://foxgen:p%40ss@postgres:5432/happyfox?connect_timeout=5"
    )


def test_redis_url_preserves_credentials_and_uses_new_logical_db() -> None:
    result = redis_url_for_db("redis://:p%40ss@redis:6379/0", 4)

    assert result == "redis://:p%40ss@redis:6379/4"


def test_miniapp_url_is_derived_from_existing_happyfox_origin() -> None:
    assert (
        mini_app_url_for_origin("https://alena.chillcreative.ru")
        == "https://alena.chillcreative.ru/mini-app/"
    )


def test_empty_admin_ids_are_safe_and_do_not_block_production() -> None:
    values = build_runtime_values(
        _legacy(),
        {},
        database_name="happyfox",
        redis_db=5,
    )

    assert "ADMIN_IDS" not in values
    assert validate(values) == []
