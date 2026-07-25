from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID

from fastapi.testclient import TestClient

from foxgen.api.app import create_app
from foxgen.application.generation_ops import UnknownResolutionAction
from foxgen.application.lifecycle import GenerationWorkItem
from foxgen.core.config import Settings
from foxgen.domain.models import GenerationStatus


GENERATION_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
NOW = datetime(2026, 7, 25, tzinfo=timezone.utc)


class FakeGenerationOperations:
    def __init__(self) -> None:
        self.item = GenerationWorkItem(
            id=GENERATION_ID,
            user_id=42,
            model_slug="seedream-5-pro",
            status=GenerationStatus.PROCESSING,
            input_payload={},
            result_payload=None,
            provider_task_id="provider-1",
            status_reason="provider_processing",
            status_changed_at=NOW,
            processing_at=NOW,
        )
        self.resolution: tuple[UnknownResolutionAction, str | None] | None = None

    async def get_for_user(
        self,
        *,
        generation_id: UUID,
        user_id: int,
    ) -> GenerationWorkItem:
        assert generation_id == GENERATION_ID
        assert user_id == 42
        return self.item

    async def cancel_for_user(
        self,
        *,
        generation_id: UUID,
        user_id: int,
    ) -> GenerationWorkItem:
        assert generation_id == GENERATION_ID
        assert user_id == 42
        self.item = replace(
            self.item,
            status=GenerationStatus.CANCELLED,
            status_reason="cancelled_by_user_before_submission",
            completed_at=NOW,
        )
        return self.item

    async def resolve_submission_unknown(
        self,
        *,
        generation_id: UUID,
        action: UnknownResolutionAction,
        provider_task_id: str | None,
        result_payload: dict[str, object] | None,
        reason: str,
    ) -> GenerationWorkItem:
        del result_payload, reason
        assert generation_id == GENERATION_ID
        self.resolution = (action, provider_task_id)
        self.item = replace(
            self.item,
            status=GenerationStatus.SUBMITTED,
            status_reason="operator:submitted",
        )
        return self.item

    async def list_stuck(
        self,
        *,
        older_than_minutes: int,
        limit: int,
        now: datetime | None = None,
    ) -> tuple[GenerationWorkItem, ...]:
        del now
        assert older_than_minutes == 30
        assert limit == 100
        return (self.item,)


def settings() -> Settings:
    return Settings(
        env="test",
        internal_api_token="internal-secret",
        billing_admin_api_enabled=True,
        billing_admin_api_token="admin-secret",
    )


def test_user_can_read_own_generation_stage_without_enabling_submissions() -> None:
    operations = FakeGenerationOperations()
    app = create_app(
        settings(),
        manage_resources=False,
        generation_operations=operations,
    )

    with TestClient(app) as client:
        response = client.get(
            f"/v1/generations/{GENERATION_ID}",
            headers={
                "Authorization": "Bearer internal-secret",
                "X-FoxGen-User-Id": "42",
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "processing"
    assert response.json()["status_reason"] == "provider_processing"
    assert response.json()["processing_at"] == "2026-07-25T00:00:00Z"


def test_user_cancel_uses_explicit_pre_submit_operation() -> None:
    operations = FakeGenerationOperations()
    app = create_app(
        settings(),
        manage_resources=False,
        generation_operations=operations,
    )

    with TestClient(app) as client:
        response = client.post(
            f"/v1/generations/{GENERATION_ID}/cancel",
            headers={
                "Authorization": "Bearer internal-secret",
                "X-FoxGen-User-Id": "42",
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_operator_can_list_and_resolve_submission_unknown() -> None:
    operations = FakeGenerationOperations()
    app = create_app(
        settings(),
        manage_resources=False,
        generation_operations=operations,
    )

    with TestClient(app) as client:
        stuck = client.get(
            "/v1/admin/generations/stuck",
            headers={"Authorization": "Bearer admin-secret"},
        )
        resolved = client.post(
            f"/v1/admin/generations/{GENERATION_ID}/resolve-unknown",
            headers={"Authorization": "Bearer admin-secret"},
            json={
                "action": "submitted",
                "provider_task_id": "provider-confirmed-1",
                "reason": "provider dashboard verified",
            },
        )

    assert stuck.status_code == 200
    assert stuck.json()[0]["id"] == str(GENERATION_ID)
    assert resolved.status_code == 200
    assert operations.resolution == (
        UnknownResolutionAction.SUBMITTED,
        "provider-confirmed-1",
    )
