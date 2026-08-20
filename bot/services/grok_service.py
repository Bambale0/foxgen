"""Grok Imagine Image-to-Video Service - Kie.ai API"""

import logging
from typing import Dict, List, Optional

from bot.config import config
from bot.services.kie_file_upload_service import kie_file_upload_service
from bot.services.kling_service import KlingService
from bot.services.media_input_utils import image_sources_to_provider_safe_png_urls

logger = logging.getLogger(__name__)

GROK_V15_VIDEO_MODEL = "grok-imagine-video-1-5-preview"
GROK_V15_ASPECT_RATIOS = {
    "1:1",
    "16:9",
    "9:16",
    "4:3",
    "3:4",
    "3:2",
    "2:3",
    "auto",
}
GROK_V15_RESOLUTIONS = {"480p", "720p"}


class GrokService(KlingService):
    """Wrapper for Grok Imagine via Kie.ai"""

    @staticmethod
    def _safe_v15_duration(duration: int) -> int:
        try:
            value = int(duration)
        except (TypeError, ValueError):
            value = 8
        return max(1, min(15, value))

    @staticmethod
    def _safe_v15_aspect_ratio(aspect_ratio: str) -> str:
        value = str(aspect_ratio or "auto").strip()
        return value if value in GROK_V15_ASPECT_RATIOS else "auto"

    @staticmethod
    def _safe_v15_resolution(resolution: str) -> str:
        value = str(resolution or "480p").strip().lower()
        return value if value in GROK_V15_RESOLUTIONS else "480p"

    async def _upload_video_reference_images(
        self, image_urls: List[str], *, max_count: int
    ) -> list[str]:
        safe_image_urls = image_sources_to_provider_safe_png_urls(image_urls[:max_count])
        return [
            url
            for url in await kie_file_upload_service.upload_local_image_sources(
                safe_image_urls
            )
            if isinstance(url, str) and url
        ]

    async def generate_image_to_video(
        self,
        image_urls: List[str],
        prompt: str = "",
        mode: str = "normal",
        duration: int = 6,
        resolution: str = "720p",
        aspect_ratio: str = "16:9",
        nsfw_checker: bool = False,
        callBackUrl: Optional[str] = None,
    ) -> Optional[Dict]:
        """Generate video from images using the legacy Grok Imagine i2v model."""
        uploaded_image_urls = await self._upload_video_reference_images(
            image_urls,
            max_count=7,
        )
        if image_urls and not uploaded_image_urls:
            logger.error("Grok image-to-video create_task aborted: no usable reference images")
            return None
        logger.info(
            "Grok image-to-video payload prepared: refs=%s",
            len(uploaded_image_urls),
        )
        input_data = {
            "image_urls": uploaded_image_urls,
            "prompt": prompt,
            "mode": mode,
            "duration": duration,
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
            "nsfw_checker": nsfw_checker,
        }
        payload = {
            "model": "grok-imagine/image-to-video",
            "input": input_data,
        }
        if callBackUrl:
            payload["callBackUrl"] = callBackUrl
        return await self._kie_post("/api/v1/jobs/createTask", payload)

    async def generate_image_to_video_v15(
        self,
        image_urls: List[str],
        prompt: str = "",
        duration: int = 8,
        resolution: str = "480p",
        aspect_ratio: str = "auto",
        nsfw_checker: bool = False,
        callBackUrl: Optional[str] = None,
    ) -> Optional[Dict]:
        """Generate video from one image using Grok Imagine Video 1.5 Preview."""
        uploaded_image_urls = await self._upload_video_reference_images(
            image_urls,
            max_count=1,
        )
        if image_urls and not uploaded_image_urls:
            logger.error("Grok 1.5 create_task aborted: no usable start image")
            return None

        input_data = {
            "prompt": str(prompt or "").strip()[:4096],
            "image_urls": uploaded_image_urls[:1],
            "aspect_ratio": self._safe_v15_aspect_ratio(aspect_ratio),
            "resolution": self._safe_v15_resolution(resolution),
            "duration": self._safe_v15_duration(duration),
            "nsfw_checker": bool(nsfw_checker),
        }
        payload = {
            "model": GROK_V15_VIDEO_MODEL,
            "input": input_data,
        }
        if callBackUrl:
            payload["callBackUrl"] = callBackUrl
        logger.info(
            "Grok 1.5 video payload prepared: refs=%s duration=%s resolution=%s ratio=%s",
            len(uploaded_image_urls),
            input_data["duration"],
            input_data["resolution"],
            input_data["aspect_ratio"],
        )
        return await self._kie_post("/api/v1/jobs/createTask", payload)

    async def generate_image_to_image(
        self,
        image_urls: List[str],
        prompt: str = "",
        nsfw_checker: bool = False,
        callBackUrl: Optional[str] = None,
    ) -> Optional[Dict]:
        """Generate image from image + prompt using Grok Imagine i2i."""
        if len(image_urls) == 0:
            logger.error("No image_urls provided for Grok i2i")
            return None

        safe_image_urls = image_sources_to_provider_safe_png_urls(image_urls)
        uploaded_image_urls = [
            url
            for url in await kie_file_upload_service.upload_local_image_sources(safe_image_urls)
            if isinstance(url, str) and url
        ]
        if not uploaded_image_urls:
            logger.error("Grok i2i create_task aborted: no usable reference images")
            return None

        image_refs = " ".join(f"@image{i + 1}" for i in range(len(uploaded_image_urls)))
        clean_prompt = str(prompt or "").strip()
        if image_refs and not clean_prompt.startswith("@image"):
            clean_prompt = f"{image_refs} {clean_prompt}".strip()

        input_data = {
            "prompt": clean_prompt,
            "image_urls": uploaded_image_urls,
            # Kie checker must stay disabled for Grok i2i.
            # The model/provider will handle generation rules itself.
            "nsfw_checker": False,
        }
        payload = {
            "model": "grok-imagine/image-to-image",
            "input": input_data,
        }
        if callBackUrl:
            payload["callBackUrl"] = callBackUrl

        logger.info(
            "Grok i2i payload prepared: refs=%s nsfw_checker=false prompt_prefix=%s",
            len(uploaded_image_urls),
            clean_prompt[:80],
        )
        return await self._kie_post("/api/v1/jobs/createTask", payload)


grok_service = GrokService(kie_key=config.KIE_AI_API_KEY)
