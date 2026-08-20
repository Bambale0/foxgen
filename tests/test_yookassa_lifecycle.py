from decimal import Decimal

from bot.payments.yookassa_lifecycle import (
    credits_from_metadata,
    is_successful_payment,
    normalize_yookassa_event,
)


def test_normalize_success_event():
    result = normalize_yookassa_event(
        {
            "id": "evt_1",
            "event": "payment.succeeded",
            "object": {
                "id": "pay_1",
                "status": "succeeded",
                "amount": {"value": "100.00"},
                "metadata": {"credits": "10"},
            },
        }
    )

    assert result["payment_id"] == "pay_1"
    assert result["amount_rub"] == Decimal("100.00")
    assert credits_from_metadata(result["metadata"]) == 10
    assert is_successful_payment(result["event_type"])
