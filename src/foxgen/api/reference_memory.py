from __future__ import annotations

from typing import Protocol
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from foxgen.api.security import authenticate_user_context
from foxgen.application.reference_memory import (
    ReferenceMemoryPage,
    ReferenceMemoryService,
    ReferenceSaveResult,
)
from foxgen.core.config import Settings


class ReferenceSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    storage_key: str = Field(min_length=8, max_length=512)


class ReferenceResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_ids: list[UUID] = Field(default_factory=list, max_length=50)


class ReferenceMemoryServiceProtocol(Protocol):
    async def save_from_temporary_input(
        self,
        *,
        user_id: int,
        username: str | None,
        storage_key: str,
    ) -> ReferenceSaveResult: ...

    async def list(
        self,
        *,
        user_id: int,
        offset: int = 0,
        limit: int = 20,
    ) -> ReferenceMemoryPage: ...

    async def resolve(
        self,
        *,
        user_id: int,
        asset_ids: tuple[UUID, ...],
    ) -> tuple[object, ...]: ...

    async def delete(self, *, user_id: int, asset_id: UUID) -> None: ...


def _item_payload(item: object) -> dict[str, object]:
    return {
        "id": str(getattr(item, "id")),
        "content_type": str(getattr(item, "content_type")),
        "size_bytes": int(getattr(item, "size_bytes")),
        "created_at": getattr(item, "created_at").isoformat(),
        "preview_url": str(getattr(item, "preview_url")),
    }


def create_reference_memory_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/v1/reference-memory", tags=["reference-memory"])

    def principal(
        *,
        authorization: str | None,
        user_id_header: str | None,
    ) -> int:
        return authenticate_user_context(
            settings=settings,
            authorization=authorization,
            user_id_header=user_id_header,
        ).user_id

    @router.get("")
    async def list_references(
        request: Request,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=20, ge=1, le=100),
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
    ) -> dict[str, object]:
        user_id = principal(authorization=authorization, user_id_header=user_id_header)
        service: ReferenceMemoryServiceProtocol = request.app.state.reference_memory_service
        page = await service.list(user_id=user_id, offset=offset, limit=limit)
        return {
            "items": [_item_payload(item) for item in page.items],
            "total": page.total,
            "used_bytes": page.used_bytes,
            "max_items": page.max_items,
            "max_bytes": page.max_bytes,
        }

    @router.post("", status_code=status.HTTP_201_CREATED)
    async def save_reference(
        body: ReferenceSaveRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
        username: str | None = Header(default=None, alias="X-FoxGen-Username"),
    ) -> dict[str, object]:
        user_id = principal(authorization=authorization, user_id_header=user_id_header)
        service: ReferenceMemoryServiceProtocol = request.app.state.reference_memory_service
        result = await service.save_from_temporary_input(
            user_id=user_id,
            username=username,
            storage_key=body.storage_key,
        )
        return {**_item_payload(result.item), "duplicate": result.duplicate}

    @router.post("/resolve")
    async def resolve_references(
        body: ReferenceResolveRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
    ) -> dict[str, object]:
        user_id = principal(authorization=authorization, user_id_header=user_id_header)
        service: ReferenceMemoryServiceProtocol = request.app.state.reference_memory_service
        items = await service.resolve(
            user_id=user_id,
            asset_ids=tuple(body.reference_ids),
        )
        return {"items": [_item_payload(item) for item in items]}

    @router.delete("/{asset_id}", status_code=status.HTTP_202_ACCEPTED)
    async def delete_reference(
        asset_id: UUID,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
    ) -> dict[str, str]:
        user_id = principal(authorization=authorization, user_id_header=user_id_header)
        service: ReferenceMemoryServiceProtocol = request.app.state.reference_memory_service
        await service.delete(user_id=user_id, asset_id=asset_id)
        return {"status": "delete_pending", "id": str(asset_id)}

    return router


__all__ = ["ReferenceMemoryService", "create_reference_memory_router"]
