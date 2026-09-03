from __future__ import annotations

from dataclasses import dataclass

from bot.quality_pricing import SEEDREAM_5_PRO_QUALITY_COSTS
from bot.services.preset_manager import preset_manager


@dataclass(frozen=True)
class InstagramCreatorModel:
    kind: str
    product_key: str
    provider_model: str
    quality: str
    resolution: str
    aspect_ratio: str


INSTAGRAM_PHOTO_MODEL = InstagramCreatorModel(
    kind="photo",
    product_key="seedream_5_pro",
    provider_model="seedream/5-pro-image-to-image",
    quality="high",
    resolution="",
    aspect_ratio="1:1",
)

INSTAGRAM_VIDEO_MODEL = InstagramCreatorModel(
    kind="video",
    product_key="seedance_2_5",
    provider_model="bytedance/seedance-2-5",
    quality="",
    resolution="720p",
    aspect_ratio="9:16",
)


def instagram_photo_cost() -> float:
    """Normal paid price for Instagram Seedream 5 Pro High generations."""
    return float(SEEDREAM_5_PRO_QUALITY_COSTS[INSTAGRAM_PHOTO_MODEL.quality])


def instagram_video_cost(*, duration: int = 5, resolution: str = "720p") -> float:
    """Use the same Seedance 2.5 quality/seconds contract as Telegram."""
    return float(
        preset_manager.get_video_cost_with_quality(
            INSTAGRAM_VIDEO_MODEL.product_key,
            duration=duration,
            quality=resolution,
        )
    )


def normalize_instagram_creation_kind(value: str) -> str:
    normalized = " ".join(str(value or "").casefold().strip().split())
    photo_values = {"фото", "photo", "image", "картинка", "изображение"}
    video_values = {"видео", "video", "ролик", "reel", "reels"}
    if normalized in photo_values:
        return "photo"
    if normalized in video_values:
        return "video"
    return ""
