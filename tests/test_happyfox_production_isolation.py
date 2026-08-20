import json
from pathlib import Path

from scripts.validate_happyfox_env import validate


def _valid_env() -> dict[str, str]:
    return {
        "PRODUCT_ID": "happyfox",
        "BOT_TOKEN": "123456:happyfox",
        "ADMIN_IDS": "123456789",
        "WEBHOOK_HOST": "https://api.happyfox.example",
        "MINI_APP_URL": "https://app.happyfox.example/mini-app/",
        "STATIC_BASE_URL": "https://media.happyfox.example",
        "DATABASE_URL": "postgresql://happyfox:secret@db:5432/happyfox",
        "REDIS_URL": "redis://redis:6379/3",
        "REDIS_PREFIX": "foxgen_happyfox",
        "KIE_AI_API_KEY": "kie-secret",
        "KIE_AI_WEBHOOK_SECRET": "webhook-secret",
        "INTERNAL_API_SECRET": "internal-secret",
        "PAYMENT_PROVIDER": "telegram_stars",
    }


def test_valid_isolated_happyfox_environment_passes() -> None:
    assert validate(_valid_env()) == []


def test_neuromix_domains_are_rejected() -> None:
    values = _valid_env()
    values["WEBHOOK_HOST"] = "https://tanyapi.chillcreative.ru"
    values["MINI_APP_URL"] = "https://cdn.chillcreative.ru/mini-app/"

    errors = validate(values)

    assert any("WEBHOOK_HOST contains blocked" in item for item in errors)
    assert any("MINI_APP_URL contains blocked" in item for item in errors)


def test_data_plane_must_be_happyfox_specific() -> None:
    values = _valid_env()
    values["DATABASE_URL"] = "sqlite:///bot.db"
    values["REDIS_PREFIX"] = "banano_kling"

    errors = validate(values)

    assert "DATABASE_URL must point to PostgreSQL in production" in errors
    assert "REDIS_PREFIX must be HappyFox/FoxGen-specific" in errors


def test_selected_payment_provider_requires_its_secrets() -> None:
    values = _valid_env()
    values["PAYMENT_PROVIDER"] = "lava"

    errors = validate(values)

    assert "LAVA_API_KEY is required for PAYMENT_PROVIDER=lava" in errors
    assert "LAVA_WEBHOOK_SECRET is required for PAYMENT_PROVIDER=lava" in errors


def test_happyfox_deploy_wrapper_overrides_imported_neuromix_runtime_names() -> None:
    script = Path("scripts/deploy_happyfox.sh").read_text(encoding="utf-8")

    assert "SYSTEMD_SERVICE=\"${SYSTEMD_SERVICE:-foxgen-happyfox}\"" in script
    assert "CONTAINER_NAME=\"${CONTAINER_NAME:-foxgen-happyfox-bot}\"" in script
    assert "validate_happyfox_env.py" in script
    assert "exec bash scripts/deploy_backend_docker.sh" in script


def test_product_runtime_defaults_do_not_point_back_to_source_product() -> None:
    config = Path("bot/config.py").read_text(encoding="utf-8")
    media_inputs = Path("bot/services/media_input_utils.py").read_text(encoding="utf-8")
    trend_api = Path("frontend/miniapp-v0/lib/trend-api.ts").read_text(encoding="utf-8")
    media_url = Path("frontend/miniapp-v0/lib/media-url.ts").read_text(encoding="utf-8")
    backend_product = Path("bot/product.py").read_text(encoding="utf-8")
    frontend_product = Path("frontend/miniapp-v0/lib/product.ts").read_text(encoding="utf-8")
    support_copy = Path("bot/support_copy.py").read_text(encoding="utf-8")

    assert 'os.getenv("REDIS_PREFIX", "foxgen_happyfox")' in config
    assert "dev.chillcreative.ru" not in config
    assert "tanyapi.chillcreative.ru" not in media_inputs
    assert "tanyapi.chillcreative.ru" not in trend_api
    assert "tanyapi.chillcreative.ru" not in media_url
    assert "tanyapp.chillcreative.ru" not in media_url
    assert "cdn.chillcreative.ru" not in media_url
    assert 'product_id != "happyfox"' in backend_product
    assert "'neuromix'" not in frontend_product
    assert "@only_tany" not in support_copy


def test_runtime_copy_normalizer_strips_source_support_contact() -> None:
    common = Path("bot/handlers/common.py").read_text(encoding="utf-8")
    miniapp = Path("bot/miniapp.py").read_text(encoding="utf-8")

    assert "@only_tany" not in common
    assert "@only_tany" not in miniapp


def test_active_pricing_source_contains_no_imported_product_credentials() -> None:
    raw = Path("data/price.json").read_text(encoding="utf-8")
    pricing = json.loads(raw)

    assert pricing["credit_name"] == "кредит"
    assert pricing["credit_name_plural"] == "кредитов"
    assert pricing["credit_rub_value"] == 10
    assert pricing["partner_exchange"]["rub_per_credit"] == 10
    assert pricing["admin_ids"] == []
    assert pricing["support_contact"] == ""
    assert "lava_offer_id" not in raw
    assert "@only_tany" not in raw
    assert "🍌" not in raw
    assert "banana_2" in pricing["costs_reference"]["image_models"]
    assert "v3_pro" in pricing["costs_reference"]["video_models"]


def test_happyfox_miniapp_deploy_has_no_source_product_defaults() -> None:
    script = Path("scripts/deploy_miniapp_local.sh").read_text(encoding="utf-8")

    assert 'MINIAPP_FRONTEND_DOMAIN:?MINIAPP_FRONTEND_DOMAIN is required' in script
    assert "/etc/foxgen-happyfox/profiles/" in script
    assert "/var/backups/foxgen-happyfox/" in script
    assert "DEFAULT_FRONTEND_DOMAIN" not in script
    assert "/etc/banano-miniapp/" not in script


def test_production_deploy_runs_automatically_after_green_main_ci() -> None:
    workflow = Path(".github/workflows/deploy-production.yml").read_text(encoding="utf-8")

    assert "vars.ENABLE_PRODUCTION_DEPLOY" not in workflow
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "github.event.workflow_run.event == 'push'" in workflow
    assert "github.event.workflow_run.head_branch == 'main'" in workflow
