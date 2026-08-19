"""Live smoke tests for real Kie.ai task creation calls.

These tests intentionally hit production provider APIs and may spend credits.
They are skipped unless BANANO_LIVE_SMOKE=1 is set.
"""

import os
from pathlib import Path
from typing import Awaitable, Callable

from dotenv import load_dotenv
import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]

pytestmark = [pytest.mark.asyncio, pytest.mark.smoke, pytest.mark.live_smoke]

LIVE_FLAG_NAMES = ("BANANO_LIVE_SMOKE", "RUN_LIVE_SMOKE")
LIVE_CASES_ENV = "BANANO_LIVE_SMOKE_CASES"
DEFAULT_CASES = ("kling_3_std", "nano_banana_2")
PUBLIC_IMAGE_URL = (
    "https://file.aiquickdraw.com/custom-page/akr/section-images/"
    "1755256596169mkkwr2ag.png"
)
PUBLIC_AVATAR_IMAGE_URL = (
    "https://file.aiquickdraw.com/custom-page/akr/section-images/"
    "17579268936223zs9l3dt.png"
)
PUBLIC_AVATAR_AUDIO_URL = (
    "https://file.aiquickdraw.com/custom-page/akr/section-images/"
    "17579258340109gghun47.mp3"
)
PUBLIC_MOTION_IMAGE_URL = (
    "https://static.aiquickdraw.com/tools/example/1767694885407_pObJoMcy.png"
)
PUBLIC_MOTION_VIDEO_URL = (
    "https://static.aiquickdraw.com/tools/example/1767525918769_QyvTNib2.mp4"
)


class ApiKey:
    def __init__(self, value: str):
        self.value = value

    def __repr__(self) -> str:
        return "<redacted Kie API key>"


def _is_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _live_smoke_enabled() -> bool:
    return any(_is_truthy(os.getenv(name)) for name in LIVE_FLAG_NAMES)


def _selected_cases() -> set[str]:
    raw = os.getenv(LIVE_CASES_ENV)
    if not raw:
        return set(DEFAULT_CASES)
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _require_case(case_name: str) -> None:
    if not _live_smoke_enabled():
        pytest.skip("set BANANO_LIVE_SMOKE=1 to run real provider smoke tests")

    selected = _selected_cases()
    if "all" not in selected and case_name not in selected:
        pytest.skip(
            f"{case_name} is not selected; set {LIVE_CASES_ENV}={case_name} or all"
        )


@pytest.fixture(scope="session")
def kie_api_key() -> ApiKey:
    if not _live_smoke_enabled():
        pytest.skip("set BANANO_LIVE_SMOKE=1 to run real provider smoke tests")

    # Loading production credentials during collection contaminates the normal
    # unit-test process. Only an explicitly enabled paid smoke test may read it.
    load_dotenv(ROOT_DIR / ".env")
    key = os.getenv("KIE_AI_API_KEY") or os.getenv("NANOBANANA_API_KEY")
    if not key:
        pytest.skip("KIE_AI_API_KEY or NANOBANANA_API_KEY is required")
    return ApiKey(key)


async def _create_kling_3_std(api_key: str) -> dict:
    from bot.services.kling_service import KlingService

    service = KlingService(kie_key=api_key)
    return await service.generate_video(
        prompt="Live smoke test: a simple quiet sunrise over a desk lamp",
        model="v3_std",
        duration=3,
        aspect_ratio="16:9",
        generate_audio=False,
    )


async def _create_kling_3_pro(api_key: str) -> dict:
    from bot.services.kling_service import KlingService

    service = KlingService(kie_key=api_key)
    return await service.generate_video(
        prompt="Live smoke test: a clean cinematic shot of a desk lamp",
        model="v3_pro",
        duration=3,
        aspect_ratio="16:9",
        generate_audio=False,
    )


async def _create_kling_3_i2v(api_key: str) -> dict:
    from bot.services.kling_service import KlingService

    service = KlingService(kie_key=api_key)
    return await service.generate_video(
        prompt="Live smoke test: animate the reference with subtle motion",
        model="v3_std",
        image_url=PUBLIC_IMAGE_URL,
        duration=3,
        aspect_ratio="16:9",
        generate_audio=False,
    )


