from __future__ import annotations

import re
from pathlib import Path


STATIC = Path("src/foxgen/miniapp_static")


def test_happy_fox_frontend_is_schema_driven_and_uses_user_safe_api() -> None:
    script = (STATIC / "app.js").read_text(encoding="utf-8")

    required_markers = (
        "input_schema",
        "MEDIA_FIELDS",
        "/models/${encodeURIComponent(item.slug)}/validate",
        "/generations?limit=${max}",
        "/ledger?limit=${max}",
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


def test_frontend_does_not_fake_unimplemented_payment_flow() -> None:
    script = (STATIC / "app.js").read_text(encoding="utf-8")

    assert "payment endpoint" in script
    assert "Пополнение" in script
    assert 'data-action="topup"' not in script
    assert "invoice" not in script.lower()


def test_studio_design_layer_is_loaded_and_grunge_is_restrained() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    css = (STATIC / "studio.css").read_text(encoding="utf-8")

    assert '<link rel="stylesheet" href="/mini-app/app.css">' in html
    assert '<link rel="stylesheet" href="/mini-app/studio.css">' in html
    assert "grunge-card" in css
    assert "stamp" in css

    match = re.search(r"--grunge-opacity:\s*([0-9.]+)", css)
    assert match is not None
    assert float(match.group(1)) <= 0.30


def test_navigation_exposes_complete_user_product_surface() -> None:
    script = (STATIC / "app.js").read_text(encoding="utf-8")

    for screen in ("home", "models", "studio", "gallery", "wallet", "generation"):
        assert screen in script
    for label in ("Главная", "Модели", "Создать", "Работы", "Баланс"):
        assert label in script
