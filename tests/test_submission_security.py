from uuid import UUID

from fastapi.testclient import TestClient

from foxgen.api.app import create_app
from foxgen.application.submissions import SubmissionReceipt
from foxgen.core.config import Settings
from foxgen.domain.models import GenerationStatus


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
    ) -> SubmissionReceipt:
        self.calls.append(
            {
                "user_id": user_id,
                "username": username,
                "model_slug": model_slug,
                "input_data": input_data,
                "idempotency_key": idempotency_key,
            }
        )
        return SubmissionReceipt(
            generation_id=UUID("11111111-1111-1111-1111-111111111111"),
            model_slug=model_slug,
            provider_model="seedream/5-pro-text-to-image",
            status=GenerationStatus.SUBMITTED,
            provider_task_id="provider-task-1",
            replayed=False,
        )


def test_paid_submission_is_disabled_by_default() -> None:
    service = FakeSubmissionService()
    app = create_app(Settings(env="test"), manage_resources=False, submission_service=service)

    with TestClient(app) as client:
        response = client.post(
            "/v1/models/seedream-5-pro/tasks",
            json={"input": {"prompt": "A fox"}},
        )

    assert response.status_code == 503
    assert service.calls == []


def test_invalid_internal_token_never_reaches_submission_service() -> None:
    service = FakeSubmissionService()
    settings = Settings(
        env="test",
        task_submission_enabled=True,
        internal_api_token="correct-token",
    )
    app = create_app(settings, manage_resources=False, submission_service=service)

    with TestClient(app) as client:
        response = client.post(
            "/v1/models/seedream-5-pro/tasks",
            headers={
                "Authorization": "Bearer wrong-token",
                "Idempotency-Key": "request-0001",
                "X-FoxGen-User-Id": "42",
            },
            json={"input": {"prompt": "A fox"}},
        )

    assert response.status_code == 401
    assert service.calls == []


def test_valid_internal_request_requires_user_and_idempotency_identity() -> None:
    service = FakeSubmissionService()
    settings = Settings(
        env="test",
        task_submission_enabled=True,
        internal_api_token="correct-token",
    )
    app = create_app(settings, manage_resources=False, submission_service=service)

    with TestClient(app) as client:
        response = client.post(
            "/v1/models/seedream-5-pro/tasks",
            headers={
                "Authorization": "Bearer correct-token",
                "Idempotency-Key": "request-0001",
                "X-FoxGen-User-Id": "42",
                "X-FoxGen-Username": "fox-user",
            },
            json={"input": {"prompt": "A premium fox portrait"}},
        )

    assert response.status_code == 202
    assert response.json() == {
        "generation_id": "11111111-1111-1111-1111-111111111111",
        "model": "seedream-5-pro",
        "provider_model": "seedream/5-pro-text-to-image",
        "status": "submitted",
        "provider_task_id": "provider-task-1",
        "replayed": False,
    }
    assert service.calls == [
        {
            "user_id": 42,
            "username": "fox-user",
            "model_slug": "seedream-5-pro",
            "input_data": {"prompt": "A premium fox portrait"},
            "idempotency_key": "request-0001",
        }
    ]
