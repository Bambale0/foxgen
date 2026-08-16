import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from foxgen.application.submissions import NoopSubmissionRateLimiter, SubmissionService
from foxgen.core.errors import ErrorCode, SubmissionError
from foxgen.domain.models import GenerationStatus, LedgerEntryType, MediaKind, ReservationStatus
from foxgen.infra.billing_models import BalanceReservation, LedgerEntry, ModelPrice, WalletAccount
from foxgen.infra.database import Database, Generation, OutboxEvent, User
from foxgen.infra.repositories import SqlAlchemyGenerationRepository

pytestmark = pytest.mark.skipif(
    os.getenv("FOXGEN_RUN_INTEGRATION") != "1",
    reason="real infrastructure tests are enabled only in the CI infrastructure job",
)


MODEL_SLUG = "suno-v5"


def payload() -> dict[str, object]:
    return {
        "custom_mode": True,
        "instrumental": False,
        "prompt": "[Verse] City lights and empty roads",
        "style": "indie pop, warm female vocal",
        "title": "Last Train",
        "negative_tags": "metal",
    }


@pytest.mark.asyncio
async def test_suno_without_active_price_rolls_back_generation_and_outbox() -> None:
    database = Database(os.environ["FOXGEN_DATABASE_URL"])
    user_id = 942_000_000 + uuid4().int % 1_000_000
    idempotency_key = f"suno-no-price-{uuid4()}"
    service = SubmissionService(
        repository=SqlAlchemyGenerationRepository(database),
        rate_limiter=NoopSubmissionRateLimiter(),
    )

    try:
        async with database.session() as session:
            outbox_before = int(await session.scalar(select(func.count(OutboxEvent.id))) or 0)

        with pytest.raises(SubmissionError) as error:
            await service.submit(
                user_id=user_id,
                username="suno-no-price",
                model_slug=MODEL_SLUG,
                input_data=payload(),
                idempotency_key=idempotency_key,
            )
        assert error.value.code == ErrorCode.PRICING_UNAVAILABLE

        async with database.session() as session:
            generation = await session.scalar(
                select(Generation).where(
                    Generation.user_id == user_id,
                    Generation.idempotency_key == idempotency_key,
                )
            )
            outbox_after = int(await session.scalar(select(func.count(OutboxEvent.id))) or 0)
            assert generation is None
            assert await session.get(User, user_id) is None
            assert outbox_after == outbox_before
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_suno_price_wallet_reservation_and_outbox_are_exactly_once() -> None:
    database = Database(os.environ["FOXGEN_DATABASE_URL"])
    user_id = 943_000_000 + uuid4().int % 1_000_000
    idempotency_key = f"suno-paid-{uuid4()}"
    service = SubmissionService(
        repository=SqlAlchemyGenerationRepository(database),
        rate_limiter=NoopSubmissionRateLimiter(),
    )
    price_id = None

    try:
        async with database.session() as session:
            async with session.begin():
                latest = int(
                    await session.scalar(
                        select(func.max(ModelPrice.version)).where(
                            ModelPrice.model_slug == MODEL_SLUG
                        )
                    )
                    or 0
                )
                user = User(id=user_id, username="suno-paid")
                session.add(user)
                await session.flush()
                wallet = WalletAccount(
                    user_id=user_id,
                    currency="CREDIT",
                    available_units=200,
                    reserved_units=0,
                    version=0,
                )
                price = ModelPrice(
                    model_slug=MODEL_SLUG,
                    version=latest + 1,
                    amount_units=55,
                    currency="CREDIT",
                    enabled=True,
                    metadata_json={"test": "suno-core"},
                )
                session.add_all([wallet, price])
                await session.flush()
                price_id = price.id

        first = await service.submit(
            user_id=user_id,
            username="suno-paid",
            model_slug=MODEL_SLUG,
            input_data=payload(),
            idempotency_key=idempotency_key,
        )
        replay = await service.submit(
            user_id=user_id,
            username="suno-paid",
            model_slug=MODEL_SLUG,
            input_data=payload(),
            idempotency_key=idempotency_key,
        )

        assert first.status == GenerationStatus.QUEUED
        assert first.replayed is False
        assert replay.generation_id == first.generation_id
        assert replay.replayed is True

        async with database.session() as session:
            generation = await session.get(Generation, first.generation_id)
            wallet = await session.get(WalletAccount, user_id)
            reservation = await session.scalar(
                select(BalanceReservation).where(
                    BalanceReservation.generation_id == first.generation_id
                )
            )
            reserve_entries = (
                await session.scalars(
                    select(LedgerEntry).where(
                        LedgerEntry.generation_id == first.generation_id,
                        LedgerEntry.entry_type == LedgerEntryType.RESERVE,
                    )
                )
            ).all()
            outbox = (
                await session.scalars(
                    select(OutboxEvent).where(
                        OutboxEvent.aggregate_id == first.generation_id,
                        OutboxEvent.event_type == "generation.submit",
                    )
                )
            ).all()

            assert generation is not None
            assert generation.media_kind == MediaKind.AUDIO
            assert generation.model_slug == MODEL_SLUG
            assert generation.input_payload == payload()
            assert wallet is not None
            assert wallet.available_units == 145
            assert wallet.reserved_units == 55
            assert reservation is not None
            assert reservation.amount_units == 55
            assert reservation.status == ReservationStatus.RESERVED
            assert len(reserve_entries) == 1
            assert reserve_entries[0].available_delta == -55
            assert reserve_entries[0].reserved_delta == 55
            assert len(outbox) == 1
    finally:
        async with database.session() as session:
            async with session.begin():
                await session.execute(delete(User).where(User.id == user_id))
                if price_id is not None:
                    await session.execute(delete(ModelPrice).where(ModelPrice.id == price_id))
        await database.close()
