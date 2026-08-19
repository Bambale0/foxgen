from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True, slots=True)
class VideoModelCapability:
    key: str
    label: str
    provider: str
    modes: tuple[str, ...] = ()
    durations: tuple[int, ...] = ()
    aspect_ratios: tuple[str, ...] = ()
    resolutions: tuple[str, ...] = ()
    output_formats: tuple[str, ...] = ()
    supports_text: bool = True
    supports_start_image: bool = False
    supports_end_image: bool = False
    supports_reference_images: bool = False
    max_reference_images: int = 0
    supports_reference_videos: bool = False
    max_reference_videos: int = 0
    supports_audio_input: bool = False
    max_reference_audio: int = 0
    supports_generated_audio: bool = False
    supports_return_last_frame: bool = False
    supports_web_search: bool = False
    supports_nsfw_checker: bool = False
    supports_auto_duration: bool = False
    camera_control_via_prompt: bool = False
    supports_negative_prompt: bool = False
    supports_cfg_scale: bool = False
    supports_multi_shot: bool = False
    supports_elements: bool = False
    supports_extend: bool = False
    supports_upscale: bool = False
    supports_repeat: bool = True


VIDEO_MODEL_CAPABILITIES: Mapping[str, VideoModelCapability] = {
    "v3_std": VideoModelCapability(
        key="v3_std", label="Kling 3.0 Standard", provider="kling",
        modes=("std",), durations=tuple(range(3, 16)),
        aspect_ratios=("16:9", "9:16", "1:1"), supports_start_image=True,
        supports_end_image=True, supports_reference_images=True,
        max_reference_images=9, supports_generated_audio=True,
        supports_multi_shot=True, supports_elements=True,
    ),
    "v3_pro": VideoModelCapability(
        key="v3_pro", label="Kling 3.0 Pro", provider="kling",
        modes=("pro",), durations=tuple(range(3, 16)),
        aspect_ratios=("16:9", "9:16", "1:1"), supports_start_image=True,
        supports_end_image=True, supports_reference_images=True,
        max_reference_images=9, supports_generated_audio=True,
        supports_multi_shot=True, supports_elements=True,
    ),
    "v3_4k": VideoModelCapability(
        key="v3_4k", label="Kling 3.0 4K", provider="kling",
        modes=("4k",), durations=tuple(range(3, 16)),
        aspect_ratios=("16:9", "9:16", "1:1"), resolutions=("4k",),
        supports_start_image=True, supports_end_image=True,
        supports_reference_images=True, max_reference_images=9,
        supports_generated_audio=True, supports_multi_shot=True,
        supports_elements=True,
    ),
    "v26_pro": VideoModelCapability(
        key="v26_pro", label="Kling 2.5 Turbo Pro", provider="kling",
        durations=(5, 10), aspect_ratios=("16:9", "9:16", "1:1"),
        supports_start_image=True, supports_negative_prompt=True,
        supports_cfg_scale=True,
    ),
    "avatar_std": VideoModelCapability(
        key="avatar_std", label="Kling AI Avatar Standard", provider="kling",
        supports_text=False, supports_start_image=True, supports_audio_input=True,
    ),
    "avatar_pro": VideoModelCapability(
        key="avatar_pro", label="Kling AI Avatar Pro", provider="kling",
        supports_text=False, supports_start_image=True, supports_audio_input=True,
    ),
    "motion_control_v26": VideoModelCapability(
        key="motion_control_v26", label="Kling 2.6 Motion Control", provider="kling",
        aspect_ratios=("1:1",), resolutions=("720p", "1080p"),
        supports_start_image=True, supports_reference_videos=True,
        max_reference_videos=1,
    ),
    "motion_control_v30": VideoModelCapability(
        key="motion_control_v30", label="Kling 3.0 Motion Control", provider="kling",
        aspect_ratios=("1:1",), resolutions=("720p", "1080p"),
        supports_start_image=True, supports_reference_videos=True,
        max_reference_videos=1,
    ),
    "glow": VideoModelCapability(
        key="glow", label="Kling Glow", provider="kling",
        durations=(5,), aspect_ratios=("16:9", "9:16", "1:1"),
        supports_start_image=True, supports_reference_videos=True,
        max_reference_videos=1,
    ),
    "seedance_2": VideoModelCapability(
        key="seedance_2", label="Seedance 2.0", provider="seedance",
        durations=(5, 10, 15), aspect_ratios=("16:9", "9:16", "1:1"),
        supports_start_image=True, supports_end_image=True,
        supports_reference_images=True, max_reference_images=9,
        supports_reference_videos=True, max_reference_videos=3,
        supports_audio_input=True,
    ),
    "seedance_2_5": VideoModelCapability(
        key="seedance_2_5", label="Seedance 2.5", provider="seedance",
        modes=("text", "first_frame", "first_last", "multimodal"),
        durations=(-1,) + tuple(range(4, 31)),
        aspect_ratios=("1:1", "4:3", "3:4", "16:9", "9:16", "21:9", "adaptive"),
        resolutions=("480p", "720p"),
        output_formats=("mp4", "mov"),
        supports_start_image=True,
        supports_end_image=True,
        supports_reference_images=True,
        max_reference_images=30,
        supports_reference_videos=True,
        max_reference_videos=10,
        supports_audio_input=True,
        max_reference_audio=10,
        supports_generated_audio=True,
        supports_return_last_frame=True,
        supports_web_search=True,
        supports_nsfw_checker=True,
        supports_auto_duration=True,
        camera_control_via_prompt=True,
    ),
    "seedance_2_fast": VideoModelCapability(
        key="seedance_2_fast", label="Seedance 2.0 Fast", provider="seedance",
        durations=(5, 10, 15), aspect_ratios=("16:9", "9:16", "1:1"),
        supports_start_image=True, supports_end_image=True,
        supports_reference_images=True, max_reference_images=9,
        supports_reference_videos=True, max_reference_videos=3,
        supports_audio_input=True,
    ),
    "grok_imagine": VideoModelCapability(
        key="grok_imagine", label="Grok Imagine", provider="grok",
        durations=(6,), aspect_ratios=("16:9", "9:16", "1:1", "3:2", "2:3"),
        supports_start_image=True, supports_reference_images=True,
        max_reference_images=7, supports_extend=True, supports_upscale=True,
    ),
    "grok_imagine_v15": VideoModelCapability(
        key="grok_imagine_v15", label="Grok Imagine 1.5", provider="grok",
        durations=(8,), aspect_ratios=("auto", "16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3"),
        resolutions=("480p", "720p"), supports_start_image=True,
        supports_reference_images=True, max_reference_images=1,
        supports_extend=True, supports_upscale=True,
    ),
    "veo3": VideoModelCapability(
        key="veo3", label="Veo 3.1 Quality", provider="veo",
        durations=(6,), aspect_ratios=("16:9", "9:16", "Auto"),
        resolutions=("720p", "1080p", "4k"), supports_start_image=True,
        supports_end_image=True, supports_reference_images=True,
        max_reference_images=2, supports_generated_audio=True,
        supports_extend=True, supports_upscale=True,
    ),
    "veo3_fast": VideoModelCapability(
        key="veo3_fast", label="Veo 3.1 Fast", provider="veo",
        durations=(6,), aspect_ratios=("16:9", "9:16", "Auto"),
        resolutions=("720p", "1080p", "4k"), supports_start_image=True,
        supports_end_image=True, supports_reference_images=True,
        max_reference_images=3, supports_generated_audio=True,
        supports_extend=True, supports_upscale=True,
    ),
    "veo3_lite": VideoModelCapability(
        key="veo3_lite", label="Veo 3.1 Lite", provider="veo",
        durations=(6,), aspect_ratios=("16:9", "9:16", "Auto"),
        resolutions=("720p", "1080p", "4k"), supports_start_image=True,
        supports_end_image=True, supports_reference_images=True,
        max_reference_images=2, supports_generated_audio=True,
        supports_extend=True, supports_upscale=True,
    ),
    "gemini_omni_video": VideoModelCapability(
        key="gemini_omni_video", label="Gemini Omni Video", provider="gemini_omni",
        durations=(6, 10, 15, 20), aspect_ratios=("16:9", "9:16"),
        resolutions=("720p", "1080p"), supports_start_image=True,
        supports_reference_images=True, max_reference_images=7,
        supports_reference_videos=True, max_reference_videos=1,
        supports_audio_input=True,
    ),
    "gemini_omni_audio": VideoModelCapability(
        key="gemini_omni_audio", label="Gemini Omni Audio", provider="gemini_omni",
        supports_text=False, supports_audio_input=True,
    ),
    "gemini_omni_character": VideoModelCapability(
        key="gemini_omni_character", label="Gemini Omni Character", provider="gemini_omni",
        supports_text=False, supports_start_image=True, supports_audio_input=True,
        supports_reference_images=True, max_reference_images=1,
    ),
}

