from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MINIAPP = ROOT / "frontend" / "miniapp-v0"


def test_layout_loads_max_bridge_and_keeps_telegram_sdk() -> None:
    layout = (MINIAPP / "app" / "layout.tsx").read_text()

    assert 'src="/mini-app/telegram-web-app.js"' in layout
    assert 'src="https://st.max.ru/js/max-web-app.js"' in layout
    assert "window.WebApp" in layout
    assert "__BANANO_MAX_INIT_DATA__" in layout


def test_frontend_api_understands_max_webappdata() -> None:
    api = (MINIAPP / "lib" / "api.ts").read_text()

    assert "getMiniAppPlatform" in api
    assert "WebAppData" in api
    assert "WebAppStartParam" in api
    assert "window.WebApp" in api
    assert "platform: getMiniAppPlatform()" in api


def test_max_payment_path_does_not_offer_telegram_stars_unconditionally() -> None:
    balance = (MINIAPP / "components" / "balance-sheet.tsx").read_text()
    payment_api = (MINIAPP / "lib" / "payment-api.ts").read_text()

    assert "const isMax = platform === 'max'" in balance
    assert "!isMax" in balance
    assert "platform: getMiniAppPlatform()" in payment_api
