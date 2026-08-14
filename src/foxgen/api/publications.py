from __future__ import annotations

from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from foxgen.api.security import authenticate_user_context
from foxgen.core.config import Settings
from foxgen.domain.publications import (
    FeedSort,
    PublicationCommentView,
    PublicationScope,
    PublicationView,
    PublicProfileView,
    RemixSourceView,
)


class PublicationServiceProtocol(Protocol):
    async def get_profile(self, *, slug: str) -> PublicProfileView | None: ...

    async def get_own_profile(
        self,
        *,
        user_id: int,
        username: str | None,
    ) -> PublicProfileView: ...

    async def update_profile(
        self,
        *,
        user_id: int,
        username: str | None,
        slug: str,
        display_name: str | None,
        bio: str | None,
    ) -> PublicProfileView: ...

    async def publish(
        self,
        *,
        user_id: int,
        username: str | None,
        generation_id: UUID,
        scope: PublicationScope,
    ) -> PublicationView: ...

    async def unpublish(
        self,
        *,
        user_id: int,
        generation_id: UUID,
        scope: PublicationScope,
    ) -> bool: ...

    async def get_publication(
        self,
        *,
        publication_id: UUID,
        viewer_user_id: int,
    ) -> PublicationView | None: ...

    async def list_feed(
        self,
        *,
        viewer_user_id: int,
        sort: FeedSort,
        limit: int,
        offset: int,
    ) -> list[PublicationView]: ...

    async def list_profile_publications(
        self,
        *,
        slug: str,
        viewer_user_id: int,
        limit: int,
        offset: int,
    ) -> list[PublicationView]: ...

    async def list_own_publications(
        self,
        *,
        user_id: int,
        scope: PublicationScope | None,
        limit: int,
        offset: int,
    ) -> list[PublicationView]: ...

    async def set_like(
        self,
        *,
        publication_id: UUID,
        user_id: int,
        username: str | None,
        liked: bool,
    ) -> tuple[bool, int]: ...

    async def add_comment(
        self,
        *,
        publication_id: UUID,
        surface: PublicationScope,
        user_id: int,
        username: str | None,
        body: str,
    ) -> PublicationCommentView: ...

    async def list_comments(
        self,
        *,
        publication_id: UUID,
        surface: PublicationScope,
        limit: int,
        offset: int,
    ) -> list[PublicationCommentView]: ...

    async def remix_source(self, *, publication_id: UUID) -> RemixSourceView: ...


class ProfileUpdateRequest(BaseModel):
    slug: str = Field(min_length=3, max_length=64)
    display_name: str | None = Field(default=None, max_length=128)
    bio: str | None = Field(default=None, max_length=500)


class PublishRequest(BaseModel):
    scope: PublicationScope


class LikeRequest(BaseModel):
    liked: bool


class CommentRequest(BaseModel):
    surface: PublicationScope
    body: str = Field(min_length=1, max_length=1000)


