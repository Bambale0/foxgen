from typing import Protocol
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from foxgen.api.security import SubmissionPrincipal, authenticate_user_context
from foxgen.core.config import Settings
from foxgen.feed.domain import (
    CommentSurface,
    FeedComment,
    FeedProfile,
    FeedSource,
    PublicationScope,
    PublicationView,
    RemixSource,
    ShareReceipt,
    post_start_param,
    profile_start_param,
    remix_start_param,
)
from foxgen.feed.service import FeedService


class FeedServiceProtocol(Protocol):
    async def ensure_profile(
        self,
        *,
        user_id: int,
        username: str | None = None,
        display_name: str | None = None,
    ) -> FeedProfile: ...

    async def update_profile(
        self,
        *,
        user_id: int,
        display_name: str | None,
        avatar_url: str | None,
        bio: str | None,
    ) -> FeedProfile: ...

    async def profile(self, *, viewer_user_id: int, public_slug: str) -> FeedProfile: ...

    async def publish(
        self,
        *,
        user_id: int,
        generation_id: UUID,
        scope: PublicationScope,
        prompt_visible: bool,
    ) -> PublicationView: ...

    async def unpublish(self, *, user_id: int, publication_id: UUID) -> bool: ...

    async def publication(
        self,
        *,
        viewer_user_id: int,
        publication_id: UUID,
        include_unpublished_owner: bool = False,
    ) -> PublicationView: ...

    async def feed(
        self,
        *,
        viewer_user_id: int,
        source: FeedSource,
        limit: int,
        offset: int,
    ) -> tuple[PublicationView, ...]: ...

    async def profile_publications(
        self,
        *,
        viewer_user_id: int,
        public_slug: str,
        limit: int,
        offset: int,
    ) -> tuple[PublicationView, ...]: ...

    async def own_publications(
        self,
        *,
        user_id: int,
        scope: PublicationScope | None,
        include_unpublished: bool,
        limit: int,
        offset: int,
    ) -> tuple[PublicationView, ...]: ...

    async def set_like(
        self,
        *,
        user_id: int,
        publication_id: UUID,
        liked: bool,
    ) -> PublicationView: ...

    async def comments(
        self,
        *,
        publication_id: UUID,
        viewer_user_id: int,
        surface: CommentSurface,
        limit: int,
        offset: int,
    ) -> tuple[FeedComment, ...]: ...

    async def add_comment(
        self,
        *,
        publication_id: UUID,
        user_id: int,
        surface: CommentSurface,
        text: str,
    ) -> FeedComment: ...

    async def share(
        self,
        *,
        publication_id: UUID,
        user_id: int,
        surface: CommentSurface,
    ) -> ShareReceipt: ...

    async def remix_source(
        self,
        *,
        viewer_user_id: int,
        publication_id: UUID,
    ) -> RemixSource: ...


class PublishRequest(BaseModel):
    generation_id: UUID
    scope: PublicationScope
    prompt_visible: bool = False


class ProfileUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=80)
    avatar_url: str | None = Field(default=None, max_length=1000)
    bio: str | None = Field(default=None, max_length=500)


class CommentRequest(BaseModel):
    surface: CommentSurface
    text: str = Field(min_length=1, max_length=300)


class ShareRequest(BaseModel):
    surface: CommentSurface


def _service(request: Request) -> FeedServiceProtocol:
    service: FeedService | None = getattr(request.app.state, "feed_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Feed service is not configured")
    return service


def _principal(
    *,
    settings: Settings,
    authorization: str | None,
    user_id_header: str | None,
) -> SubmissionPrincipal:
    return authenticate_user_context(
        settings=settings,
        authorization=authorization,
        user_id_header=user_id_header,
    )


def _profile_payload(profile: FeedProfile) -> dict[str, object]:
    return {
        "user_id": profile.user_id,
        "public_slug": profile.public_slug,
        "display_name": profile.display_name,
        "avatar_url": profile.avatar_url,
        "bio": profile.bio,
        "username": profile.username,
        "deep_link": profile_start_param(profile.public_slug),
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }


