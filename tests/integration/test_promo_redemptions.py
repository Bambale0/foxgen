import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from foxgen.core.errors import SubmissionError
from foxgen.infra.admin_models import PromoCode
from foxgen.infra.billing_models import LedgerEntry, WalletAccount
from foxgen.infra.database import Database, User
from foxgen.infra.promo_models import PromoRedemption
from foxgen.infra.promos import SqlAlchemyPromoRedemptionService

pytestmark = pytest.mark.skipif(
    os.getenv("FOXGEN_RUN_INTEGRATION") != "1",
    reason="real infrastructure tests are enabled only in the CI infrastructure job",
)


@pytest.mark.asyncio
async def test_promo_redemption_is_exactly_once_and_max_uses_is_atomic() -> None:
    database = Database(os.environ["FOXGEN_DATABASE_URL"])
    service = SqlAlchemyPromoRedemptionService(database)
    code = f"E2E{uuid4().hex[:12].upper()}"
    first_user = 998_000_000 + uuid4().int % 500_000
    second_user = first_user + 500_001

    try:
        async with database.session() as session:
            async with session.begin():
                session.add(
                    PromoCode(
                        code=code,
                        active=True,
                        reward_units=750,
                        max_uses=1,
                        uses=0,
                        metadata_json={"integration": True},
                        created_by=1,
                    )
                )

        first, duplicate = await asyncio.gather(
            service.redeem(user_id=first_user, username="promo-first", code=code.lower()),
            service.redeem(user_id=first_user, username="promo-first", code=f"  {code}  "),
        )
        assert {first.replayed, duplicate.replayed} == {False, True}
        assert first.reward_units == duplicate.reward_units == 750
        assert first.available_units == duplicate.available_units == 750

        async with database.session() as session:
            promo = await session.get(PromoCode, code)
            wallet = await session.get(WalletAccount, first_user)
            redemption_count = int(
                await session.scalar(
                    select(func.count(PromoRedemption.id)).where(
                        PromoRedemption.promo_code == code,
                        PromoRedemption.user_id == first_user,
                    )
                )
                or 0
            )
            ledger_count = int(
                await session.scalar(
                    select(func.count(LedgerEntry.id)).where(
                        LedgerEntry.idempotency_key == f"promo-credit:{code}:{first_user}"
                    )
                )
                or 0
            )
            assert promo is not None and promo.uses == 1
            assert wallet is not None and wallet.available_units == 750
            assert redemption_count == 1
            assert ledger_count == 1

        with pytest.raises(SubmissionError, match="Лимит активаций"):
            await service.redeem(
                user_id=second_user,
                username="promo-second",
                code=code,
            )

        async with database.session() as session:
            second_wallet = await session.get(WalletAccount, second_user)
            second_redemption = await session.scalar(
                select(PromoRedemption).where(
                    PromoRedemption.promo_code == code,
                    PromoRedemption.user_id == second_user,
                )
            )
            promo = await session.get(PromoCode, code)
            assert second_wallet is None
            assert second_redemption is None
            assert promo is not None and promo.uses == 1
    finally:
        async with database.session() as session:
            async with session.begin():
                await session.execute(
                    delete(PromoRedemption).where(PromoRedemption.promo_code == code)
                )
                await session.execute(
                    delete(LedgerEntry).where(LedgerEntry.user_id.in_([first_user, second_user]))
                )
                await session.execute(
                    delete(WalletAccount).where(
                        WalletAccount.user_id.in_([first_user, second_user])
                    )
                )
                await session.execute(
                    delete(User).where(User.id.in_([first_user, second_user]))
                )
                await session.execute(delete(PromoCode).where(PromoCode.code == code))
        await database.close()