def create_publication_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["feed"])

    def principal(
        authorization: str | None,
        user_id_header: str | None,
    ) -> int:
        return authenticate_user_context(
            settings=settings,
            authorization=authorization,
            user_id_header=user_id_header,
        ).user_id

    def service(request: Request) -> PublicationServiceProtocol:
        value = getattr(request.app.state, "publication_service", None)
        if value is None:
            raise HTTPException(status_code=503, detail="Publication service is not configured")
        return value

    @router.get("/v1/feed")
    async def feed(
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
        sort: FeedSort = Query(default=FeedSort.RECENT),
        limit: int = Query(default=10, ge=1, le=30),
        offset: int = Query(default=0, ge=0, le=100_000),
    ) -> dict[str, object]:
        viewer_id = principal(authorization, user_id_header)
        items = await service(request).list_feed(
            viewer_user_id=viewer_id,
            sort=sort,
            limit=limit,
            offset=offset,
        )
        return {
            "items": [_publication_payload(item) for item in items],
            "sort": sort.value,
            "limit": limit,
            "offset": offset,
            "next_offset": offset + len(items) if len(items) == limit else None,
        }

    @router.get("/v1/publications/{publication_id}")
    async def publication_detail(
        publication_id: UUID,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
    ) -> dict[str, object]:
        viewer_id = principal(authorization, user_id_header)
        item = await service(request).get_publication(
            publication_id=publication_id,
            viewer_user_id=viewer_id,
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Publication not found")
        return _publication_payload(item)

    @router.get("/v1/profiles/{slug}")
    async def profile_detail(
        slug: str,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
    ) -> dict[str, object]:
        principal(authorization, user_id_header)
        profile = await service(request).get_profile(slug=slug)
        if profile is None:
            raise HTTPException(status_code=404, detail="Profile not found")
        return _profile_payload(profile)

    @router.get("/v1/profiles/{slug}/publications")
    async def profile_publications(
        slug: str,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
        limit: int = Query(default=10, ge=1, le=30),
        offset: int = Query(default=0, ge=0, le=100_000),
    ) -> dict[str, object]:
        viewer_id = principal(authorization, user_id_header)
        items = await service(request).list_profile_publications(
            slug=slug,
            viewer_user_id=viewer_id,
            limit=limit,
            offset=offset,
        )
        return {
            "items": [_publication_payload(item) for item in items],
            "limit": limit,
            "offset": offset,
            "next_offset": offset + len(items) if len(items) == limit else None,
        }

    @router.get("/v1/me/profile")
    async def own_profile(
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
        username: str | None = Header(default=None, alias="X-FoxGen-Username"),
    ) -> dict[str, object]:
        user_id = principal(authorization, user_id_header)
        profile = await service(request).get_own_profile(user_id=user_id, username=username)
        return _profile_payload(profile)

    @router.put("/v1/me/profile")
    async def update_profile(
        payload: ProfileUpdateRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
        username: str | None = Header(default=None, alias="X-FoxGen-Username"),
    ) -> dict[str, object]:
        user_id = principal(authorization, user_id_header)
        profile = await service(request).update_profile(
            user_id=user_id,
            username=username,
            slug=payload.slug,
            display_name=payload.display_name,
            bio=payload.bio,
        )
        return _profile_payload(profile)

    @router.get("/v1/me/publications")
    async def own_publications(
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
        scope: PublicationScope | None = Query(default=None),
        limit: int = Query(default=20, ge=1, le=50),
        offset: int = Query(default=0, ge=0, le=100_000),
    ) -> dict[str, object]:
        user_id = principal(authorization, user_id_header)
        items = await service(request).list_own_publications(
            user_id=user_id,
            scope=scope,
            limit=limit,
            offset=offset,
        )
        return {"items": [_publication_payload(item) for item in items]}

    @router.post("/v1/generations/{generation_id}/publications")
    async def publish_generation(
        generation_id: UUID,
        payload: PublishRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
        username: str | None = Header(default=None, alias="X-FoxGen-Username"),
    ) -> dict[str, object]:
        user_id = principal(authorization, user_id_header)
        item = await service(request).publish(
            user_id=user_id,
            username=username,
            generation_id=generation_id,
            scope=payload.scope,
        )
        return _publication_payload(item)

    @router.delete("/v1/generations/{generation_id}/publications/{scope}")
    async def unpublish_generation(
        generation_id: UUID,
        scope: PublicationScope,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
    ) -> dict[str, object]:
        user_id = principal(authorization, user_id_header)
        existed = await service(request).unpublish(
            user_id=user_id,
            generation_id=generation_id,
            scope=scope,
        )
        return {"unpublished": existed, "scope": scope.value}

    @router.put("/v1/publications/{publication_id}/like")
    async def set_like(
        publication_id: UUID,
        payload: LikeRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
        username: str | None = Header(default=None, alias="X-FoxGen-Username"),
    ) -> dict[str, object]:
        user_id = principal(authorization, user_id_header)
        liked, count = await service(request).set_like(
            publication_id=publication_id,
            user_id=user_id,
            username=username,
            liked=payload.liked,
        )
        return {"liked": liked, "likes_count": count}

    @router.get("/v1/publications/{publication_id}/comments")
    async def comments(
        publication_id: UUID,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
        surface: PublicationScope = Query(),
        limit: int = Query(default=30, ge=1, le=100),
        offset: int = Query(default=0, ge=0, le=100_000),
    ) -> dict[str, object]:
        principal(authorization, user_id_header)
        items = await service(request).list_comments(
            publication_id=publication_id,
            surface=surface,
            limit=limit,
            offset=offset,
        )
        return {"items": [_comment_payload(item) for item in items]}

    @router.post("/v1/publications/{publication_id}/comments")
    async def add_comment(
        publication_id: UUID,
        payload: CommentRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
        username: str | None = Header(default=None, alias="X-FoxGen-Username"),
    ) -> dict[str, object]:
        user_id = principal(authorization, user_id_header)
        item = await service(request).add_comment(
            publication_id=publication_id,
            surface=payload.surface,
            user_id=user_id,
            username=username,
            body=payload.body,
        )
        return _comment_payload(item)

    @router.get("/v1/publications/{publication_id}/remix")
    async def remix_source(
        publication_id: UUID,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
    ) -> dict[str, object]:
        principal(authorization, user_id_header)
        item = await service(request).remix_source(publication_id=publication_id)
        return _remix_payload(item)

    return router


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
        "media": [
            {"storage_key": media.storage_key, "content_type": media.content_type}
            for media in item.media
        ],
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


def _remix_payload(item: RemixSourceView) -> dict[str, object]:
    return {
        "publication_id": str(item.publication_id),
        "generation_id": str(item.generation_id),
        "author_slug": item.author_slug,
        "model_slug": item.model_slug,
        "media_kind": item.media_kind,
        "prompt": item.prompt,
        "media": [
            {"storage_key": media.storage_key, "content_type": media.content_type}
            for media in item.media
        ],
    }
