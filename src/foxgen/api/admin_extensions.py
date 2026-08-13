from __future__ import annotations

import html
from typing import Annotated

from fastapi import APIRouter, Header, Request, Response
from pydantic import BaseModel, Field

from foxgen.admin.security import require_manual_confirmation
from foxgen.api.admin import _authenticate, _services
from foxgen.core.config import Settings


class AdminUserSetRequest(BaseModel):
    role: str = Field(min_length=1, max_length=32)
    scopes: list[str] = Field(default_factory=list, max_length=100)
    active: bool = True


class GenerationPreviewRequest(BaseModel):
    model_slug: str = Field(min_length=1, max_length=128)
    input: dict[str, object]


def create_admin_extensions_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/internal/admin", tags=["internal-admin"])

    @router.get("/admins")
    async def admins(request: Request) -> list[dict[str, object]]:
        context = await _authenticate(request, settings)
        return await _services(request).access.list_admins(context)

    @router.put("/admins/{user_id}")
    async def set_admin(
        user_id: int,
        body: AdminUserSetRequest,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        confirmation: Annotated[str | None, Header(alias="X-Admin-Confirm")] = None,
    ) -> dict[str, object]:
        context = await _authenticate(request, settings)
        require_manual_confirmation(confirmation)
        if idempotency_key is None or not idempotency_key.strip():
            from foxgen.admin.errors import AdminValidationError

            raise AdminValidationError("Idempotency-Key is required for admin writes")
        result = await _services(request).access.set_admin(
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

    @router.post("/previews/generation")
    async def preview_generation(
        body: GenerationPreviewRequest,
        request: Request,
    ) -> dict[str, object]:
        context = await _authenticate(request, settings)
        return await _services(request).previews.generation_preview(
            context=context,
            model_slug=body.model_slug,
            input_payload=body.input,
        )

    @router.get("/exports/users.xls")
    async def users_xls(request: Request) -> Response:
        context = await _authenticate(request, settings)
        rows = await _services(request).queries.users(
            context,
            query=None,
            limit=200,
            offset=0,
        )
        flat_rows: list[dict[str, object]] = []
        for row in rows:
            balance = row.get("balance")
            available = 0
            reserved = 0
            if isinstance(balance, dict):
                raw_available = balance.get("available_units")
                raw_reserved = balance.get("reserved_units")
                available = raw_available if isinstance(raw_available, int) else 0
                reserved = raw_reserved if isinstance(raw_reserved, int) else 0
            flat_rows.append(
                {
                    "id": row.get("id"),
                    "username": row.get("username"),
                    "created_at": row.get("created_at"),
                    "blocked": row.get("blocked"),
                    "available_units": available,
                    "reserved_units": reserved,
                }
            )
        return _xls_response(
            "users.xls",
            ["id", "username", "created_at", "blocked", "available_units", "reserved_units"],
            flat_rows,
        )

    @router.get("/exports/finance.xls")
    async def finance_xls(request: Request) -> Response:
        context = await _authenticate(request, settings)
        payload = await _services(request).queries.finance(context)
        rows = [{"metric": key, "value": value} for key, value in payload.items()]
        return _xls_response("finance.xls", ["metric", "value"], rows)

    return router


def _xls_response(
    filename: str,
    columns: list[str],
    rows: list[dict[str, object]],
) -> Response:
    # SpreadsheetML 2003 is a real Excel-readable XLS representation and avoids a
    # heavyweight mutable spreadsheet dependency in the production API image.
    parts = [
        '<?xml version="1.0"?>',
        '<?mso-application progid="Excel.Sheet"?>',
        '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
        'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">',
        '<Worksheet ss:Name="FoxGen"><Table>',
        "<Row>",
    ]
    for column in columns:
        parts.append(f'<Cell><Data ss:Type="String">{html.escape(column)}</Data></Cell>')
    parts.append("</Row>")
    for row in rows:
        parts.append("<Row>")
        for column in columns:
            value = row.get(column)
            data_type = "Number" if isinstance(value, (int, float)) and not isinstance(value, bool) else "String"
            rendered = "" if value is None else str(value)
            parts.append(
                f'<Cell><Data ss:Type="{data_type}">{html.escape(rendered)}</Data></Cell>'
            )
        parts.append("</Row>")
    parts.extend(["</Table></Worksheet>", "</Workbook>"])
    return Response(
        content="".join(parts),
        media_type="application/vnd.ms-excel; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
