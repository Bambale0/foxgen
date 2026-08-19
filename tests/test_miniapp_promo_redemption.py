from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "miniapp"


def test_promo_redemption_is_part_of_react_balance_workspace() -> None:
    workspace = (FRONTEND / "components" / "workspace-sheet.tsx").read_text(encoding="utf-8")

    assert 'data-testid="promo-redeem"' in workspace
    assert "Промокод" in workspace
    assert "Активировать" in workspace
    assert "'/promos/redeem'" in workspace
    assert "JSON.stringify({ code })" in workspace
    assert "reward_units" in workspace
    assert "available_units" in workspace
    assert "replayed" in workspace
    assert "refreshBootstrap" in workspace


def test_promo_redemption_uses_shared_authenticated_api_client() -> None:
    api = (FRONTEND / "lib" / "api.ts").read_text(encoding="utf-8")
    workspace = (FRONTEND / "components" / "workspace-sheet.tsx").read_text(encoding="utf-8")

    assert "headers.set('Authorization', `Bearer ${this.token}`)" in api
    assert "await this.authenticate()" in api
    assert "miniAppApi.request" in workspace
    assert "window.location.reload()" not in workspace
