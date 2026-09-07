from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "frontend" / "miniapp-v0" / "public"
PRODUCT = ROOT / "frontend" / "miniapp-v0" / "lib" / "product.ts"


def test_happyfox_miniapp_uses_alpha_capable_brand_asset() -> None:
    webp = (PUBLIC / "happyfox-brand.webp").read_bytes()
    assert webp[:4] == b"RIFF"
    assert webp[8:12] == b"WEBP"
    assert webp[12:16] == b"VP8X"
    assert webp[20] & 0x10, "HappyFox brand WebP must keep the alpha flag"

    product = PRODUCT.read_text(encoding="utf-8")
    assert "brandLogo: `${MINIAPP_BASE_PATH}/happyfox-brand.webp`" in product
    assert "brandLogo: `${MINIAPP_BASE_PATH}/happyfox-icon.webp`" not in product
