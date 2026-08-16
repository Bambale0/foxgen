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
from foxgen.application.submissions import SubmissionReceipt
from foxgen.application.suno_extend import SunoTrackSource
from foxgen.core.config import Settings
from foxgen.domain.models import GenerationStatus


BOT_TOKEN = "123456:test-suno-extend-bot"
JWT_SECRET = "suno-extend-miniapp-secret-long-enough"
USER_ID = 515151
SOURCE_ID = UUID("11111111-2222-3333-4444-555555555555")


def signed_init_data() -> str:
    values = {
        "auth_date": str(int(time.time())),
        "query_id": "AAE-suno-extend-test",
        "user": json.dumps(
            {
                "id": USER_ID,
                "first_name": "Suno",
                "username": "suno_owner",
            },
            separators=(",", ":"),
        ),
    }
    check = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


class FakeExtendService:
    def __init__(self) -> None:
        self.extend_calls: list[dict[str, object]] = []

    async def list_sources(
        self,
        *,
        user_id: int,
        limit: int = 40,
    ) -> tuple[SunoTrackSource, ...]:
        assert user_id == USER_ID
        assert limit == 40
        return (
            SunoTrackSource(
                generation_id=SOURCE_ID,
                model_slug="suno-v5",
                audio_id="owned-audio-id",
                title="Last Train",
                duration_seconds=120.0,
                preview_url="https://storage.example.test/source.mp3",
                created_at=datetime.now(timezone.utc),
            ),
        )

    async def extend(self, **kwargs: object) -> SubmissionReceipt:
        self.extend_calls.append(dict(kwargs))
        return SubmissionReceipt(
            generation_id=uuid4(),
            model_slug="suno-v5-extend",
            provider_model="V5",
            status=GenerationStatus.QUEUED,
            provider_task_id=None,
            replayed=False,
        )


def settings() -> Settings:
    return Settings(
        env="test",
        telegram_bot_token=BOT_TOKEN,
        miniapp_enabled=True,
        miniapp_jwt_secret=JWT_SECRET,
        internal_api_token="trusted-user-api-token",
    )


def app_client() -> tuple[TestClient, str, FakeExtendService]:
    app = create_app(settings(), manage_resources=False)
    service = FakeExtendService()
    app.state.suno_extend_service = service
    client = TestClient(app)
    auth = client.post("/v1/miniapp/auth", json={"init_data": signed_init_data()})
    assert auth.status_code == 200
    return client, auth.json()["access_token"], service


def test_miniapp_lists_only_service_projected_owned_tracks() -> None:
    client, token, _service = app_client()

    with client:
        response = client.get(
            "/v1/miniapp/music/suno/sources",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "generation_id": str(SOURCE_ID),
            "model_slug": "suno-v5",
            "audio_id": "owned-audio-id",
            "title": "Last Train",
            "duration_seconds": 120.0,
            "preview_url": "https://storage.example.test/source.mp3",
            "created_at": response.json()["items"][0]["created_at"],
        }
    ]


def test_miniapp_extend_uses_jwt_owner_and_namespaced_idempotency() -> None:
    client, token, service = app_client()

    with client:
        response = client.post(
            "/v1/miniapp/music/suno/extend",
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": "extend-ui-001",
            },
            json={
                "source_generation_id": str(SOURCE_ID),
                "audio_id": "owned-audio-id",
                "default_param_flag": True,
                "prompt": "Continue the chorus",
                "style": "indie pop",
                "title": "Last Train Extended",
                "continue_at": 92.5,
            },
        )

    assert response.status_code == 202
    assert response.json()["model_slug"] == "suno-v5-extend"
    assert service.extend_calls == [
        {
            "user_id": USER_ID,
            "username": "suno_owner",
            "source_generation_id": SOURCE_ID,
            "audio_id": "owned-audio-id",
            "input_data": {
                "default_param_flag": True,
                "prompt": "Continue the chorus",
                "style": "indie pop",
                "title": "Last Train Extended",
                "continue_at": 92.5,
                "negative_tags": "",
                "vocal_gender": None,
                "style_weight": None,
                "weirdness_constraint": None,
                "audio_weight": None,
            },
            "idempotency_key": "miniapp:suno-extend:extend-ui-001",
        }
    ]


def test_miniapp_extend_requires_real_telegram_jwt() -> None:
    client, _token, service = app_client()

    with client:
        response = client.get("/v1/miniapp/music/suno/sources")

    assert response.status_code == 401
    assert service.extend_calls == []
