from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping


class ImageReferenceMode(StrEnum):
    OPTIONAL = "optional"
    REQUIRED = "required"
    NONE = "none"


class VideoGenerationType(StrEnum):
    TEXT = "text"
    FIRST_FRAME = "first_frame"
    FIRST_LAST = "first_last"
    REFERENCES = "references"


@dataclass(frozen=True, slots=True)
class ImageModelCapability:
    key: str
    title: str
    summary: str
    text_slug: str
    edit_slug: str | None
    reference_mode: ImageReferenceMode
    max_references: int
    aspect_ratios: tuple[str, ...]
    resolutions: tuple[str, ...] = ()
    qualities: tuple[str, ...] = ()
    output_formats: tuple[str, ...] = ("png",)
    default_aspect_ratio: str = "1:1"
    default_resolution: str | None = None
    default_quality: str | None = None
    default_output_format: str = "png"

    @property
    def supports_references(self) -> bool:
        return self.reference_mode != ImageReferenceMode.NONE and self.max_references > 0

    def submission_slug(self, *, has_references: bool) -> str:
        if has_references:
            if not self.supports_references or self.edit_slug is None:
                raise ValueError(f"Model {self.key} does not accept image references")
            return self.edit_slug
        return self.text_slug


@dataclass(frozen=True, slots=True)
class VideoModelCapability:
    key: str
    title: str
    summary: str
    slug: str
    generation_types: tuple[VideoGenerationType, ...]
    aspect_ratios: tuple[str, ...]
    durations: tuple[int, ...]
    resolutions: tuple[str, ...]
    max_reference_images: int = 0
    max_reference_videos: int = 0
    max_reference_audio: int = 0
    supports_generated_audio: bool = False
    supports_return_last_frame: bool = False
    supports_web_search: bool = False
    default_aspect_ratio: str = "16:9"
    default_duration: int = 5
    default_resolution: str = "720p"

    def supports_type(self, generation_type: VideoGenerationType) -> bool:
        return generation_type in self.generation_types


IMAGE_MODELS: Mapping[str, ImageModelCapability] = {
    "seedream-5-pro": ImageModelCapability(
        key="seedream-5-pro",
        title="Seedream 5 Pro",
        summary="максимальное качество, текст и точное редактирование",
        text_slug="seedream-5-pro",
        edit_slug="seedream-5-pro-edit",
        reference_mode=ImageReferenceMode.OPTIONAL,
        max_references=10,
        aspect_ratios=("1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"),
        qualities=("basic", "high"),
        output_formats=("png", "jpg"),
        default_quality="basic",
    ),
    "nano-banana-2": ImageModelCapability(
        key="nano-banana-2",
        title="Nano Banana 2",
        summary="быстро, универсально, до 14 референсов",
        text_slug="nano-banana-2",
        edit_slug="nano-banana-2",
        reference_mode=ImageReferenceMode.OPTIONAL,
        max_references=14,
        aspect_ratios=("auto", "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"),
        resolutions=("1K", "2K", "4K"),
        output_formats=("png", "jpg"),
        default_aspect_ratio="auto",
        default_resolution="1K",
    ),
    "nano-banana-pro": ImageModelCapability(
        key="nano-banana-pro",
        title="Nano Banana Pro",
        summary="сложные композиции и консистентность",
        text_slug="nano-banana-pro",
        edit_slug="nano-banana-pro",
        reference_mode=ImageReferenceMode.OPTIONAL,
        max_references=14,
        aspect_ratios=("auto", "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"),
        resolutions=("1K", "2K", "4K"),
        output_formats=("png", "jpg"),
        default_aspect_ratio="auto",
        default_resolution="1K",
    ),
}


VIDEO_MODELS: Mapping[str, VideoModelCapability] = {
    "seedance-2": VideoModelCapability(
        key="seedance-2",
        title="Seedance 2",
        summary="мультимодальные референсы, звук и до 15 секунд",
        slug="seedance-2",
        generation_types=(
            VideoGenerationType.TEXT,
            VideoGenerationType.FIRST_FRAME,
            VideoGenerationType.FIRST_LAST,
            VideoGenerationType.REFERENCES,
        ),
        aspect_ratios=("16:9", "9:16", "1:1"),
        durations=(5, 10, 15),
        resolutions=("720p",),
        max_reference_images=6,
        max_reference_videos=3,
        max_reference_audio=3,
        supports_generated_audio=True,
        supports_return_last_frame=True,
        supports_web_search=True,
    ),
    "seedance-2-mini": VideoModelCapability(
        key="seedance-2-mini",
        title="Seedance 2 Mini",
        summary="быстрее и дешевле с теми же основными сценариями",
        slug="seedance-2-mini",
        generation_types=(
            VideoGenerationType.TEXT,
            VideoGenerationType.FIRST_FRAME,
            VideoGenerationType.FIRST_LAST,
            VideoGenerationType.REFERENCES,
        ),
        aspect_ratios=("16:9", "9:16", "1:1"),
        durations=(5, 10, 15),
        resolutions=("720p",),
        max_reference_images=6,
        max_reference_videos=3,
        max_reference_audio=3,
        supports_generated_audio=True,
        supports_return_last_frame=True,
        supports_web_search=True,
    ),
}


DEDICATED_PRODUCT_SLUGS: frozenset[str] = frozenset({"elevenlabs-turbo-2-5"})


def image_model(key: str) -> ImageModelCapability:
    try:
        return IMAGE_MODELS[key]
    except KeyError as exc:
        raise ValueError(f"Unsupported image wizard model: {key}") from exc


def video_model(key: str) -> VideoModelCapability:
    try:
        return VIDEO_MODELS[key]
    except KeyError as exc:
        raise ValueError(f"Unsupported video wizard model: {key}") from exc


def wizard_submission_slugs() -> frozenset[str]:
    """Return every paid submission slug covered by a Telegram product flow."""

    values: set[str] = set(DEDICATED_PRODUCT_SLUGS)
    for item in IMAGE_MODELS.values():
        values.add(item.text_slug)
        if item.edit_slug is not None:
            values.add(item.edit_slug)
    values.update(item.slug for item in VIDEO_MODELS.values())
    return frozenset(values)
