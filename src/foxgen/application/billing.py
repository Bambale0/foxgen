from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class BalanceSnapshot:
    user_id: int
    currency: str
    available_units: int
    reserved_units: int
    version: int


@dataclass(frozen=True, slots=True)
class PriceSnapshot:
    id: UUID
    model_slug: str
    version: int
    amount_units: int
    currency: str
    enabled: bool
    active_from: datetime
    active_until: datetime | None


@dataclass(frozen=True, slots=True)
class LedgerSnapshot:
    id: UUID
    entry_type: str
    currency: str
    available_delta: int
    reserved_delta: int
    generation_id: UUID | None
    reason: str
    actor: str
    created_at: datetime


class BillingRepository(Protocol):
    async def get_balance(self, user_id: int) -> BalanceSnapshot: ...

    async def list_ledger(
        self,
        *,
        user_id: int,
        limit: int,
    ) -> tuple[LedgerSnapshot, ...]: ...

    async def adjust_balance(
        self,
        *,
        user_id: int,
        username: str | None,
        amount_units: int,
        idempotency_key: str,
        actor: str,
        reason: str,
    ) -> BalanceSnapshot: ...

    async def set_model_price(
        self,
        *,
        model_slug: str,
        amount_units: int,
        currency: str,
        active_from: datetime,
        active_until: datetime | None,
        metadata: dict[str, object],
    ) -> PriceSnapshot: ...

    async def list_active_prices(self) -> tuple[PriceSnapshot, ...]: ...


class BillingService:
    def __init__(self, repository: BillingRepository) -> None:
        self._repository = repository

    async def get_balance(self, user_id: int) -> BalanceSnapshot:
        return await self._repository.get_balance(user_id)

    async def list_ledger(
        self,
        *,
        user_id: int,
        limit: int = 50,
    ) -> tuple[LedgerSnapshot, ...]:
        return await self._repository.list_ledger(user_id=user_id, limit=limit)

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
        if amount_units == 0:
            raise ValueError("Balance adjustment must be non-zero")
        if not reason.strip():
            raise ValueError("Balance adjustment reason is required")
        return await self._repository.adjust_balance(
            user_id=user_id,
            username=username,
            amount_units=amount_units,
            idempotency_key=idempotency_key,
            actor=actor,
            reason=reason.strip(),
        )

    async def set_model_price(
        self,
        *,
        model_slug: str,
        amount_units: int,
        currency: str = "CREDIT",
        active_from: datetime,
        active_until: datetime | None = None,
        metadata: dict[str, object] | None = None,
    ) -> PriceSnapshot:
        if amount_units <= 0:
            raise ValueError("Model price must be positive")
        if active_until is not None and active_until <= active_from:
            raise ValueError("active_until must be after active_from")
        return await self._repository.set_model_price(
            model_slug=model_slug,
            amount_units=amount_units,
            currency=currency,
            active_from=active_from,
            active_until=active_until,
            metadata=metadata or {},
        )

    async def list_active_prices(self) -> tuple[PriceSnapshot, ...]:
        return await self._repository.list_active_prices()
