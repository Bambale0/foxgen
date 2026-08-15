from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from foxgen.api.miniapp_security import MiniAppPrincipal, decode_miniapp_token
from foxgen.api.publications import PublicationServiceProtocol
from foxgen.api.reference_memory import ReferenceMemoryServiceProtocol
from foxgen.core.config import Settings
from foxgen.domain.publications import (
    FeedSort,
    PublicationCommentView,
    PublicationScope,
    PublicationView,
    PublicProfileView,
    RemixSourceView,
)
from foxgen.infra.media import S3MediaStorage


class MiniAppProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=3, max_length=56, pattern=r"^[a-zA-Z0-9_-]+$")
    display_name: str | None = Field(default=None, max_length=128)
    bio: str | None = Field(default=None, max_length=500)


class MiniAppPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: PublicationScope


class MiniAppLikeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    liked: bool


class MiniAppCommentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    surface: PublicationScope
    body: str = Field(min_length=1, max_length=1000)


class MiniAppReferenceSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    storage_key: str = Field(min_length=8, max_length=512)


class MiniAppReferenceResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_ids: list[UUID] = Field(default_factory=list, max_length=50)


def _principal(settings: Settings, authorization: str | None) -> MiniAppPrincipal:
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


def _publication_service(request: Request) -> PublicationServiceProtocol:
    value: PublicationServiceProtocol | None = getattr(
        request.app.state, "publication_service", None
    )
    if value is None:
        raise HTTPException(status_code=503, detail="Publication service is not configured")
    return value


def _reference_service(request: Request) -> ReferenceMemoryServiceProtocol:
    value: ReferenceMemoryServiceProtocol | None = getattr(
        request.app.state, "reference_memory_service", None
    )
    if value is None:
        raise HTTPException(status_code=503, detail="Reference memory service is not configured")
    return value


def _storage(settings: Settings) -> S3MediaStorage:
    return S3MediaStorage(
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
        presigned_url_ttl_seconds=settings.miniapp_media_url_ttl_seconds,
    )


def _profile_payload(profile: PublicProfileView) -> dict[str, object]:
    return {
        "user_id": profile.user_id,
        "slug": profile.slug,
        "display_name": profile.display_name,
        "bio": profile.bio,
        "deep_link_payload": f"profile_{profile.slug}",
    }


def _publication_payload(item: PublicationView) -> dict[str, object]:
    return {
        "id": str(item.id),
        "generation_id": str(item.generation_id),
        "author": _profile_payload(item.author),
        "scope": item.scope.value,
        "active": item.active,
        "model_slug": item.model_slug,
        "media_kind": item.media_kind,
        "prompt": item.prompt,
        "prompt_actions_allowed": item.prompt_actions_allowed,
        "likes_count": item.likes_count,
        "comments_count": item.comments_count,
        "remix_count": item.remix_count,
        "liked_by_viewer": item.liked_by_viewer,
        "source_publication_id": (
            str(item.source_publication_id) if item.source_publication_id is not None else None
        ),
        "created_at": item.created_at.isoformat(),
        "deep_links": {
            "post": item.post_deep_link_payload,
            "profile": item.profile_deep_link_payload,
            "remix": item.remix_deep_link_payload,
        },
    }


def _comment_payload(item: PublicationCommentView) -> dict[str, object]:
    return {
        "id": str(item.id),
        "publication_id": str(item.publication_id),
        "surface": item.surface.value,
        "author": _profile_payload(item.author),
        "body": item.body,
        "created_at": item.created_at.isoformat(),
    }


def _reference_payload(item: object) -> dict[str, object]:
    return {
        "id": str(getattr(item, "id")),
        "content_type": str(getattr(item, "content_type")),
        "size_bytes": int(getattr(item, "size_bytes")),
        "created_at": getattr(item, "created_at").isoformat(),
        "preview_url": str(getattr(item, "preview_url")),
    }


