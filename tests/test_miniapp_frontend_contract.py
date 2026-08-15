from __future__ import annotations

import re
from pathlib import Path


STATIC = Path("src/foxgen/miniapp_static")
PARITY_SCRIPT = STATIC / "parity-app.js"


def test_happy_fox_parity_runtime_is_loaded() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    assert '<link rel="stylesheet" href="/mini-app/parity.css">' in html
    assert '<script type="module" src="/mini-app/parity-app.js"></script>' in html
    assert '<script type="module" src="/mini-app/app.js"></script>' not in html
    assert "Happy Fox" in html
    assert "FOXGEN" not in html


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


def test_frontend_does_not_fake_unimplemented_payment_or_partner_flows() -> None:
    script = PARITY_SCRIPT.read_text(encoding="utf-8")

    assert "Backend invoice flow в разработке" in script
    assert "Backend epic ещё не завершён" in script
    assert 'data-action="topup"' not in script
    assert "/internal/admin" not in script


def test_parity_design_layer_is_loaded_and_grunge_is_restrained() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    css = (STATIC / "parity.css").read_text(encoding="utf-8")

    assert '<link rel="stylesheet" href="/mini-app/app.css">' in html
    assert '<link rel="stylesheet" href="/mini-app/studio.css">' in html
    assert '<link rel="stylesheet" href="/mini-app/parity.css">' in html
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
