import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from foxgen.admin.payment_refund_worker import (
    PaymentRefundWorker,
    RefundProviderResult,
    RetriablePaymentRefundError,
)
from foxgen.admin.policy import ALL_SCOPES, AdminContext
from foxgen.admin.services import AdminServices
from foxgen.infra.admin_models import PaymentEvent
from foxgen.infra.billing_models import LedgerEntry, WalletAccount
from foxgen.infra.database import Database, User
from foxgen.infra.payment_models import UserPaymentOrder
from foxgen.infra.payment_refund_models import PaymentRefundAttempt

pytestmark = pytest.mark.skipif(
    os.getenv("FOXGEN_RUN_INTEGRATION") != "1",
    reason="real infrastructure tests are enabled only in the CI infrastructure job",
)


class SuccessfulRefundSender:
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
            raw_payload={"telegram_status": "refunded"},
        )


class AmbiguousRefundSender:
    def __init__(self) -> None:
        self.calls = 0

    async def refund(
        self,
        *,
        user_id: int,
        telegram_payment_charge_id: str,
    ) -> RefundProviderResult:
        del user_id, telegram_payment_charge_id
        self.calls += 1
        raise RetriablePaymentRefundError("simulated ambiguous Telegram refund")


def _context(admin_id: int) -> AdminContext:
    return AdminContext(
        user_id=admin_id,
        role="superadmin",
        scopes=ALL_SCOPES,
        request_id=f"stars-refund-{uuid4()}",
    )


async def _seed_credited_stars_payment(
    database: Database,
    *,
    user_id: int,
) -> tuple[object, str, object]:
    charge_id = f"stars-refund-{uuid4()}"
    credit_key = f"payment-credit:telegram_stars:{charge_id}"
    async with database.session() as session:
        async with session.begin():
            session.add(User(id=user_id, username=f"refund-{user_id}"))
            # Flush the FK parent explicitly before append-only wallet/ledger audit rows.
            # These models intentionally do not rely on ORM relationships for insert ordering.
            await session.flush()
            session.add(
                WalletAccount(
                    user_id=user_id,
                    currency="CREDIT",
                    available_units=1000,
                    reserved_units=0,
                    version=1,
                )
            )
            session.add(
                LedgerEntry(
                    user_id=user_id,
                    generation_id=None,
                    reservation_id=None,
                    entry_type="credit",
                    currency="CREDIT",
                    available_delta=1000,
                    reserved_delta=0,
                    idempotency_key=credit_key,
                    actor="system:test",
                    reason="seed credited Telegram Stars payment",
                    metadata_json={"test": True},
                )
            )
            payment = PaymentEvent(
                provider="telegram_stars",
                external_id=charge_id,
                user_id=user_id,
                status="completed",
                amount_units=1000,
                currency="CREDIT",
                credited_ledger_key=credit_key,
                raw_payload={"verified": True},
            )
            session.add(payment)
            await session.flush()
            order = UserPaymentOrder(
                user_id=user_id,
                provider="telegram_stars",
                idempotency_key=f"seed-{uuid4()}",
                request_hash="a" * 64,
                package_code="starter",
                package_title="Starter",
                package_description="1000 CREDIT",
                credits_units=1000,
                provider_amount=50,
                provider_currency="XTR",
                invoice_payload=f"foxgen-stars:{uuid4()}",
                invoice_url="https://t.me/$seed-refund",
                status="credited",
                telegram_payment_charge_id=charge_id,
                provider_payment_charge_id="",
                raw_payment={"verified": True},
            )
            session.add(order)
            await session.flush()
            return payment.id, charge_id, order.id


