from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    cast,
    delete,
    exists,
    func,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from foxgen.core.errors import ErrorCode
from foxgen.domain.models import GenerationStatus, MediaAssetStatus
from foxgen.feed.domain import (
    CommentSurface,
    FeedComment,
    FeedProfile,
    FeedSource,
    PublicationRecord,
    PublicationScope,
    PublicationStatus,
)
from foxgen.feed.service import FeedError
from foxgen.infra.admin_models import FeedModerationAction
from foxgen.infra.database import Base, Database, Generation, MediaAsset, User


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        autoincrement=False,
    )
    public_slug: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(80))
    avatar_url: Mapped[str | None] = mapped_column(String(1000))
    bio: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Publication(Base):
    __tablename__ = "publications"
    __table_args__ = (
        UniqueConstraint(
            "generation_id",
            "scope",
            name="uq_publications_generation_scope",
        ),
        CheckConstraint(
            "scope IN ('feed', 'profile')",
            name="ck_publications_scope",
        ),
        CheckConstraint(
            "status IN ('published', 'unpublished')",
            name="ck_publications_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    generation_id: Mapped[UUID] = mapped_column(
        ForeignKey("generations.id", ondelete="CASCADE"), index=True
    )
    author_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    scope: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(
        String(16),
        default=PublicationStatus.PUBLISHED.value,
        server_default=PublicationStatus.PUBLISHED.value,
        index=True,
    )
    prompt_visible: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    unpublished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class GenerationDerivative(Base):
    __tablename__ = "generation_derivatives"
    __table_args__ = (
        CheckConstraint("kind IN ('remix')", name="ck_generation_derivatives_kind"),
    )

    derived_generation_id: Mapped[UUID] = mapped_column(
        ForeignKey("generations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_publication_id: Mapped[UUID] = mapped_column(
        ForeignKey("publications.id", ondelete="RESTRICT"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16), default="remix", server_default="remix")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PublicationLike(Base):
    __tablename__ = "publication_likes"
    __table_args__ = (
        UniqueConstraint(
            "publication_id",
            "user_id",
            name="uq_publication_likes_publication_user",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    publication_id: Mapped[UUID] = mapped_column(
        ForeignKey("publications.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PublicationComment(Base):
    __tablename__ = "publication_comments"
    __table_args__ = (
        CheckConstraint(
            "surface IN ('feed', 'profile')",
            name="ck_publication_comments_surface",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    publication_id: Mapped[UUID] = mapped_column(
        ForeignKey("publications.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    surface: Mapped[str] = mapped_column(String(16), index=True)
    text: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class PublicationShareEvent(Base):
    __tablename__ = "publication_share_events"
    __table_args__ = (
        CheckConstraint(
            "surface IN ('feed', 'profile')",
            name="ck_publication_share_events_surface",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    publication_id: Mapped[UUID] = mapped_column(
        ForeignKey("publications.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    surface: Mapped[str] = mapped_column(String(16), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class SqlAlchemyFeedRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def ensure_profile(
        self,
        *,
        user_id: int,
        username: str | None = None,
        display_name: str | None = None,
    ) -> FeedProfile:
        async with self._database.session() as session:
            async with session.begin():
                await self._ensure_user(session, user_id=user_id, username=username)
                existing = await session.get(UserProfile, user_id)
                if existing is None:
                    name = (display_name or username or "Автор").strip()[:80] or "Автор"
                    existing = UserProfile(
                        user_id=user_id,
                        public_slug=f"p{uuid4().hex[:15]}",
                        display_name=name,
                    )
                    session.add(existing)
                    await session.flush()
                elif display_name:
                    existing.display_name = display_name.strip()[:80] or existing.display_name
                await session.flush()
                user = await session.get(User, user_id)
                return self._profile(existing, user)

    async def update_profile(
        self,
        *,
        user_id: int,
        display_name: str | None,
        avatar_url: str | None,
        bio: str | None,
    ) -> FeedProfile:
        await self.ensure_profile(user_id=user_id)
        async with self._database.session() as session:
            async with session.begin():
                profile = await session.get(UserProfile, user_id, with_for_update=True)
                if profile is None:
                    raise FeedError(ErrorCode.TASK_NOT_FOUND, "Профиль не найден.")
                if display_name is not None:
                    profile.display_name = display_name
                profile.avatar_url = avatar_url
                profile.bio = bio
                await session.flush()
                user = await session.get(User, user_id)
                return self._profile(profile, user)

    async def get_profile_by_slug(self, public_slug: str) -> FeedProfile | None:
        async with self._database.session() as session:
            profile = await session.scalar(
                select(UserProfile).where(UserProfile.public_slug == public_slug)
            )
            if profile is None:
                return None
            user = await session.get(User, profile.user_id)
            return self._profile(profile, user)

    async def publish(
        self,
        *,
        user_id: int,
        generation_id: UUID,
        scope: PublicationScope,
        prompt_visible: bool,
    ) -> PublicationRecord:
        await self.ensure_profile(user_id=user_id)
        async with self._database.session() as session:
            async with session.begin():
                generation = await session.get(Generation, generation_id, with_for_update=True)
                if generation is None or generation.user_id != user_id:
                    raise FeedError(ErrorCode.TASK_NOT_FOUND, "Генерация не найдена.")
                if str(generation.status) != GenerationStatus.SUCCEEDED.value:
                    raise FeedError(
                        ErrorCode.VALIDATION,
                        "Публиковать можно только полностью завершённую генерацию.",
                    )

                assets = tuple(
                    (
                        await session.scalars(
                            select(MediaAsset).where(MediaAsset.generation_id == generation_id)
                        )
                    ).all()
                )
                if not assets or any(
                    str(asset.status) != MediaAssetStatus.STORED.value for asset in assets
                ):
                    raise FeedError(
                        ErrorCode.VALIDATION,
                        "Результат ещё не полностью сохранён и не готов к публикации.",
                    )

                derivative = await session.get(GenerationDerivative, generation_id)
                if derivative is not None and scope == PublicationScope.FEED:
                    raise FeedError(
                        ErrorCode.AUTHORIZATION,
                        "Производную/remix-генерацию нельзя публиковать в общую ленту.",
                    )
                effective_prompt_visible = bool(prompt_visible and derivative is None)

                result = await session.execute(
                    pg_insert(Publication)
                    .values(
                        generation_id=generation_id,
                        author_user_id=user_id,
                        scope=scope.value,
                        status=PublicationStatus.PUBLISHED.value,
                        prompt_visible=effective_prompt_visible,
                        published_at=func.now(),
                        unpublished_at=None,
                    )
                    .on_conflict_do_update(
                        index_elements=[Publication.generation_id, Publication.scope],
                        set_={
                            "status": PublicationStatus.PUBLISHED.value,
                            "prompt_visible": effective_prompt_visible,
                            "published_at": func.now(),
                            "unpublished_at": None,
                            "updated_at": func.now(),
                        },
                    )
                    .returning(Publication)
                )
                publication = result.scalar_one()
                await session.flush()
                return await self._record(session, publication, viewer_user_id=user_id)

    async def unpublish(
        self,
        *,
        user_id: int,
        publication_id: UUID,
    ) -> bool:
        async with self._database.session() as session:
            async with session.begin():
                result = await session.execute(
                    update(Publication)
                    .where(
                        Publication.id == publication_id,
                        Publication.author_user_id == user_id,
                        Publication.status == PublicationStatus.PUBLISHED.value,
                    )
                    .values(
                        status=PublicationStatus.UNPUBLISHED.value,
                        unpublished_at=func.now(),
                        updated_at=func.now(),
                    )
                    .returning(Publication.id)
                )
                return result.scalar_one_or_none() is not None

    async def get_publication(
        self,
        *,
        publication_id: UUID,
        viewer_user_id: int,
        include_unpublished_owner: bool = False,
    ) -> PublicationRecord | None:
        async with self._database.session() as session:
            publication = await session.get(Publication, publication_id)
            if publication is None:
                return None
            is_owner = publication.author_user_id == viewer_user_id
            if publication.status != PublicationStatus.PUBLISHED.value and not (
                include_unpublished_owner and is_owner
            ):
                return None
            if not is_owner and await self._is_removed(session, publication.id):
                return None
            return await self._record(session, publication, viewer_user_id=viewer_user_id)

    async def list_feed(
        self,
        *,
        viewer_user_id: int,
        source: FeedSource,
        limit: int,
        offset: int,
    ) -> tuple[PublicationRecord, ...]:
        async with self._database.session() as session:
            likes = self._count_subquery(PublicationLike, PublicationLike.publication_id)
            comments = self._count_subquery(
                PublicationComment,
                PublicationComment.publication_id,
                PublicationComment.surface == PublicationScope.FEED.value,
            )
            shares = self._count_subquery(
                PublicationShareEvent,
                PublicationShareEvent.publication_id,
                PublicationShareEvent.surface == PublicationScope.FEED.value,
            )
            remixes = self._count_subquery(
                GenerationDerivative,
                GenerationDerivative.source_publication_id,
            )
            score = likes * 3 + comments * 2 + shares + remixes * 4
            removed = exists(
                select(FeedModerationAction.id).where(
                    FeedModerationAction.content_id == cast(Publication.id, String),
                    FeedModerationAction.active.is_(True),
                    FeedModerationAction.action.in_(("remove", "hide")),
                )
            )
            statement = (
                select(Publication)
                .join(Generation, Generation.id == Publication.generation_id)
                .where(
                    Publication.scope == PublicationScope.FEED.value,
                    Publication.status == PublicationStatus.PUBLISHED.value,
                    Generation.status == GenerationStatus.SUCCEEDED.value,
                    ~removed,
                )
            )
            if source == FeedSource.TOP_DAY:
                statement = statement.where(
                    Publication.published_at >= datetime.now(timezone.utc) - timedelta(days=1)
                ).order_by(score.desc(), Publication.published_at.desc())
            elif source == FeedSource.TOP:
                statement = statement.order_by(score.desc(), Publication.published_at.desc())
            else:
                statement = statement.order_by(Publication.published_at.desc())
            publications = tuple(
                (await session.scalars(statement.offset(offset).limit(limit))).all()
            )
            return tuple(
                [
                    await self._record(session, item, viewer_user_id=viewer_user_id)
                    for item in publications
                ]
            )

    async def list_profile(
        self,
        *,
        viewer_user_id: int,
        public_slug: str,
        limit: int,
        offset: int,
    ) -> tuple[PublicationRecord, ...]:
        async with self._database.session() as session:
            profile = await session.scalar(
                select(UserProfile).where(UserProfile.public_slug == public_slug)
            )
            if profile is None:
                return ()
            removed = exists(
                select(FeedModerationAction.id).where(
                    FeedModerationAction.content_id == cast(Publication.id, String),
                    FeedModerationAction.active.is_(True),
                    FeedModerationAction.action.in_(("remove", "hide")),
                )
            )
            publications = tuple(
                (
                    await session.scalars(
                        select(Publication)
                        .join(Generation, Generation.id == Publication.generation_id)
                        .where(
                            Publication.author_user_id == profile.user_id,
                            Publication.scope == PublicationScope.PROFILE.value,
                            Publication.status == PublicationStatus.PUBLISHED.value,
                            Generation.status == GenerationStatus.SUCCEEDED.value,
                            ~removed,
                        )
                        .order_by(Publication.published_at.desc())
                        .offset(offset)
                        .limit(limit)
                    )
                ).all()
            )
            return tuple(
                [
                    await self._record(session, item, viewer_user_id=viewer_user_id)
                    for item in publications
                ]
            )

    async def list_user_publications(
        self,
        *,
        viewer_user_id: int,
        owner_user_id: int,
        scope: PublicationScope | None,
        include_unpublished: bool,
        limit: int,
        offset: int,
    ) -> tuple[PublicationRecord, ...]:
        async with self._database.session() as session:
            statement = select(Publication).where(Publication.author_user_id == owner_user_id)
            if scope is not None:
                statement = statement.where(Publication.scope == scope.value)
            if not include_unpublished:
                statement = statement.where(
                    Publication.status == PublicationStatus.PUBLISHED.value
                )
            publications = tuple(
                (
                    await session.scalars(
                        statement.order_by(Publication.published_at.desc())
                        .offset(offset)
                        .limit(limit)
                    )
                ).all()
            )
            return tuple(
                [
                    await self._record(session, item, viewer_user_id=viewer_user_id)
                    for item in publications
                ]
            )

    async def set_like(
        self,
        *,
        user_id: int,
        publication_id: UUID,
        liked: bool,
    ) -> bool:
        async with self._database.session() as session:
            async with session.begin():
                await self._ensure_user(session, user_id=user_id)
                publication = await self._require_published_surface(session, publication_id, None)
                if await self._is_removed(session, publication.id):
                    raise FeedError(ErrorCode.TASK_NOT_FOUND, "Публикация не найдена.")
                if liked:
                    result = await session.execute(
                        pg_insert(PublicationLike)
                        .values(publication_id=publication_id, user_id=user_id)
                        .on_conflict_do_nothing(
                            index_elements=[PublicationLike.publication_id, PublicationLike.user_id]
                        )
                        .returning(PublicationLike.id)
                    )
                    return result.scalar_one_or_none() is not None
                result = await session.execute(
                    delete(PublicationLike)
                    .where(
                        PublicationLike.publication_id == publication_id,
                        PublicationLike.user_id == user_id,
                    )
                    .returning(PublicationLike.id)
                )
                return result.scalar_one_or_none() is not None

    async def list_comments(
        self,
        *,
        publication_id: UUID,
        viewer_user_id: int,
        surface: CommentSurface,
        limit: int,
        offset: int,
    ) -> tuple[FeedComment, ...]:
        async with self._database.session() as session:
            await self._require_published_surface(session, publication_id, surface)
            rows = tuple(
                (
                    await session.scalars(
                        select(PublicationComment)
                        .where(
                            PublicationComment.publication_id == publication_id,
                            PublicationComment.surface == surface.value,
                        )
                        .order_by(PublicationComment.created_at.asc())
                        .offset(offset)
                        .limit(limit)
                    )
                ).all()
            )
            return tuple(
                [
                    await self._comment(session, row, viewer_user_id=viewer_user_id)
                    for row in rows
                ]
            )

    async def add_comment(
        self,
        *,
        publication_id: UUID,
        user_id: int,
        surface: CommentSurface,
        text: str,
    ) -> FeedComment:
        async with self._database.session() as session:
            async with session.begin():
                await self._ensure_user(session, user_id=user_id)
                await self._require_published_surface(session, publication_id, surface)
                comment = PublicationComment(
                    publication_id=publication_id,
                    user_id=user_id,
                    surface=surface.value,
                    text=text,
                )
                session.add(comment)
                await session.flush()
                return await self._comment(session, comment, viewer_user_id=user_id)

    async def record_share(
        self,
        *,
        publication_id: UUID,
        user_id: int,
        surface: CommentSurface,
    ) -> None:
        async with self._database.session() as session:
            async with session.begin():
                await self._ensure_user(session, user_id=user_id)
                await self._require_published_surface(session, publication_id, surface)
                session.add(
                    PublicationShareEvent(
                        publication_id=publication_id,
                        user_id=user_id,
                        surface=surface.value,
                    )
                )

    async def validate_remix_source(
        self,
        session: AsyncSession,
        *,
        source_publication_id: UUID,
    ) -> Publication:
        publication = await session.get(Publication, source_publication_id)
        if publication is None or publication.status != PublicationStatus.PUBLISHED.value:
            raise FeedError(ErrorCode.TASK_NOT_FOUND, "Исходная публикация для remix не найдена.")
        if await self._is_removed(session, publication.id):
            raise FeedError(ErrorCode.TASK_NOT_FOUND, "Исходная публикация для remix недоступна.")
        return publication

    @staticmethod
    async def create_derivative_link(
        session: AsyncSession,
        *,
        generation_id: UUID,
        source_publication_id: UUID,
    ) -> None:
        await session.execute(
            pg_insert(GenerationDerivative)
            .values(
                derived_generation_id=generation_id,
                source_publication_id=source_publication_id,
                kind="remix",
            )
            .on_conflict_do_nothing(index_elements=[GenerationDerivative.derived_generation_id])
        )

    async def _record(
        self,
        session: AsyncSession,
        publication: Publication,
        *,
        viewer_user_id: int,
    ) -> PublicationRecord:
        generation = await session.get(Generation, publication.generation_id)
        if generation is None:
            raise FeedError(ErrorCode.TASK_NOT_FOUND, "Исходная генерация не найдена.")
        profile = await session.get(UserProfile, publication.author_user_id)
        if profile is None:
            raise FeedError(ErrorCode.TASK_NOT_FOUND, "Профиль автора не найден.")
        user = await session.get(User, publication.author_user_id)
        assets = tuple(
            (
                await session.scalars(
                    select(MediaAsset)
                    .where(
                        MediaAsset.generation_id == publication.generation_id,
                        MediaAsset.status == MediaAssetStatus.STORED.value,
                    )
                    .order_by(MediaAsset.created_at.asc())
                )
            ).all()
        )
        derivative = await session.get(GenerationDerivative, publication.generation_id)
        likes_count = await self._count(
            session,
            PublicationLike,
            PublicationLike.publication_id == publication.id,
        )
        comments_count = await self._count(
            session,
            PublicationComment,
            PublicationComment.publication_id == publication.id,
            PublicationComment.surface == publication.scope,
        )
        shares_count = await self._count(
            session,
            PublicationShareEvent,
            PublicationShareEvent.publication_id == publication.id,
            PublicationShareEvent.surface == publication.scope,
        )
        remixes_count = await self._count(
            session,
            GenerationDerivative,
            GenerationDerivative.source_publication_id == publication.id,
        )
        viewer_liked = bool(
            await session.scalar(
                select(
                    exists().where(
                        PublicationLike.publication_id == publication.id,
                        PublicationLike.user_id == viewer_user_id,
                    )
                )
            )
        )
        return PublicationRecord(
            id=publication.id,
            generation_id=publication.generation_id,
            author_user_id=publication.author_user_id,
            scope=PublicationScope(publication.scope),
            status=PublicationStatus(publication.status),
            prompt_visible=publication.prompt_visible,
            media_kind=_enum_value(generation.media_kind),
            model_slug=generation.model_slug,
            prompt=generation.prompt,
            storage_keys=tuple(asset.storage_key for asset in assets),
            author_slug=profile.public_slug,
            author_display_name=profile.display_name,
            author_username=user.username if user is not None else None,
            author_avatar_url=profile.avatar_url,
            is_derivative=derivative is not None,
            source_publication_id=(
                derivative.source_publication_id if derivative is not None else None
            ),
            likes_count=likes_count,
            comments_count=comments_count,
            shares_count=shares_count,
            remixes_count=remixes_count,
            viewer_liked=viewer_liked,
            published_at=publication.published_at,
            created_at=publication.created_at,
            updated_at=publication.updated_at,
        )

    async def _comment(
        self,
        session: AsyncSession,
        comment: PublicationComment,
        *,
        viewer_user_id: int,
    ) -> FeedComment:
        profile = await session.get(UserProfile, comment.user_id)
        if profile is None:
            user = await session.get(User, comment.user_id)
            display = user.username if user is not None and user.username else "Автор"
            profile = UserProfile(
                user_id=comment.user_id,
                public_slug=f"p{uuid4().hex[:15]}",
                display_name=display,
            )
            session.add(profile)
            await session.flush()
        return FeedComment(
            id=comment.id,
            publication_id=comment.publication_id,
            user_id=comment.user_id,
            surface=CommentSurface(comment.surface),
            text=comment.text,
            author_display_name=profile.display_name,
            author_slug=profile.public_slug,
            is_mine=comment.user_id == viewer_user_id,
            created_at=comment.created_at,
        )

    async def _require_published_surface(
        self,
        session: AsyncSession,
        publication_id: UUID,
        surface: CommentSurface | None,
    ) -> Publication:
        publication = await session.get(Publication, publication_id)
        if publication is None or publication.status != PublicationStatus.PUBLISHED.value:
            raise FeedError(ErrorCode.TASK_NOT_FOUND, "Публикация не найдена.")
        if surface is not None and publication.scope != surface.value:
            raise FeedError(
                ErrorCode.VALIDATION,
                "Комментарии и действия привязаны к поверхности публикации.",
            )
        if await self._is_removed(session, publication.id):
            raise FeedError(ErrorCode.TASK_NOT_FOUND, "Публикация недоступна.")
        return publication

    @staticmethod
    async def _ensure_user(
        session: AsyncSession,
        *,
        user_id: int,
        username: str | None = None,
    ) -> None:
        await session.execute(
            pg_insert(User)
            .values(id=user_id, username=username)
            .on_conflict_do_nothing(index_elements=[User.id])
        )
        if username:
            await session.execute(
                update(User).where(User.id == user_id).values(username=username)
            )

    @staticmethod
    async def _count(
        session: AsyncSession,
        model: type[Base],
        *criteria: object,
    ) -> int:
        value = await session.scalar(select(func.count()).select_from(model).where(*criteria))
        return int(value or 0)

    @staticmethod
    def _count_subquery(
        model: type[Base],
        foreign_key: object,
        *criteria: object,
    ) -> object:
        return (
            select(func.count())
            .select_from(model)
            .where(foreign_key == Publication.id, *criteria)  # type: ignore[operator]
            .correlate(Publication)
            .scalar_subquery()
        )

    @staticmethod
    async def _is_removed(session: AsyncSession, publication_id: UUID) -> bool:
        value = await session.scalar(
            select(
                exists().where(
                    FeedModerationAction.content_id == str(publication_id),
                    FeedModerationAction.active.is_(True),
                    FeedModerationAction.action.in_(("remove", "hide")),
                )
            )
        )
        return bool(value)

    @staticmethod
    def _profile(profile: UserProfile, user: User | None) -> FeedProfile:
        return FeedProfile(
            user_id=profile.user_id,
            public_slug=profile.public_slug,
            display_name=profile.display_name,
            avatar_url=profile.avatar_url,
            bio=profile.bio,
            username=user.username if user is not None else None,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )


def _enum_value(value: object) -> str:
    raw = getattr(value, "value", value)
    return str(raw)
