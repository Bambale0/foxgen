from bot.instagram_model_contract import (
    INSTAGRAM_PHOTO_MODEL,
    INSTAGRAM_VIDEO_MODEL,
    instagram_photo_cost,
    instagram_video_cost,
    normalize_instagram_creation_kind,
)


def test_instagram_photo_uses_seedream_5_pro_high() -> None:
    assert INSTAGRAM_PHOTO_MODEL.product_key == "seedream_5_pro"
    assert INSTAGRAM_PHOTO_MODEL.provider_model == "seedream/5-pro-image-to-image"
    assert INSTAGRAM_PHOTO_MODEL.quality == "high"
    assert instagram_photo_cost() == 2.5


def test_instagram_video_uses_seedance_2_5() -> None:
    assert INSTAGRAM_VIDEO_MODEL.product_key == "seedance_2_5"
    assert INSTAGRAM_VIDEO_MODEL.provider_model == "bytedance/seedance-2-5"
    assert INSTAGRAM_VIDEO_MODEL.resolution == "720p"
    assert INSTAGRAM_VIDEO_MODEL.aspect_ratio == "9:16"
    assert instagram_video_cost(duration=5) > 0


def test_creation_kind_parser_is_explicit() -> None:
    assert normalize_instagram_creation_kind("Фото") == "photo"
    assert normalize_instagram_creation_kind("image") == "photo"
    assert normalize_instagram_creation_kind("Видео") == "video"
    assert normalize_instagram_creation_kind("reel") == "video"
    assert normalize_instagram_creation_kind("сделай красиво") == ""
