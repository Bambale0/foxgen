from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from foxgen.application.billing import (
    BalanceSnapshot,
    LedgerSnapshot,
    PriceSnapshot,
)
from foxgen.core.errors import ErrorCode, SubmissionError
from foxgen.domain.models import (
    GenerationStatus,
    LedgerEntryType,
    ReservationStatus,
)
from foxgen.infra.billing_models import (
    BalanceReservation,
    LedgerEntry,
    ModelPrice,
    WalletAccount,
)
from foxgen.infra.database import Database, User


def _balance_snapshot(account: WalletAccount) -> BalanceSnapshot:
    return BalanceSnapshot(
        user_id=account.user_id,
        currency=account.currency,
        available_units=account.available_units,
        reserved_units=account.reserved_units,
        version=account.version,
    )


def _price_snapshot(price: ModelPrice) -> PriceSnapshot:
    return PriceSnapshot(
        id=price.id,
        model_slug=price.model_slug,
        version=price.version,
        amount_units=price.amount_units,
        currency=price.currency,
        enabled=price.enabled,
        active_from=price.active_from,
        active_until=price.active_until,
    )


def _ledger_snapshot(entry: LedgerEntry) -> LedgerSnapshot:
    return LedgerSnapshot(
        id=entry.id,
        entry_type=str(entry.entry_type),
        currency=entry.currency,
        available_delta=entry.available_delta,
        reserved_delta=entry.reserved_delta,
        generation_id=entry.generation_id,
        reason=entry.reason,
        actor=entry.actor,
        created_at=entry.created_at,
    )


async def active_model_price(
    session: AsyncSession,
    *,
    model_slug: str,
    now: datetime | None = None,
) -> ModelPrice:
    resolved_now = now or datetime.now(timezone.utc)
    price = await session.scalar(
        select(ModelPrice)
        .where(
            ModelPrice.model_slug == model_slug,
            ModelPrice.enabled.is_(True),
            ModelPrice.active_from <= resolved_now,
            or_(ModelPrice.active_until.is_(None), ModelPrice.active_until > resolved_now),
        )
        .order_by(ModelPrice.version.desc())
        .limit(1)
    )
    if price is None:
        raise SubmissionError(
            ErrorCode.PRICING_UNAVAILABLE,
            "Для выбранной модели ещё не настроена активная цена.",
            details={"model_slug": model_slug},
        )
    return price


async def ensure_wallet_locked(
    session: AsyncSession,
    *,
    user_id: int,
    currency: str,
) -> WalletAccount:
    await session.execute(
        pg_insert(WalletAccount)
        .values(user_id=user_id, currency=currency)
        .on_conflict_do_nothing(index_elements=[WalletAccount.user_id])
    )
    account = await session.scalar(
        select(WalletAccount).where(WalletAccount.user_id == user_id).with_for_update()
    )
    if account is None:
        raise SubmissionError(
            ErrorCode.PROVIDER_PROTOCOL,
            "Не удалось открыть внутренний баланс пользователя.",
        )
    if account.currency != currency:
        raise SubmissionError(
            ErrorCode.VALIDATION,
            "Валюта тарифа не совпадает с валютой баланса.",
            details={"account_currency": account.currency, "price_currency": currency},
        )
    return account


async def reserve_generation_charge(
    session: AsyncSession,
    *,
    generation_id: UUID,
    user_id: int,
    model_slug: str,
) -> BalanceReservation:
    existing = await session.scalar(
        select(BalanceReservation).where(
            BalanceReservation.generation_id == generation_id
        )
    )
    if existing is not None:
        return existing

    price = await active_model_price(session, model_slug=model_slug)
    account = await ensure_wallet_locked(
        session,
        user_id=user_id,
        currency=price.currency,
    )
    if account.available_units < price.amount_units:
        raise SubmissionError(
            ErrorCode.INSUFFICIENT_CREDITS,
            "Недостаточно средств для запуска этой генерации.",
            details={
                "available_units": account.available_units,
                "required_units": price.amount_units,
                "currency": price.currency,
            },
        )

    reservation = BalanceReservation(
        generation_id=generation_id,
        user_id=user_id,
        price_id=price.id,
        amount_units=price.amount_units,
        currency=price.currency,
        status=ReservationStatus.RESERVED,
    )
    session.add(reservation)
    await session.flush()

    account.available_units -= price.amount_units
    account.reserved_units += price.amount_units
    account.version += 1
    session.add(
        LedgerEntry(
            user_id=user_id,
            generation_id=generation_id,
            reservation_id=reservation.id,
            entry_type=LedgerEntryType.RESERVE,
            currency=price.currency,
            available_delta=-price.amount_units,
            reserved_delta=price.amount_units,
            idempotency_key=f"reserve:{generation_id}",
            actor="system:submission",
            reason=f"Reserve generation price {model_slug} v{price.version}",
            metadata_json={
                "model_slug": model_slug,
                "price_id": str(price.id),
                "price_version": price.version,
            },
        )
    )
    return reservation


