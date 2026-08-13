import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class PublicationScope(StrEnum):
    FEED = "feed"
    PROFILE = "profile"


class PublicationStatus(StrEnum):
    PUBLISHED = "published"
    UNPUBLISHED = "unpublished"


class CommentSurface(StrEnum):
    FEED = "feed"
    PROFILE = "profile"


class FeedSource(StrEnum):
    RECENT = "recent"
    TOP_DAY = "top_day"
    TOP = "top"


class DeepLinkKind(StrEnum):
    POST = "post"
    PROFILE = "profile"
    REMIX = "remix"


@dataclass(frozen=True, slots=True)
class FeedProfile:
    user_id: int
    public_slug: str
    display_name: str
    avatar_url: str | None
    bio: str | None
    username: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class PublicationRecord:
    id: UUID
    generation_id: UUID
    author_user_id: int
    scope: PublicationScope
    status: PublicationStatus
    prompt_visible: bool
    media_kind: str
    model_slug: str
    prompt: str | None
    storage_keys: tuple[str, ...]
    author_slug: str
    author_display_name: str
    author_username: str | None
    author_avatar_url: str | None
    is_derivative: bool
    source_publication_id: UUID | None
    likes_count: int
    comments_count: int
    shares_count: int
    remixes_count: int
    viewer_liked: bool
    published_at: datetime
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class PublicationView:
    id: UUID
    generation_id: UUID
    author_user_id: int
    scope: PublicationScope
    media_kind: str
    model_slug: str
    media_urls: tuple[str, ...]
    prompt: str | None
    prompt_actions_allowed: bool
    is_derivative: bool
    source_publication_id: UUID | None
    likes_count: int
    comments_count: int
    shares_count: int
    remixes_count: int
    viewer_liked: bool
    is_mine: bool
    author_slug: str
    author_display_name: str
    author_username: str | None
    author_avatar_url: str | None
    published_at: datetime


@dataclass(frozen=True, slots=True)
class RemixSource:
    publication: PublicationView
    storage_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FeedComment:
    id: UUID
    publication_id: UUID
    user_id: int
    surface: CommentSurface
    text: str
    author_display_name: str
    author_slug: str
    is_mine: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ShareReceipt:
    publication: PublicationView
    start_param: str


@dataclass(frozen=True, slots=True)
class DeepLinkTarget:
    kind: DeepLinkKind
    publication_id: UUID | None = None
    profile_slug: str | None = None


_PROFILE_SLUG_RE = re.compile(r"^[A-Za-z0-9_-]{6,32}$")


def validate_profile_slug(value: str) -> str:
    slug = value.strip()
    if not _PROFILE_SLUG_RE.fullmatch(slug):
        raise ValueError("Invalid public profile slug")
    return slug


def post_start_param(publication_id: UUID) -> str:
    return f"post_{publication_id.hex}"


def remix_start_param(publication_id: UUID) -> str:
    return f"remix_{publication_id.hex}"


def profile_start_param(public_slug: str) -> str:
    return f"profile_{validate_profile_slug(public_slug)}"


def parse_start_param(value: str | None) -> DeepLinkTarget | None:
    raw = (value or "").strip()
    if not raw:
        return None
    prefix, separator, payload = raw.partition("_")
    if not separator or not payload:
        return None

    if prefix in {DeepLinkKind.POST.value, DeepLinkKind.REMIX.value}:
        try:
            publication_id = UUID(payload)
        except ValueError:
            return None
        return DeepLinkTarget(
            kind=DeepLinkKind(prefix),
            publication_id=publication_id,
        )

    if prefix == DeepLinkKind.PROFILE.value:
        try:
            slug = validate_profile_slug(payload)
        except ValueError:
            return None
        return DeepLinkTarget(kind=DeepLinkKind.PROFILE, profile_slug=slug)

    return None
