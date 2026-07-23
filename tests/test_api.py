import base64
import hashlib
import hmac
import time

from fastapi.testclient import TestClient

from foxgen.api.app import create_app
from foxgen.core.config import Settings


class FakeCallbackRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def record_provider_event(
        self,
        *,
        provider: str,
        provider_task_id: str,
        event_hash: str,
        payload: dict[str, object],
    ) -> bool:
        self.calls.append(
            {
                "provider": provider,
                "provider_task_id": provider_task_id,
                "event_hash": event_hash,
                "payload": payload,
            }
        )
        return True


def sign(task_id: str, timestamp: str, secret: str) -> str:
    digest = hmac.new(
        secret.encode(),
        f"{task_id}.{timestamp}".encode(),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode()


def test_liveness_and_catalog() -> None:
    app = create_app(Settings(env="test"), manage_resources=False)

    with TestClient(app) as client:
        live = client.get("/health/live")
        models = client.get("/v1/models")

    assert live.status_code == 200
    assert live.json()["status"] == "ok"
    assert models.status_code == 200
    assert any(item["slug"] == "gpt-image-2" for item in models.json())


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
            json={"data": {"taskId": task_id}, "state": "success"},
            headers={
                "X-Webhook-Timestamp": timestamp,
                "X-Webhook-Signature": sign(task_id, timestamp, secret),
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "accepted",
        "task_id": task_id,
        "duplicate": False,
    }
    assert recorder.calls[0]["provider_task_id"] == task_id
    assert recorder.calls[0]["payload"] == {
        "data": {"taskId": task_id},
        "state": "success",
    }
