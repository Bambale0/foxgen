from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from foxgen.api.miniapp_security import MiniAppPrincipal, decode_miniapp_token
from foxgen.api.security import authenticate_user_context, validate_idempotency_key
from foxgen.application.kling_motion import KlingMotionService
from foxgen.application.media import DownloadedMedia
from foxgen.application.submissions import SubmissionReceipt
from foxgen.core.config import Settings
from foxgen.infra.input_media import LocalInputMediaStorage
from foxgen.providers.kie.motion import (
    KLING_MOTION_IMAGE_MAX_BYTES,
    KLING_MOTION_VIDEO_MAX_BYTES,
)


class KlingMotionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=10_000)
    image_storage_key: str = Field(min_length=8, max_length=512)
    video_storage_key: str = Field(min_length=8, max_length=512)
    mode: Literal["720p"] = "720p"
    character_orientation: Literal["image"] = "image"
    background_source: Literal["input_video"] = "input_video"


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


def _storage(settings: Settings) -> LocalInputMediaStorage:
    if settings.internal_api_token is None:
        raise HTTPException(status_code=503, detail="Input media signing is not configured")
    return LocalInputMediaStorage(
        root=settings.telegram_input_storage_root,
        public_base_url=settings.telegram_input_public_base_url,
        signing_secret=settings.internal_api_token.get_secret_value(),
        presigned_url_ttl_seconds=settings.telegram_input_presigned_url_ttl_seconds,
        retention_seconds=settings.telegram_input_retention_seconds,
    )


def _service(request: Request, settings: Settings) -> KlingMotionService:
    value: KlingMotionService | None = getattr(request.app.state, "kling_motion_service", None)
    if value is not None:
        return value
    submission = getattr(request.app.state, "submission_service", None)
    if submission is None:
        raise HTTPException(status_code=503, detail="Task submission service is not configured")
    value = KlingMotionService(input_media=_storage(settings), submission=submission)
    request.app.state.kling_motion_service = value
    return value


def _receipt(receipt: SubmissionReceipt) -> dict[str, object]:
    return {
        "generation_id": str(receipt.generation_id),
        "model_slug": receipt.model_slug,
        "status": receipt.status,
        "provider_task_id": receipt.provider_task_id,
        "replayed": receipt.replayed,
    }


def _input(body: KlingMotionRequest) -> dict[str, object]:
    return body.model_dump(mode="python", exclude_none=True)


async def _upload(
    request: Request,
    *,
    settings: Settings,
    user_id: int,
    kind: str,
    content_type: str | None,
) -> dict[str, object]:
    normalized = (content_type or "").partition(";")[0].strip().lower()
    if kind == "image":
        extensions = {"image/jpeg": ".jpg", "image/png": ".png"}
        max_bytes = KLING_MOTION_IMAGE_MAX_BYTES
    elif kind == "video":
        extensions = {"video/mp4": ".mp4", "video/quicktime": ".mov"}
        max_bytes = KLING_MOTION_VIDEO_MAX_BYTES
    else:
        raise HTTPException(status_code=404, detail="Unsupported Motion Control input kind")
    suffix = extensions.get(normalized)
    if suffix is None:
        raise HTTPException(status_code=415, detail=f"Unsupported Motion Control {kind} type")

    digest = hashlib.sha256()
    size = 0
    temporary = tempfile.NamedTemporaryFile(prefix=f"foxgen-motion-{kind}-", delete=False)
    temporary_path = Path(temporary.name)
    try:
        async for chunk in request.stream():
            size += len(chunk)
            if size > max_bytes:
                raise HTTPException(status_code=413, detail=f"Motion Control {kind} is too large")
            digest.update(chunk)
            temporary.write(chunk)
        temporary.flush()
        temporary.close()
        if size <= 0:
            raise HTTPException(status_code=400, detail=f"Motion Control {kind} is empty")
        storage_key = f"inputs/miniapp/{user_id}/motion-{kind}-{uuid4().hex}{suffix}"
        media = DownloadedMedia(
            path=temporary_path,
            filename=Path(storage_key).name,
            content_type=normalized,
            size_bytes=size,
            checksum_sha256=digest.hexdigest(),
        )
        stored = await _storage(settings).store(key=storage_key, media=media)
        return {
            "kind": kind,
            "storage_key": stored.storage_key,
            "content_type": stored.content_type,
            "size_bytes": stored.size_bytes,
        }
    finally:
        if not temporary.closed:
            temporary.close()
        temporary_path.unlink(missing_ok=True)


def create_kling_motion_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["kling-motion-control"])

    @router.post("/v1/user-portal/motion/kling", status_code=status.HTTP_202_ACCEPTED)
    async def trusted_submit(
        body: KlingMotionRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
        username: str | None = Header(default=None, alias="X-FoxGen-Username"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, object]:
        principal = authenticate_user_context(
            settings=settings,
            authorization=authorization,
            user_id_header=user_id_header,
        )
        receipt = await _service(request, settings).submit(
            user_id=principal.user_id,
            username=username,
            input_data=_input(body),
            idempotency_key=f"motion:{validate_idempotency_key(idempotency_key)}",
        )
        return _receipt(receipt)

    if settings.miniapp_enabled:

        @router.post(
            "/v1/miniapp/motion/kling/inputs/image",
            status_code=status.HTTP_201_CREATED,
        )
        async def miniapp_upload_image(
            request: Request,
            authorization: str | None = Header(default=None),
            content_type: str | None = Header(default=None, alias="Content-Type"),
        ) -> dict[str, object]:
            principal = _miniapp_principal(settings, authorization)
            return await _upload(
                request,
                settings=settings,
                user_id=principal.user_id,
                kind="image",
                content_type=content_type,
            )

        @router.post(
            "/v1/miniapp/motion/kling/inputs/video",
            status_code=status.HTTP_201_CREATED,
        )
        async def miniapp_upload_video(
            request: Request,
            authorization: str | None = Header(default=None),
            content_type: str | None = Header(default=None, alias="Content-Type"),
        ) -> dict[str, object]:
            principal = _miniapp_principal(settings, authorization)
            return await _upload(
                request,
                settings=settings,
                user_id=principal.user_id,
                kind="video",
                content_type=content_type,
            )

        @router.post("/v1/miniapp/motion/kling", status_code=status.HTTP_202_ACCEPTED)
        async def miniapp_submit(
            body: KlingMotionRequest,
            request: Request,
            authorization: str | None = Header(default=None),
            idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        ) -> dict[str, object]:
            principal = _miniapp_principal(settings, authorization)
            receipt = await _service(request, settings).submit(
                user_id=principal.user_id,
                username=principal.username,
                input_data=_input(body),
                idempotency_key=(
                    f"miniapp:kling-motion:{validate_idempotency_key(idempotency_key)}"
                ),
            )
            return _receipt(receipt)

    return router
