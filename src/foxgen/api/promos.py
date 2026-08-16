from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from foxgen.api.miniapp_security import MiniAppPrincipal, decode_miniapp_token
from foxgen.api.security import authenticate_user_context
from foxgen.application.promos import PromoRedemptionResult, PromoRedemptionServiceProtocol
from foxgen.core.config import Settings
from foxgen.infra.promos import SqlAlchemyPromoRedemptionService


class PromoRedeemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64)


def _service(request: Request) -> PromoRedemptionServiceProtocol:
    value: PromoRedemptionServiceProtocol | None = getattr(
        request.app.state,
        "promo_redemption_service",
        None,
    )
    if value is not None:
        return value
    database = getattr(request.app.state, "database", None)
    if database is None:
        raise HTTPException(status_code=503, detail="Promo redemption service is not configured")
    value = SqlAlchemyPromoRedemptionService(database)
    request.app.state.promo_redemption_service = value
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


def _payload(item: PromoRedemptionResult) -> dict[str, object]:
    return {
        "code": item.code,
        "reward_units": item.reward_units,
        "available_units": item.available_units,
        "currency": "CREDIT",
        "replayed": item.replayed,
    }


def create_user_promo_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/v1/user-portal/promos", tags=["user-promos"])

    @router.post("/redeem")
    async def redeem(
        body: PromoRedeemRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
        username: str | None = Header(default=None, alias="X-FoxGen-Username"),
    ) -> dict[str, object]:
        principal = authenticate_user_context(
            settings=settings,
            authorization=authorization,
            user_id_header=user_id_header,
        )
        result = await _service(request).redeem(
            user_id=principal.user_id,
            username=username,
            code=body.code,
        )
        return _payload(result)

    return router


def create_miniapp_promo_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/v1/miniapp/promos", tags=["miniapp-promos"])

    @router.post("/redeem")
    async def redeem(
        body: PromoRedeemRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        principal = _miniapp_principal(settings, authorization)
        result = await _service(request).redeem(
            user_id=principal.user_id,
            username=principal.username,
            code=body.code,
        )
        return _payload(result)

    return router
