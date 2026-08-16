from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from foxgen.api.miniapp_security import MiniAppPrincipal, decode_miniapp_token
from foxgen.api.security import authenticate_user_context, validate_idempotency_key
from foxgen.application.suno_extend import SunoExtendService, SunoTrackSource
from foxgen.core.config import Settings
from foxgen.infra.media import S3MediaStorage
from foxgen.infra.suno_extend import SqlAlchemySunoSourceRepository


class SunoExtendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_generation_id: UUID
    audio_id: str = Field(min_length=1, max_length=128)
    default_param_flag: bool = False
    prompt: str = Field(default="", max_length=5_000)
    style: str = Field(default="", max_length=1_000)
    title: str = Field(default="", max_length=100)
    continue_at: float | None = Field(default=None, gt=0)
    negative_tags: str = Field(default="", max_length=1_000)
    vocal_gender: str | None = Field(default=None, max_length=1)
    style_weight: float | None = Field(default=None, ge=0, le=1)
    weirdness_constraint: float | None = Field(default=None, ge=0, le=1)
    audio_weight: float | None = Field(default=None, ge=0, le=1)


def _secret_value(value: SecretStr | None) -> str | None:
    return value.get_secret_value() if value is not None else None


def _service(request: Request, settings: Settings) -> SunoExtendService:
    service: SunoExtendService | None = getattr(request.app.state, "suno_extend_service", None)
    if service is not None:
        return service

    database = getattr(request.app.state, "database", None)
    submission = getattr(request.app.state, "submission_service", None)
    if database is None or submission is None:
        raise HTTPException(status_code=503, detail="Suno Extend service is not configured")

    storage = S3MediaStorage(
        bucket=settings.s3_bucket,
        region=settings.s3_region,
        endpoint_url=str(settings.s3_endpoint_url) if settings.s3_endpoint_url is not None else None,
        access_key_id=_secret_value(settings.s3_access_key_id),
        secret_access_key=_secret_value(settings.s3_secret_access_key),
        force_path_style=settings.s3_force_path_style,
        presigned_url_ttl_seconds=settings.miniapp_media_url_ttl_seconds,
    )
    service = SunoExtendService(
        sources=SqlAlchemySunoSourceRepository(database),
        submission=submission,
        media_signer=storage,
    )
    request.app.state.suno_extend_service = service
    return service


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


def _source_payload(item: SunoTrackSource) -> dict[str, object]:
    return {
        "generation_id": str(item.generation_id),
        "model_slug": item.model_slug,
        "audio_id": item.audio_id,
        "title": item.title,
        "duration_seconds": item.duration_seconds,
        "preview_url": item.preview_url,
        "created_at": item.created_at.isoformat(),
    }


def _extend_input(body: SunoExtendRequest) -> dict[str, object]:
    payload = body.model_dump(mode="python")
    payload.pop("source_generation_id", None)
    payload.pop("audio_id", None)
    return payload


def create_suno_extend_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["suno-extend"])

    @router.get("/v1/user-portal/music/suno/sources")
    async def trusted_sources(
        request: Request,
        limit: int = 40,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
    ) -> dict[str, object]:
        user_id = authenticate_user_context(
            settings=settings,
            authorization=authorization,
            user_id_header=user_id_header,
        ).user_id
        items = await _service(request, settings).list_sources(
            user_id=user_id,
            limit=max(1, min(limit, 100)),
        )
        return {"items": [_source_payload(item) for item in items]}

    @router.post(
        "/v1/user-portal/music/suno/extend",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def trusted_extend(
        body: SunoExtendRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
        username: str | None = Header(default=None, alias="X-FoxGen-Username"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, object]:
        user_id = authenticate_user_context(
            settings=settings,
            authorization=authorization,
            user_id_header=user_id_header,
        ).user_id
        receipt = await _service(request, settings).extend(
            user_id=user_id,
            username=username,
            source_generation_id=body.source_generation_id,
            audio_id=body.audio_id,
            input_data=_extend_input(body),
            idempotency_key=validate_idempotency_key(idempotency_key),
        )
        return {
            "generation_id": str(receipt.generation_id),
            "model_slug": receipt.model_slug,
            "status": receipt.status,
            "provider_task_id": receipt.provider_task_id,
            "replayed": receipt.replayed,
        }

    if settings.miniapp_enabled:

        @router.get("/v1/miniapp/music/suno/sources")
        async def miniapp_sources(
            request: Request,
            limit: int = 40,
            authorization: str | None = Header(default=None),
        ) -> dict[str, object]:
            principal = _miniapp_principal(settings, authorization)
            items = await _service(request, settings).list_sources(
                user_id=principal.user_id,
                limit=max(1, min(limit, 100)),
            )
            return {"items": [_source_payload(item) for item in items]}

        @router.post(
            "/v1/miniapp/music/suno/extend",
            status_code=status.HTTP_202_ACCEPTED,
        )
        async def miniapp_extend(
            body: SunoExtendRequest,
            request: Request,
            authorization: str | None = Header(default=None),
            idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        ) -> dict[str, object]:
            principal = _miniapp_principal(settings, authorization)
            receipt = await _service(request, settings).extend(
                user_id=principal.user_id,
                username=principal.username,
                source_generation_id=body.source_generation_id,
                audio_id=body.audio_id,
                input_data=_extend_input(body),
                idempotency_key=f"miniapp:suno-extend:{validate_idempotency_key(idempotency_key)}",
            )
            return {
                "generation_id": str(receipt.generation_id),
                "model_slug": receipt.model_slug,
                "status": receipt.status,
                "provider_task_id": receipt.provider_task_id,
                "replayed": receipt.replayed,
            }

    return router