async def _create_kling_25_turbo(api_key: str) -> dict:
    from bot.services.kling_service import KlingService

    service = KlingService(kie_key=api_key)
    return await service.generate_video(
        prompt="Live smoke test: a minimal paper boat moving on calm water",
        model="v26_pro",
        duration=5,
        aspect_ratio="16:9",
        generate_audio=False,
        cfg_scale=0.5,
    )


async def _create_kling_25_turbo_i2v(api_key: str) -> dict:
    from bot.services.kling_service import KlingService

    service = KlingService(kie_key=api_key)
    return await service.generate_video(
        prompt="Live smoke test: animate the reference with a gentle camera move",
        model="v26_pro",
        image_url=PUBLIC_IMAGE_URL,
        duration=5,
        aspect_ratio="16:9",
        generate_audio=False,
        cfg_scale=0.5,
    )


async def _create_kling_avatar_std(api_key: str) -> dict:
    from bot.services.kling_service import KlingService

    service = KlingService(kie_key=api_key)
    return await service.generate_video(
        prompt="Live smoke test avatar says one short sentence",
        model="avatar_std",
        image_url=PUBLIC_AVATAR_IMAGE_URL,
        video_urls=[PUBLIC_AVATAR_AUDIO_URL],
    )


async def _create_kling_avatar_pro(api_key: str) -> dict:
    from bot.services.kling_service import KlingService

    service = KlingService(kie_key=api_key)
    return await service.generate_video(
        prompt="Live smoke test avatar says one short sentence",
        model="avatar_pro",
        image_url=PUBLIC_AVATAR_IMAGE_URL,
        video_urls=[PUBLIC_AVATAR_AUDIO_URL],
    )


async def _create_kling_motion_26(api_key: str) -> dict:
    from bot.services.kling_service import KlingService

    service = KlingService(kie_key=api_key)
    return await service.generate_video(
        prompt="Live smoke test: apply the sample motion to the sample character",
        model="motion_control_v26",
        image_url=PUBLIC_MOTION_IMAGE_URL,
        video_urls=[PUBLIC_MOTION_VIDEO_URL],
        motion_direction="image",
        motion_mode="720p",
    )


async def _create_kling_motion_30(api_key: str) -> dict:
    from bot.services.kling_service import KlingService

    service = KlingService(kie_key=api_key)
    return await service.generate_video(
        prompt="Live smoke test: apply the sample motion to the sample character",
        model="motion_control_v30",
        image_url=PUBLIC_MOTION_IMAGE_URL,
        video_urls=[PUBLIC_MOTION_VIDEO_URL],
        motion_direction="image",
        motion_mode="720p",
    )


async def _create_kling_glow(api_key: str) -> dict:
    from bot.services.kling_service import KlingService

    service = KlingService(kie_key=api_key)
    return await service.generate_video(
        prompt="Live smoke test: glow preset on the sample character",
        model="glow",
        image_url=PUBLIC_MOTION_IMAGE_URL,
        video_urls=[PUBLIC_MOTION_VIDEO_URL],
    )


async def _create_nano_banana_2(api_key: str) -> dict | None:
    from bot.services.nano_banana_2_service import NanoBanana2Service, ProviderClient

    service = NanoBanana2Service(
        primary_provider=ProviderClient(
            api_key=api_key, base_url="https://api.kie.ai"
        )
    )
    try:
        return await service.generate_image(
            prompt="Live smoke test: small yellow banana sticker on white background",
            aspect_ratio="1:1",
            resolution="1K",
            output_format="png",
        )
    finally:
        await service.close()


async def _create_nano_banana_pro(api_key: str) -> dict | None:
    from bot.services.nano_banana_pro_service import NanoBananaProService, ProviderClient

    service = NanoBananaProService(
        primary_provider=ProviderClient(
            api_key=api_key, base_url="https://api.kie.ai"
        )
    )
    try:
        return await service.generate_image(
            prompt="Live smoke test: clean studio product photo of one banana",
            aspect_ratio="1:1",
            resolution="1K",
            output_format="png",
        )
    finally:
        await service.close()


async def _create_gpt_image_2(api_key: str) -> dict | None:
    from bot.services.gpt_image_service import GPTImageService

    service = GPTImageService(kie_key=api_key)
    return await service.generate_image(
        prompt="Live smoke test: a small red square centered on white",
        aspect_ratio="1:1",
        nsfw_checker=False,
    )


