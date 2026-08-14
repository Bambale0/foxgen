from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field, ValidationError

from foxgen.api.billing import (
    BillingServiceProtocol,
    balance_payload,
    ledger_payload,
    price_payload,
)
from foxgen.api.generations import GenerationOperationsProtocol
from foxgen.api.miniapp_security import (
    MiniAppPrincipal,
    decode_miniapp_token,
    issue_miniapp_token,
    validate_telegram_init_data,
)
from foxgen.application.media import DownloadedMedia
from foxgen.application.submissions import SubmissionReceipt
from foxgen.core.config import Settings
from foxgen.core.errors import ErrorCode, FoxGenError
from foxgen.infra.input_media import LocalInputMediaStorage
from foxgen.infra.miniapp import MiniAppGenerationSnapshot
from foxgen.providers.kie.contracts import contract_schema, validate_input
from foxgen.providers.kie.registry import ModelRegistry


class MiniAppAuthRequest(BaseModel):
    init_data: str = Field(min_length=1, max_length=16_384)


class MiniAppTaskRequest(BaseModel):
    model_slug: str = Field(min_length=1, max_length=128)
    input: dict[str, Any]


class MiniAppSubmissionServiceProtocol(Protocol):
    async def submit(
        self,
        *,
        user_id: int,
        username: str | None,
        model_slug: str,
        input_data: dict[str, object],
        idempotency_key: str,
    ) -> SubmissionReceipt: ...


class MiniAppRepositoryProtocol(Protocol):
    async def list_recent(
        self,
        *,
        user_id: int,
        limit: int,
    ) -> tuple[MiniAppGenerationSnapshot, ...]: ...

    async def get_for_user(
        self,
        *,
        generation_id: UUID,
        user_id: int,
    ) -> MiniAppGenerationSnapshot | None: ...


_UPLOAD_TYPES: dict[str, tuple[str, str]] = {
    "image/jpeg": ("image", ".jpg"),
    "image/png": ("image", ".png"),
    "image/webp": ("image", ".webp"),
    "video/mp4": ("video", ".mp4"),
    "video/webm": ("video", ".webm"),
    "audio/mpeg": ("audio", ".mp3"),
    "audio/mp4": ("audio", ".m4a"),
    "audio/wav": ("audio", ".wav"),
    "audio/x-wav": ("audio", ".wav"),
}


def _auth_secret(settings: Settings) -> str:
    if settings.miniapp_jwt_secret is None:
        raise HTTPException(status_code=503, detail="Mini App authentication is not configured")
    return settings.miniapp_jwt_secret.get_secret_value()


