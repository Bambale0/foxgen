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
from foxgen.miniapp_release import MINIAPP_RELEASE

BOT_TOKEN = "123456:test-miniapp-bot-token"
JWT_SECRET = "miniapp-jwt-test-secret-that-is-long-enough"
USER_ID = 424242
IDEMPOTENCY_KEY = "idem-001"


def signed_init_data(*, user_id: int = USER_ID) -> str:
    values = {
        "auth_date": str(int(time.time())),
        "query_id": "AAE-api-test-query",
        "user": json.dumps(
            {
                "id": user_id,
                "first_name": "Алексей",
                "username": "alex_fox",
                "language_code": "ru",
                "is_premium": True,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }
    check = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


class FakeBillingService:
    async def get_balance(self, user_id: int) -> BalanceSnapshot:
        return BalanceSnapshot(
            user_id=user_id,
            currency="CREDIT",
            available_units=2450,
            reserved_units=20,
            version=3,
        )

    async def list_active_prices(self) -> tuple[PriceSnapshot, ...]:
        now = datetime.now(timezone.utc)
        return (
            PriceSnapshot(
                id=uuid4(),
                model_slug="seedream-5-pro",
                version=1,
                amount_units=10,
                currency="CREDIT",
                enabled=True,
                active_from=now,
                active_until=None,
            ),
            PriceSnapshot(
                id=uuid4(),
                model_slug="elevenlabs-turbo-2-5",
                version=1,
                amount_units=42,
                currency="CREDIT",
                enabled=True,
                active_from=now,
                active_until=None,
            ),
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
                id=uuid4(),
                entry_type="credit",
                currency="CREDIT",
                available_delta=1000,
                reserved_delta=0,
                generation_id=None,
                reason="test credit",
                actor="test",
                created_at=datetime.now(timezone.utc),
            ),
        )


class FakeSubmissionService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def submit(
        self,
        *,
        user_id: int,
        username: str | None,
        model_slug: str,
        input_data: dict[str, object],
        idempotency_key: str,
        source_publication_id: UUID | None = None,
    ) -> SubmissionReceipt:
        self.calls.append(
            {
                "user_id": user_id,
                "username": username,
                "model_slug": model_slug,
                "input_data": input_data,
                "idempotency_key": idempotency_key,
                "source_publication_id": source_publication_id,
            }
        )
        return SubmissionReceipt(
            generation_id=uuid4(),
            model_slug=model_slug,
            provider_model=model_slug,
            status=GenerationStatus.QUEUED,
            provider_task_id=None,
            replayed=False,
        )


class FakeMiniAppRepository:
    def __init__(self) -> None:
        self.requested_user_ids: list[int] = []

    async def list_recent(
        self,
        *,
        user_id: int,
        limit: int,
    ) -> tuple[MiniAppGenerationSnapshot, ...]:
        del limit
        self.requested_user_ids.append(user_id)
        return ()

    async def get_for_user(
        self,
        *,
        generation_id: UUID,
        user_id: int,
    ) -> MiniAppGenerationSnapshot | None:
        del generation_id
        self.requested_user_ids.append(user_id)
        return None


def app_settings(tmp_path: str | None = None) -> Settings:
    values: dict[str, object] = {
        "env": "test",
        "telegram_bot_token": BOT_TOKEN,
        "miniapp_jwt_secret": JWT_SECRET,
        "miniapp_enabled": True,
        "task_submission_enabled": True,
        "internal_api_token": "input-signing-test",
        "kie_api_key": "kie-test",
    }
    if tmp_path is not None:
        values["telegram_input_storage_root"] = tmp_path
    return Settings(**values)


def authenticated_client(
    *,
    submission_service: FakeSubmissionService | None = None,
    repository: FakeMiniAppRepository | None = None,
) -> tuple[TestClient, str, FakeSubmissionService, FakeMiniAppRepository]:
    submission = submission_service or FakeSubmissionService()
    miniapp_repository = repository or FakeMiniAppRepository()
    app = create_app(
        app_settings(),
        manage_resources=False,
        submission_service=submission,
        billing_service=FakeBillingService(),
        miniapp_repository=miniapp_repository,
    )
    client = TestClient(app)
    response = client.post("/v1/miniapp/auth", json={"init_data": signed_init_data()})
    assert response.status_code == 200
    token = response.json()["access_token"]
    return client, token, submission, miniapp_repository


def test_happy_fox_static_shell_is_packaged_and_public() -> None:
    app = create_app(app_settings(), manage_resources=False)

    with TestClient(app) as client:
        response = client.get("/mini-app/")

    assert response.status_code == 200
    assert "Happy Fox" in response.text
    assert "<title>Happy Fox</title>" in response.text
    assert "FOXGEN" not in response.text
    assert f'name="foxgen-miniapp-shell" content="{MINIAPP_RELEASE}"' in response.text
    assert "React Mini App" in response.text
    assert "parity-app.js" not in response.text
    assert "tts-parity.js" not in response.text


def test_bootstrap_requires_jwt_and_is_bound_to_telegram_user() -> None:
    client, token, _submission, repository = authenticated_client()

    with client:
        denied = client.get("/v1/miniapp/bootstrap")
        response = client.get(
            "/v1/miniapp/bootstrap",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert denied.status_code == 401
    assert response.status_code == 200
    body = response.json()
    assert body["brand"] == "Happy Fox"
    assert body["user"]["id"] == USER_ID
    assert body["balance"]["available_units"] == 2450
    assert repository.requested_user_ids == [USER_ID]


def test_bootstrap_exposes_tts_as_schema_driven_audio_product() -> None:
    client, token, _submission, _repository = authenticated_client()

    with client:
        response = client.get(
            "/v1/miniapp/bootstrap",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    body = response.json()
    tts = next(item for item in body["models"] if item["slug"] == "elevenlabs-turbo-2-5")
    assert tts["media_kind"] == "audio"
    assert tts["capabilities"] == ["text_to_speech"]
    tts_price = next(
        item for item in body["prices"] if item["model_slug"] == "elevenlabs-turbo-2-5"
    )
    assert tts_price["amount_units"] == 42
    assert tts_price["currency"] == "CREDIT"
    assert tts_price["version"] == 1
    schema = tts["input_schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"text", "voice"}
    assert schema["properties"]["speed"]["minimum"] == 0.7
    assert schema["properties"]["speed"]["maximum"] == 1.2
    assert schema["properties"]["stability"]["default"] == 0.5


def test_paid_miniapp_task_reuses_submission_service_and_user_identity() -> None:
    client, token, submission, _repository = authenticated_client()

    with client:
        response = client.post(
            "/v1/miniapp/tasks",
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": IDEMPOTENCY_KEY,
            },
            json={
                "model_slug": "seedream-5-pro",
                "input": {
                    "prompt": "cinematic fox portrait",
                    "aspect_ratio": "1:1",
                    "quality": "basic",
                    "output_format": "png",
                    "nsfw_checker": False,
                },
            },
        )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert submission.calls == [
        {
            "user_id": USER_ID,
            "username": "alex_fox",
            "model_slug": "seedream-5-pro",
            "input_data": {
                "prompt": "cinematic fox portrait",
                "aspect_ratio": "1:1",
                "quality": "basic",
                "output_format": "png",
                "nsfw_checker": False,
            },
            "idempotency_key": f"miniapp:{IDEMPOTENCY_KEY}",
            "source_publication_id": None,
        }
    ]


def test_paid_miniapp_tts_reuses_same_submission_service() -> None:
    client, token, submission, _repository = authenticated_client()

    payload = {
        "text": "Привет из Happy Fox",
        "voice": "Rachel",
        "stability": 0.5,
        "similarity_boost": 0.75,
        "style": 0.0,
        "speed": 1.0,
        "timestamps": False,
        "previous_text": "",
        "next_text": "",
        "language_code": "ru",
    }
    with client:
        validation = client.post(
            "/v1/miniapp/models/elevenlabs-turbo-2-5/validate",
            headers={"Authorization": f"Bearer {token}"},
            json={"input": payload},
        )
        response = client.post(
            "/v1/miniapp/tasks",
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": "tts-miniapp-001",
            },
            json={"model_slug": "elevenlabs-turbo-2-5", "input": payload},
        )

    assert validation.status_code == 200
    assert validation.json()["input"] == payload
    assert response.status_code == 202
    assert submission.calls[-1] == {
        "user_id": USER_ID,
        "username": "alex_fox",
        "model_slug": "elevenlabs-turbo-2-5",
        "input_data": payload,
        "idempotency_key": "miniapp:tts-miniapp-001",
        "source_publication_id": None,
    }


def test_generation_detail_never_crosses_owner_boundary() -> None:
    client, token, _submission, repository = authenticated_client()
    generation_id = uuid4()

    with client:
        response = client.get(
            f"/v1/miniapp/generations/{generation_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 404
    assert repository.requested_user_ids == [USER_ID]


def test_input_upload_is_namespaced_to_authenticated_user(tmp_path: object) -> None:
    settings = app_settings(str(tmp_path))
    app = create_app(
        settings,
        manage_resources=False,
        submission_service=FakeSubmissionService(),
        billing_service=FakeBillingService(),
        miniapp_repository=FakeMiniAppRepository(),
    )

    with TestClient(app) as client:
        auth = client.post("/v1/miniapp/auth", json={"init_data": signed_init_data()})
        token = auth.json()["access_token"]
        response = client.post(
            "/v1/miniapp/input-media",
            content=b"private-test-bytes",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "image/png",
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "image"
    assert body["storage_key"].startswith(f"inputs/miniapp/{USER_ID}/")
    assert "input-signing-test" not in body["url"]
