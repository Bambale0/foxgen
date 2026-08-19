from pathlib import Path

from foxgen.miniapp_release import MINIAPP_RELEASE

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "miniapp"
COMPONENTS = FRONTEND / "components"
LIB = FRONTEND / "lib"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_happy_fox_uses_one_state_driven_application_shell() -> None:
    page = read(FRONTEND / "app" / "page.tsx")
    shell = read(COMPONENTS / "mini-app-shell.tsx")
    context = read(LIB / "app-context.tsx")

    assert "<MiniAppShell>" in page
    assert "<TabContent />" in page
    assert "<AppProvider>" in shell
    assert "<TabNav />" in shell
    assert "<WorkspaceSheet />" in shell
    assert "createContext" in context
    assert "activeTab" in context
    assert "selectedModel" in context
    assert "activeWorkspace" in context
    assert "MutationObserver" not in context


def test_bottom_navigation_changes_react_state_directly() -> None:
    nav = read(COMPONENTS / "tab-nav.tsx")
    content = read(COMPONENTS / "tab-content.tsx")

    for tab in ("home", "models", "create", "works", "services", "profile"):
        assert f"id: '{tab}'" in nav
    for label in ("Главная", "Модели", "Создать", "Работы", "Сервисы", "Профиль"):
        assert label in nav

    assert "onClick={() => setActiveTab(tab.id)}" in nav
    assert "button.click()" not in nav
    assert "document.createElement" not in nav
    assert "MutationObserver" not in nav

    for screen in ("ModelsTab", "CreateTab", "WorksTab", "ServicesTab", "ProfileTab", "HomeTab"):
        assert screen in content
    assert "activeTab" in content


def test_catalog_and_forms_are_backend_schema_driven() -> None:
    models = read(COMPONENTS / "tabs" / "models-tab.tsx")
    form = read(COMPONENTS / "model-form.tsx")
    context = read(LIB / "app-context.tsx")
    api = read(LIB / "api.ts")

    assert "bootstrap?.models" in models
    assert "bootstrap?.prices" in models
    assert "model.input_schema?.properties" in form
    assert "model.input_schema?.required" in form
    assert "model.defaults" in form
    assert "MEDIA_FIELDS" in form
    assert "uploadInput" in form
    assert "submitModel" in form
    assert "miniAppApi.validateModel(model.slug, input)" in context
    assert "miniAppApi.createTask(model.slug, validated.input)" in context

    for marker in (
        "/models/${encodeURIComponent(modelSlug)}/validate",
        "'/tasks'",
        "'/input-media'",
        "/generations?limit=${limit}",
        "'/balance'",
        "'/prices'",
        "/ledger?limit=${limit}",
        "Idempotency-Key",
    ):
        assert marker in api


def test_user_facing_backend_domains_have_real_client_routes() -> None:
    api = read(LIB / "api.ts")
    workspace = read(COMPONENTS / "workspace-sheet.tsx")
    profile = read(COMPONENTS / "tabs" / "profile-tab.tsx")
    works = read(COMPONENTS / "tabs" / "works-tab.tsx")

    for marker in (
        "/feed?sort=${encodeURIComponent(sort)}",
        "/publications/${encodeURIComponent(publicationId)}/like",
        "/reference-memory?limit=${limit}",
        "'/tariff'",
        "'/support'",
        "'/partner'",
        "'/payments/stars/packages'",
        "'/payments/stars/invoices'",
        "'/me/profile'",
    ):
        assert marker in api

    assert "Сообщество" in workspace
    assert "Референсы" in workspace
    assert "Тарифы" in workspace
    assert "Партнёры" in workspace
    assert "Поддержка" in workspace
    assert "Снять публикацию" in profile
    assert "Отменить" in works
    assert "В ленту" in works
    assert "В профиль" in works
    assert "/internal/admin" not in "\n".join((api, workspace, profile, works))


def test_private_input_models_use_dedicated_backend_workflows() -> None:
    special = read(COMPONENTS / "special-model-form.tsx")

    for slug in (
        "kling-3-motion-control",
        "suno-v5-extend",
        "suno-v5-upload-cover",
        "suno-v5-upload-extend",
    ):
        assert slug in special

    for endpoint in (
        "/motion/kling/inputs/",
        "'/motion/kling'",
        "'/music/suno/sources?limit=100'",
        "'/music/suno/extend'",
        "'/music/suno/upload-cover'",
        "'/music/suno/upload-extend'",
    ):
        assert endpoint in special or endpoint in read(LIB / "api.ts")


def test_release_marker_matches_bot_cache_buster() -> None:
    layout = read(FRONTEND / "app" / "layout.tsx")
    assert f'name="foxgen-miniapp-shell" content="{MINIAPP_RELEASE}"' in layout
