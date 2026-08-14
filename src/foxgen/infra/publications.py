from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
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


_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")


class SqlAlchemyPublicationRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def get_profile(self, *, slug: str) -> PublicProfileView | None:
        async with self._database.session() as session:
            profile = await session.scalar(select(PublicProfile).where(PublicProfile.slug == slug))
            return _profile_view(profile) if profile is not None else None

    async def get_own_profile(
        self,
        *,
        user_id: int,
        username: str | None,
    ) -> PublicProfileView:
        async with self._database.session() as session:
            async with session.begin():
                profile = await _ensure_profile(
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
        normalized_name = _optional_text(display_name, maximum=128)
        normalized_bio = _optional_text(bio, maximum=500)
        async with self._database.session() as session:
            async with session.begin():
                await _ensure_user(session, user_id=user_id, username=username)
                existing_slug_owner = await session.scalar(
                    select(PublicProfile.user_id).where(PublicProfile.slug == normalized_slug)
                )
                if existing_slug_owner is not None and existing_slug_owner != user_id:
                    raise SubmissionError(
                        ErrorCode.IDEMPOTENCY_CONFLICT,
                        "Этот публичный адрес профиля уже занят.",
                    )
                await _ensure_profile(session, user_id=user_id, username=username)
                profile = await session.scalar(
                    update(PublicProfile)
                    .where(PublicProfile.user_id == user_id)
                    .values(
                        slug=normalized_slug,
                        display_name=normalized_name,
                        bio=normalized_bio,
                        updated_at=func.now(),
                    )
                    .returning(PublicProfile)
                )
                if profile is None:
                    raise SubmissionError(
                        ErrorCode.PROVIDER_PROTOCOL,
                        "Не удалось обновить публичный профиль.",
                    )
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
                await _ensure_user(session, user_id=user_id, username=username)
                await _ensure_profile(session, user_id=user_id, username=username)
                generation = await session.scalar(
                    select(Generation)
                    .where(Generation.id == generation_id)
                    .with_for_update()
                )
                if generation is None:
                    raise _not_found("Генерация не найдена.")
                if generation.user_id != user_id:
                    raise SubmissionError(
                        ErrorCode.AUTHORIZATION,
                        "Можно публиковать только свои генерации.",
                    )
                if generation.status != GenerationStatus.SUCCEEDED:
                    raise SubmissionError(
                        ErrorCode.VALIDATION,
                        "Публиковать можно только полностью завершённую генерацию.",
                    )

                total_media = int(
                    await session.scalar(
                        select(func.count(MediaAsset.id)).where(
                            MediaAsset.generation_id == generation_id
                        )
                    )
                    or 0
                )
                stored_media = int(
                    await session.scalar(
                        select(func.count(MediaAsset.id)).where(
                            MediaAsset.generation_id == generation_id,
                            MediaAsset.status == MediaAssetStatus.STORED,
                        )
                    )
                    or 0
                )
                if total_media == 0 or stored_media != total_media:
                    raise SubmissionError(
                        ErrorCode.VALIDATION,
                        "Публикация доступна только после сохранения всех медиафайлов.",
                    )

                lineage = await session.get(GenerationLineage, generation_id)
                if scope is PublicationScope.FEED and lineage is not None:
                    raise SubmissionError(
                        ErrorCode.VALIDATION,
                        "Ремикс можно публиковать в профиле, но не в общей ленте.",
                    )

                publication = (
                    await session.execute(
                        pg_insert(Publication)
                        .values(
                            generation_id=generation_id,
                            user_id=user_id,
                            scope=scope.value,
                            active=True,
                        )
                        .on_conflict_do_update(
                            index_elements=[Publication.generation_id, Publication.scope],
                            set_={
                                "active": True,
                                "user_id": user_id,
                                "updated_at": func.now(),
                            },
                        )
                        .returning(Publication)
                    )
                ).scalar_one()

            views = await self._hydrate(session, [publication], viewer_user_id=user_id)
            if not views:
                raise SubmissionError(
                    ErrorCode.PROVIDER_PROTOCOL,
                    "Не удалось подготовить публикацию.",
                )
            return views[0]

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
                        Publication.scope == scope.value,
                    )
                )
                if publication is None:
                    return False
                if publication.user_id != user_id:
                    raise SubmissionError(
                        ErrorCode.AUTHORIZATION,
                        "Нельзя изменить чужую публикацию.",
                    )
                if publication.active:
                    publication.active = False
                    publication.updated_at = datetime.now(timezone.utc)
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
            values = await self._hydrate(session, [publication], viewer_user_id=viewer_user_id)
            return values[0] if values else None

    async def list_feed(
        self,
        *,
        viewer_user_id: int,
        sort: FeedSort,
        limit: int,
        offset: int,
    ) -> list[PublicationView]:
        async with self._database.session() as session:
            statement = select(Publication).where(
                Publication.scope == PublicationScope.FEED.value,
                Publication.active.is_(True),
            )
            if sort is FeedSort.TOP_DAY:
                statement = statement.where(
                    Publication.created_at >= datetime.now(timezone.utc) - timedelta(days=1)
                )
            if sort is FeedSort.RECENT:
                statement = statement.order_by(Publication.created_at.desc(), Publication.id.desc())
            else:
                likes = (
                    select(func.count(PublicationLike.user_id))
                    .where(PublicationLike.publication_id == Publication.id)
                    .correlate(Publication)
                    .scalar_subquery()
                )
                comments = (
                    select(func.count(PublicationComment.id))
                    .where(PublicationComment.publication_id == Publication.id)
                    .correlate(Publication)
                    .scalar_subquery()
                )
                remixes = (
                    select(func.count(GenerationLineage.generation_id))
                    .where(GenerationLineage.source_publication_id == Publication.id)
                    .correlate(Publication)
                    .scalar_subquery()
                )
                score = likes + comments * 2 + remixes * 3
                statement = statement.order_by(
                    score.desc(),
                    Publication.created_at.desc(),
                    Publication.id.desc(),
                )
            publications = list(
                (await session.scalars(statement.limit(limit).offset(offset))).all()
            )
            return await self._hydrate(
                session,
                publications,
                viewer_user_id=viewer_user_id,
            )

    async def list_profile_publications(
        self,
        *,
        slug: str,
        viewer_user_id: int,
        limit: int,
        offset: int,
    ) -> list[PublicationView]:
        async with self._database.session() as session:
            user_id = await session.scalar(
                select(PublicProfile.user_id).where(PublicProfile.slug == slug)
            )
            if user_id is None:
                return []
            publications = list(
                (
                    await session.scalars(
                        select(Publication)
                        .where(
                            Publication.user_id == user_id,
                            Publication.scope == PublicationScope.PROFILE.value,
                            Publication.active.is_(True),
                        )
                        .order_by(Publication.created_at.desc(), Publication.id.desc())
                        .limit(limit)
                        .offset(offset)
                    )
                ).all()
            )
            return await self._hydrate(
                session,
                publications,
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
        async with self._database.session() as session:
            statement = select(Publication).where(Publication.user_id == user_id)
            if scope is not None:
                statement = statement.where(Publication.scope == scope.value)
            publications = list(
                (
                    await session.scalars(
                        statement.order_by(Publication.created_at.desc(), Publication.id.desc())
                        .limit(limit)
                        .offset(offset)
                    )
                ).all()
            )
            return await self._hydrate(session, publications, viewer_user_id=user_id)

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
                await _ensure_user(session, user_id=user_id, username=username)
                publication = await session.scalar(
                    select(Publication).where(
                        Publication.id == publication_id,
                        Publication.active.is_(True),
                    )
                )
                if publication is None:
                    raise _not_found("Публикация не найдена.")
                if liked:
                    await session.execute(
                        pg_insert(PublicationLike)
                        .values(publication_id=publication_id, user_id=user_id)
                        .on_conflict_do_nothing(
                            index_elements=[
                                PublicationLike.publication_id,
                                PublicationLike.user_id,
                            ]
                        )
                    )
                else:
                    await session.execute(
                        delete(PublicationLike).where(
                            PublicationLike.publication_id == publication_id,
                            PublicationLike.user_id == user_id,
                        )
                    )
                count = int(
                    await session.scalar(
                        select(func.count(PublicationLike.user_id)).where(
                            PublicationLike.publication_id == publication_id
                        )
                    )
                    or 0
                )
                return liked, count

    async def add_comment(
        self,
        *,
        publication_id: UUID,
        surface: PublicationScope,
        user_id: int,
        username: str | None,
        body: str,
    ) -> PublicationCommentView:
        normalized = body.strip()
        if not normalized or len(normalized) > 1000:
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "Комментарий должен содержать от 1 до 1000 символов.",
            )
        async with self._database.session() as session:
            async with session.begin():
                await _ensure_user(session, user_id=user_id, username=username)
                profile = await _ensure_profile(session, user_id=user_id, username=username)
                publication = await session.scalar(
                    select(Publication).where(
                        Publication.id == publication_id,
                        Publication.active.is_(True),
                    )
                )
                if publication is None:
                    raise _not_found("Публикация не найдена.")
                if publication.scope != surface.value:
                    raise SubmissionError(
                        ErrorCode.VALIDATION,
                        "Комментарий относится к другой поверхности публикации.",
                    )
                comment = PublicationComment(
                    publication_id=publication_id,
                    surface=surface.value,
                    user_id=user_id,
                    body=normalized,
                )
                session.add(comment)
                await session.flush()
                return PublicationCommentView(
                    id=comment.id,
                    publication_id=publication_id,
                    surface=surface,
                    author=_profile_view(profile),
                    body=comment.body,
                    created_at=comment.created_at,
                )

    async def list_comments(
        self,
        *,
        publication_id: UUID,
        surface: PublicationScope,
        limit: int,
        offset: int,
    ) -> list[PublicationCommentView]:
        async with self._database.session() as session:
            publication = await session.scalar(
                select(Publication).where(
                    Publication.id == publication_id,
                    Publication.active.is_(True),
                )
            )
            if publication is None:
                raise _not_found("Публикация не найдена.")
            if publication.scope != surface.value:
                raise SubmissionError(
                    ErrorCode.VALIDATION,
                    "Комментарии этой поверхности недоступны для публикации.",
                )
            rows = (
                await session.execute(
                    select(PublicationComment, PublicProfile)
                    .join(PublicProfile, PublicProfile.user_id == PublicationComment.user_id)
                    .where(
                        PublicationComment.publication_id == publication_id,
                        PublicationComment.surface == surface.value,
                    )
                    .order_by(PublicationComment.created_at.asc(), PublicationComment.id.asc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            return [
                PublicationCommentView(
                    id=comment.id,
                    publication_id=comment.publication_id,
                    surface=PublicationScope(comment.surface),
                    author=_profile_view(profile),
                    body=comment.body,
                    created_at=comment.created_at,
                )
                for comment, profile in rows
            ]

    async def remix_source(
        self,
        *,
        publication_id: UUID,
    ) -> RemixSourceView:
        async with self._database.session() as session:
            row = (
                await session.execute(
                    select(Publication, Generation, PublicProfile, GenerationLineage)
                    .join(Generation, Generation.id == Publication.generation_id)
                    .join(PublicProfile, PublicProfile.user_id == Publication.user_id)
                    .outerjoin(
                        GenerationLineage,
                        GenerationLineage.generation_id == Generation.id,
                    )
                    .where(
                        Publication.id == publication_id,
                        Publication.active.is_(True),
                    )
                )
            ).one_or_none()
            if row is None:
                raise _not_found("Публикация не найдена.")
            publication, generation, profile, lineage = row
            if lineage is not None:
                raise SubmissionError(
                    ErrorCode.VALIDATION,
                    "Промпт производной публикации скрыт; новый ремикс из неё недоступен.",
                )
            if not generation.prompt:
                raise SubmissionError(
                    ErrorCode.VALIDATION,
                    "У этой публикации нет доступного промпта для ремикса.",
                )
            media_rows = (
                await session.execute(
                    select(MediaAsset.storage_key, MediaAsset.content_type)
                    .where(
                        MediaAsset.generation_id == generation.id,
                        MediaAsset.status == MediaAssetStatus.STORED,
                    )
                    .order_by(MediaAsset.created_at.asc(), MediaAsset.id.asc())
                )
            ).all()
            media = tuple(
                PublicationMediaView(storage_key=storage_key, content_type=content_type)
                for storage_key, content_type in media_rows
            )
            if not media:
                raise SubmissionError(
                    ErrorCode.VALIDATION,
                    "У публикации нет сохранённого медиа для ремикса.",
                )
            return RemixSourceView(
                publication_id=publication.id,
                generation_id=generation.id,
                author_slug=profile.slug,
                model_slug=generation.model_slug,
                media_kind=str(generation.media_kind),
                prompt=generation.prompt,
                media=media,
            )

    async def _hydrate(
        self,
        session: AsyncSession,
        publications: list[Publication],
        *,
        viewer_user_id: int,
    ) -> list[PublicationView]:
        if not publications:
            return []
        publication_ids = [item.id for item in publications]
        generation_ids = [item.generation_id for item in publications]
        user_ids = [item.user_id for item in publications]

        generations = {
            item.id: item
            for item in (
                await session.scalars(select(Generation).where(Generation.id.in_(generation_ids)))
            ).all()
        }
        profiles = {
            item.user_id: item
            for item in (
                await session.scalars(select(PublicProfile).where(PublicProfile.user_id.in_(user_ids)))
            ).all()
        }
        lineages = {
            item.generation_id: item
            for item in (
                await session.scalars(
                    select(GenerationLineage).where(
                        GenerationLineage.generation_id.in_(generation_ids)
                    )
                )
            ).all()
        }
        media_by_generation: dict[UUID, list[PublicationMediaView]] = defaultdict(list)
        for generation_id, storage_key, content_type in (
            await session.execute(
                select(
                    MediaAsset.generation_id,
                    MediaAsset.storage_key,
                    MediaAsset.content_type,
                )
                .where(
                    MediaAsset.generation_id.in_(generation_ids),
                    MediaAsset.status == MediaAssetStatus.STORED,
                )
                .order_by(MediaAsset.created_at.asc(), MediaAsset.id.asc())
            )
        ).all():
            media_by_generation[generation_id].append(
                PublicationMediaView(storage_key=storage_key, content_type=content_type)
            )

        like_counts = {
            publication_id: int(count)
            for publication_id, count in (
                await session.execute(
                    select(PublicationLike.publication_id, func.count(PublicationLike.user_id))
                    .where(PublicationLike.publication_id.in_(publication_ids))
                    .group_by(PublicationLike.publication_id)
                )
            ).all()
        }
        comment_counts = {
            publication_id: int(count)
            for publication_id, count in (
                await session.execute(
                    select(PublicationComment.publication_id, func.count(PublicationComment.id))
                    .where(PublicationComment.publication_id.in_(publication_ids))
                    .group_by(PublicationComment.publication_id)
                )
            ).all()
        }
        remix_counts = {
            publication_id: int(count)
            for publication_id, count in (
                await session.execute(
                    select(
                        GenerationLineage.source_publication_id,
                        func.count(GenerationLineage.generation_id),
                    )
                    .where(GenerationLineage.source_publication_id.in_(publication_ids))
                    .group_by(GenerationLineage.source_publication_id)
                )
            ).all()
        }
        viewer_likes = set(
            (
                await session.scalars(
                    select(PublicationLike.publication_id).where(
                        PublicationLike.publication_id.in_(publication_ids),
                        PublicationLike.user_id == viewer_user_id,
                    )
                )
            ).all()
        )

        values: list[PublicationView] = []
        for publication in publications:
            generation = generations.get(publication.generation_id)
            profile = profiles.get(publication.user_id)
            media = tuple(media_by_generation.get(publication.generation_id, []))
            if generation is None or profile is None or not media:
                continue
            lineage = lineages.get(generation.id)
            values.append(
                PublicationView(
                    id=publication.id,
                    generation_id=generation.id,
                    author=_profile_view(profile),
                    scope=PublicationScope(publication.scope),
                    active=publication.active,
                    model_slug=generation.model_slug,
                    media_kind=str(generation.media_kind),
                    prompt=generation.prompt if lineage is None else None,
                    prompt_actions_allowed=lineage is None,
                    media=media,
                    likes_count=like_counts.get(publication.id, 0),
                    comments_count=comment_counts.get(publication.id, 0),
                    remix_count=remix_counts.get(publication.id, 0),
                    liked_by_viewer=publication.id in viewer_likes,
                    source_publication_id=(
                        lineage.source_publication_id if lineage is not None else None
                    ),
                    created_at=publication.created_at,
                )
            )
        return values


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


async def _ensure_profile(
    session: AsyncSession,
    *,
    user_id: int,
    username: str | None,
) -> PublicProfile:
    await _ensure_user(session, user_id=user_id, username=username)
    await session.execute(
        pg_insert(PublicProfile)
        .values(user_id=user_id, slug=f"user-{user_id}")
        .on_conflict_do_nothing(index_elements=[PublicProfile.user_id])
    )
    profile = await session.get(PublicProfile, user_id)
    if profile is None:
        raise SubmissionError(
            ErrorCode.PROVIDER_PROTOCOL,
            "Не удалось подготовить публичный профиль.",
        )
    return profile


def _profile_view(profile: PublicProfile) -> PublicProfileView:
    return PublicProfileView(
        user_id=profile.user_id,
        slug=profile.slug,
        display_name=profile.display_name,
        bio=profile.bio,
    )


def _normalize_slug(value: str) -> str:
    normalized = value.strip().lower()
    if not _SLUG_RE.fullmatch(normalized):
        raise SubmissionError(
            ErrorCode.VALIDATION,
            "Адрес профиля: 3–64 символа, только a-z, 0-9, _ и -.",
        )
    return normalized


def _optional_text(value: str | None, *, maximum: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > maximum:
        raise SubmissionError(
            ErrorCode.VALIDATION,
            f"Текст длиннее допустимых {maximum} символов.",
        )
    return normalized


def _not_found(message: str) -> SubmissionError:
    return SubmissionError(ErrorCode.TASK_NOT_FOUND, message)
