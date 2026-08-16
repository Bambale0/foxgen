from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class StarPackage:
    code: str
    title: str
    description: str
    credits_units: int
    stars_amount: int


@dataclass(frozen=True, slots=True)
class StarInvoice:
    order_id: UUID
    package: StarPackage
    invoice_payload: str
    invoice_url: str
    replayed: bool


@dataclass(frozen=True, slots=True)
class PreCheckoutDecision:
    ok: bool
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class StarPaymentResult:
    order_id: UUID
    available_units: int
    credited_units: int
    replayed: bool


class TelegramStarsPaymentServiceProtocol(Protocol):
    async def list_packages(self) -> tuple[StarPackage, ...]: ...

    async def create_invoice(
        self,
        *,
        user_id: int,
        username: str | None,
        package_code: str,
        idempotency_key: str,
    ) -> StarInvoice: ...

    async def validate_pre_checkout(
        self,
        *,
        user_id: int,
        invoice_payload: str,
        currency: str,
        total_amount: int,
    ) -> PreCheckoutDecision: ...

    async def credit_successful_payment(
        self,
        *,
        user_id: int,
        username: str | None,
        invoice_payload: str,
        currency: str,
        total_amount: int,
        telegram_payment_charge_id: str,
        provider_payment_charge_id: str,
        raw_payload: dict[str, object],
    ) -> StarPaymentResult: ...
