import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

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


MODEL_SLUG = "elevenlabs-turbo-2-5"


def payload() -> dict[str, object]:
    return {
        "text": "Привет. Это реальная проверка платной TTS admission.",
        "voice": "Rachel",
        "stability": 0.5,
        "similarity_boost": 0.75,
        "style": 0.0,
        "speed": 1.0,
        "timestamps": False,
        "previous_text": "",
        "next_text": "",
        "language_code": "ru",
    }


@pytest.mark.asyncio
async def test_tts_without_active_price_rolls_back_generation_and_outbox() -> None:
    database = Database(os.environ["FOXGEN_DATABASE_URL"])
    user_id = 940_000_000 + uuid4().int % 1_000_000
    idempotency_key = f"tts-no-price-{uuid4()}"
    service = SubmissionService(
        repository=SqlAlchemyGenerationRepository(database),
        rate_limiter=NoopSubmissionRateLimiter(),
    )

    try:
        with pytest.raises(SubmissionError) as error:
            await service.submit(
                user_id=user_id,
                username="tts-no-price",
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
            user = await session.get(User, user_id)
            outbox_count = int(
                await session.scalar(
                    select(func.count(OutboxEvent.id)).where(
                        OutboxEvent.event_type == "generation.submit",
                        OutboxEvent.payload["generation_id"].astext
                        == (str(generation.id) if generation is not None else "never"),
                    )
                )
                or 0
            )
            assert generation is None
            assert user is None
            assert outbox_count == 0
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_tts_price_wallet_reservation_and_outbox_are_exactly_once() -> None:
    database = Database(os.environ["FOXGEN_DATABASE_URL"])
    user_id = 941_000_000 + uuid4().int % 1_000_000
    idempotency_key = f"tts-paid-{uuid4()}"
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
                user = User(id=user_id, username="tts-paid")
                session.add(user)
                await session.flush()
                wallet = WalletAccount(
                    user_id=user_id,
                    currency="CREDIT",
                    available_units=100,
                    reserved_units=0,
                    version=0,
                )
                price = ModelPrice(
                    model_slug=MODEL_SLUG,
                    version=latest + 1,
                    amount_units=37,
                    currency="CREDIT",
                    enabled=True,
                    metadata_json={"test": "elevenlabs-tts"},
                )
                session.add_all([wallet, price])
                await session.flush()
                price_id = price.id

        first = await service.submit(
            user_id=user_id,
            username="tts-paid",
            model_slug=MODEL_SLUG,
            input_data=payload(),
            idempotency_key=idempotency_key,
        )
        replay = await service.submit(
            user_id=user_id,
            username="tts-paid",
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
            assert wallet.available_units == 63
            assert wallet.reserved_units == 37
            assert reservation is not None
            assert reservation.amount_units == 37
            assert reservation.status == ReservationStatus.RESERVED
            assert len(reserve_entries) == 1
            assert reserve_entries[0].available_delta == -37
            assert reserve_entries[0].reserved_delta == 37
            assert len(outbox) == 1
    finally:
        # The price snapshot is referenced by the durable reservation and must remain
        # available for audit. Disable the fixture so later tests cannot select it.
        if price_id is not None:
            async with database.session() as session:
                async with session.begin():
                    await session.execute(
                        update(ModelPrice).where(ModelPrice.id == price_id).values(enabled=False)
                    )
        await database.close()
