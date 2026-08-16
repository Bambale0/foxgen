from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from foxgen.api.miniapp_security import MiniAppPrincipal, decode_miniapp_token
from foxgen.api.security import authenticate_user_context, validate_idempotency_key
from foxgen.application.payments import (
    PreCheckoutDecision,
    StarInvoice,
    StarPackage,
    StarPaymentResult,
    TelegramStarsPaymentServiceProtocol,
)
from foxgen.application.user_portal import (
    PartnerProfileSnapshot,
    PartnerWithdrawalSnapshot,
    SupportMessageSnapshot,
    SupportTicketSnapshot,
    TariffSnapshot,
    UserPortalServiceProtocol,
)
from foxgen.core.config import Settings
from foxgen.infra.payments_bonus import (
    BonusAwareTelegramStarsPaymentService as SqlAlchemyTelegramStarsPaymentService,
)


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


class StarInvoiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package_code: str = Field(min_length=1, max_length=128)


class StarPreCheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoice_payload: str = Field(min_length=1, max_length=128)
    currency: str = Field(min_length=1, max_length=16)
    total_amount: int = Field(gt=0)


class StarSuccessfulPaymentRequest(StarPreCheckoutRequest):
    telegram_payment_charge_id: str = Field(min_length=1, max_length=255)
    provider_payment_charge_id: str = Field(default="", max_length=255)


def _service(request: Request) -> UserPortalServiceProtocol:
    value: UserPortalServiceProtocol | None = getattr(
        request.app.state,
        "user_portal_service",
        None,
    )
    if value is None:
        raise HTTPException(status_code=503, detail="User portal service is not configured")
    return value


def _payment_service(
    request: Request,
    settings: Settings,
) -> TelegramStarsPaymentServiceProtocol:
    value: TelegramStarsPaymentServiceProtocol | None = getattr(
        request.app.state,
        "telegram_stars_payment_service",
        None,
    )
    if value is not None:
        return value
    database = getattr(request.app.state, "database", None)
    if database is None:
        raise HTTPException(status_code=503, detail="Payment service is not configured")
    token = settings.telegram_bot_token
    if token is None:
        raise HTTPException(status_code=503, detail="Telegram Stars payments are not configured")
    value = SqlAlchemyTelegramStarsPaymentService(
        database,
        bot_token=token.get_secret_value(),
    )
    request.app.state.telegram_stars_payment_service = value
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


def _star_package_payload(item: StarPackage) -> dict[str, object]:
    return {
        "code": item.code,
        "title": item.title,
        "description": item.description,
        "credits_units": item.total_credits_units,
        "base_credits_units": item.resolved_base_credits_units,
        "bonus_units": item.bonus_units,
        "total_credits_units": item.total_credits_units,
        "stars_amount": item.stars_amount,
        "currency": "XTR",
    }


def _star_invoice_payload(item: StarInvoice) -> dict[str, object]:
    return {
        "order_id": str(item.order_id),
        "package": _star_package_payload(item.package),
        "invoice_payload": item.invoice_payload,
        "invoice_url": item.invoice_url,
        "replayed": item.replayed,
    }


def _pre_checkout_payload(item: PreCheckoutDecision) -> dict[str, object]:
    return {"ok": item.ok, "error_message": item.error_message}


def _star_payment_payload(item: StarPaymentResult) -> dict[str, object]:
    return {
        "order_id": str(item.order_id),
        "available_units": item.available_units,
        "credited_units": item.credited_units,
        "currency": "CREDIT",
        "replayed": item.replayed,
    }


def create_user_portal_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/v1/user-portal", tags=["user-portal"])

    def principal(
        authorization: str | None,
        user_id_header: str | None,
    ) -> int:
        return authenticate_user_context(
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

    @router.get("/payments/stars/packages")
    async def stars_packages(
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
    ) -> dict[str, object]:
        principal(authorization, user_id_header)
        items = await _payment_service(request, settings).list_packages()
        return {"items": [_star_package_payload(item) for item in items]}

    @router.post("/payments/stars/invoices", status_code=status.HTTP_201_CREATED)
    async def stars_invoice(
        body: StarInvoiceRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
        username: str | None = Header(default=None, alias="X-FoxGen-Username"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, object]:
        user_id = principal(authorization, user_id_header)
        item = await _payment_service(request, settings).create_invoice(
            user_id=user_id,
            username=username,
            package_code=body.package_code,
            idempotency_key=validate_idempotency_key(idempotency_key),
        )
        return _star_invoice_payload(item)

    @router.post("/payments/stars/pre-checkout")
    async def stars_pre_checkout(
        body: StarPreCheckoutRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
    ) -> dict[str, object]:
        user_id = principal(authorization, user_id_header)
        decision = await _payment_service(request, settings).validate_pre_checkout(
            user_id=user_id,
            invoice_payload=body.invoice_payload,
            currency=body.currency,
            total_amount=body.total_amount,
        )
        return _pre_checkout_payload(decision)

    @router.post("/payments/stars/success")
    async def stars_success(
        body: StarSuccessfulPaymentRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
        username: str | None = Header(default=None, alias="X-FoxGen-Username"),
    ) -> dict[str, object]:
        user_id = principal(authorization, user_id_header)
        result = await _payment_service(request, settings).credit_successful_payment(
            user_id=user_id,
            username=username,
            invoice_payload=body.invoice_payload,
            currency=body.currency,
            total_amount=body.total_amount,
            telegram_payment_charge_id=body.telegram_payment_charge_id,
            provider_payment_charge_id=body.provider_payment_charge_id,
            raw_payload=body.model_dump(mode="json"),
        )
        return _star_payment_payload(result)

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
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, object]:
        user_id = principal(authorization, user_id_header)
        key = validate_idempotency_key(idempotency_key)
        return _withdrawal_payload(
            await _service(request).request_partner_withdrawal(
                user_id=user_id,
                amount_units=body.amount_units,
                destination=body.destination,
                idempotency_key=key,
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

    @router.get("/payments/stars/packages")
    async def stars_packages(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        _miniapp_principal(settings, authorization)
        items = await _payment_service(request, settings).list_packages()
        return {"items": [_star_package_payload(item) for item in items]}

    @router.post("/payments/stars/invoices", status_code=status.HTTP_201_CREATED)
    async def stars_invoice(
        body: StarInvoiceRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, object]:
        principal = _miniapp_principal(settings, authorization)
        item = await _payment_service(request, settings).create_invoice(
            user_id=principal.user_id,
            username=principal.username,
            package_code=body.package_code,
            idempotency_key=validate_idempotency_key(idempotency_key),
        )
        return _star_invoice_payload(item)

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
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, object]:
        principal = _miniapp_principal(settings, authorization)
        key = validate_idempotency_key(idempotency_key)
        return _withdrawal_payload(
            await _service(request).request_partner_withdrawal(
                user_id=principal.user_id,
                amount_units=body.amount_units,
                destination=body.destination,
                idempotency_key=key,
            )
        )

    return router
