from typing import Protocol
from uuid import UUID

from foxgen.core.errors import ErrorCode, FoxGenError
from foxgen.feed.domain import (
    CommentSurface,
    FeedComment,
    FeedProfile,
    FeedSource,
    PublicationRecord,
    PublicationScope,
    PublicationView,
    ShareReceipt,
    post_start_param,
)


class FeedError(FoxGenError):
    pass


class FeedRepository(Protocol):
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

    async def get_profile_by_slug(self, public_slug: str) -> FeedProfile | None: ...

    async def publish(
        self,
        *,
        user_id: int,
        generation_id: UUID,
        scope: PublicationScope,
        prompt_visible: bool,
    ) -> PublicationRecord: ...

    async def unpublish(
        self,
        *,
        user_id: int,
        publication_id: UUID,
    ) -> bool: ...

    async def get_publication(
        self,
        *,
        publication_id: UUID,
        viewer_user_id: int,
        include_unpublished_owner: bool = False,
    ) -> PublicationRecord | None: ...

    async def list_feed(
        self,
        *,
        viewer_user_id: int,
        source: FeedSource,
        limit: int,
        offset: int,
    ) -> tuple[PublicationRecord, ...]: ...

    async def list_profile(
        self,
        *,
        viewer_user_id: int,
        public_slug: str,
        limit: int,
        offset: int,
    ) -> tuple[PublicationRecord, ...]: ...

    async def list_user_publications(
        self,
        *,
        viewer_user_id: int,
        owner_user_id: int,
        scope: PublicationScope | None,
        include_unpublished: bool,
        limit: int,
        offset: int,
    ) -> tuple[PublicationRecord, ...]: ...

    async def set_like(
        self,
        *,
        user_id: int,
        publication_id: UUID,
        liked: bool,
    ) -> bool: ...

    async def list_comments(
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

    async def record_share(
        self,
        *,
        publication_id: UUID,
        user_id: int,
        surface: CommentSurface,
    ) -> None: ...


class MediaUrlSigner(Protocol):
    async def presigned_url(self, storage_key: str) -> str: ...


class FeedService:
    def __init__(self, repository: FeedRepository, media_signer: MediaUrlSigner) -> None:
        self._repository = repository
        self._media_signer = media_signer

    async def ensure_profile(
        self,
        *,
        user_id: int,
        username: str | None = None,
        display_name: str | None = None,
    ) -> FeedProfile:
        return await self._repository.ensure_profile(
            user_id=user_id,
            username=username,
            display_name=display_name,
        )

    async def update_profile(
        self,
        *,
        user_id: int,
        display_name: str | None,
        avatar_url: str | None,
        bio: str | None,
    ) -> FeedProfile:
        normalized_name = _optional_text(display_name, max_length=80)
        normalized_avatar = _optional_text(avatar_url, max_length=1000)
        normalized_bio = _optional_text(bio, max_length=500)
        return await self._repository.update_profile(
            user_id=user_id,
            display_name=normalized_name,
            avatar_url=normalized_avatar,
            bio=normalized_bio,
        )

    async def profile(self, *, viewer_user_id: int, public_slug: str) -> FeedProfile:
        profile = await self._repository.get_profile_by_slug(public_slug)
        if profile is None:
            raise FeedError(ErrorCode.TASK_NOT_FOUND, "Профиль не найден.")
        del viewer_user_id
        return profile

    async def publish(
        self,
        *,
        user_id: int,
        generation_id: UUID,
        scope: PublicationScope,
        prompt_visible: bool,
    ) -> PublicationView:
        record = await self._repository.publish(
            user_id=user_id,
            generation_id=generation_id,
            scope=scope,
            prompt_visible=prompt_visible,
        )
        return await self._view(record, viewer_user_id=user_id)

    async def unpublish(self, *, user_id: int, publication_id: UUID) -> bool:
        removed = await self._repository.unpublish(
            user_id=user_id,
            publication_id=publication_id,
        )
        if not removed:
            raise FeedError(ErrorCode.TASK_NOT_FOUND, "Публикация не найдена.")
        return True

    async def publication(
        self,
        *,
        viewer_user_id: int,
        publication_id: UUID,
        include_unpublished_owner: bool = False,
    ) -> PublicationView:
        record = await self._repository.get_publication(
            publication_id=publication_id,
            viewer_user_id=viewer_user_id,
            include_unpublished_owner=include_unpublished_owner,
        )
        if record is None:
            raise FeedError(ErrorCode.TASK_NOT_FOUND, "Публикация не найдена.")
        return await self._view(record, viewer_user_id=viewer_user_id)

    async def feed(
        self,
        *,
        viewer_user_id: int,
        source: FeedSource,
        limit: int,
        offset: int,
    ) -> tuple[PublicationView, ...]:
        records = await self._repository.list_feed(
            viewer_user_id=viewer_user_id,
            source=source,
            limit=limit,
            offset=offset,
        )
        return tuple([await self._view(item, viewer_user_id=viewer_user_id) for item in records])

    async def profile_publications(
        self,
        *,
        viewer_user_id: int,
        public_slug: str,
        limit: int,
        offset: int,
    ) -> tuple[PublicationView, ...]:
        records = await self._repository.list_profile(
            viewer_user_id=viewer_user_id,
            public_slug=public_slug,
            limit=limit,
            offset=offset,
        )
        return tuple([await self._view(item, viewer_user_id=viewer_user_id) for item in records])

    async def own_publications(
        self,
        *,
        user_id: int,
        scope: PublicationScope | None,
        include_unpublished: bool,
        limit: int,
        offset: int,
    ) -> tuple[PublicationView, ...]:
        records = await self._repository.list_user_publications(
            viewer_user_id=user_id,
            owner_user_id=user_id,
            scope=scope,
            include_unpublished=include_unpublished,
            limit=limit,
            offset=offset,
        )
        return tuple([await self._view(item, viewer_user_id=user_id) for item in records])

    async def set_like(
        self,
        *,
        user_id: int,
        publication_id: UUID,
        liked: bool,
    ) -> PublicationView:
        await self._repository.set_like(
            user_id=user_id,
            publication_id=publication_id,
            liked=liked,
        )
        return await self.publication(
            viewer_user_id=user_id,
            publication_id=publication_id,
        )

    async def comments(
        self,
        *,
        publication_id: UUID,
        viewer_user_id: int,
        surface: CommentSurface,
        limit: int,
        offset: int,
    ) -> tuple[FeedComment, ...]:
        return await self._repository.list_comments(
            publication_id=publication_id,
            viewer_user_id=viewer_user_id,
            surface=surface,
            limit=limit,
            offset=offset,
        )

    async def add_comment(
        self,
        *,
        publication_id: UUID,
        user_id: int,
        surface: CommentSurface,
        text: str,
    ) -> FeedComment:
        normalized = text.strip()
        if not 1 <= len(normalized) <= 300:
            raise FeedError(
                ErrorCode.VALIDATION,
                "Комментарий должен содержать от 1 до 300 символов.",
            )
        return await self._repository.add_comment(
            publication_id=publication_id,
            user_id=user_id,
            surface=surface,
            text=normalized,
        )

    async def share(
        self,
        *,
        publication_id: UUID,
        user_id: int,
        surface: CommentSurface,
    ) -> ShareReceipt:
        await self._repository.record_share(
            publication_id=publication_id,
            user_id=user_id,
            surface=surface,
        )
        publication = await self.publication(
            viewer_user_id=user_id,
            publication_id=publication_id,
        )
        return ShareReceipt(
            publication=publication,
            start_param=post_start_param(publication_id),
        )

    async def remix_source(
        self,
        *,
        viewer_user_id: int,
        publication_id: UUID,
    ) -> PublicationView:
        publication = await self.publication(
            viewer_user_id=viewer_user_id,
            publication_id=publication_id,
        )
        if not publication.media_urls:
            raise FeedError(
                ErrorCode.TASK_NOT_FOUND,
                "У публикации нет доступного результата для remix.",
            )
        return publication

    async def _view(
        self,
        record: PublicationRecord,
        *,
        viewer_user_id: int,
    ) -> PublicationView:
        media_urls = tuple(
            [await self._media_signer.presigned_url(key) for key in record.storage_keys]
        )
        prompt_allowed = record.prompt_visible and not record.is_derivative
        return PublicationView(
            id=record.id,
            generation_id=record.generation_id,
            author_user_id=record.author_user_id,
            scope=record.scope,
            media_kind=record.media_kind,
            model_slug=record.model_slug,
            media_urls=media_urls,
            prompt=record.prompt if prompt_allowed else None,
            prompt_actions_allowed=prompt_allowed,
            is_derivative=record.is_derivative,
            source_publication_id=record.source_publication_id,
            likes_count=record.likes_count,
            comments_count=record.comments_count,
            shares_count=record.shares_count,
            remixes_count=record.remixes_count,
            viewer_liked=record.viewer_liked,
            is_mine=record.author_user_id == viewer_user_id,
            author_slug=record.author_slug,
            author_display_name=record.author_display_name,
            author_username=record.author_username,
            author_avatar_url=record.author_avatar_url,
            published_at=record.published_at,
        )


def _optional_text(value: str | None, *, max_length: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > max_length:
        raise FeedError(
            ErrorCode.VALIDATION,
            f"Значение длиннее допустимых {max_length} символов.",
        )
    return normalized
