from unittest.mock import AsyncMock
import pytest
from bot.services.yookassa_service import YooKassaService
from bot.max_payments import MaxPaymentOrder, MaxYooKassaService


@pytest.mark.asyncio
async def test_authorized_but_uncaptured_payment_is_not_creditable(monkeypatch):
    remote = {
        "id": "p",
        "status": "waiting_for_capture",
        "paid": True,
        "amount": {"value": "250.00", "currency": "RUB"},
        "metadata": {
            "order_id": "max_audit",
            "product": "happyfox-max",
            "channel": "max",
            "max_user_id": "300",
        },
    }
    service = YooKassaService()
    service.enabled = True
    monkeypatch.setattr(service, "_request", AsyncMock(return_value=remote))
    monkeypatch.setattr(
        service,
        "_verify_success_against_local_ledger",
        AsyncMock(return_value=(True, None)),
    )
    assert not (await service.get_payment("p"))["paid"]
    order = MaxPaymentOrder(
        "max_audit", 300, "start", 25, 250, "yookassa", "p", None, "pending"
    )
    assert MaxYooKassaService._verification_state(order, remote)[0] == "pending"
