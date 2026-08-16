import os

import pytest
from sqlalchemy import delete, func, select

from foxgen.core.errors import ErrorCode, SubmissionError
from foxgen.infra.admin_models import PaymentEvent, TariffVersion
from foxgen.infra.billing_models import LedgerEntry, WalletAccount
from foxgen.infra.database import Database, User
from foxgen.infra.payment_models import UserPaymentOrder
from foxgen.infra.payments import SqlAlchemyTelegramStarsPaymentService, TelegramStarsInvoiceClient

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
        assert len(title) <= 32
        assert len(description) <= 255
        self.calls.append((payload, stars_amount))
        return f"https://t.me/$test-{len(self.calls)}"


@pytest.mark.asyncio
async def test_telegram_stars_invoice_and_credit_are_durably_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Database(os.environ["FOXGEN_DATABASE_URL"])
    invoice_client = FakeInvoiceClient()
    service = SqlAlchemyTelegramStarsPaymentService(
        database,
        bot_token="test-token",
        invoice_client=invoice_client,
    )
    user_id = 910_000_097
    tariff_version = 900_097
    charge_id = "stars-charge-integration-97"
    failed_charge_id = "stars-charge-evidence-97"

    try:
        async with database.session() as session:
            async with session.begin():
                session.add(
                    TariffVersion(
                        version=tariff_version,
                        created_by=user_id,
                        payload={
                            "packages": {
                                "starter": {
                                    "title": "S" * 80,
                                    "description": "D" * 400,
                                    "credits": 1000,
                                    "price": 199,
                                    "stars": 50,
                                },
                                "legacy": {"credits": 500, "price": 99},
                            }
                        },
                    )
                )

        packages = await service.list_packages()
        assert [item.code for item in packages] == ["starter"]
        assert packages[0].credits_units == 1000
        assert packages[0].stars_amount == 50
        assert packages[0].title == "S" * 32
        assert packages[0].description == "D" * 255

        first = await service.create_invoice(
            user_id=user_id,
            username="stars-user",
            package_code="starter",
            idempotency_key="stars:invoice:97",
        )
        replay = await service.create_invoice(
            user_id=user_id,
            username="stars-user",
            package_code="starter",
            idempotency_key="stars:invoice:97",
        )
        assert replay.order_id == first.order_id
        assert replay.invoice_url == first.invoice_url
        assert replay.replayed is True
        assert len(invoice_client.calls) == 1

        valid = await service.validate_pre_checkout(
            user_id=user_id,
            invoice_payload=first.invoice_payload,
            currency="XTR",
            total_amount=50,
        )
        changed_amount = await service.validate_pre_checkout(
            user_id=user_id,
            invoice_payload=first.invoice_payload,
            currency="XTR",
            total_amount=51,
        )
        assert valid.ok is True
        assert changed_amount.ok is False

        credited = await service.credit_successful_payment(
            user_id=user_id,
            username="stars-user",
            invoice_payload=first.invoice_payload,
            currency="XTR",
            total_amount=50,
            telegram_payment_charge_id=charge_id,
            provider_payment_charge_id="",
            raw_payload={"telegram_payment_charge_id": charge_id},
        )
        duplicate = await service.credit_successful_payment(
            user_id=user_id,
            username="stars-user",
            invoice_payload=first.invoice_payload,
            currency="XTR",
            total_amount=50,
            telegram_payment_charge_id=charge_id,
            provider_payment_charge_id="",
            raw_payload={"telegram_payment_charge_id": charge_id},
        )
        assert credited.available_units == 1000
        assert duplicate.available_units == 1000
        assert duplicate.replayed is True

        async with database.session() as session:
            wallet = await session.get(WalletAccount, user_id)
            assert wallet is not None
            assert wallet.available_units == 1000
            ledger_count = await session.scalar(
                select(func.count()).select_from(LedgerEntry).where(LedgerEntry.user_id == user_id)
            )
            payment_count = await session.scalar(
                select(func.count())
                .select_from(PaymentEvent)
                .where(
                    PaymentEvent.provider == "telegram_stars",
                    PaymentEvent.external_id == charge_id,
                )
            )
            assert ledger_count == 1
            assert payment_count == 1

        evidence_invoice = await service.create_invoice(
            user_id=user_id,
            username="stars-user",
            package_code="starter",
            idempotency_key="stars:evidence:97",
        )

        async def fail_wallet(*args: object, **kwargs: object) -> object:
            del args, kwargs
            raise RuntimeError("simulated settlement boundary failure")

        monkeypatch.setattr("foxgen.infra.payments.ensure_wallet_locked", fail_wallet)
        with pytest.raises(RuntimeError, match="simulated settlement boundary failure"):
            await service.credit_successful_payment(
                user_id=user_id,
                username="stars-user",
                invoice_payload=evidence_invoice.invoice_payload,
                currency="XTR",
                total_amount=50,
                telegram_payment_charge_id=failed_charge_id,
                provider_payment_charge_id="",
                raw_payload={"telegram_payment_charge_id": failed_charge_id},
            )

        async with database.session() as session:
            evidence_payment = await session.scalar(
                select(PaymentEvent).where(
                    PaymentEvent.provider == "telegram_stars",
                    PaymentEvent.external_id == failed_charge_id,
                )
            )
            evidence_order = await session.get(UserPaymentOrder, evidence_invoice.order_id)
            assert evidence_payment is not None
            assert evidence_payment.status == "completed"
            assert evidence_payment.credited_ledger_key is None
            assert evidence_order is not None
            assert evidence_order.telegram_payment_charge_id == failed_charge_id
            assert evidence_order.paid_at is not None
            assert evidence_order.credited_at is None

        with pytest.raises(SubmissionError) as unavailable:
            await service.create_invoice(
                user_id=user_id,
                username="stars-user",
                package_code="legacy",
                idempotency_key="stars:legacy:97",
            )
        assert unavailable.value.code == ErrorCode.PRICING_UNAVAILABLE
    finally:
        async with database.session() as session:
            async with session.begin():
                await session.execute(
                    delete(UserPaymentOrder).where(UserPaymentOrder.user_id == user_id)
                )
                await session.execute(delete(PaymentEvent).where(PaymentEvent.user_id == user_id))
                await session.execute(delete(LedgerEntry).where(LedgerEntry.user_id == user_id))
                await session.execute(delete(WalletAccount).where(WalletAccount.user_id == user_id))
                await session.execute(delete(User).where(User.id == user_id))
                await session.execute(
                    delete(TariffVersion).where(TariffVersion.version == tariff_version)
                )
        await database.close()
