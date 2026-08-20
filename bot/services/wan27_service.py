"""Wan 2.7 Image service via Kie.ai."""

import logging
from typing import Dict, List, Optional

from bot.config import config
from bot.services.kling_service import KlingService
from bot.services.media_input_utils import image_sources_to_provider_safe_png_urls

logger = logging.getLogger(__name__)


class Wan27Service(KlingService):
    """Wrapper for Wan 2.7 Image / Image Pro through Kie.ai createTask."""

    async def generate_image(
        self,
        *,
        prompt: str,
        aspect_ratio: str = "1:1",
        input_urls: Optional[List[str]] = None,
        n: int = 1,
        resolution: str = "2K",
        pro: bool = True,
        enable_sequential: bool = False,
        thinking_mode: bool = False,
        watermark: bool = False,
        seed: int = 0,
        nsfw_checker: bool = False,
        callBackUrl: Optional[str] = None,
    ) -> Optional[Dict]:
        cleaned_urls = image_sources_to_provider_safe_png_urls(input_urls or [])[:9]
        model = "wan/2-7-image-pro" if pro else "wan/2-7-image"

        # Docs: thinking_mode is only for text-to-image, non-sequential.
        if cleaned_urls or enable_sequential:
            thinking_mode = False

        if enable_sequential:
            n = max(1, min(int(n or 12), 12))
        else:
            n = max(1, min(int(n or 1), 4))

        input_data = {
            "prompt": str(prompt or "").strip()[:5000],
            "aspect_ratio": aspect_ratio,
            "enable_sequential": bool(enable_sequential),
            "n": n,
            "resolution": resolution,
            "thinking_mode": bool(thinking_mode),
            "watermark": bool(watermark),
            "seed": int(seed or 0),
            "nsfw_checker": False,
        }

        if cleaned_urls:
            input_data["input_urls"] = cleaned_urls

        payload = {
            "model": model,
            "input": input_data,
        }
        if callBackUrl:
            payload["callBackUrl"] = callBackUrl

        logger.info(
            "Wan 2.7 payload prepared: model=%s refs=%s ratio=%s n=%s resolution=%s thinking=%s",
            model,
            len(cleaned_urls),
            aspect_ratio,
            n,
            resolution,
            thinking_mode,
        )
        return await self._kie_post("/api/v1/jobs/createTask", payload)


wan27_service = Wan27Service(kie_key=config.KIE_AI_API_KEY)
