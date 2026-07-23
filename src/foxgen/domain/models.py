from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping


class MediaKind(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    CHAT = "chat"


class GenerationStatus(StrEnum):
    DRAFT = "draft"
    QUEUED = "queued"
    SUBMITTING = "submitting"
    SUBMITTED = "submitted"
    SUBMISSION_UNKNOWN = "submission_unknown"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVE_GENERATION_STATUSES: frozenset[GenerationStatus] = frozenset(
    {
        GenerationStatus.QUEUED,
        GenerationStatus.SUBMITTING,
        GenerationStatus.SUBMITTED,
        GenerationStatus.SUBMISSION_UNKNOWN,
    }
)


class OutboxStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class MediaAssetStatus(StrEnum):
    PENDING = "pending"
    STORED = "stored"
    FAILED = "failed"


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    DELIVERY_UNKNOWN = "delivery_unknown"
    FAILED = "failed"


class ReservationStatus(StrEnum):
    RESERVED = "reserved"
    CAPTURED = "captured"
    RELEASED = "released"
    REFUNDED = "refunded"


class LedgerEntryType(StrEnum):
    CREDIT = "credit"
    DEBIT = "debit"
    RESERVE = "reserve"
    CAPTURE = "capture"
    RELEASE = "release"
    REFUND = "refund"
    ADJUSTMENT = "adjustment"


class Capability(StrEnum):
    TEXT_TO_IMAGE = "text_to_image"
    IMAGE_TO_IMAGE = "image_to_image"
    IMAGE_EDIT = "image_edit"
    IMAGE_UPSCALE = "image_upscale"
    REMOVE_BACKGROUND = "remove_background"
    TEXT_TO_VIDEO = "text_to_video"
    IMAGE_TO_VIDEO = "image_to_video"
    VIDEO_TO_VIDEO = "video_to_video"
    REFERENCE_TO_VIDEO = "reference_to_video"
    VIDEO_EXTEND = "video_extend"
    VIDEO_UPSCALE = "video_upscale"
    MOTION_CONTROL = "motion_control"
    AVATAR = "avatar"
    TEXT_TO_SPEECH = "text_to_speech"
    MUSIC_GENERATION = "music_generation"
    MUSIC_EDIT = "music_edit"
    AUDIO_SEPARATION = "audio_separation"
    CHAT = "chat"


@dataclass(frozen=True, slots=True)
class ModelSpec:
    slug: str
    provider_model: str
    title: str
    family: str
    media_kind: MediaKind
    capabilities: frozenset[Capability]
    # Legacy catalog-review flag retained for API compatibility. New code must use the
    # explicit statuses below instead of treating one boolean as production readiness.
    verified: bool
    defaults: Mapping[str, object] = MappingProxyType({})
    contract: str = "passthrough"
    tier: str = "standard"
    rank: int = 100
    docs_url: str | None = None
    recommended_for: tuple[str, ...] = ()
    api_family: str = "market"
    provider_id_verified: bool = False
    schema_verified: bool = False
    enabled_for_submission: bool = False
    tested_live: bool = False
    contract_reviewed_at: str | None = None

    def supports(self, capability: Capability) -> bool:
        return capability in self.capabilities

    @property
    def production_ready(self) -> bool:
        return (
            self.provider_id_verified
            and self.schema_verified
            and self.enabled_for_submission
        )
