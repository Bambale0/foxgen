import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from foxgen.application.submissions import NoopSubmissionRateLimiter, SubmissionService
from foxgen.infra.billing import SqlAlchemyBillingRepository
from foxgen.infra.billing_models import BalanceReservation, LedgerEntry, WalletAccount
from foxgen.infra.database import Database, Generation, OutboxEvent
from foxgen.infra.repositories import SqlAlchemyGenerationRepository

pytestmark = pytest.mark.skipif(
    os.getenv("FOXGEN_RUN_INTEGRATION") != "1",
    reason="real infrastructure tests are enabled only in CI",
)


MODEL = "suno-v5-upload-cover"


@pytest.mark.asyncio
async def test_generic_submit_cannot_cover_foreign_input_and_money_rolls_back() -> None:
    database = Database(os.environ["FOXGEN_DATABASE_URL"])
    billing = SqlAlchemyBillingRepository(database)
    service = SubmissionService(
        repository=SqlAlchemyGenerationRepository(database),
        rate_limiter=NoopSubmissionRateLimiter(),
    )
    owner_id = 812_000_000 + uuid4().int % 100_000
    attacker_id = owner_id + 200_000
    idempotency_key = f"cover-forged-{uuid4()}"
    await billing.set_model_price(
        model_slug=MODEL,
        amount_units=25,
        currency="CREDIT",
        active_from=datetime.now(timezone.utc),
        active_until=None,
        metadata={"test": "cover-owner-guard"},
    )
    await billing.adjust_balance(
        user_id=attacker_id,
        username="cover_attacker",
        amount_units=100,
        idempotency_key=f"cover-guard-credit-{attacker_id}",
        actor="test",
        reason="owner guard starting balance",
    )

    try:
        with pytest.raises(IntegrityError) as error:
            await service.submit(
                user_id=attacker_id,
                username="cover_attacker",
                model_slug=MODEL,
                input_data={
                    "input_storage_key": f"inputs/{owner_id}/source.mp3",
                    "custom_mode": False,
                    "instrumental": False,
                    "prompt": "dream pop cover",
                },
                idempotency_key=idempotency_key,
            )
        assert "Suno Upload & Cover input is not owned by generation user" in str(error.value)

        async with database.session() as session:
            wallet = await session.get(WalletAccount, attacker_id)
            generation_count = int(
                await session.scalar(
                    select(func.count(Generation.id)).where(
                        Generation.user_id == attacker_id,
                        Generation.idempotency_key == idempotency_key,
                    )
                )
                or 0
            )
            reservation_count = int(
                await session.scalar(
                    select(func.count(BalanceReservation.id)).where(
                        BalanceReservation.user_id == attacker_id
                    )
                )
                or 0
            )
            submit_outbox_count = int(
                await session.scalar(
                    select(func.count(OutboxEvent.id)).where(
                        OutboxEvent.event_type == "generation.submit",
                        OutboxEvent.payload["user_id"].astext == str(attacker_id),
                    )
                )
                or 0
            )
            generation_ledger_count = int(
                await session.scalar(
                    select(func.count(LedgerEntry.id)).where(
                        LedgerEntry.user_id == attacker_id,
                        LedgerEntry.generation_id.is_not(None),
                    )
                )
                or 0
            )
            assert wallet is not None
            assert wallet.available_units == 100
            assert wallet.reserved_units == 0
            assert generation_count == 0
            assert reservation_count == 0
            assert submit_outbox_count == 0
            assert generation_ledger_count == 0
    finally:
        await database.close()
