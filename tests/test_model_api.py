from fastapi.testclient import TestClient

from foxgen.api.app import create_app
from foxgen.core.config import Settings


def test_model_detail_exposes_contract_schema() -> None:
    app = create_app(Settings(env="test"), manage_resources=False)

    with TestClient(app) as client:
        response = client.get("/v1/models/seedance-2")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider_model"] == "bytedance/seedance-2"
    assert "first_frame_url" in payload["input_schema"]["properties"]


def test_model_validation_normalizes_nano_banana_payload() -> None:
    app = create_app(Settings(env="test"), manage_resources=False)

    with TestClient(app) as client:
        response = client.post(
            "/v1/models/nano-banana-2/validate",
            json={"input": {"prompt": "A clean fox logo"}},
        )

    assert response.status_code == 200
    assert response.json()["model"] == "nano-banana-2"
    assert response.json()["input"]["resolution"] == "1K"


def test_model_validation_rejects_conflicting_seedance_modes() -> None:
    app = create_app(Settings(env="test"), manage_resources=False)

    with TestClient(app) as client:
        response = client.post(
            "/v1/models/seedance-2/validate",
            json={
                "input": {
                    "prompt": "Animate this scene",
                    "first_frame_url": "https://example.com/frame.png",
                    "reference_image_urls": ["https://example.com/reference.png"],
                }
            },
        )

    assert response.status_code == 422
