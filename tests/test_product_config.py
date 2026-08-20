from __future__ import annotations

import importlib

import pytest


def _reload_product(monkeypatch: pytest.MonkeyPatch, product_id: str):
    monkeypatch.setenv("PRODUCT_ID", product_id)
    import bot.product as product_module

    return importlib.reload(product_module)


def test_happyfox_is_default_product(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PRODUCT_ID", raising=False)
    import bot.product as product_module

    product_module = importlib.reload(product_module)
    assert product_module.product.product_id == "happyfox"
    assert product_module.product.brand_name == "HappyFox"
    assert "HappyFox" in product_module.product.welcome_text


def test_neuromix_remains_available_as_explicit_product(monkeypatch: pytest.MonkeyPatch) -> None:
    product_module = _reload_product(monkeypatch, "neuromix")
    assert product_module.product.product_id == "neuromix"
    assert product_module.product.brand_name == "NEUROMIX"


def test_unknown_product_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRODUCT_ID", "unknown-product")
    import bot.product as product_module

    with pytest.raises(RuntimeError, match="Unsupported PRODUCT_ID"):
        importlib.reload(product_module)