async def _publication_with_urls(
    settings: Settings,
    item: PublicationView,
) -> dict[str, object]:
    storage = _storage(settings)
    payload = _publication_payload(item)
    payload["media"] = [
        {
            "url": await storage.presigned_url(media.storage_key),
            "content_type": media.content_type,
        }
        for media in item.media
    ]
    return payload


async def _remix_payload(
    settings: Settings,
    item: RemixSourceView,
) -> dict[str, object]:
    storage = _storage(settings)
    return {
        "publication_id": str(item.publication_id),
        "generation_id": str(item.generation_id),
        "author_slug": item.author_slug,
        "model_slug": item.model_slug,
        "media_kind": item.media_kind,
        "prompt": item.prompt,
        "media": [
            {
                "url": await storage.presigned_url(media.storage_key),
                "content_type": media.content_type,
            }
            for media in item.media
        ],
    }


def create_miniapp_parity_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["miniapp-parity"])

    @router.get("/feed")
    async def feed(
        request: Request,
        authorization: str | None = Header(default=None),
        sort: FeedSort = Query(default=FeedSort.RECENT),
        limit: int = Query(default=12, ge=1, le=30),
        offset: int = Query(default=0, ge=0, le=100_000),
    ) -> dict[str, object]:
        principal = _principal(settings, authorization)
        items = await _publication_service(request).list_feed(
            viewer_user_id=principal.user_id,
            sort=sort,
            limit=limit,
            offset=offset,
        )
        return {
            "items": [await _publication_with_urls(settings, item) for item in items],
            "sort": sort.value,
            "limit": limit,
            "offset": offset,
            "next_offset": offset + len(items) if len(items) == limit else None,
        }

    @router.get("/publications/{publication_id}")
    async def publication_detail(
        publication_id: UUID,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        principal = _principal(settings, authorization)
        item = await _publication_service(request).get_publication(
            publication_id=publication_id,
            viewer_user_id=principal.user_id,
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Publication not found")
        return await _publication_with_urls(settings, item)

    @router.put("/publications/{publication_id}/like")
    async def set_like(
        publication_id: UUID,
        body: MiniAppLikeRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        principal = _principal(settings, authorization)
        liked, count = await _publication_service(request).set_like(
            publication_id=publication_id,
            user_id=principal.user_id,
            username=principal.username,
            liked=body.liked,
        )
        return {"liked": liked, "likes_count": count}

    @router.get("/publications/{publication_id}/comments")
    async def comments(
        publication_id: UUID,
        request: Request,
        authorization: str | None = Header(default=None),
        surface: PublicationScope = Query(),
        limit: int = Query(default=30, ge=1, le=100),
        offset: int = Query(default=0, ge=0, le=100_000),
    ) -> dict[str, object]:
        _principal(settings, authorization)
        items = await _publication_service(request).list_comments(
            publication_id=publication_id,
            surface=surface,
            limit=limit,
            offset=offset,
        )
        return {"items": [_comment_payload(item) for item in items]}

    @router.post("/publications/{publication_id}/comments", status_code=201)
    async def add_comment(
        publication_id: UUID,
        body: MiniAppCommentRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        principal = _principal(settings, authorization)
        item = await _publication_service(request).add_comment(
            publication_id=publication_id,
            surface=body.surface,
            user_id=principal.user_id,
            username=principal.username,
            body=body.body,
        )
        return _comment_payload(item)

    @router.get("/publications/{publication_id}/remix")
    async def remix_source(
        publication_id: UUID,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        _principal(settings, authorization)
        item = await _publication_service(request).remix_source(publication_id=publication_id)
        return await _remix_payload(settings, item)

    @router.get("/profiles/{slug}")
    async def profile(
        slug: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        _principal(settings, authorization)
        item = await _publication_service(request).get_profile(slug=slug)
        if item is None:
            raise HTTPException(status_code=404, detail="Profile not found")
        return _profile_payload(item)

    @router.get("/profiles/{slug}/publications")
    async def profile_publications(
        slug: str,
        request: Request,
        authorization: str | None = Header(default=None),
        limit: int = Query(default=20, ge=1, le=30),
        offset: int = Query(default=0, ge=0, le=100_000),
    ) -> dict[str, object]:
        principal = _principal(settings, authorization)
        items = await _publication_service(request).list_profile_publications(
            slug=slug,
            viewer_user_id=principal.user_id,
            limit=limit,
            offset=offset,
        )
        return {
            "items": [await _publication_with_urls(settings, item) for item in items],
            "next_offset": offset + len(items) if len(items) == limit else None,
        }

    @router.get("/me/profile")
    async def own_profile(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        principal = _principal(settings, authorization)
        profile = await _publication_service(request).get_own_profile(
            user_id=principal.user_id,
            username=principal.username,
        )
        return _profile_payload(profile)

    @router.put("/me/profile")
    async def update_profile(
        body: MiniAppProfileUpdateRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        principal = _principal(settings, authorization)
        profile = await _publication_service(request).update_profile(
            user_id=principal.user_id,
            username=principal.username,
            slug=body.slug,
            display_name=body.display_name,
            bio=body.bio,
        )
        return _profile_payload(profile)

    @router.get("/me/publications")
    async def own_publications(
        request: Request,
        authorization: str | None = Header(default=None),
        scope: PublicationScope | None = Query(default=None),
        limit: int = Query(default=30, ge=1, le=50),
        offset: int = Query(default=0, ge=0, le=100_000),
    ) -> dict[str, object]:
        principal = _principal(settings, authorization)
        items = await _publication_service(request).list_own_publications(
            user_id=principal.user_id,
            scope=scope,
            limit=limit,
            offset=offset,
        )
        return {
            "items": [await _publication_with_urls(settings, item) for item in items],
        }

    @router.post("/generations/{generation_id}/publications", status_code=201)
    async def publish_generation(
        generation_id: UUID,
        body: MiniAppPublishRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        principal = _principal(settings, authorization)
        item = await _publication_service(request).publish(
            user_id=principal.user_id,
            username=principal.username,
            generation_id=generation_id,
            scope=body.scope,
        )
        return await _publication_with_urls(settings, item)

    @router.delete("/generations/{generation_id}/publications/{scope}")
    async def unpublish_generation(
        generation_id: UUID,
        scope: PublicationScope,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        principal = _principal(settings, authorization)
        existed = await _publication_service(request).unpublish(
            user_id=principal.user_id,
            generation_id=generation_id,
            scope=scope,
        )
        return {"unpublished": existed, "scope": scope.value}

    @router.get("/reference-memory")
    async def list_references(
        request: Request,
        authorization: str | None = Header(default=None),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=30, ge=1, le=100),
    ) -> dict[str, object]:
        principal = _principal(settings, authorization)
        page = await _reference_service(request).list(
            user_id=principal.user_id,
            offset=offset,
            limit=limit,
        )
        return {
            "items": [_reference_payload(item) for item in page.items],
            "total": page.total,
            "used_bytes": page.used_bytes,
            "max_items": page.max_items,
            "max_bytes": page.max_bytes,
        }

    @router.post("/reference-memory", status_code=status.HTTP_201_CREATED)
    async def save_reference(
        body: MiniAppReferenceSaveRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        principal = _principal(settings, authorization)
        result = await _reference_service(request).save_from_temporary_input(
            user_id=principal.user_id,
            username=principal.username,
            storage_key=body.storage_key,
        )
        return {**_reference_payload(result.item), "duplicate": result.duplicate}

    @router.post("/reference-memory/resolve")
    async def resolve_references(
        body: MiniAppReferenceResolveRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        principal = _principal(settings, authorization)
        items = await _reference_service(request).resolve(
            user_id=principal.user_id,
            asset_ids=tuple(body.reference_ids),
        )
        return {"items": [_reference_payload(item) for item in items]}

    @router.delete("/reference-memory/{asset_id}", status_code=status.HTTP_202_ACCEPTED)
    async def delete_reference(
        asset_id: UUID,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, str]:
        principal = _principal(settings, authorization)
        await _reference_service(request).delete(user_id=principal.user_id, asset_id=asset_id)
        return {"status": "delete_pending", "id": str(asset_id)}

    return router
