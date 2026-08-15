from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from foxgen.api.miniapp_security import MiniAppPrincipal, decode_miniapp_token
from foxgen.api.security import authenticate_submission
from foxgen.application.user_portal import (
    PartnerProfileSnapshot,
    PartnerWithdrawalSnapshot,
    SupportMessageSnapshot,
    SupportTicketSnapshot,
    TariffSnapshot,
    UserPortalServiceProtocol,
)
from foxgen.core.config import Settings


class SupportCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1, max_length=4096)


class SupportReplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=4096)


class PartnerWithdrawalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_units: int = Field(gt=0)
    destination: str = Field(min_length=3, max_length=255)


def _service(request: Request) -> UserPortalServiceProtocol:
    value: UserPortalServiceProtocol | None = getattr(
        request.app.state,
        "user_portal_service",
        None,
    )
    if value is None:
        raise HTTPException(status_code=503, detail="User portal service is not configured")
    return value


def _miniapp_principal(settings: Settings, authorization: str | None) -> MiniAppPrincipal:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Mini App bearer token is required")
    if settings.miniapp_jwt_secret is None:
        raise HTTPException(status_code=503, detail="Mini App authentication is not configured")
    try:
        return decode_miniapp_token(
            authorization.removeprefix("Bearer ").strip(),
            secret=settings.miniapp_jwt_secret.get_secret_value(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _tariff_payload(item: TariffSnapshot | None) -> dict[str, object] | None:
    if item is None:
        return None
    return {
        "version": item.version,
        "payload": item.payload,
        "published_at": item.published_at.isoformat(),
    }


def _message_payload(item: SupportMessageSnapshot) -> dict[str, object]:
    return {
        "id": str(item.id),
        "sender_kind": item.sender_kind,
        "body": item.body,
        "status": item.status,
        "created_at": item.created_at.isoformat(),
    }


def _ticket_payload(item: SupportTicketSnapshot) -> dict[str, object]:
    return {
        "id": str(item.id),
        "subject": item.subject,
        "status": item.status,
        "priority": item.priority,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
        "messages": [_message_payload(message) for message in item.messages],
    }


def _partner_payload(item: PartnerProfileSnapshot) -> dict[str, object]:
    return {
        "joined": item.joined,
        "earned_units": item.earned_units,
        "withdrawn_units": item.withdrawn_units,
        "pending_units": item.pending_units,
        "available_units": item.available_units,
        "referrals_count": item.referrals_count,
    }


def _withdrawal_payload(item: PartnerWithdrawalSnapshot) -> dict[str, object]:
    return {
        "id": str(item.id),
        "amount_units": item.amount_units,
        "status": item.status,
        "destination": item.destination,
        "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at is not None else None,
        "created_at": item.created_at.isoformat(),
    }


def create_user_portal_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/v1/user-portal", tags=["user-portal"])

    def principal(
        authorization: str | None,
        user_id_header: str | None,
    ) -> int:
        return authenticate_submission(
            settings=settings,
            authorization=authorization,
            user_id_header=user_id_header,
        ).user_id

    @router.get("/tariff")
    async def tariff(
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
    ) -> dict[str, object] | None:
        principal(authorization, user_id_header)
        return _tariff_payload(await _service(request).current_tariff())

    @router.get("/support")
    async def support_list(
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
    ) -> dict[str, object]:
        user_id = principal(authorization, user_id_header)
        items = await _service(request).list_support_tickets(user_id=user_id)
        return {"items": [_ticket_payload(item) for item in items]}

    @router.get("/support/{ticket_id}")
    async def support_detail(
        ticket_id: UUID,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
    ) -> dict[str, object]:
        user_id = principal(authorization, user_id_header)
        item = await _service(request).get_support_ticket(user_id=user_id, ticket_id=ticket_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Support ticket not found")
        return _ticket_payload(item)

    @router.post("/support", status_code=status.HTTP_201_CREATED)
    async def support_create(
        body: SupportCreateRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
        username: str | None = Header(default=None, alias="X-FoxGen-Username"),
    ) -> dict[str, object]:
        user_id = principal(authorization, user_id_header)
        item = await _service(request).create_support_ticket(
            user_id=user_id,
            username=username,
            subject=body.subject,
            body=body.body,
        )
        return _ticket_payload(item)

    @router.post("/support/{ticket_id}/messages")
    async def support_reply(
        ticket_id: UUID,
        body: SupportReplyRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
    ) -> dict[str, object]:
        user_id = principal(authorization, user_id_header)
        return _ticket_payload(
            await _service(request).reply_support_ticket(
                user_id=user_id,
                ticket_id=ticket_id,
                body=body.body,
            )
        )

    @router.post("/support/{ticket_id}/close")
    async def support_close(
        ticket_id: UUID,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
    ) -> dict[str, object]:
        user_id = principal(authorization, user_id_header)
        return _ticket_payload(
            await _service(request).close_support_ticket(user_id=user_id, ticket_id=ticket_id)
        )

    @router.get("/partner")
    async def partner(
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
    ) -> dict[str, object]:
        user_id = principal(authorization, user_id_header)
        profile = await _service(request).partner_profile(user_id=user_id)
        withdrawals = await _service(request).list_partner_withdrawals(user_id=user_id)
        return {
            "profile": _partner_payload(profile),
            "withdrawals": [_withdrawal_payload(item) for item in withdrawals],
        }

    @router.post("/partner/join")
    async def partner_join(
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
        username: str | None = Header(default=None, alias="X-FoxGen-Username"),
    ) -> dict[str, object]:
        user_id = principal(authorization, user_id_header)
        return _partner_payload(
            await _service(request).join_partner_program(user_id=user_id, username=username)
        )

    @router.post("/partner/withdrawals", status_code=status.HTTP_201_CREATED)
    async def partner_withdrawal(
        body: PartnerWithdrawalRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
    ) -> dict[str, object]:
        user_id = principal(authorization, user_id_header)
        return _withdrawal_payload(
            await _service(request).request_partner_withdrawal(
                user_id=user_id,
                amount_units=body.amount_units,
                destination=body.destination,
            )
        )

    return router


def create_miniapp_user_portal_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["miniapp-user-portal"])

    @router.get("/tariff")
    async def tariff(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object] | None:
        _miniapp_principal(settings, authorization)
        return _tariff_payload(await _service(request).current_tariff())

    @router.get("/support")
    async def support_list(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        principal = _miniapp_principal(settings, authorization)
        items = await _service(request).list_support_tickets(user_id=principal.user_id)
        return {"items": [_ticket_payload(item) for item in items]}

    @router.get("/support/{ticket_id}")
    async def support_detail(
        ticket_id: UUID,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        principal = _miniapp_principal(settings, authorization)
        item = await _service(request).get_support_ticket(
            user_id=principal.user_id,
            ticket_id=ticket_id,
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Support ticket not found")
        return _ticket_payload(item)

    @router.post("/support", status_code=status.HTTP_201_CREATED)
    async def support_create(
        body: SupportCreateRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        principal = _miniapp_principal(settings, authorization)
        return _ticket_payload(
            await _service(request).create_support_ticket(
                user_id=principal.user_id,
                username=principal.username,
                subject=body.subject,
                body=body.body,
            )
        )

    @router.post("/support/{ticket_id}/messages")
    async def support_reply(
        ticket_id: UUID,
        body: SupportReplyRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        principal = _miniapp_principal(settings, authorization)
        return _ticket_payload(
            await _service(request).reply_support_ticket(
                user_id=principal.user_id,
                ticket_id=ticket_id,
                body=body.body,
            )
        )

    @router.post("/support/{ticket_id}/close")
    async def support_close(
        ticket_id: UUID,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        principal = _miniapp_principal(settings, authorization)
        return _ticket_payload(
            await _service(request).close_support_ticket(
                user_id=principal.user_id,
                ticket_id=ticket_id,
            )
        )

    @router.get("/partner")
    async def partner(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        principal = _miniapp_principal(settings, authorization)
        profile = await _service(request).partner_profile(user_id=principal.user_id)
        withdrawals = await _service(request).list_partner_withdrawals(user_id=principal.user_id)
        return {
            "profile": _partner_payload(profile),
            "withdrawals": [_withdrawal_payload(item) for item in withdrawals],
        }

    @router.post("/partner/join")
    async def partner_join(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        principal = _miniapp_principal(settings, authorization)
        return _partner_payload(
            await _service(request).join_partner_program(
                user_id=principal.user_id,
                username=principal.username,
            )
        )

    @router.post("/partner/withdrawals", status_code=status.HTTP_201_CREATED)
    async def partner_withdrawal(
        body: PartnerWithdrawalRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        principal = _miniapp_principal(settings, authorization)
        return _withdrawal_payload(
            await _service(request).request_partner_withdrawal(
                user_id=principal.user_id,
                amount_units=body.amount_units,
                destination=body.destination,
            )
        )

    return router
