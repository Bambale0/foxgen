from pathlib import Path


MINIAPP = Path(__file__).resolve().parents[1] / "src" / "foxgen" / "miniapp_static"


def test_promo_redemption_assets_are_loaded() -> None:
    html = (MINIAPP / "index.html").read_text(encoding="utf-8")

    assert "/mini-app/promo-redeem.css" in html
    assert "/mini-app/promo-redeem.js" in html


def test_promo_redemption_uses_telegram_auth_and_owner_api() -> None:
    script = (MINIAPP / "promo-redeem.js").read_text(encoding="utf-8")

    assert "tg?.initData" in script
    assert "/v1/miniapp/auth" in script
    assert "/v1/miniapp/promos/redeem" in script
    assert "Authorization" in script
    assert "Bearer ${token}" in script
    assert "reward_units" in script
    assert "available_units" in script
    assert "replayed" in script
    assert "window.location.reload()" in script
