from fastapi.testclient import TestClient

from foxgen.api.app import create_app
from foxgen.core.config import Settings


def test_liveness_and_catalog() -> None:
    app = create_app(Settings(env="test"), manage_resources=False)

    with TestClient(app) as client:
        live = client.get("/health/live")
        models = client.get("/v1/models")

    assert live.status_code == 200
    assert live.json()["status"] == "ok"
    assert models.status_code == 200
    assert any(item["slug"] == "gpt-image-2" for item in models.json())