@pytest.mark.asyncio
async def test_stars_refund_holds_credit_and_finishes_exactly_once() -> None:
    database = Database(os.environ["FOXGEN_DATABASE_URL"])
    services = AdminServices.build(database, bootstrap_superuser_ids=frozenset())
    sender = SuccessfulRefundSender()
    user_id = 992_000_000 + uuid4().int % 1_000_000
    admin_id = 993_000_001
    try:
        payment_id, charge_id, order_id = await _seed_credited_stars_payment(
            database,
            user_id=user_id,
        )
        key = f"refund-command-{uuid4()}"
        first = await services.payments.refund_payment(
            context=_context(admin_id),
            payment_id=payment_id,
            reason="customer requested refund",
            idempotency_key=key,
        )
        replay = await services.payments.refund_payment(
            context=_context(admin_id),
            payment_id=payment_id,
            reason="customer requested refund",
            idempotency_key=key,
        )
        assert first.replayed is False
        assert replay.replayed is True
        assert replay.payload == first.payload

        async with database.session() as session:
            wallet = await session.get(WalletAccount, user_id)
            order = await session.get(UserPaymentOrder, order_id)
            attempt = await session.scalar(
                select(PaymentRefundAttempt).where(PaymentRefundAttempt.payment_id == payment_id)
            )
            assert wallet is not None and wallet.available_units == 0
            assert order is not None and order.status == "refund_pending"
            assert attempt is not None and attempt.status == "pending"
            debit_count = int(
                await session.scalar(
                    select(func.count(LedgerEntry.id)).where(
                        LedgerEntry.idempotency_key == attempt.debit_ledger_key
                    )
                )
                or 0
            )
            assert debit_count == 1

        worker = PaymentRefundWorker(
            database=database,
            sender=sender,
            worker_id="integration-stars-refund",
            max_attempts=2,
        )
        assert await worker.run_once() == 1
        assert await worker.run_once() == 0
        assert sender.calls == [(user_id, charge_id)]

        async with database.session() as session:
            payment = await session.get(PaymentEvent, payment_id)
            order = await session.get(UserPaymentOrder, order_id)
            attempt = await session.scalar(
                select(PaymentRefundAttempt).where(PaymentRefundAttempt.payment_id == payment_id)
            )
            wallet = await session.get(WalletAccount, user_id)
            assert payment is not None and payment.status == "refunded"
            assert order is not None and order.status == "refunded"
            assert attempt is not None and attempt.status == "succeeded"
            assert wallet is not None and wallet.available_units == 0
            assert attempt.restore_ledger_key is None
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_ambiguous_stars_refund_keeps_hold_until_evidence_restores_once() -> None:
    database = Database(os.environ["FOXGEN_DATABASE_URL"])
    services = AdminServices.build(database, bootstrap_superuser_ids=frozenset())
    sender = AmbiguousRefundSender()
    user_id = 994_000_000 + uuid4().int % 1_000_000
    admin_id = 995_000_001
    try:
        payment_id, _charge_id, order_id = await _seed_credited_stars_payment(
            database,
            user_id=user_id,
        )
        await services.payments.refund_payment(
            context=_context(admin_id),
            payment_id=payment_id,
            reason="ambiguous refund test",
            idempotency_key=f"refund-unknown-{uuid4()}",
        )

        worker = PaymentRefundWorker(
            database=database,
            sender=sender,
            worker_id="integration-stars-refund-unknown",
            max_attempts=1,
        )
        assert await worker.run_once() == 1
        assert sender.calls == 1

        async with database.session() as session:
            wallet = await session.get(WalletAccount, user_id)
            order = await session.get(UserPaymentOrder, order_id)
            attempt = await session.scalar(
                select(PaymentRefundAttempt).where(PaymentRefundAttempt.payment_id == payment_id)
            )
            assert wallet is not None and wallet.available_units == 0
            assert order is not None and order.status == "refund_unknown"
            assert attempt is not None and attempt.status == "unknown"
            assert attempt.restore_ledger_key is None

        resolution_key = f"refund-resolution-{uuid4()}"
        resolved = await services.payments.resolve_refund(
            context=_context(admin_id),
            payment_id=payment_id,
            outcome="not_refunded",
            evidence="Telegram transaction history confirms no refund",
            idempotency_key=resolution_key,
        )
        replay = await services.payments.resolve_refund(
            context=_context(admin_id),
            payment_id=payment_id,
            outcome="not_refunded",
            evidence="Telegram transaction history confirms no refund",
            idempotency_key=resolution_key,
        )
        assert resolved.replayed is False
        assert replay.replayed is True
        assert replay.payload == resolved.payload

        async with database.session() as session:
            wallet = await session.get(WalletAccount, user_id)
            order = await session.get(UserPaymentOrder, order_id)
            payment = await session.get(PaymentEvent, payment_id)
            attempt = await session.scalar(
                select(PaymentRefundAttempt).where(PaymentRefundAttempt.payment_id == payment_id)
            )
            assert wallet is not None and wallet.available_units == 1000
            assert order is not None and order.status == "credited"
            assert payment is not None and payment.status == "completed"
            assert attempt is not None and attempt.status == "resolved_not_refunded"
            assert attempt.restore_ledger_key is not None
            restore_count = int(
                await session.scalar(
                    select(func.count(LedgerEntry.id)).where(
                        LedgerEntry.idempotency_key == attempt.restore_ledger_key
                    )
                )
                or 0
            )
            assert restore_count == 1
    finally:
        await database.close()
