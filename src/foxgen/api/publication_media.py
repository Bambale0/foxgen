from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request

from foxgen.api.publications import PublicationServiceProtocol
from foxgen.api.security import authenticate_user_context
from foxgen.core.config import Settings
from foxgen.infra.media import S3MediaStorage


def create_publication_media_router(settings: Settings) -> APIRouter:
    """Expose short-lived read URLs for durable publication media to trusted clients."""

    router = APIRouter(tags=["feed"])
    storage = S3MediaStorage(
        bucket=settings.s3_bucket,
        region=settings.s3_region,
        endpoint_url=str(settings.s3_endpoint_url) if settings.s3_endpoint_url else None,
        access_key_id=(
            settings.s3_access_key_id.get_secret_value()
            if settings.s3_access_key_id is not None
            else None
        ),
        secret_access_key=(
            settings.s3_secret_access_key.get_secret_value()
            if settings.s3_secret_access_key is not None
            else None
        ),
        force_path_style=settings.s3_force_path_style,
        presigned_url_ttl_seconds=settings.media_presigned_url_ttl_seconds,
    )

    @router.get("/v1/publications/{publication_id}/media")
    async def publication_media(
        publication_id: UUID,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
    ) -> dict[str, object]:
        viewer_id = authenticate_user_context(
            settings=settings,
            authorization=authorization,
            user_id_header=user_id_header,
        ).user_id
        service: PublicationServiceProtocol | None = getattr(
            request.app.state,
            "publication_service",
            None,
        )
        if service is None:
            raise HTTPException(status_code=503, detail="Publication service is not configured")
        publication = await service.get_publication(
            publication_id=publication_id,
            viewer_user_id=viewer_id,
        )
        if publication is None:
            raise HTTPException(status_code=404, detail="Publication not found")
        items: list[dict[str, object]] = []
        for media in publication.media:
            items.append(
                {
                    "url": await storage.presigned_url(media.storage_key),
                    "content_type": media.content_type,
                }
            )
        return {"publication_id": str(publication_id), "items": items}

    return router
