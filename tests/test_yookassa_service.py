import asyncio
from decimal import Decimal

from bot.config import config
from bot.services.yookassa_service import (
    YooKassaService,
    _idempotence_key,
    normalize_amount,
)


def _service(monkeypatch) -> YooKassaService:
    monkeypatch.setattr(config, "YOOKASSA_SHOP_ID", "shop-1")
    monkeypatch.setattr(config, "YOOKASSA_SECRET_KEY", "secret-1")
    monkeypatch.setattr(config, "YOOKASSA_API_BASE_URL", "https://api.yookassa.ru/v3")
    monkeypatch.setattr(config, "YOOKASSA_REQUEST_TIMEOUT_SECONDS", 30)
    monkeypatch.setattr(config, "YOOKASSA_RETURN_URL", "https://happyfox.example/mini-app/")
    return YooKassaService()


def test_normalize_amount_is_stable() -> None:
    assert normalize_amount(100) == "100.00"
    assert normalize_amount(Decimal("100.005")) == "100.01"


def test_idempotence_key_is_stable_per_order() -> None:
    first = _idempotence_key("order-1")
    assert first == _idempotence_key("order-1")
    assert first != _idempotence_key("order-2")
    assert len(first) == 36


def test_create_payment_uses_redirect_capture_and_order_metadata(monkeypatch) -> None:
    service = _service(monkeypatch)
    captured = {}

    async def fake_request(method, endpoint, *, json_payload=None, idempotence_key=None):
        captured.update(
            method=method,
            endpoint=endpoint,
            payload=json_payload,
            idempotence_key=idempotence_key,
        )
        return {
            "id": "pay-1",
            "status": "pending",
            "confirmation": {"confirmation_url": "https://yookassa.test/pay-1"},
            "metadata": {"order_id": "order-1"},
        }

    service._request = fake_request  # type: ignore[method-assign]
    result = asyncio.run(
        service.create_payment(
            amount_rub=150,
            order_id="order-1",
            description="HappyFox credits",
            return_url="https://happyfox.example/mini-app/",
        )
    )

    assert result and result["Success"] is True
    assert result["PaymentId"] == "pay-1"
    assert result["PaymentURL"] == "https://yookassa.test/pay-1"
    assert captured["method"] == "POST"
    assert captured["endpoint"] == "payments"
    assert captured["payload"]["capture"] is True
    assert captured["payload"]["amount"] == {"value": "150.00", "currency": "RUB"}
    assert captured["payload"]["metadata"]["order_id"] == "order-1"
    assert captured["idempotence_key"] == _idempotence_key("order-1")


def test_succeeded_payment_is_rejected_on_amount_mismatch(monkeypatch) -> None:
    service = _service(monkeypatch)

    async def fake_request(method, endpoint, *, json_payload=None, idempotence_key=None):
        assert method == "GET"
        return {
            "id": "pay-1",
            "status": "succeeded",
            "paid": True,
            "amount": {"value": "999.00", "currency": "RUB"},
            "metadata": {"order_id": "order-1"},
        }

    async def fake_local(**_kwargs):
        return {
            "order_id": "order-1",
            "payment_id": "pay-1",
            "provider": "yookassa",
            "amount_rub": 150.0,
            "status": "pending",
        }

    service._request = fake_request  # type: ignore[method-assign]
    service._local_transaction_for_payment = fake_local  # type: ignore[method-assign]
    payment = asyncio.run(service.get_payment("pay-1"))

    assert payment
    assert payment["paid"] is False
    assert payment["status"] == "verification_failed"
    assert payment["verification_error"] == "amount_mismatch"


def test_succeeded_payment_is_accepted_after_local_cross_check(monkeypatch) -> None:
    service = _service(monkeypatch)

    async def fake_request(method, endpoint, *, json_payload=None, idempotence_key=None):
        assert method == "GET"
        return {
            "id": "pay-1",
            "status": "succeeded",
            "paid": True,
            "amount": {"value": "150.00", "currency": "RUB"},
            "metadata": {"order_id": "order-1"},
        }

    async def fake_local(**_kwargs):
        return {
            "order_id": "order-1",
            "payment_id": "pay-1",
            "provider": "yookassa",
            "amount_rub": 150.0,
            "status": "pending",
        }

    service._request = fake_request  # type: ignore[method-assign]
    service._local_transaction_for_payment = fake_local  # type: ignore[method-assign]
    payment = asyncio.run(service.get_payment("pay-1"))

    assert payment
    assert payment["paid"] is True
    assert payment["status"] == "succeeded"
    assert payment["verification_error"] is None