VIDEO_MODEL_ALIASES: Mapping[str, str] = {
    "kling_v3": "v3_std", "kling_3": "v3_pro", "kling_3_pro": "v3_pro",
    "kling_3_4k": "v3_4k", "kling-3.0-4k": "v3_4k",
    "motion_control": "motion_control_v26",
    "kling-2.6/motion-control": "motion_control_v26",
    "kling-3.0/motion-control": "motion_control_v30",
    "seedance-2.5": "seedance_2_5",
    "seedance_2.5": "seedance_2_5",
    "bytedance/seedance-2-5": "seedance_2_5",
    "gemini_omni": "gemini_omni_video",
}


def normalize_video_model_key(model: str | None) -> str:
    key = str(model or "").strip()
    return VIDEO_MODEL_ALIASES.get(key, key)


def get_video_capability(model: str | None) -> VideoModelCapability | None:
    return VIDEO_MODEL_CAPABILITIES.get(normalize_video_model_key(model))


def require_video_capability(model: str | None) -> VideoModelCapability:
    capability = get_video_capability(model)
    if capability is None:
        raise ValueError(f"Unsupported video model: {model}")
    return capability


def video_model_keys() -> tuple[str, ...]:
    return tuple(VIDEO_MODEL_CAPABILITIES)


def supports_video_reference(model: str | None) -> bool:
    capability = get_video_capability(model)
    return bool(capability and capability.supports_reference_videos)


def max_video_references(model: str | None) -> int:
    capability = get_video_capability(model)
    return capability.max_reference_videos if capability else 0


def max_image_references(model: str | None) -> int:
    capability = get_video_capability(model)
    return capability.max_reference_images if capability else 0
