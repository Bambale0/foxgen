from __future__ import annotations

import re
from pathlib import Path

from foxgen.miniapp_release import MINIAPP_RELEASE

STATIC = Path("src/foxgen/miniapp_static")
PARITY_SCRIPT = STATIC / "parity-app.js"
BACKEND_UI_SCRIPT = STATIC / "backend-parity-ui.js"
RUNTIME_LOADER = STATIC / "runtime-loader.js"
ENHANCEMENT_LOADER = STATIC / "enhancement-loader.js"
BOOT_GUARD = STATIC / "boot-guard.js"


def test_happy_fox_current_runtime_and_backend_ui_are_production_assets() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    assert f'<link rel="stylesheet" href="/mini-app/parity.css?v={MINIAPP_RELEASE}">' in html
    assert f'<link rel="stylesheet" href="/mini-app/backend-parity.css?v={MINIAPP_RELEASE}">' in html
    assert f'data-parity-src="/mini-app/parity-app.js?v={MINIAPP_RELEASE}"' in html
    assert f'/mini-app/backend-parity-ui.js?v={MINIAPP_RELEASE}' in html
    assert f'<script src="/mini-app/runtime-loader.js?v={MINIAPP_RELEASE}"></script>' in html
    assert f'<script src="/mini-app/enhancement-loader.js?v={MINIAPP_RELEASE}"></script>' in html
    assert "data-product-home-src" not in html
    assert "product-home" not in html
    assert "data-legacy-src" not in html
    assert "/mini-app/app.js" not in html
    assert f'<script defer src="/mini-app/parity-app.js?v={MINIAPP_RELEASE}"></script>' not in html
    assert '<script type="module" src="/mini-app/parity-app.js' not in html
    assert "Happy Fox" in html
    assert "FOXGEN" not in html


def test_runtime_fails_closed_instead_of_downgrading_or_hiding_core() -> None:
    loader = RUNTIME_LOADER.read_text(encoding="utf-8")
    enhancements = ENHANCEMENT_LOADER.read_text(encoding="utf-8")
    guard = BOOT_GUARD.read_text(encoding="utf-8")
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    assert "String.prototype.replaceAll" in loader
    assert "window.structuredClone" in loader
    assert "new Function" in loader
    assert "??=" in loader
    assert "&&=" in loader
    assert "data-parity-src" in loader
    assert "data-product-home-src" not in loader
    assert "data-legacy-src" not in loader
    assert "legacy=1" not in loader
    assert "__FOXGEN_BOOT_FATAL__" in loader
    assert "__FOXGEN_CORE_LOADED__" in loader
    assert "foxgen:core-loaded" in loader

    assert "visibility: hidden" not in html
    assert "data-foxgen-catalog" not in html
    assert "loadSequentially" in enhancements
    assert "optional enhancement failed to load" in enhancements
    assert "showCriticalFailure" not in enhancements
    assert "__FOXGEN_BOOT_FATAL__" not in enhancements
    assert "data-foxgen-catalog" not in enhancements

    assert "__FOXGEN_BOOT_FAIL__" in guard
    assert "__FOXGEN_BOOT_FATAL__" in guard
    assert "legacy=1" not in guard
    assert "location.replace" not in guard
    assert "совместимый режим" not in guard
    assert ".replaceAll(" not in guard
    assert "?." not in guard
    assert "??" not in guard


def test_happy_fox_frontend_is_schema_driven_and_uses_user_safe_api() -> None:
    script = PARITY_SCRIPT.read_text(encoding="utf-8")

    required_markers = (
        "input_schema",
        "MEDIA_FIELDS",
        "/models/${encodeURIComponent(built.model.slug)}/validate",
        "/generations?limit=100",
        "/ledger?limit=200",
        "api('/balance')",
        "api('/prices')",
        "api('/input-media'",
        "Idempotency-Key",
        "/cancel",
        "reference_image_urls",
        "reference_video_urls",
        "reference_audio_urls",
        "first_frame_url",
        "last_frame_url",
    )
    for marker in required_markers:
        assert marker in script

    assert "planned:mini_app" not in script
    assert "balance-adjustments" not in script
    assert "/internal/admin" not in script


