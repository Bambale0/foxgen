from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi.testclient import TestClient

from foxgen.api.app import create_app
from foxgen.application.reference_memory import (
    ReferenceMemoryItem,
    ReferenceMemoryPage,
    ReferenceSaveResult,
)
from foxgen.core.config import Settings


REFERENCE_ID = UUID("99999999-9999-9999-9999-999999999999")
ITEM = ReferenceMemoryItem(
    id=REFERENCE_ID,
    content_type="image/png",
    size_bytes=123,
    created_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
    preview_url="https://private.example/ref.png?signed=1",
)


class FakeReferenceMemoryService:
    def __init__(self) -> None:
        self.saved: list[tuple[int, str]] = []
        self.deleted: list[tuple[int, UUID]] = []

    async def save_from_temporary_input(
        self,
        *,
        user_id: int,
        username: str | None,
        storage_key: str,
    ) -> ReferenceSaveResult:
        del username
        self.saved.append((user_id, storage_key))
        return ReferenceSaveResult(item=ITEM, duplicate=False)

    async def list(
        self,
        *,
        user_id: int,
        offset: int = 0,
        limit: int = 20,
    ) -> ReferenceMemoryPage:
        del offset, limit
        assert user_id == 42
        return ReferenceMemoryPage(
            items=(ITEM,),
            total=1,
            used_bytes=123,
            max_items=50,
            max_bytes=1024,
        )

    async def resolve(
        self,
        *,
        user_id: int,
        asset_ids: tuple[UUID, ...],
    ) -> tuple[ReferenceMemoryItem, ...]:
        assert user_id == 42
        assert asset_ids == (REFERENCE_ID,)
        return (ITEM,)

    async def delete(self, *, user_id: int, asset_id: UUID) -> None:
        self.deleted.append((user_id, asset_id))


def _settings() -> Settings:
    return Settings(
        internal_api_token="internal-secret",
        miniapp_enabled=False,
    )


def _headers() -> dict[str, str]:
    return {
        "Authorization": "Bearer internal-secret",
        "X-FoxGen-User-Id": "42",
    }


def test_reference_api_requires_internal_user_context() -> None:
    service = FakeReferenceMemoryService()
    client = TestClient(
        create_app(
            _settings(),
            manage_resources=False,
            reference_memory_service=service,
        )
    )

    assert client.get("/v1/reference-memory").status_code == 401
    assert (
        client.get(
            "/v1/reference-memory",
            headers={"Authorization": "Bearer internal-secret"},
        ).status_code
        == 400
    )


def test_reference_api_save_list_resolve_delete() -> None:
    service = FakeReferenceMemoryService()
    client = TestClient(
        create_app(
            _settings(),
            manage_resources=False,
            reference_memory_service=service,
        )
    )

    save = client.post(
        "/v1/reference-memory",
        headers=_headers(),
        json={"storage_key": "inputs/42/source.png"},
    )
    assert save.status_code == 201
    assert save.json()["id"] == str(REFERENCE_ID)
    assert service.saved == [(42, "inputs/42/source.png")]

    listing = client.get("/v1/reference-memory", headers=_headers())
    assert listing.status_code == 200
    assert listing.json()["items"][0]["preview_url"].endswith("signed=1")

    resolved = client.post(
        "/v1/reference-memory/resolve",
        headers=_headers(),
        json={"reference_ids": [str(REFERENCE_ID)]},
    )
    assert resolved.status_code == 200
    assert resolved.json()["items"][0]["id"] == str(REFERENCE_ID)

    deleted = client.delete(
        f"/v1/reference-memory/{REFERENCE_ID}",
        headers=_headers(),
    )
    assert deleted.status_code == 202
    assert service.deleted == [(42, REFERENCE_ID)]
