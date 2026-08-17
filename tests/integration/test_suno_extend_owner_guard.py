import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from foxgen.application.submissions import NoopSubmissionRateLimiter, SubmissionService
from foxgen.domain.models import GenerationStatus
from foxgen.infra.billing_models import BalanceReservation, LedgerEntry, ModelPrice, WalletAccount
from foxgen.infra.database import Database, Generation, OutboxEvent, User
from foxgen.infra.repositories import SqlAlchemyGenerationRepository

pytestmark = pytest.mark.skipif(
    os.getenv("FOXGEN_RUN_INTEGRATION") != "1",
    reason="real infrastructure tests are enabled only in the CI infrastructure job",
)


EXTEND_MODEL = "suno-v5-extend"


@pytest.mark.asyncio
async def test_generic_extend_cannot_reference_foreign_owned_suno_track() -> None:
    database = Database(os.environ["FOXGEN_DATABASE_URL"])
    owner_id = 944_000_000 + uuid4().int % 200_000
    foreign_id = owner_id + 300_000
    source_id = uuid4()
    price_id = None
    service = SubmissionService(
        repository=SqlAlchemyGenerationRepository(database),
        rate_limiter=NoopSubmissionRateLimiter(),
    )

    try:
        async with database.session() as session:
            async with session.begin():
                latest = int(
                    await session.scalar(
                        select(func.max(ModelPrice.version)).where(
                            ModelPrice.model_slug == EXTEND_MODEL
                        )
                    )
                    or 0
                )
                owner = User(id=owner_id, username="extend-owner")
                foreign = User(id=foreign_id, username="extend-foreign")
                session.add_all([owner, foreign])
                await session.flush()
                session.add(
                    Generation(
                        id=source_id,
                        user_id=owner_id,
                        idempotency_key=f"source-{source_id}",
                        request_hash=f"source-hash-{source_id}",
                        model_slug="suno-v5",
                        media_kind="audio",
                        prompt="source",
                        input_payload={"prompt": "source"},
                        status=GenerationStatus.SUCCEEDED,
                        result_payload={
                            "audioUrls": ["https://cdn.example.test/owned.mp3"],
                            "tracks": [
                                {
                                    "id": "owned-track-id",
                                    "title": "Owned track",
                                    "duration": 120.0,
                                }
                            ],
                        },
                    )
                )
                session.add(
                    WalletAccount(
                        user_id=foreign_id,
                        currency="CREDIT",
                        available_units=100,
                        reserved_units=0,
                        version=0,
                    )
                )
                price = ModelPrice(
                    model_slug=EXTEND_MODEL,
                    version=latest + 1,
                    amount_units=30,
                    currency="CREDIT",
                    enabled=True,
                    metadata_json={"test": "suno-extend-owner-guard"},
                )
                session.add(price)
                await session.flush()
                price_id = price.id

        async with database.session() as session:
            before_wallet = await session.get(WalletAccount, foreign_id)
            assert before_wallet is not None
            assert before_wallet.available_units == 100
            outbox_before = int(await session.scalar(select(func.count(OutboxEvent.id))) or 0)
            ledger_before = int(
                await session.scalar(
                    select(func.count(LedgerEntry.id)).where(LedgerEntry.user_id == foreign_id)
                )
                or 0
            )

        with pytest.raises(IntegrityError) as error:
            await service.submit(
                user_id=foreign_id,
                username="extend-foreign",
                model_slug=EXTEND_MODEL,
                input_data={
                    "source_generation_id": str(source_id),
                    "audio_id": "owned-track-id",
                    "default_param_flag": False,
                    "prompt": "",
                    "style": "",
                    "title": "",
                    "negative_tags": "",
                },
                idempotency_key=f"foreign-extend-{uuid4()}",
            )
        assert "Suno Extend source is not an owned succeeded Suno track" in str(error.value)

        async with database.session() as session:
            wallet = await session.get(WalletAccount, foreign_id)
            assert wallet is not None
            assert wallet.available_units == 100
            assert wallet.reserved_units == 0
            reservation_count = int(
                await session.scalar(
                    select(func.count(BalanceReservation.id)).where(
                        BalanceReservation.user_id == foreign_id
                    )
                )
                or 0
            )
            ledger_after = int(
                await session.scalar(
                    select(func.count(LedgerEntry.id)).where(LedgerEntry.user_id == foreign_id)
                )
                or 0
            )
            outbox_after = int(await session.scalar(select(func.count(OutboxEvent.id))) or 0)
            foreign_generation = await session.scalar(
                select(Generation).where(
                    Generation.user_id == foreign_id,
                    Generation.model_slug == EXTEND_MODEL,
                )
            )
            assert reservation_count == 0
            assert ledger_after == ledger_before
            assert outbox_after == outbox_before
            assert foreign_generation is None
    finally:
        async with database.session() as session:
            async with session.begin():
                await session.execute(delete(User).where(User.id.in_([owner_id, foreign_id])))
                if price_id is not None:
                    await session.execute(delete(ModelPrice).where(ModelPrice.id == price_id))
        await database.close()
