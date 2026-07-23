from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping


class MediaKind(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    CHAT = "chat"


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
    verified: bool
    defaults: Mapping[str, object] = MappingProxyType({})
    contract: str = "passthrough"
    tier: str = "standard"
    rank: int = 100
    docs_url: str | None = None
    recommended_for: tuple[str, ...] = ()
    api_family: str = "market"

    def supports(self, capability: Capability) -> bool:
        return capability in self.capabilities
