from uuid import UUID

from fastapi.testclient import TestClient

from foxgen.api.app import create_app
from foxgen.application.reconciliation import (
    DeliveryResolutionAction,
    ReconciliationFinding,
    ReconciliationResult,
)
from foxgen.core.config import Settings


GENERATION_ID = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
RESOURCE_ID = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")


class FakeReconciliationService:
    def __init__(self) -> None:
        self.finding = ReconciliationFinding(
            code="delivery_unknown",
            severity="critical",
            generation_id=GENERATION_ID,
            resource_id=RESOURCE_ID,
            status="delivery_unknown",
            details={"attempts": 1},
        )
        self.resolution: tuple[DeliveryResolutionAction, bool, str | None] | None = None

    async def report(self, *, limit: int) -> tuple[ReconciliationFinding, ...]:
        assert limit == 100
        return (self.finding,)

    async def run_safe(self, *, limit: int) -> ReconciliationResult:
        assert limit == 100
        return ReconciliationResult(
            findings=(self.finding,),
            fixed_codes=("settle_reservation:test",),
        )

    async def resolve_delivery_unknown(
        self,
        *,
        generation_id: UUID,
        action: DeliveryResolutionAction,
        message_ids: list[int] | None,
        confirmed_not_sent: bool,
        idempotency_key: str | None,
        reason: str,
    ) -> None:
        del message_ids, reason
        assert generation_id == GENERATION_ID
        self.resolution = (action, confirmed_not_sent, idempotency_key)


def settings() -> Settings:
    return Settings(
        env="test",
        billing_admin_api_enabled=True,
        billing_admin_api_token="admin-secret",
    )


def test_admin_can_read_and_run_safe_reconciliation() -> None:
    service = FakeReconciliationService()
    app = create_app(
        settings(),
        manage_resources=False,
        reconciliation_service=service,
    )

    with TestClient(app) as client:
        report = client.get(
            "/v1/admin/reconciliation",
            headers={"Authorization": "Bearer admin-secret"},
        )
        run = client.post(
            "/v1/admin/reconciliation/run",
            headers={"Authorization": "Bearer admin-secret"},
            json={"apply_safe_fixes": True, "limit": 100},
        )

    assert report.status_code == 200
    assert report.json()[0]["generation_id"] == str(GENERATION_ID)
    assert run.status_code == 200
    assert run.json()["fixed_codes"] == ["settle_reservation:test"]


def test_delivery_retry_requires_admin_and_explicit_payload() -> None:
    service = FakeReconciliationService()
    app = create_app(
        settings(),
        manage_resources=False,
        reconciliation_service=service,
    )

    with TestClient(app) as client:
        unauthorized = client.post(
            f"/v1/admin/generations/{GENERATION_ID}/resolve-delivery",
            json={
                "action": "retry",
                "confirmed_not_sent": True,
                "idempotency_key": "delivery-retry-1",
                "reason": "Telegram history confirms no message",
            },
        )
        resolved = client.post(
            f"/v1/admin/generations/{GENERATION_ID}/resolve-delivery",
            headers={"Authorization": "Bearer admin-secret"},
            json={
                "action": "retry",
                "confirmed_not_sent": True,
                "idempotency_key": "delivery-retry-1",
                "reason": "Telegram history confirms no message",
            },
        )

    assert unauthorized.status_code == 401
    assert resolved.status_code == 200
    assert service.resolution == (
        DeliveryResolutionAction.RETRY,
        True,
        "delivery-retry-1",
    )
