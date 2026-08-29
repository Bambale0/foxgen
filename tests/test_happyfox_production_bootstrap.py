from pathlib import Path

from scripts.prepare_happyfox_production import (
    build_runtime_values,
    mini_app_url_for_origin,
    pin_public_origin,
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


def test_bootstrap_preserves_explicit_yookassa_configuration() -> None:
    legacy = _legacy()
    legacy.update(
        {
            "PAYMENT_PROVIDER": "yookassa",
            "YOOKASSA_SHOP_ID": "shop-123",
            "YOOKASSA_SECRET_KEY": "secret",
        }
    )
    values = build_runtime_values(
        legacy,
        {},
        database_name="happyfox",
        redis_db=6,
    )

    assert values["PAYMENT_PROVIDER"] == "yookassa"
    assert values["YOOKASSA_SHOP_ID"] == "shop-123"
    assert values["YOOKASSA_SECRET_KEY"] == "secret"
    assert values["YOOKASSA_WEBHOOK_PATH"] == "/yookassa/webhook"
    assert values["YOOKASSA_RETURN_URL"] == values["MINI_APP_URL"]
    assert validate(values) == []


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


def test_verified_public_origin_overrides_stale_runtime_domain() -> None:
    existing = {
        "WEBHOOK_HOST": "https://alena.нейроныч.online",
        "MINI_APP_URL": "https://alena.нейроныч.online/mini-app/",
        "STATIC_BASE_URL": "https://alena.нейроныч.online",
        "REDIS_URL": "redis://redis:6379/5",
    }

    pinned = pin_public_origin(existing, "https://alena.chillcreative.ru")

    assert pinned["WEBHOOK_HOST"] == "https://alena.chillcreative.ru"
    assert pinned["MINI_APP_URL"] == "https://alena.chillcreative.ru/mini-app/"
    assert pinned["STATIC_BASE_URL"] == "https://alena.chillcreative.ru"
    assert pinned["REDIS_URL"] == existing["REDIS_URL"]


def test_verified_public_origin_rejects_paths_and_non_https_urls() -> None:
    for invalid in (
        "http://alena.chillcreative.ru",
        "https://alena.chillcreative.ru/mini-app/",
        "https://user:pass@alena.chillcreative.ru",
    ):
        try:
            pin_public_origin({}, invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"public origin should be rejected: {invalid}")


def test_empty_admin_ids_are_safe_and_do_not_block_production() -> None:
    values = build_runtime_values(
        _legacy(),
        {},
        database_name="happyfox",
        redis_db=5,
    )

    assert "ADMIN_IDS" not in values
    assert validate(values) == []


def test_compose_uses_existing_backend_network_and_runtime_overlay() -> None:
    compose = Path("compose.backend.yml").read_text(encoding="utf-8")

    assert ".env.happyfox.runtime" in compose
    assert "network_mode: host" not in compose
    assert "name: ${HAPPYFOX_BACKEND_NETWORK:-foxgen_backend}" in compose
    assert "- api" in compose
    assert 'WEBHOOK_PORT: "8080"' in compose


def test_happyfox_deploy_stops_only_legacy_app_tier_and_has_public_rollback() -> None:
    wrapper = Path("scripts/deploy_happyfox.sh").read_text(encoding="utf-8")
    generic = Path("scripts/deploy_backend_docker.sh").read_text(encoding="utf-8")

    for container in ("foxgen-api-1", "foxgen-bot-1", "foxgen-worker-1"):
        assert container in wrapper
    for infrastructure in ("foxgen-postgres-1", "foxgen-redis-1", "foxgen-minio-1"):
        assert infrastructure not in wrapper

    assert "rollback_legacy_app" in wrapper
    assert "PUBLIC_HEALTH_OK" in wrapper
    assert "HAPPYFOX_REVERSE_PROXY_CONTAINER" in wrapper
    assert "restore_cutover_containers" in generic
    assert "CUTOVER_RESTART_ON_FAILURE" in generic


def test_production_workflow_prepares_runtime_before_strict_validation() -> None:
    workflow = Path(".github/workflows/deploy-production.yml").read_text(encoding="utf-8")

    prepare_index = workflow.index("prepare_happyfox_production.py")
    runtime_validation_index = workflow.index(
        ".env .env.happyfox.runtime .env.postgres"
    )
    assert prepare_index < runtime_validation_index
    assert "docker network inspect" in workflow
    assert 'HAPPYFOX_PUBLIC_ORIGIN="https://${MINIAPP_FRONTEND_DOMAIN}"' in workflow
