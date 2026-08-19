from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "miniapp"
HOME = FRONTEND / "components" / "tabs" / "home-tab.tsx"
MODELS = FRONTEND / "components" / "tabs" / "models-tab.tsx"
SERVICES = FRONTEND / "components" / "tabs" / "services-tab.tsx"
CSS = FRONTEND / "app" / "globals.css"


def test_home_keeps_polished_create_first_information_architecture() -> None:
    source = HOME.read_text(encoding="utf-8")

    for label in (
        "Что создаём",
        "Создать изображение",
        "Создать видео",
        "Быстрый доступ",
        "Мои работы",
        "Сообщество",
        "Баланс",
        "Референсы",
        "Партнёры",
        "Поддержка",
        "Популярные модели",
        "Недавние работы",
    ):
        assert label in source


def test_model_catalog_is_backend_driven() -> None:
    source = MODELS.read_text(encoding="utf-8")

    assert "bootstrap?.models" in source
    assert "bootstrap?.prices" in source
    assert "selectModel(model)" in source
    assert "hardcodedModels" not in source
    assert "api.kie.ai" not in source
    assert "KIE_API_KEY" not in source


def test_services_surface_all_non_generation_user_domains() -> None:
    source = SERVICES.read_text(encoding="utf-8")

    for label in (
        "Баланс и Stars",
        "Сообщество",
        "Референсы",
        "Тарифы",
        "Партнёры",
        "Поддержка",
    ):
        assert label in source
    assert "openWorkspace(item.id)" in source


def test_mobile_navigation_has_six_equal_product_destinations() -> None:
    css = CSS.read_text(encoding="utf-8")
    assert "grid-template-columns:repeat(6,1fr)" in css