def test_frontend_exposes_social_reference_and_remix_parity() -> None:
    script = PARITY_SCRIPT.read_text(encoding="utf-8")

    for marker in (
        "api(`/feed?sort=",
        "/publications/${id}",
        "/comments?surface=",
        "/like",
        "/profiles/${encodeURIComponent(slug)}",
        "api('/me/profile'",
        "api('/me/publications",
        "api('/reference-memory",
        "/reference-memory/resolve",
        "source_publication_id",
        "start_param",
        "tgWebAppStartParam",
    ):
        assert marker in script

    for label in (
        "Лента",
        "Создать",
        "Работы",
        "Профиль",
        "Память референсов",
        "Ремикс",
    ):
        assert label in script


def test_frontend_does_not_expose_admin_billing_paths() -> None:
    script = PARITY_SCRIPT.read_text(encoding="utf-8")

    assert "Backend invoice flow в разработке" in script
    assert 'data-action="topup"' not in script
    assert "/internal/admin" not in script


def test_parity_design_layer_is_loaded_and_grunge_is_restrained() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    css = (STATIC / "parity.css").read_text(encoding="utf-8")

    assert f'<link rel="stylesheet" href="/mini-app/app.css?v={MINIAPP_RELEASE}">' in html
    assert f'<link rel="stylesheet" href="/mini-app/studio.css?v={MINIAPP_RELEASE}">' in html
    assert f'<link rel="stylesheet" href="/mini-app/parity.css?v={MINIAPP_RELEASE}">' in html
    assert f'<link rel="stylesheet" href="/mini-app/backend-parity.css?v={MINIAPP_RELEASE}">' in html
    assert "grunge-card" in css
    assert "grunge-lite" in css

    match = re.search(r"--grunge-opacity:\s*([0-9.]+)", css)
    assert match is not None
    assert float(match.group(1)) <= 0.30


def test_navigation_exposes_six_primary_product_surfaces_and_all_core_screens() -> None:
    parity = PARITY_SCRIPT.read_text(encoding="utf-8")
    backend_ui = BACKEND_UI_SCRIPT.read_text(encoding="utf-8")

    for screen in (
        "feed",
        "create",
        "studio",
        "works",
        "profile",
        "wallet",
        "references",
        "publication",
        "publicProfile",
        "generation",
        "tariff",
        "support",
        "partner",
    ):
        assert screen in parity

    for label in ("Главная", "Модели", "Создать", "Работы", "Баланс", "Профиль"):
        assert label in backend_ui
    assert "repeat(6" in (STATIC / "backend-parity.css").read_text(encoding="utf-8")


def test_boot_renders_before_optional_feed_and_network_calls_are_bounded() -> None:
    parity = PARITY_SCRIPT.read_text(encoding="utf-8")
    backend_ui = BACKEND_UI_SCRIPT.read_text(encoding="utf-8")
    enhancements = ENHANCEMENT_LOADER.read_text(encoding="utf-8")

    init_start = parity.index("async function init()")
    first_render = parity.index("render();", init_start)
    background_feed = parity.index("void loadFeed(true)", init_start)

    assert first_render < background_feed
    assert "API_TIMEOUT_MS = 10000" in parity
    assert "controller.abort()" in parity
    assert "foxgen:bootstrap" in parity
    assert "__FOXGEN_BOOTSTRAP__" in parity

    assert "window.addEventListener('foxgen:bootstrap'" in backend_ui
    assert "bootstrap()?.models" in backend_ui
    assert "bootstrap()?.prices" in backend_ui
    assert "loadSequentially" in enhancements
