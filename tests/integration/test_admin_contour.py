import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from foxgen.admin.policy import ALL_SCOPES, AdminContext
from foxgen.admin.services import AdminServices
from foxgen.admin.worker import AdminWorker
from foxgen.core.errors import SubmissionError
from foxgen.domain.models import MediaKind
from foxgen.infra.admin_models import (
    AdminOutbox,
    NotificationDelivery,
    OperationEvent,
    PaymentEvent,
    SupportMessage,
    SupportOutbox,
    SupportTicket,
)
from foxgen.infra.billing_models import LedgerEntry
from foxgen.infra.database import Database, OutboxEvent, User
from foxgen.infra.repositories import SqlAlchemyGenerationRepository


pytestmark = pytest.mark.skipif(
    os.getenv("FOXGEN_RUN_INTEGRATION") != "1",
    reason="real infrastructure tests are enabled only in the CI infrastructure job",
)


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_text(self, recipient_id: int, text: str) -> int:
        self.sent.append((recipient_id, text))
        return 10_000 + len(self.sent)


def _context(admin_id: int, suffix: str) -> AdminContext:
    return AdminContext(
        user_id=admin_id,
        role="superadmin",
        scopes=ALL_SCOPES,
        request_id=f"integration-{suffix}-{uuid4()}",
    )


