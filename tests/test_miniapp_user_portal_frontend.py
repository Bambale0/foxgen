from pathlib import Path


def _frontend() -> str:
    return Path("src/foxgen/miniapp_static/parity-app.js").read_text(encoding="utf-8")


def test_user_portal_screens_are_real_miniapp_routes() -> None:
    text = _frontend()
    for marker in (
        "renderTariff",
        "renderSupport",
        "renderSupportTicket",
        "renderPartner",
        "api('/tariff')",
        "api('/support')",
        "api('/partner')",
        "data-nav=\"tariff\"",
        "data-nav=\"partner\"",
        "data-nav=\"support\"",
    ):
        assert marker in text


def test_user_portal_frontend_keeps_admin_boundary_private() -> None:
    text = _frontend()
    assert "/internal/admin" not in text
    assert "admin_hmac" not in text.lower()
