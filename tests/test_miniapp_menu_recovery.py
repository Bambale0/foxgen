from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "miniapp"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_react_state_owner_replaces_dom_menu_recovery_layer() -> None:
    context = read(FRONTEND / "lib" / "app-context.tsx")
    nav = read(FRONTEND / "components" / "tab-nav.tsx")
    content = read(FRONTEND / "components" / "tab-content.tsx")

    assert "createContext" in context
    assert "activeTab" in context
    assert "selectedModel" in context
    assert "setActiveTab" in context
    assert "onClick={() => setActiveTab(tab.id)}" in nav
    assert "activeTab" in content

    source = "\n".join((context, nav, content))
    assert "MutationObserver" not in source
    assert "menu-recovery.js" not in source
    assert "document.createElement" not in nav


def test_model_availability_comes_from_backend_bootstrap() -> None:
    models = read(FRONTEND / "components" / "tabs" / "models-tab.tsx")
    create = read(FRONTEND / "components" / "tabs" / "create-tab.tsx")

    assert "bootstrap?.models" in models
    assert "bootstrap?.prices" in models
    assert "bootstrap?.models" in create
    assert "selectModel(model)" in models
    assert "selectModel(model)" in create


def test_motion_keeps_its_dedicated_owner_flow() -> None:
    special = read(FRONTEND / "components" / "special-model-form.tsx")

    assert "kling-3-motion-control" in special
    assert "uploadMotion('image'" in special
    assert "uploadMotion('video'" in special
    assert "submitMotion" in special
