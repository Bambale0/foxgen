from __future__ import annotations

from pathlib import Path


PUBLIC_DIR = Path("frontend/miniapp-v0/public")


def test_happyfox_brand_assets_exist_and_are_nontrivial() -> None:
    expected_assets = {
        "happyfox-logo.webp": 20_000,
        "happyfox-icon.webp": 8_000,
        "apple-icon.png": 10_000,
        "favicon.ico": 8_000,
        "icon-dark-32x32.png": 500,
        "icon-light-32x32.png": 500,
        "icon.svg": 5_000,
    }

    for filename, minimum_size in expected_assets.items():
        path = PUBLIC_DIR / filename
        assert path.is_file(), f"missing HappyFox brand asset: {filename}"
        assert path.stat().st_size >= minimum_size, f"HappyFox asset is too small: {filename}"


def test_happyfox_brand_assets_are_wired_to_loader_and_app_chrome() -> None:
    product = Path("frontend/miniapp-v0/lib/product.ts").read_text(encoding="utf-8")
    brand = Path("frontend/miniapp-v0/lib/brand.ts").read_text(encoding="utf-8")
    loader = Path("frontend/miniapp-v0/components/mini-app-loader.tsx").read_text(
        encoding="utf-8"
    )
    header = Path("frontend/miniapp-v0/components/hero-header.tsx").read_text(
        encoding="utf-8"
    )
    studio = Path("frontend/miniapp-v0/components/tabs/studio-tab.tsx").read_text(
        encoding="utf-8"
    )
    layout = Path("frontend/miniapp-v0/app/layout.tsx").read_text(encoding="utf-8")

    assert "happyfox-logo.webp" in product
    assert "happyfox-icon.webp" in product
    assert "BRAND_ICON = PRODUCT.brandIcon" in brand
    assert "src={BRAND_LOGO}" in loader
    assert "src={BRAND_ICON}" in header
    assert "src={BRAND_ICON}" in studio
    assert "BRAND_ICON" in layout
    assert "/mini-app/apple-icon.png" in layout
    assert "/mini-app/favicon.ico" in layout
    assert "/mini-app/icon-light-32x32.png" in layout
    assert "/mini-app/icon-dark-32x32.png" in layout
