import json
import os
import time
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select

from foxgen.admin.payment_refund_worker import (
    PaymentRefundWorker,
    RefundProviderResult,
)
from foxgen.admin.security import request_signature
from foxgen.admin.services import AdminServices
from foxgen.api.app import create_app
from foxgen.api.miniapp_security import TelegramMiniAppUser, issue_miniapp_token
from foxgen.core.config import Settings
from foxgen.infra.admin_models import PaymentEvent, TariffVersion
from foxgen.infra.billing_models import LedgerEntry, WalletAccount
from foxgen.infra.database import Database
from foxgen.infra.payment_models import UserPaymentOrder
from foxgen.infra.payment_refund_models import PaymentRefundAttempt
from foxgen.infra.payments import SqlAlchemyTelegramStarsPaymentService, TelegramStarsInvoiceClient

pytestmark = pytest.mark.skipif(
    os.getenv("FOXGEN_RUN_E2E") != "1",
    reason="cross-layer E2E tests run only in the CI infrastructure job",
)


ADMIN_ID = 996_000_001
INTERNAL_TOKEN = "e2e-internal-token-long-enough"
JWT_SECRET = "e2e-miniapp-jwt-secret-long-enough"
ADMIN_SECRET = "e2e-admin-hmac-secret-long-enough"


class FakeInvoiceClient(TelegramStarsInvoiceClient):
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    async def create_invoice_link(
        self,
        *,
        title: str,
        description: str,
        payload: str,
        stars_amount: int,
    ) -> str:
        del title, description
        self.calls.append((payload, stars_amount))
        return f"https://t.me/$e2e-stars-{len(self.calls)}"


class FakeRefundSender:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    async def refund(
        self,
        *,
        user_id: int,
        telegram_payment_charge_id: str,
    ) -> RefundProviderResult:
        self.calls.append((user_id, telegram_payment_charge_id))
        return RefundProviderResult(
            already_refunded=False,
            raw_payload={"telegram_status": "refunded", "e2e": True},
        )


def _settings() -> Settings:
    return Settings(
        env="test",
        miniapp_enabled=True,
        miniapp_jwt_secret=JWT_SECRET,
        internal_api_token=INTERNAL_TOKEN,
        admin_api_enabled=True,
        admin_web_enabled=False,
        admin_hmac_key=ADMIN_SECRET,
        admin_network_allowlist="127.0.0.1/32",
    )


def _miniapp_headers(user_id: int) -> dict[str, str]:
    token = issue_miniapp_token(
        TelegramMiniAppUser(id=user_id, first_name="E2E", username="e2e_stars"),
        secret=JWT_SECRET,
        ttl_seconds=3600,
    )
    return {"Authorization": f"Bearer {token}"}


def _internal_headers(user_id: int) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {INTERNAL_TOKEN}",
        "X-FoxGen-User-Id": str(user_id),
        "X-FoxGen-Username": "e2e_stars",
    }


