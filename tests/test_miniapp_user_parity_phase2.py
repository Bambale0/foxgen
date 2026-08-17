from pathlib import Path


MINIAPP = Path(__file__).resolve().parents[1] / "src" / "foxgen" / "miniapp_static"


def test_failed_and_cancelled_generations_get_retry_action() -> None:
    script = (MINIAPP / "user-parity-phase2.js").read_text(encoding="utf-8")

    assert ".status-badge.failed, .status-badge.cancelled" in script
    assert "button.dataset.repeatGeneration = generationId" in script
    assert "Повторить после ошибки" in script


def test_studio_fails_closed_when_price_is_missing() -> None:
    script = (MINIAPP / "user-parity-phase2.js").read_text(encoding="utf-8")

    assert "cost <= 0" in script
    assert "submit.disabled = true" in script
    assert "Цена не опубликована" in script
    assert "активной серверной цены" in script


def test_studio_surfaces_insufficient_balance_and_real_topup_action() -> None:
    script = (MINIAPP / "user-parity-phase2.js").read_text(encoding="utf-8")

    assert "available < cost" in script
    assert "Недостаточно CREDIT" in script
    assert "data-stars-topup" in script
    assert "Пополнить баланс" in script
