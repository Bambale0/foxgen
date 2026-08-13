from __future__ import annotations

import csv
import io
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from foxgen.admin.errors import AdminAuthenticationError, AdminValidationError
from foxgen.admin.policy import AI_ADMIN, AdminContext
from foxgen.admin.security import (
    ip_is_allowed,
    require_manual_confirmation,
    verify_request_signature,
)
from foxgen.admin.services import AdminServices
from foxgen.core.config import Settings


class BalanceAdjustmentRequest(BaseModel):
    amount_units: int
    reason: str = Field(min_length=1, max_length=1000)


class BlockUserRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class TariffPublishRequest(BaseModel):
    payload: dict[str, object]


class OperationRefundRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class TicketAssignRequest(BaseModel):
    assignee_id: int


class TicketUpdateRequest(BaseModel):
    status: str | None = None
    priority: str | None = None
    operator_note: str | None = Field(default=None, max_length=5000)


class TicketReplyRequest(BaseModel):
    body: str = Field(min_length=1, max_length=4096)


class CmsSaveRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1)
    metadata: dict[str, object] = Field(default_factory=dict)


class CmsPublishRequest(BaseModel):
    version_id: UUID | None = None


class CampaignPreviewRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4096)
    segment: dict[str, object] = Field(default_factory=dict)


class CampaignCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    message: str = Field(min_length=1, max_length=4096)
    segment: dict[str, object] = Field(default_factory=dict)


class CampaignTestRequest(BaseModel):
    recipient_id: int


class WithdrawalActionRequest(BaseModel):
    action: str


class PromoCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    reward_units: int = Field(ge=0)
    max_uses: int | None = Field(default=None, ge=1)
    metadata: dict[str, object] = Field(default_factory=dict)


class PromoActiveRequest(BaseModel):
    active: bool


class PromptModerationRequest(BaseModel):
    action: str
    reason: str | None = Field(default=None, max_length=2000)


class RuntimeFlagRequest(BaseModel):
    enabled: bool
    value: dict[str, object] = Field(default_factory=dict)


class ModelAvailabilityRequest(BaseModel):
    enabled: bool
    reason: str | None = Field(default=None, max_length=1000)


class TrendCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    payload: dict[str, object] = Field(default_factory=dict)


class FeedModerationRequest(BaseModel):
    action: str
    reason: str | None = Field(default=None, max_length=2000)


