from __future__ import annotations

import hashlib
import json

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from foxgen.application.user_portal import (
    PartnerProfileSnapshot,
    PartnerWithdrawalSnapshot,
    SupportMessageSnapshot,
    SupportTicketSnapshot,
    TariffSnapshot,
)
from foxgen.core.errors import ErrorCode, SubmissionError
from foxgen.infra.admin_models import (
    PartnerProfile,
    PartnerWithdrawal,
    SupportMessage,
    SupportTicket,
    TariffVersion,
)
from foxgen.infra.database import Database, User


class SqlAlchemyUserPortalService:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def current_tariff(self) -> TariffSnapshot | None:
        async with self._database.session() as session:
            item = await session.scalar(
                select(TariffVersion).order_by(TariffVersion.version.desc()).limit(1)
            )
            if item is None:
                return None
            return TariffSnapshot(
                version=item.version,
                payload=dict(item.payload),
                published_at=item.published_at,
            )

    async def list_support_tickets(
        self,
        *,
        user_id: int,
        limit: int = 30,
    ) -> tuple[SupportTicketSnapshot, ...]:
        if user_id <= 0 or limit < 1 or limit > 100:
            raise SubmissionError(ErrorCode.VALIDATION, "Некорректный запрос поддержки.")
        async with self._database.session() as session:
            rows = (
                await session.scalars(
                    select(SupportTicket)
                    .where(SupportTicket.user_id == user_id)
                    .order_by(SupportTicket.updated_at.desc())
                    .limit(limit)
                )
            ).all()
            return tuple(self._ticket_snapshot(item) for item in rows)

    async def get_support_ticket(
        self,
        *,
        user_id: int,
        ticket_id: UUID,
    ) -> SupportTicketSnapshot | None:
        async with self._database.session() as session:
            ticket = await session.scalar(
                select(SupportTicket).where(
                    SupportTicket.id == ticket_id,
                    SupportTicket.user_id == user_id,
                )
            )
            if ticket is None:
                return None
            messages = (
                await session.scalars(
                    select(SupportMessage)
                    .where(SupportMessage.ticket_id == ticket.id)
                    .order_by(SupportMessage.created_at.asc())
                )
            ).all()
            return self._ticket_snapshot(
                ticket,
                messages=tuple(self._message_snapshot(item) for item in messages),
            )

    async def create_support_ticket(
        self,
        *,
        user_id: int,
        username: str | None,
        subject: str,
        body: str,
    ) -> SupportTicketSnapshot:
        clean_subject = subject.strip()
        clean_body = body.strip()
        if user_id <= 0:
            raise SubmissionError(ErrorCode.VALIDATION, "Не удалось определить пользователя.")
        if not clean_subject or len(clean_subject) > 255:
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "Тема обращения должна содержать от 1 до 255 символов.",
            )
        if not clean_body or len(clean_body) > 4096:
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "Сообщение поддержки должно содержать от 1 до 4096 символов.",
            )

        async with self._database.session() as session:
            async with session.begin():
                await self._ensure_user(session, user_id=user_id, username=username)
                ticket = SupportTicket(
                    user_id=user_id,
                    subject=clean_subject,
                    status="open",
                    priority="normal",
                )
                session.add(ticket)
                await session.flush()
                message = SupportMessage(
                    ticket_id=ticket.id,
                    sender_kind="user",
                    sender_id=user_id,
                    body=clean_body,
                    status="stored",
                )
                session.add(message)
                await session.flush()
                snapshot = self._ticket_snapshot(
                    ticket,
                    messages=(self._message_snapshot(message),),
                )
            return snapshot

    async def reply_support_ticket(
        self,
        *,
        user_id: int,
        ticket_id: UUID,
        body: str,
    ) -> SupportTicketSnapshot:
        clean_body = body.strip()
        if not clean_body or len(clean_body) > 4096:
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "Сообщение поддержки должно содержать от 1 до 4096 символов.",
            )
        async with self._database.session() as session:
            async with session.begin():
                ticket = await session.scalar(
                    select(SupportTicket)
                    .where(
                        SupportTicket.id == ticket_id,
                        SupportTicket.user_id == user_id,
                    )
                    .with_for_update()
                )
                if ticket is None:
                    raise SubmissionError(ErrorCode.TASK_NOT_FOUND, "Обращение не найдено.")
                if ticket.status == "closed":
                    raise SubmissionError(
                        ErrorCode.VALIDATION,
                        "Закрытое обращение нельзя дополнить. Создайте новое.",
                    )
                if ticket.status == "resolved":
                    ticket.status = "open"
                ticket.updated_at = func.now()
                message = SupportMessage(
                    ticket_id=ticket.id,
                    sender_kind="user",
                    sender_id=user_id,
                    body=clean_body,
                    status="stored",
                )
                session.add(message)
                await session.flush()

            result = await self.get_support_ticket(user_id=user_id, ticket_id=ticket_id)
            if result is None:
                raise SubmissionError(ErrorCode.TASK_NOT_FOUND, "Обращение не найдено.")
            return result

    async def close_support_ticket(
        self,
        *,
        user_id: int,
        ticket_id: UUID,
    ) -> SupportTicketSnapshot:
        async with self._database.session() as session:
            async with session.begin():
                ticket = await session.scalar(
                    select(SupportTicket)
                    .where(
                        SupportTicket.id == ticket_id,
                        SupportTicket.user_id == user_id,
                    )
                    .with_for_update()
                )
                if ticket is None:
                    raise SubmissionError(ErrorCode.TASK_NOT_FOUND, "Обращение не найдено.")
                ticket.status = "closed"
                ticket.updated_at = func.now()
            result = await self.get_support_ticket(user_id=user_id, ticket_id=ticket_id)
            if result is None:
                raise SubmissionError(ErrorCode.TASK_NOT_FOUND, "Обращение не найдено.")
            return result

    async def partner_profile(self, *, user_id: int) -> PartnerProfileSnapshot:
        async with self._database.session() as session:
            partner = await session.get(PartnerProfile, user_id)
            if partner is None:
                return PartnerProfileSnapshot(
                    joined=False,
                    earned_units=0,
                    withdrawn_units=0,
                    pending_units=0,
                    available_units=0,
                    referrals_count=0,
                )
            pending = await self._pending_withdrawal_units(session, user_id=user_id)
            return self._partner_snapshot(partner, pending=pending)

    async def join_partner_program(
        self,
        *,
        user_id: int,
        username: str | None,
    ) -> PartnerProfileSnapshot:
        if user_id <= 0:
            raise SubmissionError(ErrorCode.VALIDATION, "Не удалось определить пользователя.")
        async with self._database.session() as session:
            async with session.begin():
                await self._ensure_user(session, user_id=user_id, username=username)
                await session.execute(
                    pg_insert(PartnerProfile)
                    .values(user_id=user_id)
                    .on_conflict_do_nothing(index_elements=[PartnerProfile.user_id])
                )
            partner = await session.get(PartnerProfile, user_id)
            if partner is None:
                raise SubmissionError(
                    ErrorCode.PROVIDER_PROTOCOL,
                    "Не удалось открыть партнёрский профиль.",
                )
            pending = await self._pending_withdrawal_units(session, user_id=user_id)
            return self._partner_snapshot(partner, pending=pending)

    async def list_partner_withdrawals(
        self,
        *,
        user_id: int,
        limit: int = 50,
    ) -> tuple[PartnerWithdrawalSnapshot, ...]:
        if limit < 1 or limit > 100:
            raise SubmissionError(ErrorCode.VALIDATION, "Некорректный лимит выплат.")
        async with self._database.session() as session:
            rows = (
                await session.scalars(
                    select(PartnerWithdrawal)
                    .where(PartnerWithdrawal.user_id == user_id)
                    .order_by(PartnerWithdrawal.created_at.desc())
                    .limit(limit)
                )
            ).all()
            return tuple(self._withdrawal_snapshot(item) for item in rows)

    async def request_partner_withdrawal(
        self,
        *,
        user_id: int,
        amount_units: int,
        destination: str,
        idempotency_key: str,
    ) -> PartnerWithdrawalSnapshot:
        clean_destination = destination.strip()
        clean_key = idempotency_key.strip()
        if amount_units <= 0:
            raise SubmissionError(ErrorCode.VALIDATION, "Сумма выплаты должна быть положительной.")
        if not 3 <= len(clean_destination) <= 255:
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "Укажите корректные реквизиты для выплаты.",
            )
        if not 8 <= len(clean_key) <= 128:
            raise SubmissionError(ErrorCode.VALIDATION, "Некорректный ключ операции выплаты.")
        request_hash = hashlib.sha256(
            json.dumps(
                {"amount_units": amount_units, "destination": clean_destination},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        async with self._database.session() as session:
            async with session.begin():
                partner = await session.get(PartnerProfile, user_id, with_for_update=True)
                if partner is None:
                    raise SubmissionError(
                        ErrorCode.AUTHORIZATION,
                        "Сначала подключите партнёрскую программу.",
                    )
                existing = await session.scalar(
                    select(PartnerWithdrawal).where(
                        PartnerWithdrawal.user_id == user_id,
                        PartnerWithdrawal.idempotency_key == clean_key,
                    )
                )
                if existing is not None:
                    if existing.request_hash != request_hash:
                        raise SubmissionError(
                            ErrorCode.VALIDATION,
                            "Ключ операции уже использован с другими параметрами выплаты.",
                        )
                    return self._withdrawal_snapshot(existing)
                pending = await self._pending_withdrawal_units(session, user_id=user_id)
                available = max(0, partner.earned_units - partner.withdrawn_units - pending)
                if amount_units > available:
                    raise SubmissionError(
                        ErrorCode.INSUFFICIENT_CREDITS,
                        "Запрошенная выплата превышает доступный партнёрский баланс.",
                    )
                withdrawal = PartnerWithdrawal(
                    user_id=user_id,
                    amount_units=amount_units,
                    status="pending",
                    destination=clean_destination,
                    idempotency_key=clean_key,
                    request_hash=request_hash,
                )
                session.add(withdrawal)
                await session.flush()
                return self._withdrawal_snapshot(withdrawal)

    @staticmethod
    async def _ensure_user(session: AsyncSession, *, user_id: int, username: str | None) -> None:
        # Kept as a small insert-only identity side effect: Telegram auth remains authoritative.
        await session.execute(
            pg_insert(User)
            .values(id=user_id, username=username)
            .on_conflict_do_update(
                index_elements=[User.id],
                set_={"username": username},
            )
        )

    @staticmethod
    async def _pending_withdrawal_units(session: AsyncSession, *, user_id: int) -> int:
        value = await session.scalar(
            select(func.coalesce(func.sum(PartnerWithdrawal.amount_units), 0)).where(
                PartnerWithdrawal.user_id == user_id,
                PartnerWithdrawal.status.in_(("pending", "approved")),
            )
        )
        return int(value or 0)

    @staticmethod
    def _ticket_snapshot(
        ticket: SupportTicket,
        *,
        messages: tuple[SupportMessageSnapshot, ...] = (),
    ) -> SupportTicketSnapshot:
        return SupportTicketSnapshot(
            id=ticket.id,
            subject=ticket.subject,
            status=ticket.status,
            priority=ticket.priority,
            created_at=ticket.created_at,
            updated_at=ticket.updated_at,
            messages=messages,
        )

    @staticmethod
    def _message_snapshot(item: SupportMessage) -> SupportMessageSnapshot:
        return SupportMessageSnapshot(
            id=item.id,
            sender_kind=item.sender_kind,
            body=item.body,
            status=item.status,
            created_at=item.created_at,
        )

    @staticmethod
    def _partner_snapshot(partner: PartnerProfile, *, pending: int) -> PartnerProfileSnapshot:
        available = max(0, partner.earned_units - partner.withdrawn_units - pending)
        return PartnerProfileSnapshot(
            joined=True,
            earned_units=partner.earned_units,
            withdrawn_units=partner.withdrawn_units,
            pending_units=pending,
            available_units=available,
            referrals_count=partner.referrals_count,
        )

    @staticmethod
    def _withdrawal_snapshot(item: PartnerWithdrawal) -> PartnerWithdrawalSnapshot:
        return PartnerWithdrawalSnapshot(
            id=item.id,
            amount_units=item.amount_units,
            status=item.status,
            destination=item.destination,
            reviewed_at=item.reviewed_at,
            created_at=item.created_at,
        )