def _publication_payload(item: PublicationView) -> dict[str, object]:
    return {
        "id": str(item.id),
        "generation_id": str(item.generation_id),
        "author_user_id": item.author_user_id,
        "scope": item.scope.value,
        "media_kind": item.media_kind,
        "model_slug": item.model_slug,
        "media_urls": list(item.media_urls),
        "prompt": item.prompt,
        "prompt_actions_allowed": item.prompt_actions_allowed,
        "is_derivative": item.is_derivative,
        "source_publication_id": (
            str(item.source_publication_id) if item.source_publication_id is not None else None
        ),
        "likes_count": item.likes_count,
        "comments_count": item.comments_count,
        "shares_count": item.shares_count,
        "remixes_count": item.remixes_count,
        "viewer_liked": item.viewer_liked,
        "is_mine": item.is_mine,
        "author": {
            "public_slug": item.author_slug,
            "display_name": item.author_display_name,
            "username": item.author_username,
            "avatar_url": item.author_avatar_url,
            "profile_deep_link": profile_start_param(item.author_slug),
        },
        "post_deep_link": post_start_param(item.id),
        "remix_deep_link": remix_start_param(item.id),
        "published_at": item.published_at,
    }


def _comment_payload(item: FeedComment) -> dict[str, object]:
    return {
        "id": str(item.id),
        "publication_id": str(item.publication_id),
        "user_id": item.user_id,
        "surface": item.surface.value,
        "text": item.text,
        "author": {
            "display_name": item.author_display_name,
            "public_slug": item.author_slug,
        },
        "is_mine": item.is_mine,
        "created_at": item.created_at,
    }