async def _create_gpt_image_2_i2i(api_key: str) -> dict | None:
    from bot.services.gpt_image_service import GPTImageService

    service = GPTImageService(kie_key=api_key)
    return await service.generate_image_to_image(
        prompt="Live smoke test: keep the subject, place it on a white background",
        input_urls=[PUBLIC_IMAGE_URL],
        aspect_ratio="1:1",
        nsfw_checker=False,
    )


async def _create_seedream_45_edit(api_key: str) -> dict | None:
    from bot.services.seedream_service import SeedreamService

    service = SeedreamService(kie_key=api_key)
    return await service.generate_image(
        prompt="Live smoke test: keep the main subject and make the background plain",
        image_urls=[PUBLIC_IMAGE_URL],
        aspect_ratio="1:1",
        quality="basic",
        nsfw_checker=False,
    )


async def _create_seedance_2(api_key: str) -> dict:
    from bot.services.seedance_service import SeedanceService

    service = SeedanceService(kie_key=api_key)
    return await service.generate_video(
        prompt="Live smoke test: a small paper plane glides across a plain room",
        duration=5,
        aspect_ratio="16:9",
        resolution="480p",
        generate_audio=False,
        web_search=False,
    )


async def _create_grok_i2i(api_key: str) -> dict | None:
    from bot.services.grok_service import GrokService

    service = GrokService(kie_key=api_key)
    return await service.generate_image_to_image(
        image_urls=[PUBLIC_IMAGE_URL],
        prompt="Live smoke test: make a clean icon-like version",
        nsfw_checker=False,
    )


async def _create_grok_i2v(api_key: str) -> dict | None:
    from bot.services.grok_service import GrokService

    service = GrokService(kie_key=api_key)
    return await service.generate_image_to_video(
        image_urls=[PUBLIC_IMAGE_URL],
        prompt="Live smoke test: subtle camera movement only",
        mode="normal",
        duration=6,
        resolution="720p",
        aspect_ratio="16:9",
        nsfw_checker=False,
    )


async def _create_grok_i2v_v15(api_key: str) -> dict | None:
    from bot.services.grok_service import GrokService

    service = GrokService(kie_key=api_key)
    return await service.generate_image_to_video_v15(
        image_urls=[PUBLIC_IMAGE_URL],
        prompt="Live smoke test: subtle camera movement only",
        duration=8,
        resolution="480p",
        aspect_ratio="auto",
        nsfw_checker=False,
    )


async def _create_veo3_fast(api_key: str) -> dict | None:
    from bot.services.veo_service import VeoService

    service = VeoService(kie_key=api_key)
    return await service.generate_video(
        prompt="Live smoke test: a pencil rolls gently on a clean table",
        model="veo3_fast",
        duration=4,
        aspect_ratio="16:9",
        enable_translation=False,
        resolution="720p",
    )


async def _create_veo3_lite(api_key: str) -> dict | None:
    from bot.services.veo_service import VeoService

    service = VeoService(kie_key=api_key)
    return await service.generate_video(
        prompt="Live smoke test: a pencil rolls gently on a clean table",
        model="veo3_lite",
        duration=4,
        aspect_ratio="16:9",
        enable_translation=False,
        resolution="720p",
    )


async def _create_veo3_quality(api_key: str) -> dict | None:
    from bot.services.veo_service import VeoService

    service = VeoService(kie_key=api_key)
    return await service.generate_video(
        prompt="Live smoke test: a pencil rolls gently on a clean table",
        model="veo3",
        duration=4,
        aspect_ratio="16:9",
        enable_translation=False,
        resolution="720p",
    )


async def _create_wan27_image(api_key: str) -> dict | None:
    from bot.services.wan27_service import Wan27Service

    service = Wan27Service(kie_key=api_key)
    return await service.generate_image(
        prompt="Live smoke test: a simple clean product icon on white",
        aspect_ratio="1:1",
        n=1,
        resolution="2K",
        pro=False,
        nsfw_checker=False,
    )


async def _create_wan27_image_pro(api_key: str) -> dict | None:
    from bot.services.wan27_service import Wan27Service

    service = Wan27Service(kie_key=api_key)
    return await service.generate_image(
        prompt="Live smoke test: a simple clean product icon on white",
        aspect_ratio="1:1",
        n=1,
        resolution="2K",
        pro=True,
        thinking_mode=False,
        nsfw_checker=False,
    )


