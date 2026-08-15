from __future__ import annotations

import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from foxgen.core.errors import ErrorCode, SubmissionError
from foxgen.domain.models import GenerationStatus, MediaAssetStatus
from foxgen.domain.publications import (
    FeedSort,
    PublicationCommentView,
    PublicationMediaView,
    PublicationScope,
    PublicationView,
    PublicProfileView,
    RemixSourceView,
)
from foxgen.infra.database import Database, Generation, MediaAsset, User
from foxgen.infra.publication_models import (
    GenerationLineage,
    Publication,
    PublicationComment,
    PublicationLike,
    PublicProfile,
)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,55}$")


def _default_slug(user_id: int, username: str | None) -> str:
    candidate = (username or "").strip().lower().lstrip("@")
    candidate = re.sub(r"[^a-z0-9_-]+", "-", candidate).strip("-_")
    if _SLUG_RE.fullmatch(candidate):
        return candidate
    return f"user-{user_id}"


def _normalize_slug(value: str) -> str:
    slug = value.strip().lower().lstrip("@")
    if not 3 <= len(slug) <= 56 or not _SLUG_RE.fullmatch(slug):
        raise SubmissionError(
            ErrorCode.VALIDATION,
            "Публичный адрес профиля должен содержать 3–56 символов: a-z, 0-9, _ или -.",
        )
    return slug


def _profile_view(profile: PublicProfile) -> PublicProfileView:
    return PublicProfileView(
        user_id=profile.user_id,
        slug=profile.slug,
        display_name=profile.display_name,
        bio=profile.bio,
    )


async def _ensure_user(
    session: AsyncSession,
    *,
    user_id: int,
    username: str | None,
) -> None:
    await session.execute(
        pg_insert(User)
        .values(id=user_id, username=username)
        .on_conflict_do_nothing(index_elements=[User.id])
    )
    if username:
        await session.execute(update(User).where(User.id == user_id).values(username=username))


class SqlAlchemyPublicationRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def get_profile(self, *, slug: str) -> PublicProfileView | None:
        normalized = slug.strip().lower()
        async with self._database.session() as session:
            profile = await session.scalar(
                select(PublicProfile).where(PublicProfile.slug == normalized)
            )
            return _profile_view(profile) if profile is not None else None

    async def get_own_profile(
        self,
        *,
        user_id: int,
        username: str | None,
    ) -> PublicProfileView:
        async with self._database.session() as session:
            async with session.begin():
                profile = await self._ensure_profile(
                    session,
                    user_id=user_id,
                    username=username,
                )
                return _profile_view(profile)

    async def update_profile(
        self,
        *,
        user_id: int,
        username: str | None,
        slug: str,
        display_name: str | None,
        bio: str | None,
    ) -> PublicProfileView:
        normalized_slug = _normalize_slug(slug)
        normalized_name = (display_name or "").strip() or None
        normalized_bio = (bio or "").strip() or None
        if normalized_name is not None and len(normalized_name) > 128:
            raise SubmissionError(ErrorCode.VALIDATION, "Имя профиля длиннее 128 символов.")
        if normalized_bio is not None and len(normalized_bio) > 500:
            raise SubmissionError(ErrorCode.VALIDATION, "Описание профиля длиннее 500 символов.")
        async with self._database.session() as session:
            async with session.begin():
                profile = await self._ensure_profile(
                    session,
                    user_id=user_id,
                    username=username,
                )
                duplicate = await session.scalar(
                    select(PublicProfile).where(
                        PublicProfile.slug == normalized_slug,
                        PublicProfile.user_id != user_id,
                    )
                )
                if duplicate is not None:
                    raise SubmissionError(
                        ErrorCode.IDEMPOTENCY_CONFLICT,
                        "Этот адрес профиля уже занят.",
                    )
                profile.slug = normalized_slug
                profile.display_name = normalized_name
                profile.bio = normalized_bio
                await session.flush()
                return _profile_view(profile)

    async def publish(
        self,
        *,
        user_id: int,
        username: str | None,
        generation_id: UUID,
        scope: PublicationScope,
    ) -> PublicationView:
        async with self._database.session() as session:
            async with session.begin():
                await self._ensure_profile(session, user_id=user_id, username=username)
                generation = await session.scalar(
                    select(Generation).where(
                        Generation.id == generation_id,
                        Generation.user_id == user_id,
                    )
                )
                if generation is None:
                    raise SubmissionError(
                        ErrorCode.TASK_NOT_FOUND,
                        "Генерация не найдена.",
                    )
                await self._assert_publishable(session, generation=generation, scope=scope)
                await session.execute(
                    pg_insert(Publication)
                    .values(
                        generation_id=generation.id,
                        user_id=user_id,
                        scope=scope.value,
                        active=True,
                    )
                    .on_conflict_do_update(
                        index_elements=[Publication.generation_id, Publication.scope],
                        set_={"active": True, "updated_at": func.now()},
                    )
                )
                publication = await session.scalar(
                    select(Publication).where(
                        Publication.generation_id == generation.id,
                        Publication.scope == scope.value,
                    )
                )
                if publication is None:
                    raise SubmissionError(
                        ErrorCode.PROVIDER_PROTOCOL,
                        "Не удалось сохранить публикацию.",
                    )
            return await self._hydrate_publication(
                session,
                publication=publication,
                viewer_user_id=user_id,
            )

    async def unpublish(
        self,
        *,
        user_id: int,
        generation_id: UUID,
        scope: PublicationScope,
    ) -> bool:
        async with self._database.session() as session:
            async with session.begin():
                publication = await session.scalar(
                    select(Publication).where(
                        Publication.generation_id == generation_id,
                        Publication.user_id == user_id,
                        Publication.scope == scope.value,
                    )
                )
                if publication is None:
                    return False
                if publication.active:
                    publication.active = False
                    await session.flush()
                return True

    async def get_publication(
        self,
        *,
        publication_id: UUID,
        viewer_user_id: int,
    ) -> PublicationView | None:
        async with self._database.session() as session:
            publication = await session.scalar(
                select(Publication).where(
                    Publication.id == publication_id,
                    Publication.active.is_(True),
                )
            )
            if publication is None:
                return None
            return await self._hydrate_publication(
                session,
                publication=publication,
                viewer_user_id=viewer_user_id,
            )

    async def list_feed(
        self,
        *,
        viewer_user_id: int,
        sort: FeedSort,
        limit: int,
        offset: int,
    ) -> list[PublicationView]:
        safe_limit = min(max(limit, 1), 30)
        safe_offset = max(offset, 0)
        async with self._database.session() as session:
            statement = select(Publication).where(
                Publication.scope == PublicationScope.FEED.value,
                Publication.active.is_(True),
            )
            if sort == FeedSort.TOP_DAY:
                statement = statement.where(
                    Publication.created_at >= datetime.now(UTC) - timedelta(days=1)
                )
            if sort == FeedSort.RECENT:
                rows = list(
                    await session.scalars(
                        statement.order_by(Publication.created_at.desc())
                        .offset(safe_offset)
                        .limit(safe_limit)
                    )
                )
                return await self._hydrate_many(
                    session,
                    publications=rows,
                    viewer_user_id=viewer_user_id,
                )

            rows = list(await session.scalars(statement))
            hydrated = await self._hydrate_many(
                session,
                publications=rows,
                viewer_user_id=viewer_user_id,
            )
            hydrated.sort(key=self._score, reverse=True)
            return hydrated[safe_offset : safe_offset + safe_limit]

    async def list_profile_publications(
        self,
        *,
        slug: str,
        viewer_user_id: int,
        limit: int,
        offset: int,
    ) -> list[PublicationView]:
        safe_limit = min(max(limit, 1), 30)
        safe_offset = max(offset, 0)
        async with self._database.session() as session:
            profile = await session.scalar(
                select(PublicProfile).where(PublicProfile.slug == slug.strip().lower())
            )
            if profile is None:
                return []
            publications = list(
                await session.scalars(
                    select(Publication)
                    .where(
                        Publication.user_id == profile.user_id,
                        Publication.scope == PublicationScope.PROFILE.value,
                        Publication.active.is_(True),
                    )
                    .order_by(Publication.created_at.desc())
                    .offset(safe_offset)
                    .limit(safe_limit)
                )
            )
            return await self._hydrate_many(
                session,
                publications=publications,
                viewer_user_id=viewer_user_id,
            )

    async def list_own_publications(
        self,
        *,
        user_id: int,
        scope: PublicationScope | None,
        limit: int,
        offset: int,
    ) -> list[PublicationView]:
        safe_limit = min(max(limit, 1), 50)
        safe_offset = max(offset, 0)
        async with self._database.session() as session:
            statement = select(Publication).where(Publication.user_id == user_id)
            if scope is not None:
                statement = statement.where(Publication.scope == scope.value)
            publications = list(
                await session.scalars(
                    statement.order_by(Publication.created_at.desc())
                    .offset(safe_offset)
                    .limit(safe_limit)
                )
            )
            return await self._hydrate_many(
                session,
                publications=publications,
                viewer_user_id=user_id,
            )

    async def set_like(
        self,
        *,
        publication_id: UUID,
        user_id: int,
        username: str | None,
        liked: bool,
    ) -> tuple[bool, int]:
        async with self._database.session() as session:
            async with session.begin():
                publication = await session.scalar(
                    select(Publication).where(
                        Publication.id == publication_id,
                        Publication.active.is_(True),
                    )
                )
                if publication is None:
                    raise SubmissionError(ErrorCode.TASK_NOT_FOUND, "Публикация не найдена.")
                await self._ensure_profile(session, user_id=user_id, username=username)
                if liked:
                    await session.execute(
                        pg_insert(PublicationLike)
                        .values(publication_id=publication_id, user_id=user_id)
                        .on_conflict_do_nothing(
                            index_elements=[PublicationLike.publication_id, PublicationLike.user_id]
                        )
                    )
                else:
                    await session.execute(
                        delete(PublicationLike).where(
                            PublicationLike.publication_id == publication_id,
                            PublicationLike.user_id == user_id,
                        )
                    )
                count = await session.scalar(
                    select(func.count(PublicationLike.user_id)).where(
                        PublicationLike.publication_id == publication_id
                    )
                )
                return liked, int(count or 0)

    async def add_comment(
        self,
        *,
        publication_id: UUID,
        surface: PublicationScope,
        user_id: int,
        username: str | None,
        body: str,
    ) -> PublicationCommentView:
        normalized = " ".join(body.split()).strip()
        if not normalized:
            raise SubmissionError(ErrorCode.VALIDATION, "Комментарий не может быть пустым.")
        if len(normalized) > 1000:
            raise SubmissionError(ErrorCode.VALIDATION, "Комментарий длиннее 1000 символов.")
        async with self._database.session() as session:
            async with session.begin():
                publication = await self._publication_for_surface(
                    session,
                    publication_id=publication_id,
                    surface=surface,
                )
                await self._ensure_profile(session, user_id=user_id, username=username)
                comment = PublicationComment(
                    publication_id=publication.id,
                    surface=surface.value,
                    user_id=user_id,
                    body=normalized,
                )
                session.add(comment)
                await session.flush()
                profile = await session.get(PublicProfile, user_id)
                if profile is None:
                    raise SubmissionError(ErrorCode.PROVIDER_PROTOCOL, "Профиль автора потерян.")
                return self._comment_view(comment, profile)

    async def list_comments(
        self,
        *,
        publication_id: UUID,
        surface: PublicationScope,
        limit: int,
        offset: int,
    ) -> list[PublicationCommentView]:
        safe_limit = min(max(limit, 1), 100)
        safe_offset = max(offset, 0)
        async with self._database.session() as session:
            await self._publication_for_surface(
                session,
                publication_id=publication_id,
                surface=surface,
            )
            rows = list(
                await session.scalars(
                    select(PublicationComment)
                    .where(
                        PublicationComment.publication_id == publication_id,
                        PublicationComment.surface == surface.value,
                    )
                    .order_by(PublicationComment.created_at.asc(), PublicationComment.id.asc())
                    .offset(safe_offset)
                    .limit(safe_limit)
                )
            )
            profiles = await self._profiles(session, {row.user_id for row in rows})
            return [
                self._comment_view(row, profiles[row.user_id])
                for row in rows
                if row.user_id in profiles
            ]

    async def remix_source(self, *, publication_id: UUID) -> RemixSourceView:
        async with self._database.session() as session:
            publication = await session.scalar(
                select(Publication).where(
                    Publication.id == publication_id,
                    Publication.active.is_(True),
                )
            )
            if publication is None:
                raise SubmissionError(ErrorCode.TASK_NOT_FOUND, "Публикация не найдена.")
            derivative = await session.get(GenerationLineage, publication.generation_id)
            if derivative is not None:
                raise SubmissionError(
                    ErrorCode.VALIDATION,
                    "Ремикс производной публикации недоступен.",
                )
            generation = await session.get(Generation, publication.generation_id)
            if generation is None or generation.status != GenerationStatus.SUCCEEDED.value:
                raise SubmissionError(
                    ErrorCode.VALIDATION,
                    "Источник ремикса больше недоступен.",
                )
            prompt = (generation.prompt or "").strip()
            if not prompt:
                raise SubmissionError(
                    ErrorCode.VALIDATION,
                    "У публикации нет доступного промпта для ремикса.",
                )
            media = await self._stored_media(session, generation.id, require_all=True)
            if not media:
                raise SubmissionError(
                    ErrorCode.VALIDATION,
                    "У публикации нет сохранённого медиа для ремикса.",
                )
            profile = await session.get(PublicProfile, publication.user_id)
            if profile is None:
                raise SubmissionError(ErrorCode.PROVIDER_PROTOCOL, "Профиль автора потерян.")
            return RemixSourceView(
                publication_id=publication.id,
                generation_id=generation.id,
                author_slug=profile.slug,
                model_slug=generation.model_slug,
                media_kind=generation.media_kind.value,
                prompt=prompt,
                media=tuple(media),
            )

    async def _ensure_profile(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        username: str | None,
    ) -> PublicProfile:
        await _ensure_user(session, user_id=user_id, username=username)
        existing = await session.get(PublicProfile, user_id)
        if existing is not None:
            return existing
        base = _default_slug(user_id, username)
        candidate = base
        suffix = 0
        while await session.scalar(
            select(PublicProfile.user_id).where(PublicProfile.slug == candidate)
        ):
            suffix += 1
            tail = f"-{suffix}"
            candidate = f"{base[: 56 - len(tail)]}{tail}"
        profile = PublicProfile(user_id=user_id, slug=candidate)
        session.add(profile)
        await session.flush()
        return profile

    async def _assert_publishable(
        self,
        session: AsyncSession,
        *,
        generation: Generation,
        scope: PublicationScope,
    ) -> None:
        if generation.status != GenerationStatus.SUCCEEDED.value:
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "Опубликовать можно только успешно завершённую генерацию.",
            )
        media = list(
            await session.scalars(
                select(MediaAsset).where(MediaAsset.generation_id == generation.id)
            )
        )
        if not media or any(asset.status != MediaAssetStatus.STORED.value for asset in media):
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "Сначала дождитесь полного сохранения результата.",
            )
        lineage = await session.get(GenerationLineage, generation.id)
        if lineage is not None and scope == PublicationScope.FEED:
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "Результат ремикса можно публиковать в профиль, но не в общую ленту.",
            )

    async def _publication_for_surface(
        self,
        session: AsyncSession,
        *,
        publication_id: UUID,
        surface: PublicationScope,
    ) -> Publication:
        publication = await session.scalar(
            select(Publication).where(
                Publication.id == publication_id,
                Publication.active.is_(True),
            )
        )
        if publication is None:
            raise SubmissionError(ErrorCode.TASK_NOT_FOUND, "Публикация не найдена.")
        if publication.scope != surface.value:
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "Комментарии этого раздела недоступны на другой поверхности.",
            )
        return publication

    async def _hydrate_publication(
        self,
        session: AsyncSession,
        *,
        publication: Publication,
        viewer_user_id: int,
    ) -> PublicationView:
        return (
            await self._hydrate_many(
                session,
                publications=[publication],
                viewer_user_id=viewer_user_id,
            )
        )[0]

    async def _hydrate_many(
        self,
        session: AsyncSession,
        *,
        publications: list[Publication],
        viewer_user_id: int,
    ) -> list[PublicationView]:
        if not publications:
            return []
        publication_ids = [item.id for item in publications]
        generation_ids = [item.generation_id for item in publications]
        user_ids = {item.user_id for item in publications}

        generations = {
            row.id: row
            for row in await session.scalars(
                select(Generation).where(Generation.id.in_(generation_ids))
            )
        }
        profiles = await self._profiles(session, user_ids)
        media_rows = list(
            await session.scalars(
                select(MediaAsset)
                .where(
                    MediaAsset.generation_id.in_(generation_ids),
                    MediaAsset.status == MediaAssetStatus.STORED.value,
                )
                .order_by(MediaAsset.created_at.asc(), MediaAsset.id.asc())
            )
        )
        media_by_generation: dict[UUID, list[PublicationMediaView]] = defaultdict(list)
        for media in media_rows:
            media_by_generation[media.generation_id].append(
                PublicationMediaView(
                    storage_key=media.storage_key,
                    content_type=media.content_type,
                )
            )
        lineages = {
            row.generation_id: row
            for row in await session.scalars(
                select(GenerationLineage).where(GenerationLineage.generation_id.in_(generation_ids))
            )
        }
        like_counts = dict(
            (
                publication_id,
                int(count),
            )
            for publication_id, count in (
                await session.execute(
                    select(
                        PublicationLike.publication_id,
                        func.count(PublicationLike.user_id),
                    )
                    .where(PublicationLike.publication_id.in_(publication_ids))
                    .group_by(PublicationLike.publication_id)
                )
            ).all()
        )
        liked_ids = set(
            await session.scalars(
                select(PublicationLike.publication_id).where(
                    PublicationLike.publication_id.in_(publication_ids),
                    PublicationLike.user_id == viewer_user_id,
                )
            )
        )
        comment_counts = dict(
            (
                publication_id,
                int(count),
            )
            for publication_id, count in (
                await session.execute(
                    select(
                        PublicationComment.publication_id,
                        func.count(PublicationComment.id),
                    )
                    .where(
                        PublicationComment.publication_id.in_(publication_ids),
                        PublicationComment.surface == PublicationScope.FEED.value,
                    )
                    .group_by(PublicationComment.publication_id)
                )
            ).all()
        )
        profile_comment_counts = dict(
            (
                publication_id,
                int(count),
            )
            for publication_id, count in (
                await session.execute(
                    select(
                        PublicationComment.publication_id,
                        func.count(PublicationComment.id),
                    )
                    .where(
                        PublicationComment.publication_id.in_(publication_ids),
                        PublicationComment.surface == PublicationScope.PROFILE.value,
                    )
                    .group_by(PublicationComment.publication_id)
                )
            ).all()
        )
        remix_counts = dict(
            (
                source_publication_id,
                int(count),
            )
            for source_publication_id, count in (
                await session.execute(
                    select(
                        GenerationLineage.source_publication_id,
                        func.count(GenerationLineage.generation_id),
                    )
                    .where(GenerationLineage.source_publication_id.in_(publication_ids))
                    .group_by(GenerationLineage.source_publication_id)
                )
            ).all()
        )

        result: list[PublicationView] = []
        for publication in publications:
            generation = generations.get(publication.generation_id)
            profile = profiles.get(publication.user_id)
            if generation is None or profile is None:
                continue
            lineage = lineages.get(generation.id)
            derived = lineage is not None
            prompt = None if derived else generation.prompt
            result.append(
                PublicationView(
                    id=publication.id,
                    generation_id=generation.id,
                    author=_profile_view(profile),
                    scope=PublicationScope(publication.scope),
                    active=publication.active,
                    model_slug=generation.model_slug,
                    media_kind=generation.media_kind.value,
                    prompt=prompt,
                    prompt_actions_allowed=not derived and bool((prompt or "").strip()),
                    media=tuple(media_by_generation.get(generation.id, [])),
                    likes_count=like_counts.get(publication.id, 0),
                    comments_count=(
                        comment_counts.get(publication.id, 0)
                        + profile_comment_counts.get(publication.id, 0)
                    ),
                    remix_count=remix_counts.get(publication.id, 0),
                    liked_by_viewer=publication.id in liked_ids,
                    source_publication_id=(
                        lineage.source_publication_id if lineage is not None else None
                    ),
                    created_at=publication.created_at,
                )
            )
        return result

    async def _stored_media(
        self,
        session: AsyncSession,
        generation_id: UUID,
        *,
        require_all: bool,
    ) -> list[PublicationMediaView]:
        rows = list(
            await session.scalars(
                select(MediaAsset)
                .where(MediaAsset.generation_id == generation_id)
                .order_by(MediaAsset.created_at.asc(), MediaAsset.id.asc())
            )
        )
        if require_all and any(row.status != MediaAssetStatus.STORED.value for row in rows):
            return []
        return [
            PublicationMediaView(storage_key=row.storage_key, content_type=row.content_type)
            for row in rows
            if row.status == MediaAssetStatus.STORED.value
        ]

    async def _profiles(
        self,
        session: AsyncSession,
        user_ids: set[int],
    ) -> dict[int, PublicProfile]:
        if not user_ids:
            return {}
        return {
            profile.user_id: profile
            for profile in await session.scalars(
                select(PublicProfile).where(PublicProfile.user_id.in_(user_ids))
            )
        }

    @staticmethod
    def _comment_view(
        comment: PublicationComment,
        profile: PublicProfile,
    ) -> PublicationCommentView:
        return PublicationCommentView(
            id=comment.id,
            publication_id=comment.publication_id,
            surface=PublicationScope(comment.surface),
            author=_profile_view(profile),
            body=comment.body,
            created_at=comment.created_at,
        )

    @staticmethod
    def _score(item: PublicationView) -> tuple[int, datetime]:
        score = item.likes_count + item.comments_count * 2 + item.remix_count * 3
        return score, item.created_at