def _principal(settings: Settings, authorization: str | None) -> MiniAppPrincipal:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Mini App bearer token is required")
    try:
        return decode_miniapp_token(
            authorization.removeprefix("Bearer ").strip(),
            secret=_auth_secret(settings),
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _billing(request: Request) -> BillingServiceProtocol:
    service: BillingServiceProtocol | None = getattr(request.app.state, "billing_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Billing service is not configured")
    return service


def _submissions(request: Request) -> MiniAppSubmissionServiceProtocol:
    service: MiniAppSubmissionServiceProtocol | None = getattr(
        request.app.state,
        "submission_service",
        None,
    )
    if service is None:
        raise HTTPException(status_code=503, detail="Task submission service is not configured")
    return service


def _operations(request: Request) -> GenerationOperationsProtocol:
    service: GenerationOperationsProtocol | None = getattr(
        request.app.state,
        "generation_operations",
        None,
    )
    if service is None:
        raise HTTPException(status_code=503, detail="Generation operations are not configured")
    return service


def _repository(request: Request) -> MiniAppRepositoryProtocol:
    service: MiniAppRepositoryProtocol | None = getattr(
        request.app.state,
        "miniapp_repository",
        None,
    )
    if service is None:
        raise HTTPException(status_code=503, detail="Mini App data service is not configured")
    return service


def _input_storage(settings: Settings) -> LocalInputMediaStorage:
    if settings.internal_api_token is None:
        raise HTTPException(status_code=503, detail="Input media signing is not configured")
    return LocalInputMediaStorage(
        root=settings.telegram_input_storage_root,
        public_base_url=settings.telegram_input_public_base_url,
        signing_secret=settings.internal_api_token.get_secret_value(),
        presigned_url_ttl_seconds=settings.telegram_input_presigned_url_ttl_seconds,
        retention_seconds=settings.telegram_input_retention_seconds,
    )


def _public_model_payload(item: Any) -> dict[str, object]:
    ui_key = "seedream-5-pro" if item.slug == "seedream-5-pro-edit" else item.slug
    variant = "edit" if item.slug == "seedream-5-pro-edit" else "default"
    return {
        "slug": item.slug,
        "ui_key": ui_key,
        "variant": variant,
        "title": item.title,
        "media_kind": item.media_kind.value,
        "capabilities": sorted(capability.value for capability in item.capabilities),
        "defaults": dict(item.defaults),
        "recommended_for": list(item.recommended_for),
        "tier": item.tier,
        "enabled": item.enabled_for_submission,
        "input_schema": contract_schema(item.contract),
    }


def _generation_payload(item: MiniAppGenerationSnapshot) -> dict[str, object]:
    return {
        "id": str(item.id),
        "model_slug": item.model_slug,
        "media_kind": item.media_kind,
        "status": item.status,
        "prompt": item.prompt,
        "created_at": item.created_at,
        "completed_at": item.completed_at,
        "error_code": item.error_code,
        "media": [
            {
                "id": str(media.id),
                "url": media.url,
                "content_type": media.content_type,
                "size_bytes": media.size_bytes,
            }
            for media in item.media
        ],
    }


def _receipt_payload(receipt: SubmissionReceipt) -> dict[str, object]:
    return {
        "generation_id": str(receipt.generation_id),
        "model": receipt.model_slug,
        "status": receipt.status,
        "replayed": receipt.replayed,
    }


def create_miniapp_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/v1/miniapp", tags=["miniapp"])
    registry = ModelRegistry()

    @router.post("/auth")
    async def authenticate(body: MiniAppAuthRequest) -> dict[str, object]:
        if settings.telegram_bot_token is None:
            raise HTTPException(status_code=503, detail="Telegram bot token is not configured")
        try:
            user = validate_telegram_init_data(
                body.init_data,
                bot_token=settings.telegram_bot_token.get_secret_value(),
                max_age_seconds=settings.miniapp_auth_max_age_seconds,
            )
            access_token = issue_miniapp_token(
                user,
                secret=_auth_secret(settings),
                ttl_seconds=settings.miniapp_jwt_ttl_seconds,
            )
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": settings.miniapp_jwt_ttl_seconds,
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "photo_url": user.photo_url,
                "language_code": user.language_code,
                "is_premium": user.is_premium,
            },
        }

    @router.get("/bootstrap")
    async def bootstrap(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        principal = _principal(settings, authorization)
        billing = _billing(request)
        balance = await billing.get_balance(principal.user_id)
        prices = await billing.list_active_prices()
        ledger = await billing.list_ledger(user_id=principal.user_id, limit=8)
        recent = await _repository(request).list_recent(user_id=principal.user_id, limit=12)
        models = [
            _public_model_payload(item) for item in registry.list() if item.enabled_for_submission
        ]
        return {
            "brand": "Happy Fox",
            "user": {
                "id": principal.user_id,
                "username": principal.username,
                "display_name": principal.display_name,
                "photo_url": principal.photo_url,
                "language_code": principal.language_code,
                "is_premium": principal.is_premium,
            },
            "balance": balance_payload(balance),
            "prices": [price_payload(price) for price in prices],
            "ledger": [ledger_payload(entry) for entry in ledger],
            "models": models,
            "recent": [_generation_payload(item) for item in recent],
        }

    @router.get("/generations")
    async def list_generations(
        request: Request,
        authorization: str | None = Header(default=None),
        limit: int = Query(default=30, ge=1, le=100),
    ) -> list[dict[str, object]]:
        principal = _principal(settings, authorization)
        items = await _repository(request).list_recent(user_id=principal.user_id, limit=limit)
        return [_generation_payload(item) for item in items]

    @router.get("/generations/{generation_id}")
    async def generation_detail(
        generation_id: UUID,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        principal = _principal(settings, authorization)
        item = await _repository(request).get_for_user(
            generation_id=generation_id,
            user_id=principal.user_id,
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Generation not found")
        return _generation_payload(item)

    @router.post("/generations/{generation_id}/cancel")
    async def cancel_generation(
        generation_id: UUID,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        principal = _principal(settings, authorization)
        await _operations(request).cancel_for_user(
            generation_id=generation_id,
            user_id=principal.user_id,
        )
        item = await _repository(request).get_for_user(
            generation_id=generation_id,
            user_id=principal.user_id,
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Generation not found")
        return _generation_payload(item)

    @router.post("/tasks", status_code=202)
    async def create_task(
        body: MiniAppTaskRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, object]:
        principal = _principal(settings, authorization)
        if not settings.task_submission_enabled:
            raise HTTPException(status_code=503, detail="Task submission is disabled")
        if settings.kie_api_key is None:
            raise HTTPException(status_code=503, detail="KIE API key is not configured")
        if not idempotency_key or not 8 <= len(idempotency_key) <= 128:
            raise HTTPException(status_code=400, detail="Valid Idempotency-Key is required")
        try:
            item = registry.get(body.model_slug)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if not item.enabled_for_submission:
            raise HTTPException(status_code=503, detail="Selected model is not enabled")
        try:
            normalized = validate_input(item.contract, body.input)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors(include_url=False)) from exc
        receipt = await _submissions(request).submit(
            user_id=principal.user_id,
            username=principal.username,
            model_slug=body.model_slug,
            input_data=normalized,
            idempotency_key=f"miniapp:{idempotency_key}",
        )
        return _receipt_payload(receipt)

    @router.post("/input-media", status_code=201)
    async def upload_input_media(
        request: Request,
        authorization: str | None = Header(default=None),
        content_type: str | None = Header(default=None, alias="Content-Type"),
    ) -> dict[str, object]:
        principal = _principal(settings, authorization)
        normalized_type = (content_type or "").partition(";")[0].strip().lower()
        upload = _UPLOAD_TYPES.get(normalized_type)
        if upload is None:
            raise HTTPException(status_code=415, detail="Unsupported input media type")
        kind, suffix = upload
        storage = _input_storage(settings)
        digest = hashlib.sha256()
        size = 0
        temporary = tempfile.NamedTemporaryFile(prefix="happy-fox-upload-", delete=False)
        temporary_path = Path(temporary.name)
        try:
            async for chunk in request.stream():
                size += len(chunk)
                if size > settings.telegram_input_max_bytes:
                    raise HTTPException(status_code=413, detail="Input media is too large")
                digest.update(chunk)
                temporary.write(chunk)
            temporary.flush()
            temporary.close()
            if size == 0:
                raise HTTPException(status_code=400, detail="Input media is empty")
            storage_key = f"inputs/miniapp/{principal.user_id}/{uuid4().hex}{suffix}"
            downloaded = DownloadedMedia(
                path=temporary_path,
                filename=Path(storage_key).name,
                content_type=normalized_type,
                size_bytes=size,
                checksum_sha256=digest.hexdigest(),
            )
            stored = await storage.store(key=storage_key, media=downloaded)
            url = await storage.presigned_url(stored.storage_key)
            return {
                "kind": kind,
                "storage_key": stored.storage_key,
                "url": url,
                "content_type": stored.content_type,
                "size_bytes": stored.size_bytes,
            }
        finally:
            if not temporary.closed:
                temporary.close()
            temporary_path.unlink(missing_ok=True)

    @router.delete("/input-media/{storage_key:path}", status_code=204)
    async def delete_input_media(
        storage_key: str,
        authorization: str | None = Header(default=None),
    ) -> None:
        principal = _principal(settings, authorization)
        expected_prefix = f"inputs/miniapp/{principal.user_id}/"
        if not storage_key.startswith(expected_prefix):
            raise HTTPException(status_code=404, detail="Input media not found")
        try:
            await _input_storage(settings).delete(storage_key)
        except FoxGenError as exc:
            if exc.code == ErrorCode.TASK_NOT_FOUND:
                raise HTTPException(status_code=404, detail=exc.public_message) from exc
            raise

    return router