async def _create_gemini_omni_video(api_key: str) -> dict:
    from bot.services.gemini_omni_service import GeminiOmniService

    service = GeminiOmniService(kie_key=api_key)
    return await service.generate_video(
        prompt="Live smoke test: a tiny paper boat drifting on a tabletop",
        duration=6,
        aspect_ratio="16:9",
        resolution="720p",
    )


async def _analyze_video_prompt(api_key: str) -> dict:
    from bot.services.video_prompt_service import VideoPromptService

    service = VideoPromptService(api_key=api_key)
    return await service.analyze_video(
        video_url=PUBLIC_MOTION_VIDEO_URL,
        user_note="Live smoke test: describe this clip for generating a similar short video.",
        duration_seconds=5,
        filename="live_smoke_reference.mp4",
    )


LIVE_CASES: dict[str, Callable[[str], Awaitable[dict | None]]] = {
    "kling_3_std": _create_kling_3_std,
    "kling_3_pro": _create_kling_3_pro,
    "kling_3_i2v": _create_kling_3_i2v,
    "kling_25_turbo": _create_kling_25_turbo,
    "kling_25_turbo_i2v": _create_kling_25_turbo_i2v,
    "kling_avatar_std": _create_kling_avatar_std,
    "kling_avatar_pro": _create_kling_avatar_pro,
    "kling_motion_26": _create_kling_motion_26,
    "kling_motion_30": _create_kling_motion_30,
    "kling_glow": _create_kling_glow,
    "nano_banana_2": _create_nano_banana_2,
    "nano_banana_pro": _create_nano_banana_pro,
    "gpt_image_2": _create_gpt_image_2,
    "gpt_image_2_i2i": _create_gpt_image_2_i2i,
    "seedance_2": _create_seedance_2,
    "seedream_45_edit": _create_seedream_45_edit,
    "grok_i2i": _create_grok_i2i,
    "grok_i2v": _create_grok_i2v,
    "grok_i2v_v15": _create_grok_i2v_v15,
    "veo3_fast": _create_veo3_fast,
    "veo3_lite": _create_veo3_lite,
    "veo3_quality": _create_veo3_quality,
    "wan27_image": _create_wan27_image,
    "wan27_image_pro": _create_wan27_image_pro,
    "gemini_omni_video": _create_gemini_omni_video,
}

LIVE_ANALYSIS_CASES: dict[str, Callable[[str], Awaitable[dict | None]]] = {
    "video_prompt_analysis": _analyze_video_prompt,
}


def _task_id_from(result: dict | None) -> str:
    if not isinstance(result, dict):
        return ""

    task_id = result.get("task_id") or result.get("taskId")
    if task_id:
        return str(task_id)

    data = result.get("data")
    if isinstance(data, dict):
        task_id = data.get("taskId") or data.get("task_id")
        if task_id:
            return str(task_id)

    raw = result.get("raw")
    if isinstance(raw, dict):
        data = raw.get("data")
        if isinstance(data, dict):
            task_id = data.get("taskId") or data.get("task_id")
            if task_id:
                return str(task_id)

    return ""


@pytest.mark.parametrize("case_name", sorted(LIVE_CASES))
async def test_kie_create_task_live_smoke(case_name: str, kie_api_key: ApiKey):
    _require_case(case_name)

    result = await LIVE_CASES[case_name](kie_api_key.value)
    task_id = _task_id_from(result)

    assert task_id, f"{case_name} did not return a task id: {result!r}"
    assert not (isinstance(result, dict) and result.get("error")), result


@pytest.mark.parametrize("case_name", sorted(LIVE_ANALYSIS_CASES))
async def test_kie_analysis_live_smoke(case_name: str, kie_api_key: ApiKey):
    _require_case(case_name)

    result = await LIVE_ANALYSIS_CASES[case_name](kie_api_key.value)

    assert isinstance(result, dict), result
    assert not result.get("error"), result
    assert len(str(result.get("prompt_ru") or "")) > 80, result
    assert len(str(result.get("prompt_en") or "")) > 80, result
    assert str(result.get("provider") or "") in {"gpt-5.5", "gpt-5.5-frames"}, result