@pytest.mark.asyncio
async def test_balance_adjustment_idempotency_replays_without_double_credit() -> None:
    database = Database(os.environ["FOXGEN_DATABASE_URL"])
    services = AdminServices.build(database, bootstrap_superuser_ids=frozenset())
    context = _context(990_001, "balance")
    user_id = 991_001
    key = f"balance-{uuid4()}"
    try:
        first = await services.users.adjust_balance(
            context=context,
            user_id=user_id,
            amount_units=750,
            reason="integration funding",
            idempotency_key=key,
        )
        second = await services.users.adjust_balance(
            context=context,
            user_id=user_id,
            amount_units=750,
            reason="integration funding",
            idempotency_key=key,
        )

        assert first.replayed is False
        assert second.replayed is True
        assert first.payload == second.payload
        assert first.payload["available_units"] == 750

        async with database.session() as session:
            ledger_count = int(
                await session.scalar(
                    select(func.count(LedgerEntry.id)).where(
                        LedgerEntry.idempotency_key == f"admin-adjust:{context.user_id}:{key}"
                    )
                )
                or 0
            )
        assert ledger_count == 1
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_support_reply_is_outboxed_and_duplicate_key_does_not_duplicate_message() -> None:
    database = Database(os.environ["FOXGEN_DATABASE_URL"])
    services = AdminServices.build(database, bootstrap_superuser_ids=frozenset())
    context = _context(990_002, "support")
    user_id = 991_002
    key = f"reply-{uuid4()}"
    try:
        async with database.session() as session:
            async with session.begin():
                session.add(User(id=user_id, username="support-integration"))
                ticket = SupportTicket(user_id=user_id, subject="Integration support ticket")
                session.add(ticket)
                await session.flush()
                ticket_id = ticket.id

        first = await services.support.reply_ticket(
            context=context,
            ticket_id=ticket_id,
            body="Queued support response",
            idempotency_key=key,
        )
        second = await services.support.reply_ticket(
            context=context,
            ticket_id=ticket_id,
            body="Queued support response",
            idempotency_key=key,
        )

        assert first.replayed is False
        assert second.replayed is True
        async with database.session() as session:
            message_count = int(
                await session.scalar(
                    select(func.count(SupportMessage.id)).where(
                        SupportMessage.ticket_id == ticket_id,
                        SupportMessage.sender_kind == "admin",
                    )
                )
                or 0
            )
            outbox_count = int(
                await session.scalar(
                    select(func.count(SupportOutbox.id))
                    .join(
                        SupportMessage,
                        SupportMessage.id == SupportOutbox.message_id,
                    )
                    .where(SupportMessage.ticket_id == ticket_id)
                )
                or 0
            )
        assert message_count == 1
        assert outbox_count == 1
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_campaign_start_materializes_each_recipient_once() -> None:
    database = Database(os.environ["FOXGEN_DATABASE_URL"])
    services = AdminServices.build(database, bootstrap_superuser_ids=frozenset())
    context = _context(990_003, "campaign")
    recipients = [991_010, 991_011, 991_012]
    try:
        async with database.session() as session:
            async with session.begin():
                for user_id in recipients:
                    session.add(User(id=user_id, username=f"campaign-{user_id}"))

        created = await services.notifications.create_campaign(
            context=context,
            name="Integration campaign",
            message="Campaign message",
            segment={"user_ids": recipients},
            idempotency_key=f"create-{uuid4()}",
        )
        campaign_id = created.payload["campaign_id"]
        assert isinstance(campaign_id, str)

        start_key = f"start-{uuid4()}"
        first = await services.notifications.start_campaign(
            context=context,
            campaign_id=uuid4() if False else __import__("uuid").UUID(campaign_id),
            idempotency_key=start_key,
        )
        second = await services.notifications.start_campaign(
            context=context,
            campaign_id=__import__("uuid").UUID(campaign_id),
            idempotency_key=start_key,
        )
        assert first.replayed is False
        assert second.replayed is True
        assert first.payload["delivery_count"] == len(recipients)

        async with database.session() as session:
            count = int(
                await session.scalar(
                    select(func.count(NotificationDelivery.id)).where(
                        NotificationDelivery.campaign_id == __import__("uuid").UUID(campaign_id)
                    )
                )
                or 0
            )
        assert count == len(recipients)
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_payment_reprocess_worker_cannot_double_credit_completed_payment() -> None:
    database = Database(os.environ["FOXGEN_DATABASE_URL"])
    services = AdminServices.build(database, bootstrap_superuser_ids=frozenset())
    context = _context(990_004, "payment")
    sender = FakeSender()
    user_id = 991_020
    try:
        async with database.session() as session:
            async with session.begin():
                payment = PaymentEvent(
                    provider="integration",
                    external_id=f"payment-{uuid4()}",
                    user_id=user_id,
                    status="completed",
                    amount_units=425,
                    currency="CREDIT",
                    raw_payload={"verified": True},
                )
                session.add(payment)
                await session.flush()
                payment_id = payment.id

        queued = await services.payments.reprocess_payment(
            context=context,
            payment_id=payment_id,
            idempotency_key=f"reprocess-{uuid4()}",
        )
        assert queued.payload["queued"] is True

        worker = AdminWorker(
            database=database,
            sender=sender,
            worker_id="integration-admin-worker",
            batch_size=100,
            max_attempts=2,
        )
        await worker.run_once()

        no_second_credit = await services.payments.reprocess_payment(
            context=context,
            payment_id=payment_id,
            idempotency_key=f"reprocess-second-{uuid4()}",
        )
        assert no_second_credit.payload["already_credited"] is True
        assert no_second_credit.payload["queued"] is False

        async with database.session() as session:
            payment = await session.get(PaymentEvent, payment_id)
            assert payment is not None
            assert payment.credited_ledger_key is not None
            count = int(
                await session.scalar(
                    select(func.count(LedgerEntry.id)).where(
                        LedgerEntry.idempotency_key == payment.credited_ledger_key
                    )
                )
                or 0
            )
        assert count == 1
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_safe_operation_replay_creates_child_and_non_billable_outbox_once() -> None:
    database = Database(os.environ["FOXGEN_DATABASE_URL"])
    services = AdminServices.build(database, bootstrap_superuser_ids=frozenset())
    context = _context(990_005, "operation")
    sender = FakeSender()
    aggregate_id = uuid4()
    try:
        async with database.session() as session:
            async with session.begin():
                parent = OperationEvent(
                    operation_type="local.postprocess",
                    status="failed",
                    payload={
                        "event_type": "generation.archive",
                        "aggregate_id": str(aggregate_id),
                    },
                    created_by=None,
                )
                session.add(parent)
                await session.flush()
                parent_id = parent.id

        replay = await services.operations.replay(
            context=context,
            operation_id=parent_id,
            idempotency_key=f"replay-{uuid4()}",
        )
        child_id = replay.payload["operation_id"]
        assert isinstance(child_id, str)
        assert replay.payload["charged"] is False

        worker = AdminWorker(
            database=database,
            sender=sender,
            worker_id="integration-admin-replay-worker",
            batch_size=100,
            max_attempts=2,
        )
        await worker.run_once()

        async with database.session() as session:
            child = await session.get(OperationEvent, __import__("uuid").UUID(child_id))
            assert child is not None
            assert child.status == "completed"
            outbox_count = int(
                await session.scalar(
                    select(func.count(OutboxEvent.id)).where(
                        OutboxEvent.deduplication_key
                        == f"admin-replay:{child.id}:generation.archive"
                    )
                )
                or 0
            )
        assert outbox_count == 1
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_blocked_user_is_rejected_at_transactional_generation_admission() -> None:
    database = Database(os.environ["FOXGEN_DATABASE_URL"])
    services = AdminServices.build(database, bootstrap_superuser_ids=frozenset())
    repository = SqlAlchemyGenerationRepository(database)
    context = _context(990_006, "block")
    user_id = 991_030
    try:
        async with database.session() as session:
            async with session.begin():
                session.add(User(id=user_id, username="blocked-integration"))
        await services.users.block_user(
            context=context,
            user_id=user_id,
            reason="integration block",
            idempotency_key=f"block-{uuid4()}",
        )

        with pytest.raises(SubmissionError):
            await repository.admit(
                user_id=user_id,
                username="blocked-integration",
                idempotency_key=f"generation-{uuid4()}",
                request_hash="a" * 64,
                model_slug="seedream-5-pro",
                media_kind=MediaKind.IMAGE,
                prompt="blocked",
                input_payload={"prompt": "blocked"},
                source_publication_id=None,
                user_concurrency_limit=2,
                global_concurrency_limit=20,
            )
    finally:
        await database.close()
