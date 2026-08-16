from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from foxgen.api.app import create_app
from foxgen.api.miniapp_security import TelegramMiniAppUser, issue_miniapp_token
from foxgen.application.user_portal import (
    PartnerProfileSnapshot,
    PartnerWithdrawalSnapshot,
    SupportMessageSnapshot,
    SupportTicketSnapshot,
    TariffSnapshot,
)
from foxgen.core.config import Settings


USER_ID = 123456789
JWT_SECRET = "portal-miniapp-jwt-secret-long-enough"
INTERNAL_TOKEN = "portal-internal-token-long-enough"
NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)
TICKET_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-111111111111")


class FakePortalService:
    def __init__(self) -> None:
        self.user_ids: list[int] = []
        self.ticket = SupportTicketSnapshot(
            id=TICKET_ID,
            subject="Support",
            status="open",
            priority="normal",
            created_at=NOW,
            updated_at=NOW,
            messages=(
                SupportMessageSnapshot(
                    id=uuid4(),
                    sender_kind="user",
                    body="Hello",
                    status="stored",
                    created_at=NOW,
                ),
            ),
        )
        self.partner = PartnerProfileSnapshot(
            joined=True,
            earned_units=500,
            withdrawn_units=100,
            pending_units=100,
            available_units=300,
            referrals_count=3,
        )
        self.withdrawal = PartnerWithdrawalSnapshot(
            id=uuid4(),
            amount_units=100,
            status="pending",
            destination="SBP:+79990000000",
            reviewed_at=None,
            created_at=NOW,
        )

    async def current_tariff(self) -> TariffSnapshot | None:
        return TariffSnapshot(
            version=7,
            payload={"title": "Creator", "description": "Happy Fox tariff"},
            published_at=NOW,
        )

    async def list_support_tickets(
        self, *, user_id: int, limit: int = 30
    ) -> tuple[SupportTicketSnapshot, ...]:
        del limit
        self.user_ids.append(user_id)
        return (self.ticket,)

    async def get_support_ticket(
        self, *, user_id: int, ticket_id: UUID
    ) -> SupportTicketSnapshot | None:
        self.user_ids.append(user_id)
        return self.ticket if ticket_id == TICKET_ID else None

    async def create_support_ticket(
        self,
        *,
        user_id: int,
        username: str | None,
        subject: str,
        body: str,
    ) -> SupportTicketSnapshot:
        del username, subject, body
        self.user_ids.append(user_id)
        return self.ticket

    async def reply_support_ticket(
        self, *, user_id: int, ticket_id: UUID, body: str
    ) -> SupportTicketSnapshot:
        del ticket_id, body
        self.user_ids.append(user_id)
        return self.ticket

    async def close_support_ticket(self, *, user_id: int, ticket_id: UUID) -> SupportTicketSnapshot:
        del ticket_id
        self.user_ids.append(user_id)
        return SupportTicketSnapshot(
            id=self.ticket.id,
            subject=self.ticket.subject,
            status="closed",
            priority=self.ticket.priority,
            created_at=self.ticket.created_at,
            updated_at=self.ticket.updated_at,
            messages=self.ticket.messages,
        )

    async def partner_profile(self, *, user_id: int) -> PartnerProfileSnapshot:
        self.user_ids.append(user_id)
        return self.partner

    async def join_partner_program(
        self, *, user_id: int, username: str | None
    ) -> PartnerProfileSnapshot:
        del username
        self.user_ids.append(user_id)
        return self.partner

    async def list_partner_withdrawals(
        self, *, user_id: int, limit: int = 50
    ) -> tuple[PartnerWithdrawalSnapshot, ...]:
        del limit
        self.user_ids.append(user_id)
        return (self.withdrawal,)

    async def request_partner_withdrawal(
        self, *, user_id: int, amount_units: int, destination: str
    ) -> PartnerWithdrawalSnapshot:
        del amount_units, destination
        self.user_ids.append(user_id)
        return self.withdrawal


def settings() -> Settings:
    return Settings(
        env="test",
        miniapp_enabled=True,
        miniapp_jwt_secret=JWT_SECRET,
        internal_api_token=INTERNAL_TOKEN,
    )


def jwt() -> str:
    return issue_miniapp_token(
        TelegramMiniAppUser(
            id=USER_ID,
            first_name="Portal",
            username="portal_user",
        ),
        secret=JWT_SECRET,
        ttl_seconds=3600,
    )


def miniapp_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {jwt()}"}


def internal_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {INTERNAL_TOKEN}",
        "X-FoxGen-User-Id": str(USER_ID),
        "X-FoxGen-Username": "portal_user",
    }


def client() -> tuple[TestClient, FakePortalService]:
    service = FakePortalService()
    app = create_app(
        settings(),
        manage_resources=False,
        user_portal_service=service,
    )
    return TestClient(app), service


def test_miniapp_user_portal_requires_telegram_jwt() -> None:
    test_client, _service = client()
    with test_client:
        assert test_client.get("/v1/miniapp/tariff").status_code == 401
        assert test_client.get("/v1/miniapp/support").status_code == 401
        assert test_client.get("/v1/miniapp/partner").status_code == 401


def test_miniapp_support_tariff_and_partner_are_owner_scoped() -> None:
    test_client, service = client()
    with test_client:
        tariff = test_client.get("/v1/miniapp/tariff", headers=miniapp_headers())
        tickets = test_client.get("/v1/miniapp/support", headers=miniapp_headers())
        created = test_client.post(
            "/v1/miniapp/support",
            headers=miniapp_headers(),
            json={"subject": "Help", "body": "Need help"},
        )
        replied = test_client.post(
            f"/v1/miniapp/support/{TICKET_ID}/messages",
            headers=miniapp_headers(),
            json={"body": "More details"},
        )
        closed = test_client.post(
            f"/v1/miniapp/support/{TICKET_ID}/close",
            headers=miniapp_headers(),
        )
        partner = test_client.get("/v1/miniapp/partner", headers=miniapp_headers())
        joined = test_client.post("/v1/miniapp/partner/join", headers=miniapp_headers())
        withdrawal = test_client.post(
            "/v1/miniapp/partner/withdrawals",
            headers=miniapp_headers(),
            json={"amount_units": 100, "destination": "SBP:+79990000000"},
        )

    assert tariff.status_code == 200
    assert tariff.json()["version"] == 7
    assert tickets.json()["items"][0]["id"] == str(TICKET_ID)
    assert created.status_code == 201
    assert replied.status_code == 200
    assert closed.json()["status"] == "closed"
    assert partner.json()["profile"]["available_units"] == 300
    assert joined.json()["joined"] is True
    assert withdrawal.status_code == 201
    assert service.user_ids and set(service.user_ids) == {USER_ID}


def test_internal_portal_uses_trusted_user_header_and_rejects_missing_identity() -> None:
    test_client, service = client()
    with test_client:
        assert (
            test_client.get(
                "/v1/user-portal/support",
                headers={"Authorization": f"Bearer {INTERNAL_TOKEN}"},
            ).status_code
            == 401
        )
        response = test_client.get("/v1/user-portal/support", headers=internal_headers())

    assert response.status_code == 200
    assert service.user_ids[-1] == USER_ID
