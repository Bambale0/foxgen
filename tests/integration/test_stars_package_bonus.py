import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from foxgen.infra.admin_models import PaymentEvent, TariffVersion
from foxgen.infra.billing_models import LedgerEntry, WalletAccount
from foxgen.infra.database import Database, User
from foxgen.infra.payment_models import UserPaymentOrder
from foxgen.infra.payments import TelegramStarsInvoiceClient
from foxgen.infra.payments_bonus import BonusAwareTelegramStarsPaymentService

pytestmark = pytest.mark.skipif(
    os.getenv("FOXGEN_RUN_INTEGRATION") != "1",
    reason="real infrastructure tests are enabled only in the CI infrastructure job",
)


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
        return f"https://t.me/$bonus-integration-{len(self.calls)}"


@pytest.mark.asyncio
async def test_stars_package_bonus_is_snapshotted_and_settled_exactly_once() -> None:
    database = Database(os.environ["FOXGEN_DATABASE_URL"])
    invoice_client = FakeInvoiceClient()
    service = BonusAwareTelegramStarsPaymentService(
        database,
        bot_token="test-token",
        invoice_client=invoice_client,
    )
    user_id = 930_000_000 + uuid4().int % 1_000_000
    charge_id = f"stars-bonus-charge-{uuid4()}"
    created_versions: list[int] = []

    try:
        async with database.session() as session:
            async with session.begin():
                latest = int(await session.scalar(select(func.max(TariffVersion.version))) or 0)
                version = latest + 1
                created_versions.append(version)
                session.add(
                    TariffVersion(
                        version=version,
                        created_by=user_id,
                        payload={
                            "packages": {
                                "bonus": {
                                    "title": "Bonus pack",
                                    "credits_units": 1000,
                                    "bonus_units": 250,
                                    "stars_amount": 50,
                                },
                                "plain": {
                                    "credits_units": 500,
                                    "stars_amount": 30,
                                },
                                "negative_bonus": {
                                    "credits_units": 1000,
                                    "bonus_units": -1,
                                    "stars_amount": 40,
                                },
                                "bool_bonus": {
                                    "credits_units": 1000,
                                    "bonus_units": True,
                                    "stars_amount": 40,
                                },
                            }
                        },
                    )
                )

        packages = await service.list_packages()
        assert [item.code for item in packages] == ["plain", "bonus"]
        bonus_package = packages[1]
        assert bonus_package.resolved_base_credits_units == 1000
        assert bonus_package.bonus_units == 250
        assert bonus_package.total_credits_units == 1250
        assert bonus_package.credits_units == 1250
        assert "250" in bonus_package.description

        invoice = await service.create_invoice(
            user_id=user_id,
            username="bonus-user",
            package_code="bonus",
            idempotency_key=f"bonus-invoice-{uuid4()}",
        )
        assert invoice.package.total_credits_units == 1250
        assert invoice.package.bonus_units == 250
        assert invoice_client.calls == [(invoice.invoice_payload, 50)]

        async with database.session() as session:
            order = await session.get(UserPaymentOrder, invoice.order_id)
            assert order is not None
            assert order.credits_units == 1250
            assert order.bonus_units == 250

        async with database.session() as session:
            async with session.begin():
                latest = int(await session.scalar(select(func.max(TariffVersion.version))) or 0)
                changed_version = latest + 1
                created_versions.append(changed_version)
                session.add(
                    TariffVersion(
                        version=changed_version,
                        created_by=user_id,
                        payload={
                            "packages": {
                                "bonus": {
                                    "credits_units": 1000,
                                    "bonus_units": 999,
                                    "stars_amount": 50,
                                }
                            }
                        },
                    )
                )

        valid = await service.validate_pre_checkout(
            user_id=user_id,
            invoice_payload=invoice.invoice_payload,
            currency="XTR",
            total_amount=50,
        )
        assert valid.ok is True

        credited = await service.credit_successful_payment(
            user_id=user_id,
            username="bonus-user",
            invoice_payload=invoice.invoice_payload,
            currency="XTR",
            total_amount=50,
            telegram_payment_charge_id=charge_id,
            provider_payment_charge_id="",
            raw_payload={"telegram_payment_charge_id": charge_id},
        )
        replay = await service.credit_successful_payment(
            user_id=user_id,
            username="bonus-user",
            invoice_payload=invoice.invoice_payload,
            currency="XTR",
            total_amount=50,
            telegram_payment_charge_id=charge_id,
            provider_payment_charge_id="",
            raw_payload={"telegram_payment_charge_id": charge_id},
        )
        assert credited.credited_units == 1250
        assert credited.available_units == 1250
        assert replay.available_units == 1250
        assert replay.replayed is True

        async with database.session() as session:
            wallet = await session.get(WalletAccount, user_id)
            payment = await session.scalar(
                select(PaymentEvent).where(
                    PaymentEvent.provider == "telegram_stars",
                    PaymentEvent.external_id == charge_id,
                )
            )
            order = await session.get(UserPaymentOrder, invoice.order_id)
            ledger = await session.scalar(
                select(LedgerEntry).where(
                    LedgerEntry.idempotency_key
                    == f"payment-credit:telegram_stars:{charge_id}"
                )
            )
            assert wallet is not None and wallet.available_units == 1250
            assert payment is not None and payment.amount_units == 1250
            assert order is not None and order.bonus_units == 250
            assert order.credits_units == 1250
            assert ledger is not None and ledger.available_delta == 1250
    finally:
        async with database.session() as session:
            async with session.begin():
                await session.execute(delete(UserPaymentOrder).where(UserPaymentOrder.user_id == user_id))
                await session.execute(delete(PaymentEvent).where(PaymentEvent.user_id == user_id))
                await session.execute(delete(LedgerEntry).where(LedgerEntry.user_id == user_id))
                await session.execute(delete(WalletAccount).where(WalletAccount.user_id == user_id))
                await session.execute(delete(User).where(User.id == user_id))
                if created_versions:
                    await session.execute(
                        delete(TariffVersion).where(TariffVersion.version.in_(created_versions))
                    )
        await database.close()
