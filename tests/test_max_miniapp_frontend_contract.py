from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MINIAPP = ROOT / "frontend" / "miniapp-v0"


def test_layout_selects_exactly_one_platform_bridge_from_launch_data() -> None:
    layout = (MINIAPP / "app" / "layout.tsx").read_text()

    assert 'id="miniapp-bridge-loader"' in layout
    assert 'id="miniapp-early-ready"' in layout
    assert "'/mini-app/telegram-web-app.js'" in layout
    assert "'https://st.max.ru/js/max-web-app.js'" in layout
    assert 'src="/mini-app/telegram-web-app.js"' not in layout
    assert 'src="https://st.max.ru/js/max-web-app.js"' not in layout
    assert "tgWebAppData" in layout
    assert "WebAppData" in layout
    assert "document.write" in layout
    assert "__BANANO_MINIAPP_PLATFORM_HINT__" in layout


def test_frontend_api_uses_explicit_launch_platform_before_bridge_globals() -> None:
    api = (MINIAPP / "lib" / "api.ts").read_text()

    assert "getMiniAppPlatform" in api
    telegram_launch = "if (params.get('tgWebAppData')) return 'telegram'"
    max_launch = "if (params.get('WebAppData')) return 'max'"
    telegram_bridge = "if (window.Telegram?.WebApp?.initData) return 'telegram'"
    max_bridge = "if (window.WebApp?.initData) return 'max'"
    assert telegram_launch in api
    assert max_launch in api
    assert telegram_bridge in api
    assert max_bridge in api
    assert api.index(telegram_launch) < api.index(max_launch)
    assert api.index(max_launch) < api.index(telegram_bridge)
    assert api.index(telegram_bridge) < api.index(max_bridge)
    assert "WebAppStartParam" in api
    assert "platform: getMiniAppPlatform()" in api


def test_max_payment_path_does_not_offer_telegram_stars_unconditionally() -> None:
    balance = (MINIAPP / "components" / "balance-sheet.tsx").read_text()
    payment_api = (MINIAPP / "lib" / "payment-api.ts").read_text()

    assert "const isMax = platform === 'max'" in balance
    assert "!isMax" in balance
    assert "platform: getMiniAppPlatform()" in payment_api
