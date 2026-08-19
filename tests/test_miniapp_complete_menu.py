from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "miniapp"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_primary_product_menu_is_a_direct_react_navigation() -> None:
    nav = read(FRONTEND / "components" / "tab-nav.tsx")
    services = read(FRONTEND / "components" / "tabs" / "services-tab.tsx")

    for label in ("Главная", "Модели", "Создать", "Работы", "Сервисы", "Профиль"):
        assert label in nav
    for label in ("Баланс и Stars", "Сообщество", "Референсы", "Тарифы", "Партнёры", "Поддержка"):
        assert label in services

    assert "onClick={() => setActiveTab(tab.id)}" in nav
    assert "document.createElement" not in nav
    assert ".click()" not in nav


def test_wallet_topup_uses_authenticated_stars_invoice_flow() -> None:
    api = read(FRONTEND / "lib" / "api.ts")
    workspace = read(FRONTEND / "components" / "workspace-sheet.tsx")
    context = read(FRONTEND / "lib" / "app-context.tsx")

    assert "'/payments/stars/packages'" in api
    assert "'/payments/stars/invoices'" in api
    assert "Idempotency-Key" in api
    assert "package_code: packageCode" in api
    assert "openInvoice" in context
    assert "total_credits_units" in workspace
    assert "stars_amount" in workspace


def test_ready_generation_has_real_result_and_publication_actions() -> None:
    works = read(FRONTEND / "components" / "tabs" / "works-tab.tsx")

    assert "Открыть результат" in works
    assert "window.open" in works
    assert "В ленту" in works
    assert "В профиль" in works
    assert "Отменить" in works
