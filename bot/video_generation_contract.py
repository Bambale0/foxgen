from __future__ import annotations

from typing import Any

from bot.model_capabilities import get_video_capability, normalize_video_model_key
from bot.video_reference_policy import normalize_reference_urls


VIDEO_REQUEST_KEYS = (
    "source",
    "generation_type",
    "v_model",
    "v_type",
    "v_duration",
    "v_ratio",
    "v_mode",
    "user_prompt",
    "v_image_url",
    "v_end_image_url",
    "reference_images",
    "v_reference_videos",
    "v_reference_audio",
    "avatar_audio_url",
    "audio_url",
    "motion_quality",
    "motion_direction",
    "v_orientation",
    "kling_negative_prompt",
    "kling_cfg_scale",
    "kling_sound",
    "kling_multi_shots",
    "kling_multi_prompt",
    "kling_elements",
    "grok_mode",
    "grok_resolution",
    "veo_generation_type",
    "veo_translation",
    "veo_resolution",
    "veo_seed",
    "veo_watermark",
    "omni_resolution",
    "omni_seed",
    "omni_audio_ids",
    "omni_character_ids",
    "omni_base_voice",
    "omni_voice_name",
    "omni_voice_description",
    "omni_example_dialogue",
    "omni_character_name",
    "omni_character_audio_ids",
)


def _clean_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [item for item in value if item not in (None, "")]
    return [value]


def normalize_video_request(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = dict(payload or {})
    model = normalize_video_model_key(source.get("v_model") or source.get("model"))
    capability = get_video_capability(model)

    normalized: dict[str, Any] = {
        key: source[key]
        for key in VIDEO_REQUEST_KEYS
        if key in source and source[key] is not None
    }
    normalized["generation_type"] = "video"
    normalized["v_model"] = model
    normalized["user_prompt"] = str(
        source.get("user_prompt") or source.get("prompt") or ""
    ).strip()

    try:
        duration = int(source.get("v_duration") or source.get("duration") or 5)
    except (TypeError, ValueError):
        duration = 5
    if capability and capability.durations:
        duration = min(capability.durations, key=lambda value: abs(value - duration))
    normalized["v_duration"] = duration

    ratio = str(source.get("v_ratio") or source.get("aspect_ratio") or "16:9")
    if capability and capability.aspect_ratios and ratio not in capability.aspect_ratios:
        ratio = capability.aspect_ratios[0]
    normalized["v_ratio"] = ratio

    image_limit = capability.max_reference_images if capability else 0
    video_limit = capability.max_reference_videos if capability else 0
    normalized["reference_images"] = normalize_reference_urls(
        _clean_list(source.get("reference_images")), max_count=image_limit
    ) if image_limit else []
    normalized["v_reference_videos"] = normalize_reference_urls(
        _clean_list(source.get("v_reference_videos") or source.get("video_references")),
        max_count=video_limit,
    ) if video_limit else []
    normalized["v_reference_audio"] = normalize_reference_urls(
        _clean_list(source.get("v_reference_audio") or source.get("audio_references")),
        max_count=1,
    )

    return normalized


def validate_video_request(payload: dict[str, Any] | None) -> list[str]:
    source = dict(payload or {})
    model = normalize_video_model_key(source.get("v_model") or source.get("model"))
    capability = get_video_capability(model)
    errors: list[str] = []
    if capability is None:
        return [f"Unsupported video model: {model}"]

    raw_images = _clean_list(source.get("reference_images"))
    raw_videos = _clean_list(source.get("v_reference_videos") or source.get("video_references"))
    raw_audio = _clean_list(source.get("v_reference_audio") or source.get("audio_references"))
    if len(raw_images) > capability.max_reference_images:
        errors.append(f"Too many image references: {len(raw_images)} > {capability.max_reference_images}")
    if len(raw_videos) > capability.max_reference_videos:
        errors.append(f"Too many video references: {len(raw_videos)} > {capability.max_reference_videos}")
    if raw_audio and not capability.supports_audio_input:
        errors.append(f"Model {model} does not support audio input")
    return errors


def build_repeat_video_state(
    request_data: dict[str, Any] | None,
    *,
    include_private_media: bool,
) -> dict[str, Any]:
    restored = normalize_video_request(request_data)
    if not include_private_media:
        for key in (
            "v_image_url",
            "v_end_image_url",
            "reference_images",
            "v_reference_videos",
            "v_reference_audio",
            "avatar_audio_url",
            "audio_url",
        ):
            restored.pop(key, None)
        restored["reference_images"] = []
        restored["v_reference_videos"] = []
        restored["v_reference_audio"] = []
    restored["generation_type"] = "video"
    restored["video_flow_step"] = "review"
    return restored
