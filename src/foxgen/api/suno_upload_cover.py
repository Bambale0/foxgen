from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from foxgen.api.miniapp_security import MiniAppPrincipal, decode_miniapp_token
from foxgen.api.security import authenticate_user_context, validate_idempotency_key
from foxgen.application.suno_upload_cover import SunoUploadCoverService
from foxgen.core.config import Settings
from foxgen.infra.input_media import LocalInputMediaStorage


class SunoUploadCoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_storage_key: str = Field(min_length=8, max_length=512)
    custom_mode: bool = False
    instrumental: bool = False
    prompt: str = Field(default="", max_length=5_000)
    style: str = Field(default="", max_length=1_000)
    title: str = Field(default="", max_length=100)
    negative_tags: str = Field(default="", max_length=1_000)
    vocal_gender: str | None = Field(default=None, max_length=1)
    style_weight: float | None = Field(default=None, ge=0, le=1)
    weirdness_constraint: float | None = Field(default=None, ge=0, le=1)
    audio_weight: float | None = Field(default=None, ge=0, le=1)
    persona_id: str | None = Field(default=None, max_length=128)


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


def _service(request: Request, settings: Settings) -> SunoUploadCoverService:
    value: SunoUploadCoverService | None = getattr(
        request.app.state,
        "suno_upload_cover_service",
        None,
    )
    if value is not None:
        return value
    submission = getattr(request.app.state, "submission_service", None)
    if submission is None:
        raise HTTPException(status_code=503, detail="Task submission service is not configured")
    if settings.internal_api_token is None:
        raise HTTPException(status_code=503, detail="Input media signing is not configured")
    storage = LocalInputMediaStorage(
        root=settings.telegram_input_storage_root,
        public_base_url=settings.telegram_input_public_base_url,
        signing_secret=settings.internal_api_token.get_secret_value(),
        presigned_url_ttl_seconds=settings.telegram_input_presigned_url_ttl_seconds,
        retention_seconds=settings.telegram_input_retention_seconds,
    )
    value = SunoUploadCoverService(
        input_media=storage,
        submission=submission,
        max_bytes=settings.telegram_input_max_bytes,
    )
    request.app.state.suno_upload_cover_service = value
    return value


def _input(body: SunoUploadCoverRequest) -> dict[str, object]:
    return body.model_dump(mode="python", exclude_none=True)


def _receipt(receipt: object) -> dict[str, object]:
    return {
        "generation_id": str(getattr(receipt, "generation_id")),
        "model_slug": str(getattr(receipt, "model_slug")),
        "status": getattr(receipt, "status"),
        "provider_task_id": getattr(receipt, "provider_task_id"),
        "replayed": bool(getattr(receipt, "replayed")),
    }


def create_suno_upload_cover_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["suno-upload-cover"])

    @router.post(
        "/v1/user-portal/music/suno/upload-cover",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def trusted_upload_cover(
        body: SunoUploadCoverRequest,
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
        result = await _service(request, settings).submit(
            user_id=user_id,
            username=username,
            input_data=_input(body),
            idempotency_key=validate_idempotency_key(idempotency_key),
        )
        return _receipt(result)

    if settings.miniapp_enabled:

        @router.post(
            "/v1/miniapp/music/suno/upload-cover",
            status_code=status.HTTP_202_ACCEPTED,
        )
        async def miniapp_upload_cover(
            body: SunoUploadCoverRequest,
            request: Request,
            authorization: str | None = Header(default=None),
            idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        ) -> dict[str, object]:
            principal = _miniapp_principal(settings, authorization)
            result = await _service(request, settings).submit(
                user_id=principal.user_id,
                username=principal.username,
                input_data=_input(body),
                idempotency_key=(
                    f"miniapp:suno-upload-cover:{validate_idempotency_key(idempotency_key)}"
                ),
            )
            return _receipt(result)

    return router
