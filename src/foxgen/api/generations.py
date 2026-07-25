from datetime import datetime
from typing import Protocol
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from foxgen.api.security import authenticate_billing_admin, authenticate_user_context
from foxgen.application.generation_ops import (
    GenerationOperationsService,
    UnknownResolutionAction,
)
from foxgen.application.lifecycle import GenerationWorkItem
from foxgen.application.reconciliation import (
    DeliveryResolutionAction,
    ReconciliationFinding,
    ReconciliationResult,
    ReconciliationService,
)
from foxgen.core.config import Settings


class GenerationOperationsProtocol(Protocol):
    async def get_for_user(
        self,
        *,
        generation_id: UUID,
        user_id: int,
    ) -> GenerationWorkItem: ...

    async def cancel_for_user(
        self,
        *,
        generation_id: UUID,
        user_id: int,
    ) -> GenerationWorkItem: ...

    async def resolve_submission_unknown(
        self,
        *,
        generation_id: UUID,
        action: UnknownResolutionAction,
        provider_task_id: str | None,
        result_payload: dict[str, object] | None,
        reason: str,
    ) -> GenerationWorkItem: ...

    async def list_stuck(
        self,
        *,
        older_than_minutes: int,
        limit: int,
        now: datetime | None = None,
    ) -> tuple[GenerationWorkItem, ...]: ...


class ReconciliationProtocol(Protocol):
    async def report(self, *, limit: int) -> tuple[ReconciliationFinding, ...]: ...

    async def run_safe(self, *, limit: int) -> ReconciliationResult: ...

    async def resolve_delivery_unknown(
        self,
        *,
        generation_id: UUID,
        action: DeliveryResolutionAction,
        message_ids: list[int] | None,
        confirmed_not_sent: bool,
        idempotency_key: str | None,
        reason: str,
    ) -> None: ...


class UnknownResolutionRequest(BaseModel):
    action: UnknownResolutionAction
    provider_task_id: str | None = Field(default=None, max_length=255)
    result_payload: dict[str, object] | None = None
    reason: str = Field(min_length=3, max_length=128)


class DeliveryResolutionRequest(BaseModel):
    action: DeliveryResolutionAction
    telegram_message_ids: list[int] | None = None
    confirmed_not_sent: bool = False
    idempotency_key: str | None = Field(default=None, max_length=128)
    reason: str = Field(min_length=3, max_length=128)


class ReconciliationRunRequest(BaseModel):
    apply_safe_fixes: bool = False
    limit: int = Field(default=100, ge=1, le=500)


def _service(request: Request) -> GenerationOperationsProtocol:
    service: GenerationOperationsService | None = getattr(
        request.app.state,
        "generation_operations",
        None,
    )
    if service is None:
        raise HTTPException(status_code=503, detail="Generation operations are not configured")
    return service


def _reconciliation_service(request: Request) -> ReconciliationProtocol:
    service: ReconciliationService | None = getattr(
        request.app.state,
        "reconciliation_service",
        None,
    )
    if service is None:
        raise HTTPException(status_code=503, detail="Reconciliation is not configured")
    return service


def generation_payload(item: GenerationWorkItem) -> dict[str, object]:
    return {
        "id": str(item.id),
        "user_id": item.user_id,
        "model_slug": item.model_slug,
        "status": item.status.value,
        "error_code": item.error_code,
        "failure_stage": item.failure_stage,
        "status_reason": item.status_reason,
        "status_changed_at": item.status_changed_at,
        "submitted_at": item.submitted_at,
        "processing_at": item.processing_at,
        "result_ready_at": item.result_ready_at,
        "storage_started_at": item.storage_started_at,
        "delivery_pending_at": item.delivery_pending_at,
        "completed_at": item.completed_at,
        "next_poll_at": item.next_poll_at,
    }


def finding_payload(item: ReconciliationFinding) -> dict[str, object]:
    return {
        "code": item.code,
        "severity": item.severity,
        "generation_id": str(item.generation_id) if item.generation_id else None,
        "resource_id": str(item.resource_id) if item.resource_id else None,
        "status": item.status,
        "details": item.details,
    }


def create_generation_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["generations"])

    @router.get("/v1/generations/{generation_id}")
    async def generation_status(
        generation_id: UUID,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
    ) -> dict[str, object]:
        principal = authenticate_user_context(
            settings=settings,
            authorization=authorization,
            user_id_header=user_id_header,
        )
        generation = await _service(request).get_for_user(
            generation_id=generation_id,
            user_id=principal.user_id,
        )
        return generation_payload(generation)

    @router.post("/v1/generations/{generation_id}/cancel")
    async def cancel_generation(
        generation_id: UUID,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
    ) -> dict[str, object]:
        principal = authenticate_user_context(
            settings=settings,
            authorization=authorization,
            user_id_header=user_id_header,
        )
        generation = await _service(request).cancel_for_user(
            generation_id=generation_id,
            user_id=principal.user_id,
        )
        return generation_payload(generation)

    @router.get("/v1/admin/generations/stuck")
    async def stuck_generations(
        request: Request,
        authorization: str | None = Header(default=None),
        older_than_minutes: int = Query(default=30, ge=1, le=43_200),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, object]]:
        authenticate_billing_admin(settings=settings, authorization=authorization)
        generations = await _service(request).list_stuck(
            older_than_minutes=older_than_minutes,
            limit=limit,
        )
        return [generation_payload(item) for item in generations]

    @router.post("/v1/admin/generations/{generation_id}/resolve-unknown")
    async def resolve_unknown_generation(
        generation_id: UUID,
        body: UnknownResolutionRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        authenticate_billing_admin(settings=settings, authorization=authorization)
        generation = await _service(request).resolve_submission_unknown(
            generation_id=generation_id,
            action=body.action,
            provider_task_id=body.provider_task_id,
            result_payload=body.result_payload,
            reason=body.reason,
        )
        return generation_payload(generation)

    @router.get("/v1/admin/reconciliation")
    async def reconciliation_report(
        request: Request,
        authorization: str | None = Header(default=None),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, object]]:
        authenticate_billing_admin(settings=settings, authorization=authorization)
        findings = await _reconciliation_service(request).report(limit=limit)
        return [finding_payload(item) for item in findings]

    @router.post("/v1/admin/reconciliation/run")
    async def run_reconciliation(
        body: ReconciliationRunRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        authenticate_billing_admin(settings=settings, authorization=authorization)
        service = _reconciliation_service(request)
        if body.apply_safe_fixes:
            result = await service.run_safe(limit=body.limit)
            return {
                "fixed_codes": list(result.fixed_codes),
                "findings": [finding_payload(item) for item in result.findings],
            }
        findings = await service.report(limit=body.limit)
        return {
            "fixed_codes": [],
            "findings": [finding_payload(item) for item in findings],
        }

    @router.post("/v1/admin/generations/{generation_id}/resolve-delivery")
    async def resolve_unknown_delivery(
        generation_id: UUID,
        body: DeliveryResolutionRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        authenticate_billing_admin(settings=settings, authorization=authorization)
        await _reconciliation_service(request).resolve_delivery_unknown(
            generation_id=generation_id,
            action=body.action,
            message_ids=body.telegram_message_ids,
            confirmed_not_sent=body.confirmed_not_sent,
            idempotency_key=body.idempotency_key,
            reason=body.reason,
        )
        return {"status": "resolved", "action": body.action.value}

    return router
