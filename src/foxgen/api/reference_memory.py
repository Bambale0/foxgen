from __future__ import annotations

from typing import Protocol
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from foxgen.api.security import authenticate_user_context
from foxgen.application.reference_memory import (
    ReferenceMemoryItem,
    ReferenceMemoryPage,
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
    ) -> tuple[ReferenceMemoryItem, ...]: ...

    async def delete(self, *, user_id: int, asset_id: UUID) -> None: ...


def _item_payload(item: ReferenceMemoryItem) -> dict[str, object]:
    return {
        "id": str(item.id),
        "content_type": item.content_type,
        "size_bytes": item.size_bytes,
        "created_at": item.created_at.isoformat(),
        "preview_url": item.preview_url,
    }


def _service(request: Request) -> ReferenceMemoryServiceProtocol:
    service = request.app.state.reference_memory_service
    if service is None:
        raise HTTPException(status_code=503, detail="Reference memory service is not configured")
    return service


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
        page = await _service(request).list(user_id=user_id, offset=offset, limit=limit)
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
        result = await _service(request).save_from_temporary_input(
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
        items = await _service(request).resolve(
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
        await _service(request).delete(user_id=user_id, asset_id=asset_id)
        return {"status": "delete_pending", "id": str(asset_id)}

    return router
