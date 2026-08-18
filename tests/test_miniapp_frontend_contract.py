from __future__ import annotations

import re
from pathlib import Path

from foxgen.miniapp_release import MINIAPP_RELEASE

STATIC = Path("src/foxgen/miniapp_static")
PARITY_SCRIPT = STATIC / "parity-app.js"
PRODUCT_HOME_SCRIPT = STATIC / "product-home.js"
RUNTIME_LOADER = STATIC / "runtime-loader.js"
BOOT_GUARD = STATIC / "boot-guard.js"


def test_happy_fox_parity_runtime_is_loaded_through_compatibility_gate() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    assert f'<link rel="stylesheet" href="/mini-app/parity.css?v={MINIAPP_RELEASE}">' in html
    assert f'data-parity-src="/mini-app/parity-app.js?v={MINIAPP_RELEASE}"' in html
    assert f'data-legacy-src="/mini-app/app.js?v={MINIAPP_RELEASE}"' in html
    assert f'<script src="/mini-app/runtime-loader.js?v={MINIAPP_RELEASE}"></script>' in html
    assert f'<script src="/mini-app/enhancement-loader.js?v={MINIAPP_RELEASE}"></script>' in html
    assert f'<script defer src="/mini-app/parity-app.js?v={MINIAPP_RELEASE}"></script>' not in html
    assert '<script type="module" src="/mini-app/parity-app.js' not in html
    assert '<script type="module" src="/mini-app/app.js' not in html
    assert "Happy Fox" in html
    assert "FOXGEN" not in html


def test_runtime_loader_falls_back_for_legacy_telegram_webviews() -> None:
    loader = RUNTIME_LOADER.read_text(encoding="utf-8")
    guard = BOOT_GUARD.read_text(encoding="utf-8")

    assert "String.prototype.replaceAll" in loader
    assert "window.structuredClone" in loader
    assert "new Function" in loader
    assert "??=" in loader
    assert "&&=" in loader
    assert "data-legacy-src" in loader
    assert "legacy=1" in loader

    assert "__FOXGEN_BOOT_FAIL__" in guard
    assert "Переключаем совместимый режим" in guard
    assert "legacy=1" in guard
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
    assert "grunge-card" in css
    assert "grunge-lite" in css

    match = re.search(r"--grunge-opacity:\s*([0-9.]+)", css)
    assert match is not None
    assert float(match.group(1)) <= 0.30


def test_navigation_exposes_four_primary_product_surfaces() -> None:
    script = PARITY_SCRIPT.read_text(encoding="utf-8")

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
    ):
        assert screen in script
    assert "[['feed','Лента'" in script
    assert "['create','Создать'" in script
    assert "['works','Работы'" in script
    assert "['profile','Профиль'" in script


def test_boot_renders_before_optional_feed_and_network_calls_are_bounded() -> None:
    parity = PARITY_SCRIPT.read_text(encoding="utf-8")
    product_home = PRODUCT_HOME_SCRIPT.read_text(encoding="utf-8")

    init_start = parity.index("async function init()")
    first_render = parity.index("render();", init_start)
    background_feed = parity.index("void loadFeed(true)", init_start)

    assert first_render < background_feed
    assert "API_TIMEOUT_MS = 10000" in parity
    assert "controller.abort()" in parity
    assert "foxgen:bootstrap" in parity
    assert "__FOXGEN_BOOTSTRAP__" in parity

    assert "API_TIMEOUT_MS = 10000" in product_home
    assert "fetchBounded" in product_home
    assert "foxgen:bootstrap" in product_home
    assert "__FOXGEN_BOOTSTRAP__" in product_home
