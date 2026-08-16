from uuid import UUID

from fastapi.testclient import TestClient

from foxgen.api.app import create_app
from foxgen.api.miniapp_security import TelegramMiniAppUser, issue_miniapp_token
from foxgen.application.payments import (
    PreCheckoutDecision,
    StarInvoice,
    StarPackage,
    StarPaymentResult,
)
from foxgen.core.config import Settings


USER_ID = 123456798
INTERNAL_TOKEN = "stars-internal-token-long-enough"
JWT_SECRET = "stars-miniapp-jwt-secret-long-enough"
ORDER_ID = UUID("11111111-2222-3333-4444-555555555555")


class FakeStarsService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []
        self.package = StarPackage(
            code="starter",
            title="Starter",
            description="1000 credits",
            credits_units=1000,
            stars_amount=50,
        )

    async def list_packages(self) -> tuple[StarPackage, ...]:
        return (self.package,)

    async def create_invoice(
        self,
        *,
        user_id: int,
        username: str | None,
        package_code: str,
        idempotency_key: str,
    ) -> StarInvoice:
        del username
        self.calls.append((f"invoice:{package_code}:{idempotency_key}", user_id))
        return StarInvoice(
            order_id=ORDER_ID,
            package=self.package,
            invoice_payload=f"foxgen-stars:{ORDER_ID}",
            invoice_url="https://t.me/$invoice-test",
            replayed=False,
        )

    async def validate_pre_checkout(
        self,
        *,
        user_id: int,
        invoice_payload: str,
        currency: str,
        total_amount: int,
    ) -> PreCheckoutDecision:
        del invoice_payload, currency, total_amount
        self.calls.append(("pre_checkout", user_id))
        return PreCheckoutDecision(ok=True)

    async def credit_successful_payment(
        self,
        *,
        user_id: int,
        username: str | None,
        invoice_payload: str,
        currency: str,
        total_amount: int,
        telegram_payment_charge_id: str,
        provider_payment_charge_id: str,
        raw_payload: dict[str, object],
    ) -> StarPaymentResult:
        del (
            username,
            invoice_payload,
            currency,
            total_amount,
            telegram_payment_charge_id,
            provider_payment_charge_id,
            raw_payload,
        )
        self.calls.append(("success", user_id))
        return StarPaymentResult(
            order_id=ORDER_ID,
            available_units=1000,
            credited_units=1000,
            replayed=False,
        )


def settings() -> Settings:
    return Settings(
        env="test",
        miniapp_enabled=True,
        miniapp_jwt_secret=JWT_SECRET,
        internal_api_token=INTERNAL_TOKEN,
    )


def miniapp_headers() -> dict[str, str]:
    token = issue_miniapp_token(
        TelegramMiniAppUser(id=USER_ID, first_name="Stars", username="stars_user"),
        secret=JWT_SECRET,
        ttl_seconds=3600,
    )
    return {"Authorization": f"Bearer {token}"}


def internal_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {INTERNAL_TOKEN}",
        "X-FoxGen-User-Id": str(USER_ID),
        "X-FoxGen-Username": "stars_user",
    }


def client() -> tuple[TestClient, FakeStarsService]:
    service = FakeStarsService()
    app = create_app(settings(), manage_resources=False)
    app.state.telegram_stars_payment_service = service
    return TestClient(app), service


def test_miniapp_stars_packages_and_invoice_use_telegram_identity() -> None:
    test_client, service = client()
    with test_client:
        assert test_client.get("/v1/miniapp/payments/stars/packages").status_code == 401
        packages = test_client.get(
            "/v1/miniapp/payments/stars/packages",
            headers=miniapp_headers(),
        )
        missing_key = test_client.post(
            "/v1/miniapp/payments/stars/invoices",
            headers=miniapp_headers(),
            json={"package_code": "starter"},
        )
        invoice_headers = miniapp_headers() | {"Idempotency-Key": "stars:miniapp:invoice"}
        invoice = test_client.post(
            "/v1/miniapp/payments/stars/invoices",
            headers=invoice_headers,
            json={"package_code": "starter"},
        )

    assert packages.status_code == 200
    assert packages.json()["items"][0]["stars_amount"] == 50
    assert missing_key.status_code == 400
    assert invoice.status_code == 201
    assert invoice.json()["invoice_url"] == "https://t.me/$invoice-test"
    assert service.calls[-1][1] == USER_ID


def test_trusted_bot_payment_callbacks_are_owner_bound() -> None:
    test_client, service = client()
    headers = internal_headers()
    with test_client:
        assert (
            test_client.post(
                "/v1/user-portal/payments/stars/pre-checkout",
                headers={"Authorization": f"Bearer {INTERNAL_TOKEN}"},
                json={
                    "invoice_payload": f"foxgen-stars:{ORDER_ID}",
                    "currency": "XTR",
                    "total_amount": 50,
                },
            ).status_code
            == 401
        )
        pre_checkout = test_client.post(
            "/v1/user-portal/payments/stars/pre-checkout",
            headers=headers,
            json={
                "invoice_payload": f"foxgen-stars:{ORDER_ID}",
                "currency": "XTR",
                "total_amount": 50,
            },
        )
        success = test_client.post(
            "/v1/user-portal/payments/stars/success",
            headers=headers,
            json={
                "invoice_payload": f"foxgen-stars:{ORDER_ID}",
                "currency": "XTR",
                "total_amount": 50,
                "telegram_payment_charge_id": "tg-charge-1",
                "provider_payment_charge_id": "",
            },
        )

    assert pre_checkout.status_code == 200
    assert pre_checkout.json()["ok"] is True
    assert success.status_code == 200
    assert success.json()["available_units"] == 1000
    assert ("pre_checkout", USER_ID) in service.calls
    assert ("success", USER_ID) in service.calls
