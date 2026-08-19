from pathlib import Path

from foxgen.providers.kie.registry import SUBMISSION_MODEL_SLUGS, ModelRegistry

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "foxgen" / "miniapp_static"


def test_backend_model_catalog_is_dynamic_and_covers_every_submission_model() -> None:
    registry = ModelRegistry()
    enabled = {
        item.slug
        for item in registry.list()
        if item.enabled_for_submission
    }

    assert enabled == set(SUBMISSION_MODEL_SLUGS)

    ui = (STATIC / "backend-parity-ui.js").read_text(encoding="utf-8")
    assert "bootstrap()?.models" in ui
    assert "item.enabled !== false" in ui
    assert "bootstrap()?.prices" in ui
    assert "data-backend-model" in ui
    assert "invokeParityModel(slug)" in ui

    special = {
        "suno-v5-extend",
        "suno-v5-upload-cover",
        "suno-v5-upload-extend",
        "kling-3-motion-control",
    }
    assert special <= enabled
    for slug in special:
        assert slug in ui


def test_special_suno_and_motion_workflows_quote_real_backend_prices() -> None:
    extend = (STATIC / "suno-extend.js").read_text(encoding="utf-8")
    cover = (STATIC / "suno-upload-cover.js").read_text(encoding="utf-8")
    upload_extend = (STATIC / "suno-upload-extend.js").read_text(encoding="utf-8")
    motion = (STATIC / "motion-control.js").read_text(encoding="utf-8")

    assert "bootstrap?.prices" in extend
    assert "item?.model_slug === EXTEND_SLUG" in extend
    assert "data?.prices" in cover
    assert "item?.model_slug === MODEL" in cover
    assert "data?.prices" in upload_extend
    assert "data?.prices" in motion


def test_full_user_backend_domains_are_reachable_from_primary_surface() -> None:
    ui = (STATIC / "backend-parity-ui.js").read_text(encoding="utf-8")
    parity = (STATIC / "parity-app.js").read_text(encoding="utf-8")
    complete = (STATIC / "complete-menu.js").read_text(encoding="utf-8")
    promo = (STATIC / "promo-redeem.js").read_text(encoding="utf-8")

    for screen in (
        "feed",
        "create",
        "works",
        "wallet",
        "profile",
        "references",
        "tariff",
        "partner",
        "support",
    ):
        assert f"screen: '{screen}'" in ui or f"{screen}:render" in parity

    for path in (
        "/feed?sort=",
        "/generations?limit=100",
        "/balance",
        "/prices",
        "/ledger?limit=200",
        "/me/profile",
        "/reference-memory?limit=100",
        "/tariff",
        "/support",
        "/partner",
    ):
        assert path in parity

    assert "/stars/packages" in complete
    assert "/stars/invoices" in complete
    assert "openInvoice" in complete
    assert "/v1/miniapp/promos/redeem" in promo
    assert "/me/publications?limit=50" in ui
    assert "/publications/${encodeURIComponent(scope)}" in ui
