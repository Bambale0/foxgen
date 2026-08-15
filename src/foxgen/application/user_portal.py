from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class TariffSnapshot:
    version: int
    payload: dict[str, object]
    published_at: datetime


@dataclass(frozen=True, slots=True)
class SupportMessageSnapshot:
    id: UUID
    sender_kind: str
    body: str
    status: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SupportTicketSnapshot:
    id: UUID
    subject: str
    status: str
    priority: str
    created_at: datetime
    updated_at: datetime
    messages: tuple[SupportMessageSnapshot, ...] = ()


@dataclass(frozen=True, slots=True)
class PartnerProfileSnapshot:
    joined: bool
    earned_units: int
    withdrawn_units: int
    pending_units: int
    available_units: int
    referrals_count: int


@dataclass(frozen=True, slots=True)
class PartnerWithdrawalSnapshot:
    id: UUID
    amount_units: int
    status: str
    destination: str | None
    reviewed_at: datetime | None
    created_at: datetime


class UserPortalServiceProtocol(Protocol):
    async def current_tariff(self) -> TariffSnapshot | None: ...

    async def list_support_tickets(
        self,
        *,
        user_id: int,
        limit: int = 30,
    ) -> tuple[SupportTicketSnapshot, ...]: ...

    async def get_support_ticket(
        self,
        *,
        user_id: int,
        ticket_id: UUID,
    ) -> SupportTicketSnapshot | None: ...

    async def create_support_ticket(
        self,
        *,
        user_id: int,
        username: str | None,
        subject: str,
        body: str,
    ) -> SupportTicketSnapshot: ...

    async def reply_support_ticket(
        self,
        *,
        user_id: int,
        ticket_id: UUID,
        body: str,
    ) -> SupportTicketSnapshot: ...

    async def close_support_ticket(
        self,
        *,
        user_id: int,
        ticket_id: UUID,
    ) -> SupportTicketSnapshot: ...

    async def partner_profile(self, *, user_id: int) -> PartnerProfileSnapshot: ...

    async def join_partner_program(
        self,
        *,
        user_id: int,
        username: str | None,
    ) -> PartnerProfileSnapshot: ...

    async def list_partner_withdrawals(
        self,
        *,
        user_id: int,
        limit: int = 50,
    ) -> tuple[PartnerWithdrawalSnapshot, ...]: ...

    async def request_partner_withdrawal(
        self,
        *,
        user_id: int,
        amount_units: int,
        destination: str,
    ) -> PartnerWithdrawalSnapshot: ...
