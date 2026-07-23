from datetime import datetime, timezone
from uuid import UUID

from fastapi.testclient import TestClient

from foxgen.api.app import create_app
from foxgen.application.billing import (
    BalanceSnapshot,
    LedgerSnapshot,
    PriceSnapshot,
)
from foxgen.core.config import Settings


class FakeBillingService:
    def __init__(self) -> None:
        self.balance = BalanceSnapshot(
            user_id=42,
            currency="CREDIT",
            available_units=1000,
            reserved_units=250,
            version=3,
        )
        self.adjustments: list[dict[str, object]] = []
        self.price_updates: list[dict[str, object]] = []
        now = datetime(2026, 7, 23, tzinfo=timezone.utc)
        self.price = PriceSnapshot(
            id=UUID("11111111-1111-1111-1111-111111111111"),
            model_slug="seedream-5-pro",
            version=1,
            amount_units=250,
            currency="CREDIT",
            enabled=True,
            active_from=now,
            active_until=None,
        )

    async def get_balance(self, user_id: int) -> BalanceSnapshot:
        return BalanceSnapshot(
            user_id=user_id,
            currency=self.balance.currency,
            available_units=self.balance.available_units,
            reserved_units=self.balance.reserved_units,
            version=self.balance.version,
        )

    async def list_ledger(
        self,
        *,
        user_id: int,
        limit: int = 50,
    ) -> tuple[LedgerSnapshot, ...]:
        del limit
        return (
            LedgerSnapshot(
                id=UUID("22222222-2222-2222-2222-222222222222"),
                entry_type="credit",
                currency="CREDIT",
                available_delta=1000,
                reserved_delta=0,
                generation_id=None,
                reason="Initial balance",
                actor="admin-api",
                created_at=datetime(2026, 7, 23, tzinfo=timezone.utc),
            ),
        ) if user_id == 42 else ()

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
        self.adjustments.append(
            {
                "user_id": user_id,
                "username": username,
                "amount_units": amount_units,
                "idempotency_key": idempotency_key,
                "actor": actor,
                "reason": reason,
            }
        )
        return BalanceSnapshot(
            user_id=user_id,
            currency="CREDIT",
            available_units=self.balance.available_units + amount_units,
            reserved_units=self.balance.reserved_units,
            version=self.balance.version + 1,
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
        self.price_updates.append(
            {
                "model_slug": model_slug,
                "amount_units": amount_units,
                "currency": currency,
                "active_from": active_from,
                "active_until": active_until,
                "metadata": metadata,
            }
        )
        return PriceSnapshot(
            id=self.price.id,
            model_slug=model_slug,
            version=2,
            amount_units=amount_units,
            currency=currency,
            enabled=True,
            active_from=active_from,
            active_until=active_until,
        )

    async def list_active_prices(self) -> tuple[PriceSnapshot, ...]:
        return (self.price,)


def test_active_price_catalog_is_readable() -> None:
    service = FakeBillingService()
    app = create_app(
        Settings(env="test"),
        manage_resources=False,
        billing_service=service,
    )

    with TestClient(app) as client:
        response = client.get("/v1/prices")

    assert response.status_code == 200
    assert response.json()[0]["model_slug"] == "seedream-5-pro"
    assert response.json()[0]["amount_units"] == 250


def test_balance_requires_internal_service_token() -> None:
    service = FakeBillingService()
    app = create_app(
        Settings(env="test", internal_api_token="internal-secret"),
        manage_resources=False,
        billing_service=service,
    )

    with TestClient(app) as client:
        unauthorized = client.get("/v1/users/42/balance")
        authorized = client.get(
            "/v1/users/42/balance",
            headers={"Authorization": "Bearer internal-secret"},
        )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    assert authorized.json()["available_units"] == 1000
    assert authorized.json()["reserved_units"] == 250
    assert authorized.json()["total_units"] == 1250


def test_admin_adjustment_is_disabled_by_default() -> None:
    service = FakeBillingService()
    app = create_app(
        Settings(env="test", billing_admin_api_token="admin-secret"),
        manage_resources=False,
        billing_service=service,
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/admin/users/42/balance-adjustments",
            headers={
                "Authorization": "Bearer admin-secret",
                "Idempotency-Key": "adjustment-0001",
            },
            json={"amount_units": 500, "reason": "Test funding"},
        )

    assert response.status_code == 503
    assert service.adjustments == []


def test_admin_can_idempotently_adjust_balance_with_separate_token() -> None:
    service = FakeBillingService()
    app = create_app(
        Settings(
            env="test",
            billing_admin_api_enabled=True,
            billing_admin_api_token="admin-secret",
        ),
        manage_resources=False,
        billing_service=service,
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/admin/users/42/balance-adjustments",
            headers={
                "Authorization": "Bearer admin-secret",
                "Idempotency-Key": "adjustment-0001",
            },
            json={
                "amount_units": 500,
                "reason": "Manual test credit",
                "username": "fox-user",
            },
        )

    assert response.status_code == 200
    assert response.json()["available_units"] == 1500
    assert service.adjustments == [
        {
            "user_id": 42,
            "username": "fox-user",
            "amount_units": 500,
            "idempotency_key": "admin-adjustment:adjustment-0001",
            "actor": "admin-api",
            "reason": "Manual test credit",
        }
    ]


def test_admin_can_publish_versioned_model_price() -> None:
    service = FakeBillingService()
    app = create_app(
        Settings(
            env="test",
            billing_admin_api_enabled=True,
            billing_admin_api_token="admin-secret",
        ),
        manage_resources=False,
        billing_service=service,
    )

    with TestClient(app) as client:
        response = client.put(
            "/v1/admin/prices/seedream-5-pro",
            headers={"Authorization": "Bearer admin-secret"},
            json={
                "amount_units": 300,
                "currency": "CREDIT",
                "active_from": "2026-07-23T00:00:00Z",
                "metadata": {"reason": "provider cost update"},
            },
        )

    assert response.status_code == 200
    assert response.json()["version"] == 2
    assert response.json()["amount_units"] == 300
    assert service.price_updates[0]["model_slug"] == "seedream-5-pro"
