from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from foxgen.bot.api_client import FoxGenApiClient, FoxGenApiError
from foxgen.bot.payments import apply_stars_payment, validate_stars_pre_checkout


@pytest.mark.asyncio
async def test_pre_checkout_accepts_backend_validated_order() -> None:
    query = SimpleNamespace(
        from_user=SimpleNamespace(id=42, username="fox"),
        invoice_payload="foxgen-stars:order",
        currency="XTR",
        total_amount=50,
        answer=AsyncMock(),
    )
    api_client = SimpleNamespace(
        _user_request=AsyncMock(return_value={"ok": True, "error_message": None})
    )

    await validate_stars_pre_checkout(cast(Any, query), cast(FoxGenApiClient, api_client))

    api_client._user_request.assert_awaited_once_with(
        "POST",
        "/v1/user-portal/payments/stars/pre-checkout",
        user_id=42,
        username="fox",
        json={
            "invoice_payload": "foxgen-stars:order",
            "currency": "XTR",
            "total_amount": 50,
        },
    )
    query.answer.assert_awaited_once_with(ok=True)


@pytest.mark.asyncio
async def test_pre_checkout_fails_closed_on_backend_error() -> None:
    query = SimpleNamespace(
        from_user=SimpleNamespace(id=42, username="fox"),
        invoice_payload="foxgen-stars:order",
        currency="XTR",
        total_amount=50,
        answer=AsyncMock(),
    )
    api_client = SimpleNamespace(
        _user_request=AsyncMock(
            side_effect=FoxGenApiError(
                "Проверка оплаты временно недоступна",
                status_code=503,
                retryable=True,
            )
        )
    )

    await validate_stars_pre_checkout(cast(Any, query), cast(FoxGenApiClient, api_client))

    query.answer.assert_awaited_once_with(
        ok=False,
        error_message="Проверка оплаты временно недоступна",
    )


@pytest.mark.asyncio
async def test_successful_payment_reports_backend_credit_projection() -> None:
    payment = SimpleNamespace(
        invoice_payload="foxgen-stars:order",
        currency="XTR",
        total_amount=50,
        telegram_payment_charge_id="tg-charge-42",
        provider_payment_charge_id="",
    )
    message = SimpleNamespace(
        successful_payment=payment,
        from_user=SimpleNamespace(id=42, username="fox"),
        answer=AsyncMock(),
    )
    api_client = SimpleNamespace(
        _user_request=AsyncMock(
            return_value={
                "order_id": "11111111-2222-3333-4444-555555555555",
                "available_units": 2500,
                "credited_units": 1000,
                "currency": "CREDIT",
                "replayed": True,
            }
        )
    )

    await apply_stars_payment(cast(Any, message), cast(FoxGenApiClient, api_client))

    api_client._user_request.assert_awaited_once_with(
        "POST",
        "/v1/user-portal/payments/stars/success",
        user_id=42,
        username="fox",
        json={
            "invoice_payload": "foxgen-stars:order",
            "currency": "XTR",
            "total_amount": 50,
            "telegram_payment_charge_id": "tg-charge-42",
            "provider_payment_charge_id": "",
        },
    )
    rendered = message.answer.await_args.args[0]
    assert "1000 CREDIT" in rendered
    assert "2500 CREDIT" in rendered
