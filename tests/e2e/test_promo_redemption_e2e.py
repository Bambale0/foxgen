import json
import os
import time
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select

from foxgen.admin.security import request_signature
from foxgen.admin.services import AdminServices
from foxgen.api.app import create_app
from foxgen.api.miniapp_security import TelegramMiniAppUser, issue_miniapp_token
from foxgen.core.config import Settings
from foxgen.infra.admin_models import PromoCode
from foxgen.infra.billing import SqlAlchemyBillingRepository
from foxgen.infra.billing_models import LedgerEntry, WalletAccount
from foxgen.infra.database import Database, User
from foxgen.infra.promo_models import PromoRedemption

pytestmark = pytest.mark.skipif(
    os.getenv("FOXGEN_RUN_E2E") != "1",
    reason="cross-layer E2E tests run only in the CI infrastructure job",
)


ADMIN_ID = 996_100_001
INTERNAL_TOKEN = "promo-e2e-internal-token-long-enough"
JWT_SECRET = "promo-e2e-miniapp-jwt-secret-long-enough"
ADMIN_SECRET = "promo-e2e-admin-hmac-secret-long-enough"


def _settings() -> Settings:
    return Settings(
        env="test",
        miniapp_enabled=True,
        miniapp_jwt_secret=JWT_SECRET,
        internal_api_token=INTERNAL_TOKEN,
        admin_api_enabled=True,
        admin_web_enabled=False,
        admin_hmac_key=ADMIN_SECRET,
        admin_network_allowlist="127.0.0.1/32",
    )


def _miniapp_headers(user_id: int) -> dict[str, str]:
    token = issue_miniapp_token(
        TelegramMiniAppUser(id=user_id, first_name="Promo", username="promo_e2e"),
        secret=JWT_SECRET,
        ttl_seconds=3600,
    )
    return {"Authorization": f"Bearer {token}"}


def _internal_headers(user_id: int) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {INTERNAL_TOKEN}",
        "X-FoxGen-User-Id": str(user_id),
        "X-FoxGen-Username": "promo_e2e_second",
    }


def _admin_headers(*, path: str, raw_body: bytes, request_id: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    return {
        "Content-Type": "application/json",
        "X-Admin-User-Id": str(ADMIN_ID),
        "X-Request-Id": request_id,
        "X-Admin-Timestamp": timestamp,
        "X-Admin-Signature": request_signature(
            secret=ADMIN_SECRET,
            timestamp=timestamp,
            method="POST",
            path=path,
            request_id=request_id,
            raw_body=raw_body,
        ),
        "Idempotency-Key": f"promo-create-{uuid4()}",
    }


@pytest.mark.asyncio
async def test_admin_created_promo_redeems_once_in_happy_fox_and_hits_max_uses() -> None:
    database = Database(os.environ["FOXGEN_DATABASE_URL"])
    admin_services = AdminServices.build(
        database,
        bootstrap_superuser_ids=frozenset({ADMIN_ID}),
    )
    app = create_app(
        _settings(),
        manage_resources=False,
        billing_service=SqlAlchemyBillingRepository(database),
        admin_services=admin_services,
    )
    app.state.database = database

    code = f"FOX{uuid4().hex[:10].upper()}"
    first_user = 997_100_000 + uuid4().int % 400_000
    second_user = first_user + 500_000
    try:
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 32124))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            promo_path = "/internal/admin/promos"
            promo_body = json.dumps(
                {
                    "code": code.lower(),
                    "reward_units": 600,
                    "max_uses": 1,
                    "metadata": {"source": "promo-e2e"},
                },
                separators=(",", ":"),
            ).encode("utf-8")
            created = await client.post(
                promo_path,
                content=promo_body,
                headers=_admin_headers(
                    path=promo_path,
                    raw_body=promo_body,
                    request_id=f"promo-admin-{uuid4()}",
                ),
            )
            assert created.status_code == 200
            assert created.json()["code"] == code
            assert created.json()["reward_units"] == 600
            assert created.json()["max_uses"] == 1

            unauthorized = await client.post(
                "/v1/miniapp/promos/redeem",
                json={"code": code},
            )
            assert unauthorized.status_code == 401

            first = await client.post(
                "/v1/miniapp/promos/redeem",
                headers=_miniapp_headers(first_user),
                json={"code": f"  {code.lower()}  "},
            )
            replay = await client.post(
                "/v1/miniapp/promos/redeem",
                headers=_miniapp_headers(first_user),
                json={"code": code},
            )
            assert first.status_code == 200
            assert first.json() == {
                "code": code,
                "reward_units": 600,
                "available_units": 600,
                "currency": "CREDIT",
                "replayed": False,
            }
            assert replay.status_code == 200
            assert replay.json()["available_units"] == 600
            assert replay.json()["replayed"] is True

            ledger = await client.get(
                f"/v1/users/{first_user}/ledger",
                headers={"Authorization": f"Bearer {INTERNAL_TOKEN}"},
            )
            assert ledger.status_code == 200
            promo_entries = [
                item
                for item in ledger.json()
                if item["actor"] == "system:promo" and item["available_delta"] == 600
            ]
            assert len(promo_entries) == 1
            assert promo_entries[0]["reason"] == f"Promo code {code}"

            exhausted = await client.post(
                "/v1/user-portal/promos/redeem",
                headers=_internal_headers(second_user),
                json={"code": code},
            )
            assert exhausted.status_code == 422
            assert "Лимит активаций" in exhausted.json()["message"]

        async with database.session() as session:
            promo = await session.get(PromoCode, code)
            wallet = await session.get(WalletAccount, first_user)
            second_wallet = await session.get(WalletAccount, second_user)
            redemptions = int(
                await session.scalar(
                    select(func.count(PromoRedemption.id)).where(PromoRedemption.promo_code == code)
                )
                or 0
            )
            promo_ledger = int(
                await session.scalar(
                    select(func.count(LedgerEntry.id)).where(
                        LedgerEntry.idempotency_key == f"promo-credit:{code}:{first_user}"
                    )
                )
                or 0
            )
            assert promo is not None and promo.uses == 1
            assert wallet is not None and wallet.available_units == 600
            assert second_wallet is None
            assert redemptions == 1
            assert promo_ledger == 1
    finally:
        async with database.session() as session:
            async with session.begin():
                await session.execute(
                    delete(PromoRedemption).where(PromoRedemption.promo_code == code)
                )
                await session.execute(
                    delete(LedgerEntry).where(LedgerEntry.user_id.in_([first_user, second_user]))
                )
                await session.execute(
                    delete(WalletAccount).where(
                        WalletAccount.user_id.in_([first_user, second_user])
                    )
                )
                await session.execute(delete(User).where(User.id.in_([first_user, second_user])))
                await session.execute(delete(PromoCode).where(PromoCode.code == code))
        await database.close()
