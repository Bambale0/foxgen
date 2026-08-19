import shutil
import subprocess
from pathlib import Path

from foxgen.miniapp_release import MINIAPP_RELEASE

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "foxgen" / "miniapp_static"
HOME_JS = STATIC / "backend-parity-ui.js"
HOME_CSS = STATIC / "backend-parity.css"
INDEX = STATIC / "index.html"


def test_backend_parity_home_is_loaded_by_production_shell() -> None:
    html = INDEX.read_text(encoding="utf-8")

    assert f"/mini-app/backend-parity.css?v={MINIAPP_RELEASE}" in html
    assert f"/mini-app/backend-parity-ui.js?v={MINIAPP_RELEASE}" in html
    assert html.index("backend-parity-ui.js") < html.index("motion-control.js")
    assert "product-home" not in html


def test_backend_parity_home_exposes_primary_and_secondary_user_domains() -> None:
    source = HOME_JS.read_text(encoding="utf-8")

    for label in (
        "Главная",
        "Модели",
        "Создать",
        "Работы",
        "Баланс",
        "Профиль",
        "Сообщество",
        "Референсы",
        "Тарифы",
        "Партнёры",
        "Поддержка",
    ):
        assert label in source
    assert "Весь функционал" in source


def test_backend_parity_home_routes_private_input_products_to_dedicated_flows() -> None:
    source = HOME_JS.read_text(encoding="utf-8")

    assert "'kling-3-motion-control': '[data-motion-open]'" in source
    assert "'suno-v5-extend': '[data-suno-extend-open]'" in source
    assert "'suno-v5-upload-cover': '[data-suno-cover-action]'" in source
    assert "'suno-v5-upload-extend': '[data-suno-upload-extend-action]'" in source
    assert "SPECIAL_MODEL_OPENERS" in source


def test_backend_parity_home_is_server_driven_and_does_not_embed_provider_secrets() -> None:
    source = HOME_JS.read_text(encoding="utf-8")

    assert "bootstrap()?.models" in source
    assert "bootstrap()?.prices" in source
    assert "data-backend-model" in source
    assert "api.kie.ai" not in source
    assert "KIE_API_KEY" not in source
    assert "internal_api_token" not in source


def test_planned_tools_are_not_presented_as_primary_actions() -> None:
    css = HOME_CSS.read_text(encoding="utf-8")

    assert ".complete-tool.is-planned" in css
    assert "display:none!important" in css


def test_backend_parity_javascript_parses_when_node_is_available() -> None:
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
