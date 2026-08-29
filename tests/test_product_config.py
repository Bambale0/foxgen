from __future__ import annotations

import importlib

import pytest


def test_happyfox_is_default_product(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PRODUCT_ID", raising=False)
    import bot.product as product_module

    product_module = importlib.reload(product_module)
    assert product_module.product.product_id == "happyfox"
    assert product_module.product.brand_name == "HappyFox"
    assert "HappyFox" in product_module.product.welcome_text
    assert product_module.product.credit_emoji == "🐾"
    assert product_module.product.credit_short == "🐾"


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (1, "1 лапка"),
        (2, "2 лапки"),
        (4, "4 лапки"),
        (5, "5 лапок"),
        (11, "11 лапок"),
        (14, "14 лапок"),
        (21, "21 лапка"),
        (22, "22 лапки"),
        (25, "25 лапок"),
    ],
)
def test_happyfox_formats_paw_currency(amount: int, expected: str) -> None:
    from bot.product import product

    assert product.format_credits(amount) == expected


def test_source_product_profile_is_not_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRODUCT_ID", "neuromix")
    import bot.product as product_module

    with pytest.raises(RuntimeError, match="HappyFox-only"):
        importlib.reload(product_module)


def test_unknown_product_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRODUCT_ID", "unknown-product")
    import bot.product as product_module

    with pytest.raises(RuntimeError, match="Unsupported PRODUCT_ID"):
        importlib.reload(product_module)
