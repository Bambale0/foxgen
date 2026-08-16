from fastapi.testclient import TestClient

from foxgen.api.app import create_app
from foxgen.api.miniapp_security import TelegramMiniAppUser, issue_miniapp_token
from foxgen.application.promos import PromoRedemptionResult
from foxgen.core.config import Settings


USER_ID = 123456899
INTERNAL_TOKEN = "promo-internal-token-long-enough"
JWT_SECRET = "promo-miniapp-jwt-secret-long-enough"


class FakePromoService:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str | None, str]] = []

    async def redeem(
        self,
        *,
        user_id: int,
        username: str | None,
        code: str,
    ) -> PromoRedemptionResult:
        self.calls.append((user_id, username, code))
        return PromoRedemptionResult(
            code=code.strip().upper(),
            reward_units=500,
            available_units=1500,
            replayed=False,
        )


def settings() -> Settings:
    return Settings(
        env="test",
        miniapp_enabled=True,
        miniapp_jwt_secret=JWT_SECRET,
        internal_api_token=INTERNAL_TOKEN,
    )


def miniapp_headers() -> dict[str, str]:
    token = issue_miniapp_token(
        TelegramMiniAppUser(id=USER_ID, first_name="Promo", username="promo_user"),
        secret=JWT_SECRET,
        ttl_seconds=3600,
    )
    return {"Authorization": f"Bearer {token}"}


def trusted_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {INTERNAL_TOKEN}",
        "X-FoxGen-User-Id": str(USER_ID),
        "X-FoxGen-Username": "promo_user",
    }


def client() -> tuple[TestClient, FakePromoService]:
    service = FakePromoService()
    app = create_app(settings(), manage_resources=False)
    app.state.promo_redemption_service = service
    return TestClient(app), service


def test_miniapp_promo_redeem_is_owner_bound() -> None:
    test_client, service = client()
    with test_client:
        assert (
            test_client.post(
                "/v1/miniapp/promos/redeem",
                json={"code": "fox500"},
            ).status_code
            == 401
        )
        response = test_client.post(
            "/v1/miniapp/promos/redeem",
            headers=miniapp_headers(),
            json={"code": "fox500"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "code": "FOX500",
        "reward_units": 500,
        "available_units": 1500,
        "currency": "CREDIT",
        "replayed": False,
    }
    assert service.calls == [(USER_ID, "promo_user", "fox500")]


def test_trusted_bot_promo_redeem_requires_owner_header() -> None:
    test_client, service = client()
    with test_client:
        missing_owner = test_client.post(
            "/v1/user-portal/promos/redeem",
            headers={"Authorization": f"Bearer {INTERNAL_TOKEN}"},
            json={"code": "FOX500"},
        )
        response = test_client.post(
            "/v1/user-portal/promos/redeem",
            headers=trusted_headers(),
            json={"code": "FOX500"},
        )

    assert missing_owner.status_code == 401
    assert response.status_code == 200
    assert service.calls == [(USER_ID, "promo_user", "FOX500")]
