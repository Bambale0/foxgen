import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi.testclient import TestClient

from foxgen.api.app import create_app
from foxgen.core.config import Settings
from foxgen.domain.lifecycle import CallbackEvent
from foxgen.miniapp_release import MINIAPP_RELEASE


@dataclass
class FakeCallbackRecorder:
    events: list[CallbackEvent] = field(default_factory=list)

    async def record(self, event: CallbackEvent) -> None:
        self.events.append(event)


def _sign(body: bytes, timestamp: str, secret: str) -> str:
    return hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def test_liveness_and_catalog() -> None:
    app = create_app(Settings(env="test"), manage_resources=False)

    with TestClient(app) as client:
        live = client.get("/health/live")
        models = client.get("/v1/models")

    assert live.status_code == 200
    assert live.json()["status"] == "ok"
    assert models.status_code == 200
    assert any(item["slug"] == "gpt-image-2" for item in models.json())


def test_miniapp_html_shell_is_never_cacheable() -> None:
    app = create_app(Settings(env="test"), manage_resources=False)

    with TestClient(app) as client:
        response = client.get(f"/mini-app/?release={MINIAPP_RELEASE}")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["expires"] == "0"
    assert f'name="foxgen-miniapp-shell" content="{MINIAPP_RELEASE}"' in response.text
    assert f"/mini-app/parity-app.js?v={MINIAPP_RELEASE}" in response.text
    assert f"/mini-app/backend-parity-ui.js?v={MINIAPP_RELEASE}" in response.text
    assert "product-home" not in response.text


def test_kie_webhook_accepts_nested_task_id_persists_and_returns_200() -> None:
    secret = "test-webhook-secret"
    timestamp = str(int(time.time()))
    task_id = "task-nested-1"
    recorder = FakeCallbackRecorder()
    app = create_app(
        Settings(env="test", kie_webhook_hmac_key=secret),
        manage_resources=False,
        callback_recorder=recorder,
    )

    with TestClient(app) as client:
        response = client.post(
            "/webhooks/kie",
            content=json.dumps({"code": 200, "data": {"taskId": task_id, "state": "success"}}),
            headers={
                "Content-Type": "application/json",
                "X-Kie-Timestamp": timestamp,
                "X-Kie-Signature": _sign(
                    json.dumps({"code": 200, "data": {"taskId": task_id, "state": "success"}}).encode(),
                    timestamp,
                    secret,
                ),
            },
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert recorder.events[-1].provider_task_id == task_id


def test_kie_webhook_rejects_bad_signature() -> None:
    app = create_app(
        Settings(env="test", kie_webhook_hmac_key="test-webhook-secret"),
        manage_resources=False,
    )
    with TestClient(app) as client:
        response = client.post(
            "/webhooks/kie",
            content=b'{"taskId":"bad"}',
            headers={
                "Content-Type": "application/json",
                "X-Kie-Timestamp": str(int(time.time())),
                "X-Kie-Signature": "bad",
            },
        )
    assert response.status_code == 401


def test_kie_webhook_rejects_missing_task_id() -> None:
    secret = "test-webhook-secret"
    timestamp = str(int(time.time()))
    body = json.dumps({"code": 200, "data": {"state": "success"}}).encode()
    app = create_app(
        Settings(env="test", kie_webhook_hmac_key=secret),
        manage_resources=False,
    )
    with TestClient(app) as client:
        response = client.post(
            "/webhooks/kie",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Kie-Timestamp": timestamp,
                "X-Kie-Signature": _sign(body, timestamp, secret),
            },
        )
    assert response.status_code == 422


def test_kie_webhook_rejects_stale_timestamp() -> None:
    secret = "test-webhook-secret"
    timestamp = str(int(time.time()) - 600)
    body = json.dumps({"taskId": "stale", "state": "success"}).encode()
    app = create_app(
        Settings(env="test", kie_webhook_hmac_key=secret),
        manage_resources=False,
    )
    with TestClient(app) as client:
        response = client.post(
            "/webhooks/kie",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Kie-Timestamp": timestamp,
                "X-Kie-Signature": _sign(body, timestamp, secret),
            },
        )
    assert response.status_code == 401


def test_openapi_exposes_expected_endpoints() -> None:
    app = create_app(Settings(env="test"), manage_resources=False)
    schema: dict[str, Any] = app.openapi()
    paths = schema["paths"]
    assert "/v1/models" in paths
    assert "/v1/generations" in paths
    assert "/v1/tasks" in paths
    assert "/webhooks/kie" in paths
