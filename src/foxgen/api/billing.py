from datetime import datetime, timezone
from typing import Any, Protocol

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from foxgen.api.security import (
    authenticate_billing_admin,
    authenticate_internal_service,
    validate_idempotency_key,
)
from foxgen.application.billing import (
    BalanceSnapshot,
    LedgerSnapshot,
    PriceSnapshot,
)
from foxgen.core.config import Settings
from foxgen.providers.kie.registry import ModelRegistry


class BillingServiceProtocol(Protocol):
    async def get_balance(self, user_id: int) -> BalanceSnapshot: ...

    async def list_ledger(
        self,
        *,
        user_id: int,
        limit: int = 50,
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
        currency: str = "CREDIT",
        active_from: datetime,
        active_until: datetime | None = None,
        metadata: dict[str, object] | None = None,
    ) -> PriceSnapshot: ...

    async def list_active_prices(self) -> tuple[PriceSnapshot, ...]: ...


class BalanceAdjustmentRequest(BaseModel):
    amount_units: int
    reason: str = Field(min_length=3, max_length=1000)
    username: str | None = Field(default=None, max_length=64)


class ModelPriceRequest(BaseModel):
    amount_units: int = Field(gt=0)
    currency: str = Field(default="CREDIT", min_length=1, max_length=16)
    active_from: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    active_until: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def _service(request: Request) -> BillingServiceProtocol:
    service: BillingServiceProtocol | None = getattr(
        request.app.state,
        "billing_service",
        None,
    )
    if service is None:
        raise HTTPException(status_code=503, detail="Billing service is not configured")
    return service


def balance_payload(balance: BalanceSnapshot) -> dict[str, object]:
    return {
        "user_id": balance.user_id,
        "currency": balance.currency,
        "available_units": balance.available_units,
        "reserved_units": balance.reserved_units,
        "total_units": balance.available_units + balance.reserved_units,
        "version": balance.version,
    }


def price_payload(price: PriceSnapshot) -> dict[str, object]:
    return {
        "id": str(price.id),
        "model_slug": price.model_slug,
        "version": price.version,
        "amount_units": price.amount_units,
        "currency": price.currency,
        "enabled": price.enabled,
        "active_from": price.active_from,
        "active_until": price.active_until,
    }


def ledger_payload(entry: LedgerSnapshot) -> dict[str, object]:
    return {
        "id": str(entry.id),
        "entry_type": entry.entry_type,
        "currency": entry.currency,
        "available_delta": entry.available_delta,
        "reserved_delta": entry.reserved_delta,
        "generation_id": str(entry.generation_id) if entry.generation_id else None,
        "reason": entry.reason,
        "actor": entry.actor,
        "created_at": entry.created_at,
    }


def create_billing_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["billing"])
    registry = ModelRegistry()

    @router.get("/v1/prices")
    async def active_prices(request: Request) -> list[dict[str, object]]:
        prices = await _service(request).list_active_prices()
        return [price_payload(price) for price in prices]

    @router.get("/v1/users/{user_id}/balance")
    async def user_balance(
        user_id: int,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        authenticate_internal_service(settings=settings, authorization=authorization)
        if user_id <= 0:
            raise HTTPException(status_code=400, detail="user_id must be positive")
        return balance_payload(await _service(request).get_balance(user_id))

    @router.get("/v1/users/{user_id}/ledger")
    async def user_ledger(
        user_id: int,
        request: Request,
        authorization: str | None = Header(default=None),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> list[dict[str, object]]:
        authenticate_internal_service(settings=settings, authorization=authorization)
        if user_id <= 0:
            raise HTTPException(status_code=400, detail="user_id must be positive")
        entries = await _service(request).list_ledger(user_id=user_id, limit=limit)
        return [ledger_payload(entry) for entry in entries]

    @router.post("/v1/admin/users/{user_id}/balance-adjustments")
    async def adjust_user_balance(
        user_id: int,
        body: BalanceAdjustmentRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, object]:
        authenticate_billing_admin(settings=settings, authorization=authorization)
        if user_id <= 0:
            raise HTTPException(status_code=400, detail="user_id must be positive")
        idempotency_key = validate_idempotency_key(idempotency_key_header)
        try:
            balance = await _service(request).adjust_balance(
                user_id=user_id,
                username=body.username,
                amount_units=body.amount_units,
                idempotency_key=f"admin-adjustment:{idempotency_key}",
                actor="admin-api",
                reason=body.reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return balance_payload(balance)

    @router.put("/v1/admin/prices/{model_slug}")
    async def configure_model_price(
        model_slug: str,
        body: ModelPriceRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        authenticate_billing_admin(settings=settings, authorization=authorization)
        try:
            registry.get(model_slug)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        try:
            price = await _service(request).set_model_price(
                model_slug=model_slug,
                amount_units=body.amount_units,
                currency=body.currency,
                active_from=body.active_from,
                active_until=body.active_until,
                metadata=body.metadata,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return price_payload(price)

    return router
