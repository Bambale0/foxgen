from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, Field

from foxgen.admin.errors import AdminValidationError
from foxgen.admin.security import require_manual_confirmation
from foxgen.api.admin_web import _session_context
from foxgen.core.config import Settings


class WebGenerationPreviewRequest(BaseModel):
    model_slug: str = Field(min_length=1, max_length=128)
    input: dict[str, object]


class WebAdminSetRequest(BaseModel):
    role: str = Field(min_length=1, max_length=32)
    scopes: list[str] = Field(default_factory=list, max_length=100)
    active: bool = True


def create_admin_web_extensions_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/internal/admin/ui/api", tags=["internal-admin-web"])

    @router.get("/analytics")
    async def web_analytics(
        request: Request,
        hours: int = 24,
        admin_session: Annotated[str | None, Header(alias="X-Admin-Session")] = None,
    ) -> dict[str, object]:
        context, services = await _session_context(request, settings, admin_session)
        return await services.analytics.snapshot(context, hours=hours)

    @router.post("/preview-generation")
    async def web_generation_preview(
        body: WebGenerationPreviewRequest,
        request: Request,
        admin_session: Annotated[str | None, Header(alias="X-Admin-Session")] = None,
    ) -> dict[str, object]:
        context, services = await _session_context(request, settings, admin_session)
        return await services.previews.generation_preview(
            context=context,
            model_slug=body.model_slug,
            input_payload=body.input,
        )

    @router.get("/admins")
    async def web_admins(
        request: Request,
        admin_session: Annotated[str | None, Header(alias="X-Admin-Session")] = None,
    ) -> list[dict[str, object]]:
        context, services = await _session_context(request, settings, admin_session)
        return await services.access.list_admins(context)

    @router.put("/admins/{user_id}")
    async def web_set_admin(
        user_id: int,
        body: WebAdminSetRequest,
        request: Request,
        admin_session: Annotated[str | None, Header(alias="X-Admin-Session")] = None,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        confirmation: Annotated[str | None, Header(alias="X-Admin-Confirm")] = None,
    ) -> dict[str, object]:
        context, services = await _session_context(request, settings, admin_session)
        require_manual_confirmation(confirmation)
        if idempotency_key is None or not idempotency_key.strip():
            raise AdminValidationError("Idempotency-Key is required")
        result = await services.access.set_admin(
            context=context,
            user_id=user_id,
            role=body.role,
            scopes=body.scopes,
            active=body.active,
            idempotency_key=idempotency_key.strip(),
        )
        payload = dict(result.payload)
        payload["replayed"] = result.replayed
        return payload

    return router