def create_admin_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/internal/admin", tags=["internal-admin"])

    @router.get("/health")
    async def health(request: Request) -> dict[str, object]:
        context = await _authenticate(request, settings)
        return {
            "status": "ok",
            "admin_user_id": context.user_id,
            "role": context.role,
            "request_id": context.request_id,
        }

    @router.get("/summary")
    async def summary(request: Request) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        return await services.queries.summary(context)

    @router.get("/users")
    async def users(
        request: Request,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        context, services = await _auth_services(request, settings)
        return await services.queries.users(context, query=q, limit=limit, offset=offset)

    @router.post("/users/{user_id}/block")
    async def block_user(
        user_id: int,
        body: BlockUserRequest,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        confirmation: Annotated[str | None, Header(alias="X-Admin-Confirm")] = None,
    ) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        require_manual_confirmation(confirmation)
        result = await services.users.block_user(
            context=context,
            user_id=user_id,
            reason=body.reason,
            idempotency_key=_idempotency(idempotency_key),
        )
        return _command_payload(result.payload, result.replayed)

    @router.post("/users/{user_id}/unblock")
    async def unblock_user(
        user_id: int,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        confirmation: Annotated[str | None, Header(alias="X-Admin-Confirm")] = None,
    ) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        require_manual_confirmation(confirmation)
        result = await services.users.unblock_user(
            context=context,
            user_id=user_id,
            idempotency_key=_idempotency(idempotency_key),
        )
        return _command_payload(result.payload, result.replayed)

    @router.post("/users/{user_id}/balance-adjustments")
    async def adjust_balance(
        user_id: int,
        body: BalanceAdjustmentRequest,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        confirmation: Annotated[str | None, Header(alias="X-Admin-Confirm")] = None,
    ) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        require_manual_confirmation(confirmation)
        result = await services.users.adjust_balance(
            context=context,
            user_id=user_id,
            amount_units=body.amount_units,
            reason=body.reason,
            idempotency_key=_idempotency(idempotency_key),
        )
        return _command_payload(result.payload, result.replayed)

    @router.get("/generations")
    async def generations(
        request: Request,
        user_id: int | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        context, services = await _auth_services(request, settings)
        return await services.queries.generations(
            context,
            user_id=user_id,
            status=status,
            limit=limit,
        )

    @router.get("/finance")
    async def finance(request: Request) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        return await services.queries.finance(context)

    @router.get("/payments")
    async def payments(
        request: Request,
        status: str | None = None,
        user_id: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        context, services = await _auth_services(request, settings)
        return await services.queries.payments(context, status=status, user_id=user_id, limit=limit)

    @router.get("/payments/{payment_id}")
    async def payment_detail(payment_id: UUID, request: Request) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        return await services.queries.payment_detail(context, payment_id)

    @router.post("/payments/{payment_id}/recheck")
    async def payment_recheck(
        payment_id: UUID,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        result = await services.payments.recheck_payment(
            context=context,
            payment_id=payment_id,
            idempotency_key=_idempotency(idempotency_key),
        )
        return _command_payload(result.payload, result.replayed)

    @router.post("/payments/{payment_id}/reprocess")
    async def payment_reprocess(
        payment_id: UUID,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        confirmation: Annotated[str | None, Header(alias="X-Admin-Confirm")] = None,
    ) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        require_manual_confirmation(confirmation)
        result = await services.payments.reprocess_payment(
            context=context,
            payment_id=payment_id,
            idempotency_key=_idempotency(idempotency_key),
        )
        return _command_payload(result.payload, result.replayed)

    @router.get("/tariffs")
    async def tariffs(request: Request) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        return await services.queries.tariffs(context)

    @router.get("/tariffs/versions")
    async def tariff_versions(request: Request, limit: int = 50) -> list[dict[str, object]]:
        context, services = await _auth_services(request, settings)
        return await services.queries.tariff_versions(context, limit=limit)

    @router.get("/tariffs/versions/{version_id}")
    async def tariff_version(version_id: UUID, request: Request) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        return await services.queries.tariff_version(context, version_id)

    @router.post("/tariffs/publish")
    async def tariff_publish(
        body: TariffPublishRequest,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        confirmation: Annotated[str | None, Header(alias="X-Admin-Confirm")] = None,
    ) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        require_manual_confirmation(confirmation)
        result = await services.tariffs.publish(
            context=context,
            payload=body.payload,
            idempotency_key=_idempotency(idempotency_key),
        )
        return _command_payload(result.payload, result.replayed)

    @router.get("/operations")
    async def operations(
        request: Request,
        generation_id: UUID | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        context, services = await _auth_services(request, settings)
        return await services.queries.operations(
            context,
            generation_id=generation_id,
            status=status,
            limit=limit,
        )

    @router.get("/operations/{operation_id}")
    async def operation_detail(operation_id: UUID, request: Request) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        return await services.queries.operation_detail(context, operation_id)

    @router.get("/operations/{operation_id}/timeline")
    async def operation_timeline(operation_id: UUID, request: Request) -> list[dict[str, object]]:
        context, services = await _auth_services(request, settings)
        return await services.queries.operation_timeline(context, operation_id)

    @router.post("/operations/{operation_id}/replay")
    async def operation_replay(
        operation_id: UUID,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        confirmation: Annotated[str | None, Header(alias="X-Admin-Confirm")] = None,
    ) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        require_manual_confirmation(confirmation)
        result = await services.operations.replay(
            context=context,
            operation_id=operation_id,
            idempotency_key=_idempotency(idempotency_key),
        )
        return _command_payload(result.payload, result.replayed)

    @router.post("/operations/{operation_id}/refund")
    async def operation_refund(
        operation_id: UUID,
        body: OperationRefundRequest,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        confirmation: Annotated[str | None, Header(alias="X-Admin-Confirm")] = None,
    ) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        require_manual_confirmation(confirmation)
        result = await services.operations.refund(
            context=context,
            operation_id=operation_id,
            reason=body.reason,
            idempotency_key=_idempotency(idempotency_key),
        )
        return _command_payload(result.payload, result.replayed)

    @router.get("/tickets")
    async def tickets(
        request: Request,
        status: str | None = None,
        assignee_id: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        context, services = await _auth_services(request, settings)
        return await services.queries.tickets(
            context,
            status=status,
            assignee_id=assignee_id,
            limit=limit,
        )

    @router.get("/tickets/{ticket_id}")
    async def ticket_detail(ticket_id: UUID, request: Request) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        return await services.queries.ticket_detail(context, ticket_id)

    @router.post("/tickets/{ticket_id}/assign")
    async def ticket_assign(
        ticket_id: UUID,
        body: TicketAssignRequest,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        result = await services.support.assign_ticket(
            context=context,
            ticket_id=ticket_id,
            assignee_id=body.assignee_id,
            idempotency_key=_idempotency(idempotency_key),
        )
        return _command_payload(result.payload, result.replayed)

    @router.post("/tickets/{ticket_id}/update")
    async def ticket_update(
        ticket_id: UUID,
        body: TicketUpdateRequest,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        result = await services.support.update_ticket(
            context=context,
            ticket_id=ticket_id,
            status=body.status,
            priority=body.priority,
            operator_note=body.operator_note,
            idempotency_key=_idempotency(idempotency_key),
        )
        return _command_payload(result.payload, result.replayed)

    @router.post("/tickets/{ticket_id}/reply")
    async def ticket_reply(
        ticket_id: UUID,
        body: TicketReplyRequest,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        confirmation: Annotated[str | None, Header(alias="X-Admin-Confirm")] = None,
    ) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        require_manual_confirmation(confirmation)
        result = await services.support.reply_ticket(
            context=context,
            ticket_id=ticket_id,
            body=body.body,
            idempotency_key=_idempotency(idempotency_key),
        )
        return _command_payload(result.payload, result.replayed)

    @router.get("/cms/documents")
    async def cms_documents(request: Request) -> list[dict[str, object]]:
        context, services = await _auth_services(request, settings)
        return await services.queries.cms_documents(context)

    @router.get("/cms/documents/{document_id}")
    async def cms_document(document_id: UUID, request: Request) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        return await services.queries.cms_document(context, document_id)

    @router.post("/cms/documents")
    async def cms_save(
        body: CmsSaveRequest,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        result = await services.cms.save_document(
            context=context,
            slug=body.slug,
            title=body.title,
            body=body.body,
            metadata=body.metadata,
            idempotency_key=_idempotency(idempotency_key),
        )
        return _command_payload(result.payload, result.replayed)

    @router.post("/cms/documents/{document_id}/publish")
    async def cms_publish(
        document_id: UUID,
        body: CmsPublishRequest,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        confirmation: Annotated[str | None, Header(alias="X-Admin-Confirm")] = None,
    ) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        require_manual_confirmation(confirmation)
        result = await services.cms.publish_document(
            context=context,
            document_id=document_id,
            version_id=body.version_id,
            idempotency_key=_idempotency(idempotency_key),
        )
        return _command_payload(result.payload, result.replayed)

    @router.post("/notifications/preview")
    async def notification_preview(
        body: CampaignPreviewRequest,
        request: Request,
    ) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        return await services.notifications.preview(
            context=context,
            message=body.message,
            segment=body.segment,
        )

    @router.get("/notifications/campaigns")
    async def notification_campaigns(request: Request, limit: int = 50) -> list[dict[str, object]]:
        context, services = await _auth_services(request, settings)
        return await services.queries.campaigns(context, limit=limit)

    @router.post("/notifications/campaigns")
    async def notification_create(
        body: CampaignCreateRequest,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        result = await services.notifications.create_campaign(
            context=context,
            name=body.name,
            message=body.message,
            segment=body.segment,
            idempotency_key=_idempotency(idempotency_key),
        )
        return _command_payload(result.payload, result.replayed)

    @router.get("/notifications/campaigns/{campaign_id}")
    async def notification_detail(campaign_id: UUID, request: Request) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        return await services.queries.campaign_detail(context, campaign_id)

    @router.post("/notifications/campaigns/{campaign_id}/test")
    async def notification_test(
        campaign_id: UUID,
        body: CampaignTestRequest,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        result = await services.notifications.test_campaign(
            context=context,
            campaign_id=campaign_id,
            recipient_id=body.recipient_id,
            idempotency_key=_idempotency(idempotency_key),
        )
        return _command_payload(result.payload, result.replayed)

    @router.post("/notifications/campaigns/{campaign_id}/start")
    async def notification_start(
        campaign_id: UUID,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        confirmation: Annotated[str | None, Header(alias="X-Admin-Confirm")] = None,
    ) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        require_manual_confirmation(confirmation)
        result = await services.notifications.start_campaign(
            context=context,
            campaign_id=campaign_id,
            idempotency_key=_idempotency(idempotency_key),
        )
        return _command_payload(result.payload, result.replayed)

    @router.post("/notifications/campaigns/{campaign_id}/cancel")
    async def notification_cancel(
        campaign_id: UUID,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        confirmation: Annotated[str | None, Header(alias="X-Admin-Confirm")] = None,
    ) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        require_manual_confirmation(confirmation)
        result = await services.notifications.cancel_campaign(
            context=context,
            campaign_id=campaign_id,
            idempotency_key=_idempotency(idempotency_key),
        )
        return _command_payload(result.payload, result.replayed)

    @router.get("/partners/summary")
    async def partner_summary(request: Request) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        return await services.queries.partner_summary(context)

    @router.get("/partners/withdrawals")
    async def partner_withdrawals(
        request: Request,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        context, services = await _auth_services(request, settings)
        return await services.queries.partner_withdrawals(context, status=status, limit=limit)

    @router.post("/partners/withdrawals/{withdrawal_id}/actions")
    async def partner_withdrawal_action(
        withdrawal_id: UUID,
        body: WithdrawalActionRequest,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        confirmation: Annotated[str | None, Header(alias="X-Admin-Confirm")] = None,
    ) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        require_manual_confirmation(confirmation)
        result = await services.partners.act_on_withdrawal(
            context=context,
            withdrawal_id=withdrawal_id,
            action=body.action,
            idempotency_key=_idempotency(idempotency_key),
        )
        return _command_payload(result.payload, result.replayed)

    @router.get("/promos/{code}")
    async def promo_detail(code: str, request: Request) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        return await services.queries.promo(context, code)

    @router.post("/promos")
    async def promo_create(
        body: PromoCreateRequest,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        result = await services.promos.create(
            context=context,
            code=body.code,
            reward_units=body.reward_units,
            max_uses=body.max_uses,
            metadata=body.metadata,
            idempotency_key=_idempotency(idempotency_key),
        )
        return _command_payload(result.payload, result.replayed)

    @router.post("/promos/{code}/active")
    async def promo_active(
        code: str,
        body: PromoActiveRequest,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        confirmation: Annotated[str | None, Header(alias="X-Admin-Confirm")] = None,
    ) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        require_manual_confirmation(confirmation)
        result = await services.promos.set_active(
            context=context,
            code=code,
            active=body.active,
            idempotency_key=_idempotency(idempotency_key),
        )
        return _command_payload(result.payload, result.replayed)

    @router.get("/prompts")
    async def prompts(
        request: Request,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        context, services = await _auth_services(request, settings)
        return await services.queries.prompts(context, status=status, limit=limit)

    @router.get("/prompts/{item_id}")
    async def prompt_detail(item_id: UUID, request: Request) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        return await services.queries.prompt_detail(context, item_id)

    @router.post("/prompts/{item_id}/moderate")
    async def prompt_moderate(
        item_id: UUID,
        body: PromptModerationRequest,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        confirmation: Annotated[str | None, Header(alias="X-Admin-Confirm")] = None,
    ) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        require_manual_confirmation(confirmation)
        result = await services.prompts.moderate(
            context=context,
            item_id=item_id,
            action=body.action,
            reason=body.reason,
            idempotency_key=_idempotency(idempotency_key),
        )
        return _command_payload(result.payload, result.replayed)

    @router.get("/runtime")
    async def runtime(request: Request) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        return await services.queries.runtime(context)

    @router.post("/runtime/flags/{key}")
    async def runtime_flag(
        key: str,
        body: RuntimeFlagRequest,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        confirmation: Annotated[str | None, Header(alias="X-Admin-Confirm")] = None,
    ) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        require_manual_confirmation(confirmation)
        result = await services.runtime.set_flag(
            context=context,
            key=key,
            enabled=body.enabled,
            value=body.value,
            idempotency_key=_idempotency(idempotency_key),
        )
        return _command_payload(result.payload, result.replayed)

    @router.post("/models/{model_slug}/availability")
    async def model_availability(
        model_slug: str,
        body: ModelAvailabilityRequest,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        confirmation: Annotated[str | None, Header(alias="X-Admin-Confirm")] = None,
    ) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        require_manual_confirmation(confirmation)
        result = await services.runtime.set_model_availability(
            context=context,
            model_slug=model_slug,
            enabled=body.enabled,
            reason=body.reason,
            idempotency_key=_idempotency(idempotency_key),
        )
        return _command_payload(result.payload, result.replayed)

    @router.get("/moderation")
    async def moderation(request: Request) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        return await services.queries.moderation(context)

    @router.post("/trends")
    async def trend_create(
        body: TrendCreateRequest,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        result = await services.moderation.create_trend(
            context=context,
            title=body.title,
            payload=body.payload,
            idempotency_key=_idempotency(idempotency_key),
        )
        return _command_payload(result.payload, result.replayed)

    @router.post("/trends/{trend_id}/remove")
    async def trend_remove(
        trend_id: UUID,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        confirmation: Annotated[str | None, Header(alias="X-Admin-Confirm")] = None,
    ) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        require_manual_confirmation(confirmation)
        result = await services.moderation.remove_trend(
            context=context,
            trend_id=trend_id,
            idempotency_key=_idempotency(idempotency_key),
        )
        return _command_payload(result.payload, result.replayed)

    @router.post("/feed/{content_id}/moderate")
    async def feed_moderate(
        content_id: str,
        body: FeedModerationRequest,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        confirmation: Annotated[str | None, Header(alias="X-Admin-Confirm")] = None,
    ) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        require_manual_confirmation(confirmation)
        result = await services.moderation.moderate_feed(
            context=context,
            content_id=content_id,
            action=body.action,
            reason=body.reason,
            idempotency_key=_idempotency(idempotency_key),
        )
        return _command_payload(result.payload, result.replayed)

    @router.get("/audit")
    async def audit(request: Request, limit: int = 100) -> list[dict[str, object]]:
        context, services = await _auth_services(request, settings)
        return await services.queries.audit(context, limit=limit)

    @router.get("/commands/{command_id}")
    async def command(command_id: UUID, request: Request) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        return await services.queries.command(context, command_id)

    @router.get("/ai/diagnostics")
    async def ai_diagnostics(request: Request) -> dict[str, object]:
        context, services = await _auth_services(request, settings)
        context.require(AI_ADMIN)
        summary_payload = await services.queries.summary(context)
        finance_payload = await services.queries.finance(context)
        failures = await services.queries.generations(
            context, user_id=None, status="failed", limit=20
        )
        return {
            "summary": summary_payload,
            "finance": finance_payload,
            "recent_failures": failures,
            "signals": _diagnostic_signals(summary_payload, failures),
        }

    @router.get("/exports/users.csv")
    async def users_csv(request: Request) -> Response:
        context, services = await _auth_services(request, settings)
        rows = await services.queries.users(context, query=None, limit=200, offset=0)
        return _csv_response(
            "users.csv",
            ["id", "username", "created_at", "blocked", "available_units", "reserved_units"],
            [
                {
                    "id": row["id"],
                    "username": row["username"],
                    "created_at": row["created_at"],
                    "blocked": row["blocked"],
                    "available_units": _nested_int(row, "balance", "available_units"),
                    "reserved_units": _nested_int(row, "balance", "reserved_units"),
                }
                for row in rows
            ],
        )

    @router.get("/exports/finance.csv")
    async def finance_csv(request: Request) -> Response:
        context, services = await _auth_services(request, settings)
        payload = await services.queries.finance(context)
        return _csv_response(
            "finance.csv",
            ["metric", "value"],
            [{"metric": key, "value": value} for key, value in payload.items()],
        )

    return router


async def _authenticate(request: Request, settings: Settings) -> AdminContext:
    if not settings.admin_api_enabled:
        raise HTTPException(status_code=404, detail="Not found")
    secret = settings.admin_hmac_key
    if secret is None:
        raise HTTPException(status_code=503, detail="Admin HMAC key is not configured")
    client_address = request.client.host if request.client is not None else None
    if not ip_is_allowed(client_address, settings.admin_networks):
        raise AdminAuthenticationError("Admin request source is outside the network allowlist")
    user_id_raw = request.headers.get("X-Admin-User-Id")
    request_id = request.headers.get("X-Request-Id")
    timestamp = request.headers.get("X-Admin-Timestamp")
    signature = request.headers.get("X-Admin-Signature")
    if not user_id_raw or not request_id or not timestamp or not signature:
        raise AdminAuthenticationError("Missing signed admin request headers")
    if len(request_id) > 128:
        raise AdminAuthenticationError("Invalid admin request id")
    try:
        user_id = int(user_id_raw)
    except ValueError as exc:
        raise AdminAuthenticationError("Invalid admin user id") from exc
    raw_body = await request.body()
    verify_request_signature(
        secret=secret.get_secret_value(),
        timestamp=timestamp,
        method=request.method,
        path=request.url.path,
        request_id=request_id,
        raw_body=raw_body,
        signature=signature,
        max_skew_seconds=settings.admin_hmac_max_skew_seconds,
    )
    services = _services(request)
    return await services.policy.authorize(user_id=user_id, request_id=request_id)


async def _auth_services(
    request: Request, settings: Settings
) -> tuple[AdminContext, AdminServices]:
    context = await _authenticate(request, settings)
    return context, _services(request)


def _services(request: Request) -> AdminServices:
    services: AdminServices | None = getattr(request.app.state, "admin_services", None)
    if services is None:
        raise HTTPException(status_code=503, detail="Admin services are not configured")
    return services


def _idempotency(value: str | None) -> str:
    if value is None or not value.strip():
        raise AdminValidationError("Idempotency-Key is required for admin writes")
    return value.strip()


def _command_payload(payload: dict[str, object], replayed: bool) -> dict[str, object]:
    result = dict(payload)
    result["replayed"] = replayed
    return result


def _diagnostic_signals(
    summary: dict[str, object],
    failures: list[dict[str, object]],
) -> list[dict[str, object]]:
    signals: list[dict[str, object]] = []
    failed_24h = summary.get("failed_generations_24h")
    if isinstance(failed_24h, int) and failed_24h > 0:
        signals.append(
            {
                "severity": "warning" if failed_24h < 10 else "critical",
                "code": "generation_failures",
                "message": f"{failed_24h} generations failed in the last 24 hours",
            }
        )
    error_counts: dict[str, int] = {}
    for item in failures:
        code = item.get("error_code")
        if isinstance(code, str) and code:
            error_counts[code] = error_counts.get(code, 0) + 1
    for code, count in sorted(error_counts.items(), key=lambda pair: pair[1], reverse=True)[:5]:
        signals.append(
            {
                "severity": "info",
                "code": "failure_cluster",
                "message": f"{count} recent failures share error code {code}",
            }
        )
    return signals


def _csv_response(filename: str, fieldnames: list[str], rows: list[dict[str, object]]) -> Response:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _nested_int(row: dict[str, object], parent: str, key: str) -> int:
    value = row.get(parent)
    if not isinstance(value, dict):
        return 0
    nested = value.get(key)
    return int(nested) if isinstance(nested, int) else 0