async def settle_generation_charge(
    session: AsyncSession,
    *,
    generation_id: UUID,
    target: GenerationStatus,
) -> None:
    reservation = await session.scalar(
        select(BalanceReservation)
        .where(BalanceReservation.generation_id == generation_id)
        .with_for_update()
    )
    if reservation is None:
        # Legacy/pre-billing generations are allowed to finish without inventing money events.
        return

    status = ReservationStatus(reservation.status)
    if target in {GenerationStatus.SUBMITTED, GenerationStatus.SUCCEEDED}:
        if status == ReservationStatus.RESERVED:
            await _capture(session, reservation)
        return

    if target in {GenerationStatus.FAILED, GenerationStatus.CANCELLED}:
        if status == ReservationStatus.RESERVED:
            await _release(session, reservation)
        elif status == ReservationStatus.CAPTURED:
            await _refund(session, reservation)


async def _capture(session: AsyncSession, reservation: BalanceReservation) -> None:
    account = await ensure_wallet_locked(
        session,
        user_id=reservation.user_id,
        currency=reservation.currency,
    )
    if account.reserved_units < reservation.amount_units:
        raise SubmissionError(
            ErrorCode.PROVIDER_PROTOCOL,
            "Резерв баланса повреждён: недостаточно зарезервированных средств.",
        )
    account.reserved_units -= reservation.amount_units
    account.version += 1
    reservation.status = ReservationStatus.CAPTURED
    reservation.captured_at = func.now()
    session.add(
        LedgerEntry(
            user_id=reservation.user_id,
            generation_id=reservation.generation_id,
            reservation_id=reservation.id,
            entry_type=LedgerEntryType.CAPTURE,
            currency=reservation.currency,
            available_delta=0,
            reserved_delta=-reservation.amount_units,
            idempotency_key=f"capture:{reservation.generation_id}",
            actor="system:worker",
            reason="Capture generation reservation after provider acceptance",
            metadata_json={},
        )
    )


async def _release(session: AsyncSession, reservation: BalanceReservation) -> None:
    account = await ensure_wallet_locked(
        session,
        user_id=reservation.user_id,
        currency=reservation.currency,
    )
    if account.reserved_units < reservation.amount_units:
        raise SubmissionError(
            ErrorCode.PROVIDER_PROTOCOL,
            "Резерв баланса повреждён: недостаточно средств для освобождения.",
        )
    account.available_units += reservation.amount_units
    account.reserved_units -= reservation.amount_units
    account.version += 1
    reservation.status = ReservationStatus.RELEASED
    reservation.released_at = func.now()
    session.add(
        LedgerEntry(
            user_id=reservation.user_id,
            generation_id=reservation.generation_id,
            reservation_id=reservation.id,
            entry_type=LedgerEntryType.RELEASE,
            currency=reservation.currency,
            available_delta=reservation.amount_units,
            reserved_delta=-reservation.amount_units,
            idempotency_key=f"release:{reservation.generation_id}",
            actor="system:worker",
            reason="Release reservation after deterministic pre-capture failure",
            metadata_json={},
        )
    )


async def _refund(session: AsyncSession, reservation: BalanceReservation) -> None:
    account = await ensure_wallet_locked(
        session,
        user_id=reservation.user_id,
        currency=reservation.currency,
    )
    account.available_units += reservation.amount_units
    account.version += 1
    reservation.status = ReservationStatus.REFUNDED
    reservation.refunded_at = func.now()
    session.add(
        LedgerEntry(
            user_id=reservation.user_id,
            generation_id=reservation.generation_id,
            reservation_id=reservation.id,
            entry_type=LedgerEntryType.REFUND,
            currency=reservation.currency,
            available_delta=reservation.amount_units,
            reserved_delta=0,
            idempotency_key=f"refund:{reservation.generation_id}",
            actor="system:worker",
            reason="Refund captured generation after terminal failure",
            metadata_json={},
        )
    )


class SqlAlchemyBillingRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def get_balance(self, user_id: int) -> BalanceSnapshot:
        async with self._database.session() as session:
            account = await session.get(WalletAccount, user_id)
            if account is None:
                return BalanceSnapshot(
                    user_id=user_id,
                    currency="CREDIT",
                    available_units=0,
                    reserved_units=0,
                    version=0,
                )
            return _balance_snapshot(account)

    async def list_ledger(
        self,
        *,
        user_id: int,
        limit: int,
    ) -> tuple[LedgerSnapshot, ...]:
        async with self._database.session() as session:
            entries = tuple(
                (
                    await session.scalars(
                        select(LedgerEntry)
                        .where(LedgerEntry.user_id == user_id)
                        .order_by(LedgerEntry.created_at.desc(), LedgerEntry.id.desc())
                        .limit(limit)
                    )
                ).all()
            )
            return tuple(_ledger_snapshot(entry) for entry in entries)

    async def adjust_balance(
        self,
        *,
        user_id: int,
        username: str | None,
        amount_units: int,
        idempotency_key: str,
        actor: str,
        reason: str,
    ) -> BalanceSnapshot:
        async with self._database.session() as session:
            async with session.begin():
                existing = await session.scalar(
                    select(LedgerEntry).where(
                        LedgerEntry.idempotency_key == idempotency_key
                    )
                )
                if existing is not None:
                    if existing.user_id != user_id or existing.available_delta != amount_units:
                        raise SubmissionError(
                            ErrorCode.IDEMPOTENCY_CONFLICT,
                            "Этот ключ корректировки уже использован с другими параметрами.",
                        )
                    account = await ensure_wallet_locked(
                        session,
                        user_id=user_id,
                        currency=existing.currency,
                    )
                    return _balance_snapshot(account)

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
                if account.available_units + amount_units < 0:
                    raise SubmissionError(
                        ErrorCode.INSUFFICIENT_CREDITS,
                        "Корректировка сделает доступный баланс отрицательным.",
                    )
                account.available_units += amount_units
                account.version += 1
                entry_type = (
                    LedgerEntryType.CREDIT if amount_units > 0 else LedgerEntryType.DEBIT
                )
                session.add(
                    LedgerEntry(
                        user_id=user_id,
                        generation_id=None,
                        reservation_id=None,
                        entry_type=entry_type,
                        currency=account.currency,
                        available_delta=amount_units,
                        reserved_delta=0,
                        idempotency_key=idempotency_key,
                        actor=actor,
                        reason=reason,
                        metadata_json={},
                    )
                )
                await session.flush()
                return _balance_snapshot(account)

    async def set_model_price(
        self,
        *,
        model_slug: str,
        amount_units: int,
        currency: str,
        active_from: datetime,
        active_until: datetime | None,
        metadata: dict[str, object],
    ) -> PriceSnapshot:
        async with self._database.session() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": f"foxgen:price:{model_slug}"},
                )
                latest_version = await session.scalar(
                    select(func.max(ModelPrice.version)).where(
                        ModelPrice.model_slug == model_slug
                    )
                )
                await session.execute(
                    update(ModelPrice)
                    .where(
                        ModelPrice.model_slug == model_slug,
                        ModelPrice.enabled.is_(True),
                    )
                    .values(enabled=False, active_until=active_from)
                )
                price = ModelPrice(
                    model_slug=model_slug,
                    version=int(latest_version or 0) + 1,
                    amount_units=amount_units,
                    currency=currency,
                    enabled=True,
                    active_from=active_from,
                    active_until=active_until,
                    metadata_json=metadata,
                )
                session.add(price)
                await session.flush()
                return _price_snapshot(price)

    async def list_active_prices(self) -> tuple[PriceSnapshot, ...]:
        now = datetime.now(timezone.utc)
        async with self._database.session() as session:
            prices = tuple(
                (
                    await session.scalars(
                        select(ModelPrice)
                        .where(
                            ModelPrice.enabled.is_(True),
                            ModelPrice.active_from <= now,
                            or_(ModelPrice.active_until.is_(None), ModelPrice.active_until > now),
                        )
                        .order_by(ModelPrice.model_slug, ModelPrice.version.desc())
                    )
                ).all()
            )
            latest: dict[str, ModelPrice] = {}
            for price in prices:
                latest.setdefault(price.model_slug, price)
            return tuple(_price_snapshot(price) for price in latest.values())
