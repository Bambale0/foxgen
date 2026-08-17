import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "foxgen" / "miniapp_static"
HOME_JS = STATIC / "product-home.js"
HOME_CSS = STATIC / "product-home.css"
INDEX = STATIC / "index.html"


def test_catalog_home_is_loaded_by_production_shell() -> None:
    html = INDEX.read_text(encoding="utf-8")

    assert "/mini-app/product-home.css?v=parity-v3" in html
    assert "/mini-app/product-home.js?v=parity-v3" in html
    assert html.index("product-home.js") > html.index("motion-control.js")


def test_catalog_home_replaces_feed_tab_without_removing_community() -> None:
    source = HOME_JS.read_text(encoding="utf-8")

    assert "label.textContent = 'Каталог'" in source
    assert "data-home-community" in source
    assert "COMMUNITY / LIVE" in source
    assert "AI CATALOG / LIVE" in source
    assert "data-quick-start" in source
    assert 'data-nav="create"' in source
    assert 'data-nav="works"' in source
    assert 'data-nav="wallet"' in source
    assert 'data-nav="profile"' in source


def test_catalog_home_routes_private_input_products_to_dedicated_flows() -> None:
    source = HOME_JS.read_text(encoding="utf-8")

    assert "'kling-3-motion-control': '[data-motion-open]'" in source
    assert "'suno-v5-extend': '[data-suno-extend-open]'" in source
    assert "'suno-v5-upload-cover': '[data-suno-cover-action]'" in source
    assert "'suno-v5-upload-extend': '[data-suno-upload-extend-action]'" in source
    assert "data-home-special" in source


def test_catalog_home_is_server_driven_and_does_not_embed_provider_secrets() -> None:
    source = HOME_JS.read_text(encoding="utf-8")

    assert "api('/bootstrap')" in source
    assert "bootstrap?.models" in source
    assert "bootstrap?.prices" in source
    assert "api.kie.ai" not in source
    assert "KIE_API_KEY" not in source
    assert "internal_api_token" not in source


def test_planned_tools_are_not_presented_as_primary_actions() -> None:
    css = HOME_CSS.read_text(encoding="utf-8")

    assert ".complete-tool.is-planned{display:none}" in css


def test_catalog_home_javascript_parses_when_node_is_available() -> None:
    node = shutil.which("node")
    if node is None:
        return

    result = subprocess.run(
        [node, "--check", str(HOME_JS)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
