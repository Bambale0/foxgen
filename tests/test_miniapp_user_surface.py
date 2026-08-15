from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from foxgen.api.app import create_app
from foxgen.application.billing import BalanceSnapshot, LedgerSnapshot, PriceSnapshot
from foxgen.application.submissions import SubmissionReceipt
from foxgen.core.config import Settings
from foxgen.domain.models import GenerationStatus
from foxgen.infra.miniapp import MiniAppGenerationSnapshot


BOT_TOKEN = "123456:expanded-miniapp-token"
JWT_SECRET = "expanded-miniapp-jwt-secret-long-enough"
USER_ID = 515151


def signed_init_data() -> str:
    values = {
        "auth_date": str(int(time.time())),
        "query_id": "AAE-expanded-surface",
        "user": json.dumps(
            {
                "id": USER_ID,
                "first_name": "Happy",
                "username": "fox_user",
                "language_code": "ru",
            },
            separators=(",", ":"),
        ),
    }
    check = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


class Billing:
    def __init__(self) -> None:
        self.user_ids: list[int] = []

    async def get_balance(self, user_id: int) -> BalanceSnapshot:
        self.user_ids.append(user_id)
        return BalanceSnapshot(
            user_id=user_id,
            currency="CREDIT",
            available_units=120,
            reserved_units=10,
            version=4,
        )

    async def list_active_prices(self) -> tuple[PriceSnapshot, ...]:
        return (
            PriceSnapshot(
                id=uuid4(),
                model_slug="seedream-5-pro",
                version=1,
                amount_units=11,
                currency="CREDIT",
                enabled=True,
                active_from=datetime.now(timezone.utc),
                active_until=None,
            ),
        )

    async def list_ledger(
        self,
        *,
        user_id: int,
        limit: int = 50,
    ) -> tuple[LedgerSnapshot, ...]:
        self.user_ids.append(user_id)
        return (
            LedgerSnapshot(
                id=uuid4(),
                entry_type="reserve",
                currency="CREDIT",
                available_delta=-11,
                reserved_delta=11,
                generation_id=None,
                reason=f"limit={limit}",
                actor="test",
                created_at=datetime.now(timezone.utc),
            ),
        )


class Submission:
    async def submit(
        self,
        *,
        user_id: int,
        username: str | None,
        model_slug: str,
        input_data: dict[str, object],
        idempotency_key: str,
    ) -> SubmissionReceipt:
        del user_id, username, input_data, idempotency_key
        return SubmissionReceipt(
            generation_id=uuid4(),
            model_slug=model_slug,
            provider_model=model_slug,
            status=GenerationStatus.QUEUED,
            provider_task_id=None,
            replayed=False,
        )


class Repository:
    async def list_recent(
        self,
        *,
        user_id: int,
        limit: int,
    ) -> tuple[MiniAppGenerationSnapshot, ...]:
        del user_id, limit
        return ()

    async def get_for_user(
        self,
        *,
        generation_id: UUID,
        user_id: int,
    ) -> MiniAppGenerationSnapshot | None:
        del generation_id, user_id
        return None


def settings() -> Settings:
    return Settings(
        env="test",
        telegram_bot_token=BOT_TOKEN,
        miniapp_jwt_secret=JWT_SECRET,
        miniapp_enabled=True,
        task_submission_enabled=True,
        internal_api_token="expanded-input-secret",
        kie_api_key="kie-test",
    )


def client_and_token() -> tuple[TestClient, str, Billing]:
    billing = Billing()
    app = create_app(
        settings(),
        manage_resources=False,
        submission_service=Submission(),
        billing_service=billing,
        miniapp_repository=Repository(),
    )
    client = TestClient(app)
    auth = client.post("/v1/miniapp/auth", json={"init_data": signed_init_data()})
    assert auth.status_code == 200
    return client, auth.json()["access_token"], billing


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_model_catalog_exposes_schema_and_only_submission_models() -> None:
    client, token, _billing = client_and_token()

    with client:
        denied = client.get("/v1/miniapp/models")
        response = client.get("/v1/miniapp/models", headers=auth_headers(token))

    assert denied.status_code == 401
    assert response.status_code == 200
    models = response.json()
    slugs = {item["slug"] for item in models}
    assert slugs == {
        "seedream-5-pro",
        "seedream-5-pro-edit",
        "nano-banana-2",
        "nano-banana-pro",
        "seedance-2",
        "seedance-2-mini",
    }
    for item in models:
        assert item["enabled"] is True
        assert item["family"]
        assert item["contract"]
        assert isinstance(item["rank"], int)
        assert item["input_schema"]["type"] == "object"
        assert "properties" in item["input_schema"]


def test_model_validation_normalizes_defaults_before_paid_submit() -> None:
    client, token, _billing = client_and_token()

    with client:
        valid = client.post(
            "/v1/miniapp/models/seedream-5-pro/validate",
            headers=auth_headers(token),
            json={"input": {"prompt": "fox in cinematic light"}},
        )
        invalid = client.post(
            "/v1/miniapp/models/seedream-5-pro/validate",
            headers=auth_headers(token),
            json={"input": {"prompt": "fox", "aspect_ratio": "not-a-ratio"}},
        )

    assert valid.status_code == 200
    assert valid.json()["input"] == {
        "prompt": "fox in cinematic light",
        "aspect_ratio": "1:1",
        "quality": "basic",
        "output_format": "png",
        "nsfw_checker": False,
    }
    assert invalid.status_code == 422
    assert isinstance(invalid.json()["detail"], list)


def test_user_wallet_projection_is_owner_bound_and_refreshable() -> None:
    client, token, billing = client_and_token()

    with client:
        balance = client.get("/v1/miniapp/balance", headers=auth_headers(token))
        prices = client.get("/v1/miniapp/prices", headers=auth_headers(token))
        ledger = client.get("/v1/miniapp/ledger?limit=137", headers=auth_headers(token))

    assert balance.status_code == 200
    assert balance.json()["user_id"] == USER_ID
    assert balance.json()["available_units"] == 120
    assert balance.json()["reserved_units"] == 10
    assert prices.status_code == 200
    assert prices.json()[0]["model_slug"] == "seedream-5-pro"
    assert ledger.status_code == 200
    assert ledger.json()[0]["reason"] == "limit=137"
    assert billing.user_ids == [USER_ID, USER_ID]


def test_bootstrap_advertises_frontend_runtime_limits_and_features() -> None:
    client, token, _billing = client_and_token()

    with client:
        response = client.get("/v1/miniapp/bootstrap", headers=auth_headers(token))

    assert response.status_code == 200
    body = response.json()
    assert body["features"] == {"task_submission": True, "input_media": True}
    assert body["limits"]["generation_history_max"] == 100
    assert body["limits"]["ledger_history_max"] == 200
    assert body["limits"]["input_media_max_bytes"] > 0