def _admin_headers(*, path: str, raw_body: bytes, request_id: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    return {
        "Content-Type": "application/json",
        "X-Admin-User-Id": str(ADMIN_ID),
        "X-Request-Id": request_id,
        "X-Admin-Timestamp": timestamp,
        "X-Admin-Signature": request_signature(
            secret=ADMIN_SECRET,
            timestamp=timestamp,
            method="POST",
            path=path,
            request_id=request_id,
            raw_body=raw_body,
        ),
        "Idempotency-Key": f"e2e-refund-{uuid4()}",
        "X-Admin-Confirm": "CONFIRM",
    }


@pytest.mark.asyncio
async def test_happy_fox_stars_payment_to_admin_refund_e2e() -> None:
    database = Database(os.environ["FOXGEN_DATABASE_URL"])
    invoice_client = FakeInvoiceClient()
    stars_service = SqlAlchemyTelegramStarsPaymentService(
        database,
        bot_token="e2e-test-token",
        invoice_client=invoice_client,
    )
    admin_services = AdminServices.build(
        database,
        bootstrap_superuser_ids=frozenset({ADMIN_ID}),
    )
    settings = _settings()
    app = create_app(
        settings,
        manage_resources=False,
        admin_services=admin_services,
    )
    app.state.database = database
    app.state.telegram_stars_payment_service = stars_service

    user_id = 997_000_000 + uuid4().int % 1_000_000
    charge_id = f"e2e-charge-{uuid4()}"
    try:
        async with database.session() as session:
            async with session.begin():
                latest = int(await session.scalar(select(func.max(TariffVersion.version))) or 0)
                session.add(
                    TariffVersion(
                        version=latest + 1,
                        created_by=ADMIN_ID,
                        payload={
                            "packages": {
                                "e2e_starter": {
                                    "title": "E2E Starter",
                                    "description": "E2E 1000 CREDIT",
                                    "credits": 1000,
                                    "stars": 50,
                                }
                            }
                        },
                    )
                )

        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 32123))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            packages = await client.get(
                "/v1/miniapp/payments/stars/packages",
                headers=_miniapp_headers(user_id),
            )
            assert packages.status_code == 200
            assert packages.json()["items"] == [
                {
                    "code": "e2e_starter",
                    "title": "E2E Starter",
                    "description": "E2E 1000 CREDIT",
                    "credits_units": 1000,
                    "stars_amount": 50,
                    "currency": "XTR",
                }
            ]

            invoice = await client.post(
                "/v1/miniapp/payments/stars/invoices",
                headers=_miniapp_headers(user_id) | {"Idempotency-Key": f"e2e-invoice-{uuid4()}"},
                json={"package_code": "e2e_starter"},
            )
            assert invoice.status_code == 201
            invoice_payload = invoice.json()["invoice_payload"]
            assert invoice.json()["invoice_url"].startswith("https://t.me/$e2e-stars-")

            pre_checkout = await client.post(
                "/v1/user-portal/payments/stars/pre-checkout",
                headers=_internal_headers(user_id),
                json={
                    "invoice_payload": invoice_payload,
                    "currency": "XTR",
                    "total_amount": 50,
                },
            )
            assert pre_checkout.status_code == 200
            assert pre_checkout.json() == {"ok": True, "error_message": None}

            success = await client.post(
                "/v1/user-portal/payments/stars/success",
                headers=_internal_headers(user_id),
                json={
                    "invoice_payload": invoice_payload,
                    "currency": "XTR",
                    "total_amount": 50,
                    "telegram_payment_charge_id": charge_id,
                    "provider_payment_charge_id": "",
                },
            )
            assert success.status_code == 200
            assert success.json()["credited_units"] == 1000
            assert success.json()["available_units"] == 1000

            async with database.session() as session:
                payment = await session.scalar(
                    select(PaymentEvent).where(
                        PaymentEvent.provider == "telegram_stars",
                        PaymentEvent.external_id == charge_id,
                    )
                )
                assert payment is not None
                payment_id = payment.id

            refund_path = f"/internal/admin/payments/{payment_id}/refund"
            refund_body = json.dumps(
                {"reason": "E2E customer refund"},
                separators=(",", ":"),
            ).encode("utf-8")
            refund = await client.post(
                refund_path,
                content=refund_body,
                headers=_admin_headers(
                    path=refund_path,
                    raw_body=refund_body,
                    request_id=f"e2e-refund-request-{uuid4()}",
                ),
            )
            assert refund.status_code == 200
            assert refund.json()["status"] == "refund_pending"
            assert refund.json()["held_units"] == 1000

        async with database.session() as session:
            wallet = await session.get(WalletAccount, user_id)
            assert wallet is not None and wallet.available_units == 0
            attempt = await session.scalar(
                select(PaymentRefundAttempt).where(PaymentRefundAttempt.payment_id == payment_id)
            )
            assert attempt is not None and attempt.status == "pending"
            attempt_id = attempt.id

        refund_sender = FakeRefundSender()
        worker = PaymentRefundWorker(
            database=database,
            sender=refund_sender,
            worker_id="e2e-stars-refund-worker",
            max_attempts=2,
        )
        assert await worker.run_once() == 1
        assert refund_sender.calls == [(user_id, charge_id)]

        async with database.session() as session:
            payment = await session.get(PaymentEvent, payment_id)
            order = await session.scalar(
                select(UserPaymentOrder).where(
                    UserPaymentOrder.telegram_payment_charge_id == charge_id
                )
            )
            attempt = await session.get(PaymentRefundAttempt, attempt_id)
            wallet = await session.get(WalletAccount, user_id)
            assert payment is not None and payment.status == "refunded"
            assert order is not None and order.status == "refunded"
            assert attempt is not None and attempt.status == "succeeded"
            assert wallet is not None and wallet.available_units == 0

            credit_count = int(
                await session.scalar(
                    select(func.count(LedgerEntry.id)).where(
                        LedgerEntry.user_id == user_id,
                        LedgerEntry.available_delta == 1000,
                    )
                )
                or 0
            )
            refund_debit_count = int(
                await session.scalar(
                    select(func.count(LedgerEntry.id)).where(
                        LedgerEntry.user_id == user_id,
                        LedgerEntry.available_delta == -1000,
                    )
                )
                or 0
            )
            assert credit_count == 1
            assert refund_debit_count == 1
    finally:
        await database.close()
