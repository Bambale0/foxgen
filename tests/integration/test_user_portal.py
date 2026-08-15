import os

import pytest
from sqlalchemy import delete

from foxgen.core.errors import ErrorCode, SubmissionError
from foxgen.infra.admin_models import (
    PartnerProfile,
    PartnerWithdrawal,
    SupportTicket,
    TariffVersion,
)
from foxgen.infra.database import Database, User
from foxgen.infra.user_portal import SqlAlchemyUserPortalService

pytestmark = pytest.mark.skipif(
    os.getenv("FOXGEN_RUN_INTEGRATION") != "1",
    reason="real infrastructure tests are enabled only in the CI infrastructure job",
)


@pytest.mark.asyncio
async def test_user_portal_support_tariff_and_partner_invariants() -> None:
    database = Database(os.environ["FOXGEN_DATABASE_URL"])
    service = SqlAlchemyUserPortalService(database)
    user_id = 910_000_089
    other_user_id = 910_000_090
    tariff_version = 900_089

    try:
        async with database.session() as session:
            async with session.begin():
                session.add(User(id=other_user_id, username="portal-other"))
                session.add(
                    TariffVersion(
                        version=tariff_version,
                        payload={
                            "title": "Happy Fox Creator",
                            "description": "Актуальные условия",
                            "credit_packages": [
                                {"credits": 100, "price_rub": 1000},
                            ],
                        },
                    )
                )

        tariff = await service.current_tariff()
        assert tariff is not None
        assert tariff.version == tariff_version
        assert tariff.payload["title"] == "Happy Fox Creator"

        ticket = await service.create_support_ticket(
            user_id=user_id,
            username="portal-owner",
            subject="Помогите с генерацией",
            body="У меня вопрос по результату.",
        )
        assert ticket.status == "open"
        assert len(ticket.messages) == 1
        assert ticket.messages[0].sender_kind == "user"

        assert (
            await service.get_support_ticket(user_id=other_user_id, ticket_id=ticket.id)
            is None
        )

        replied = await service.reply_support_ticket(
            user_id=user_id,
            ticket_id=ticket.id,
            body="Добавляю детали.",
        )
        assert [message.body for message in replied.messages] == [
            "У меня вопрос по результату.",
            "Добавляю детали.",
        ]

        closed = await service.close_support_ticket(user_id=user_id, ticket_id=ticket.id)
        assert closed.status == "closed"
        with pytest.raises(SubmissionError) as closed_reply:
            await service.reply_support_ticket(
                user_id=user_id,
                ticket_id=ticket.id,
                body="Это не должно сохраниться.",
            )
        assert closed_reply.value.code == ErrorCode.VALIDATION

        empty_partner = await service.partner_profile(user_id=user_id)
        assert empty_partner.joined is False

        partner = await service.join_partner_program(
            user_id=user_id,
            username="portal-owner",
        )
        assert partner.joined is True

        async with database.session() as session:
            async with session.begin():
                row = await session.get(PartnerProfile, user_id, with_for_update=True)
                assert row is not None
                row.earned_units = 1000
                row.referrals_count = 4

        first = await service.request_partner_withdrawal(
            user_id=user_id,
            amount_units=700,
            destination="SBP:+79990000000",
        )
        assert first.status == "pending"
        assert first.amount_units == 700

        dashboard = await service.partner_profile(user_id=user_id)
        assert dashboard.earned_units == 1000
        assert dashboard.pending_units == 700
        assert dashboard.available_units == 300
        assert dashboard.referrals_count == 4

        with pytest.raises(SubmissionError) as overspend:
            await service.request_partner_withdrawal(
                user_id=user_id,
                amount_units=400,
                destination="SBP:+79990000000",
            )
        assert overspend.value.code == ErrorCode.INSUFFICIENT_CREDITS

        withdrawals = await service.list_partner_withdrawals(user_id=user_id)
        assert [item.id for item in withdrawals] == [first.id]
    finally:
        async with database.session() as session:
            async with session.begin():
                await session.execute(
                    delete(PartnerWithdrawal).where(PartnerWithdrawal.user_id == user_id)
                )
                await session.execute(
                    delete(SupportTicket).where(SupportTicket.user_id == user_id)
                )
                await session.execute(delete(PartnerProfile).where(PartnerProfile.user_id == user_id))
                await session.execute(
                    delete(User).where(User.id.in_((user_id, other_user_id)))
                )
                await session.execute(
                    delete(TariffVersion).where(TariffVersion.version == tariff_version)
                )
        await database.close()