def create_feed_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/v1/feed", tags=["feed"])

    @router.get("")
    async def list_feed(
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
        source: FeedSource = Query(default=FeedSource.RECENT),
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0, le=100_000),
    ) -> dict[str, object]:
        principal = _principal(
            settings=settings,
            authorization=authorization,
            user_id_header=user_id_header,
        )
        items = await _service(request).feed(
            viewer_user_id=principal.user_id,
            source=source,
            limit=limit,
            offset=offset,
        )
        return {
            "items": [_publication_payload(item) for item in items],
            "source": source.value,
            "limit": limit,
            "offset": offset,
        }

    @router.get("/me")
    async def own_publications(
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
        scope: PublicationScope | None = Query(default=None),
        include_unpublished: bool = Query(default=False),
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0, le=100_000),
    ) -> dict[str, object]:
        principal = _principal(
            settings=settings,
            authorization=authorization,
            user_id_header=user_id_header,
        )
        items = await _service(request).own_publications(
            user_id=principal.user_id,
            scope=scope,
            include_unpublished=include_unpublished,
            limit=limit,
            offset=offset,
        )
        return {"items": [_publication_payload(item) for item in items]}

    @router.get("/profile/me")
    async def own_profile(
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
        username: str | None = Header(default=None, alias="X-FoxGen-Username"),
        display_name: str | None = Header(default=None, alias="X-FoxGen-Display-Name"),
    ) -> dict[str, object]:
        principal = _principal(
            settings=settings,
            authorization=authorization,
            user_id_header=user_id_header,
        )
        profile = await _service(request).ensure_profile(
            user_id=principal.user_id,
            username=username,
            display_name=display_name,
        )
        return _profile_payload(profile)

    @router.put("/profile/me")
    async def update_profile(
        body: ProfileUpdateRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
    ) -> dict[str, object]:
        principal = _principal(
            settings=settings,
            authorization=authorization,
            user_id_header=user_id_header,
        )
        profile = await _service(request).update_profile(
            user_id=principal.user_id,
            display_name=body.display_name,
            avatar_url=body.avatar_url,
            bio=body.bio,
        )
        return _profile_payload(profile)

    @router.get("/profile/{public_slug}")
    async def public_profile(
        public_slug: str,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
        limit: int = Query(default=30, ge=1, le=100),
        offset: int = Query(default=0, ge=0, le=100_000),
    ) -> dict[str, object]:
        principal = _principal(
            settings=settings,
            authorization=authorization,
            user_id_header=user_id_header,
        )
        service = _service(request)
        profile = await service.profile(
            viewer_user_id=principal.user_id,
            public_slug=public_slug,
        )
        items = await service.profile_publications(
            viewer_user_id=principal.user_id,
            public_slug=public_slug,
            limit=limit,
            offset=offset,
        )
        return {
            "profile": _profile_payload(profile),
            "items": [_publication_payload(item) for item in items],
        }

    @router.put("/publications")
    async def publish(
        body: PublishRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
    ) -> dict[str, object]:
        principal = _principal(
            settings=settings,
            authorization=authorization,
            user_id_header=user_id_header,
        )
        publication = await _service(request).publish(
            user_id=principal.user_id,
            generation_id=body.generation_id,
            scope=body.scope,
            prompt_visible=body.prompt_visible,
        )
        return _publication_payload(publication)

    @router.get("/publications/{publication_id}")
    async def publication_detail(
        publication_id: UUID,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
    ) -> dict[str, object]:
        principal = _principal(
            settings=settings,
            authorization=authorization,
            user_id_header=user_id_header,
        )
        publication = await _service(request).publication(
            viewer_user_id=principal.user_id,
            publication_id=publication_id,
        )
        return _publication_payload(publication)

    @router.delete("/publications/{publication_id}")
    async def unpublish(
        publication_id: UUID,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
    ) -> dict[str, object]:
        principal = _principal(
            settings=settings,
            authorization=authorization,
            user_id_header=user_id_header,
        )
        await _service(request).unpublish(
            user_id=principal.user_id,
            publication_id=publication_id,
        )
        return {"status": "unpublished", "publication_id": str(publication_id)}

    @router.put("/publications/{publication_id}/like")
    async def like(
        publication_id: UUID,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
    ) -> dict[str, object]:
        principal = _principal(
            settings=settings,
            authorization=authorization,
            user_id_header=user_id_header,
        )
        publication = await _service(request).set_like(
            user_id=principal.user_id,
            publication_id=publication_id,
            liked=True,
        )
        return _publication_payload(publication)

    @router.delete("/publications/{publication_id}/like")
    async def unlike(
        publication_id: UUID,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
    ) -> dict[str, object]:
        principal = _principal(
            settings=settings,
            authorization=authorization,
            user_id_header=user_id_header,
        )
        publication = await _service(request).set_like(
            user_id=principal.user_id,
            publication_id=publication_id,
            liked=False,
        )
        return _publication_payload(publication)

    @router.get("/publications/{publication_id}/comments")
    async def comments(
        publication_id: UUID,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
        surface: CommentSurface = Query(...),
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0, le=100_000),
    ) -> dict[str, object]:
        principal = _principal(
            settings=settings,
            authorization=authorization,
            user_id_header=user_id_header,
        )
        items = await _service(request).comments(
            publication_id=publication_id,
            viewer_user_id=principal.user_id,
            surface=surface,
            limit=limit,
            offset=offset,
        )
        return {
            "surface": surface.value,
            "items": [_comment_payload(item) for item in items],
        }

    @router.post("/publications/{publication_id}/comments", status_code=201)
    async def add_comment(
        publication_id: UUID,
        body: CommentRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
    ) -> dict[str, object]:
        principal = _principal(
            settings=settings,
            authorization=authorization,
            user_id_header=user_id_header,
        )
        comment = await _service(request).add_comment(
            publication_id=publication_id,
            user_id=principal.user_id,
            surface=body.surface,
            text=body.text,
        )
        return _comment_payload(comment)

    @router.post("/publications/{publication_id}/share")
    async def share(
        publication_id: UUID,
        body: ShareRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
    ) -> dict[str, object]:
        principal = _principal(
            settings=settings,
            authorization=authorization,
            user_id_header=user_id_header,
        )
        receipt = await _service(request).share(
            publication_id=publication_id,
            user_id=principal.user_id,
            surface=body.surface,
        )
        return {
            "start_param": receipt.start_param,
            "publication": _publication_payload(receipt.publication),
        }

    @router.get("/publications/{publication_id}/remix")
    async def remix_source(
        publication_id: UUID,
        request: Request,
        authorization: str | None = Header(default=None),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
    ) -> dict[str, object]:
        principal = _principal(
            settings=settings,
            authorization=authorization,
            user_id_header=user_id_header,
        )
        remix = await _service(request).remix_source(
            viewer_user_id=principal.user_id,
            publication_id=publication_id,
        )
        return {
            "source": _publication_payload(remix.publication),
            "source_publication_id": str(remix.publication.id),
            # Trusted internal bot/backend callers may use these private object keys only
            # to mint a fresh presigned reference at final generation confirmation.
            "reference_storage_keys": list(remix.storage_keys),
        }

    return router
