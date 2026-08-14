from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class PublicationScope(StrEnum):
    FEED = "feed"
    PROFILE = "profile"


class FeedSort(StrEnum):
    RECENT = "recent"
    TOP_DAY = "top_day"
    TOP = "top"


@dataclass(frozen=True, slots=True)
class PublicProfileView:
    user_id: int
    slug: str
    display_name: str | None
    bio: str | None


@dataclass(frozen=True, slots=True)
class PublicationMediaView:
    storage_key: str
    content_type: str


@dataclass(frozen=True, slots=True)
class PublicationView:
    id: UUID
    generation_id: UUID
    author: PublicProfileView
    scope: PublicationScope
    model_slug: str
    media_kind: str
    prompt: str | None
    prompt_actions_allowed: bool
    media: tuple[PublicationMediaView, ...]
    likes_count: int
    comments_count: int
    remix_count: int
    liked_by_viewer: bool
    source_publication_id: UUID | None
    created_at: datetime

    @property
    def post_deep_link_payload(self) -> str:
        return f"post_{self.id}"

    @property
    def profile_deep_link_payload(self) -> str:
        return f"profile_{self.author.slug}"

    @property
    def remix_deep_link_payload(self) -> str | None:
        if not self.prompt_actions_allowed:
            return None
        return f"remix_{self.id}"


@dataclass(frozen=True, slots=True)
class PublicationCommentView:
    id: UUID
    publication_id: UUID
    surface: PublicationScope
    author: PublicProfileView
    body: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RemixSourceView:
    publication_id: UUID
    generation_id: UUID
    author_slug: str
    model_slug: str
    media_kind: str
    prompt: str
    media: tuple[PublicationMediaView, ...]
