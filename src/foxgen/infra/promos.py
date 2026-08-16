from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from foxgen.application.promos import PromoRedemptionResult
from foxgen.core.errors import ErrorCode, SubmissionError
from foxgen.domain.models import LedgerEntryType
from foxgen.infra.admin_models import PromoCode
from foxgen.infra.billing import ensure_wallet_locked
from foxgen.infra.billing_models import LedgerEntry
from foxgen.infra.database import Database, User
from foxgen.infra.promo_models import PromoRedemption


class SqlAlchemyPromoRedemptionService:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def redeem(
        self,
        *,
        user_id: int,
        username: str | None,
        code: str,
    ) -> PromoRedemptionResult:
        normalized = code.strip().upper()
        if not normalized or len(normalized) > 64:
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "Промокод должен содержать от 1 до 64 символов.",
            )

        async with self._database.session() as session:
            async with session.begin():
                promo = await session.scalar(
                    select(PromoCode).where(PromoCode.code == normalized).with_for_update()
                )
                if promo is None:
                    raise SubmissionError(
                        ErrorCode.VALIDATION,
                        "Промокод не найден.",
                    )

                existing = await session.scalar(
                    select(PromoRedemption).where(
                        PromoRedemption.promo_code == normalized,
                        PromoRedemption.user_id == user_id,
                    )
                )
                if existing is not None:
                    account = await ensure_wallet_locked(
                        session,
                        user_id=user_id,
                        currency="CREDIT",
                    )
                    return PromoRedemptionResult(
                        code=normalized,
                        reward_units=existing.reward_units,
                        available_units=account.available_units,
                        replayed=True,
                    )

                if not promo.active:
                    raise SubmissionError(
                        ErrorCode.VALIDATION,
                        "Промокод больше не активен.",
                    )
                if promo.reward_units <= 0:
                    raise SubmissionError(
                        ErrorCode.VALIDATION,
                        "У промокода нет доступного бонуса.",
                    )
                if promo.max_uses is not None and promo.uses >= promo.max_uses:
                    raise SubmissionError(
                        ErrorCode.VALIDATION,
                        "Лимит активаций промокода исчерпан.",
                    )

                await session.execute(
                    pg_insert(User)
                    .values(id=user_id, username=username)
                    .on_conflict_do_nothing(index_elements=[User.id])
                )
                if username:
                    await session.execute(
                        update(User).where(User.id == user_id).values(username=username)
                    )

                account = await ensure_wallet_locked(
                    session,
                    user_id=user_id,
                    currency="CREDIT",
                )
                ledger_key = f"promo-credit:{normalized}:{user_id}"
                ledger = await session.scalar(
                    select(LedgerEntry).where(LedgerEntry.idempotency_key == ledger_key)
                )
                if ledger is not None:
                    raise SubmissionError(
                        ErrorCode.IDEMPOTENCY_CONFLICT,
                        "Бонус этого промокода уже существует без записи активации.",
                    )

                account.available_units += promo.reward_units
                account.version += 1
                session.add(
                    LedgerEntry(
                        user_id=user_id,
                        generation_id=None,
                        reservation_id=None,
                        entry_type=LedgerEntryType.CREDIT,
                        currency="CREDIT",
                        available_delta=promo.reward_units,
                        reserved_delta=0,
                        idempotency_key=ledger_key,
                        actor="system:promo",
                        reason=f"Promo code {normalized}",
                        metadata_json={
                            "promo_code": normalized,
                            "reward_units": promo.reward_units,
                        },
                    )
                )
                session.add(
                    PromoRedemption(
                        promo_code=normalized,
                        user_id=user_id,
                        reward_units=promo.reward_units,
                        ledger_key=ledger_key,
                    )
                )
                promo.uses += 1
                await session.flush()

                return PromoRedemptionResult(
                    code=normalized,
                    reward_units=promo.reward_units,
                    available_units=account.available_units,
                    replayed=False,
                )
