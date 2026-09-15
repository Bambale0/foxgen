from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MINIAPP = ROOT / "frontend" / "miniapp-v0"


def test_layout_loads_max_bridge_without_stealing_telegram_launch() -> None:
    layout = (MINIAPP / "app" / "layout.tsx").read_text()

    telegram_sdk = 'src="/mini-app/telegram-web-app.js"'
    launch_snapshot = 'id="miniapp-launch-snapshot"'
    max_bridge = 'src="https://st.max.ru/js/max-web-app.js"'
    telegram_bootstrap = 'id="telegram-early-ready"'

    assert telegram_sdk in layout
    assert launch_snapshot in layout
    assert max_bridge in layout
    assert telegram_bootstrap in layout
    assert layout.index(telegram_sdk) < layout.index(launch_snapshot)
    assert layout.index(launch_snapshot) < layout.index(max_bridge)
    assert layout.index(max_bridge) < layout.index(telegram_bootstrap)
    assert layout.index("var telegramWebApp") < layout.index("var maxWebApp")
    assert "window.WebApp" in layout
    assert "__BANANO_MAX_INIT_DATA__" in layout


def test_frontend_api_understands_max_webappdata_but_prefers_telegram() -> None:
    api = (MINIAPP / "lib" / "api.ts").read_text()

    assert "getMiniAppPlatform" in api
    telegram_probe = "if (window.Telegram?.WebApp?.initData || params.get('tgWebAppData')) return 'telegram'"
    max_probe = "if (window.WebApp?.initData || params.get('WebAppData')) return 'max'"
    assert telegram_probe in api
    assert max_probe in api
    assert api.index(telegram_probe) < api.index(max_probe)
    assert "WebAppStartParam" in api
    assert "window.WebApp" in api
    assert "platform: getMiniAppPlatform()" in api


def test_server_injection_does_not_overwrite_early_launch_snapshot() -> None:
    miniapp = (ROOT / "bot" / "miniapp.py").read_text()

    assert "existing=window.__BANANO_INITIAL_LAUNCH__" in miniapp
    assert "if(existing&&(existing.hash||existing.search)){return;}" in miniapp
    assert '"initial_hash_len"' in miniapp
    assert '"max_init_data_len"' in miniapp


def test_max_payment_path_does_not_offer_telegram_stars_unconditionally() -> None:
    balance = (MINIAPP / "components" / "balance-sheet.tsx").read_text()
    payment_api = (MINIAPP / "lib" / "payment-api.ts").read_text()

    assert "const isMax = platform === 'max'" in balance
    assert "!isMax" in balance
    assert "platform: getMiniAppPlatform()" in payment_api
