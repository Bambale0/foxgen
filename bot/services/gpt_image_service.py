import logging
from typing import Dict, List, Optional

from bot.config import config
from bot.services.kling_service import KlingService

logger = logging.getLogger(__name__)


class GPTImageService(KlingService):
    """GPT Image-2 text-to-image via Kie.ai Market API."""

    SUPPORTED_TEXT_MODEL = "gpt-image-2-text-to-image"
    SUPPORTED_IMAGE_MODEL = "gpt-image-2-image-to-image"
    SUPPORTED_ASPECT_RATIOS = {"auto", "1:1", "9:16", "16:9", "4:3", "3:4"}

    async def generate_image(
        self,
        prompt: str,
        *,
        aspect_ratio: str = "auto",
        nsfw_checker: bool = False,
        callBackUrl: Optional[str] = None,
        model: str = SUPPORTED_TEXT_MODEL,
    ) -> Optional[Dict]:
        if model != self.SUPPORTED_TEXT_MODEL:
            logger.error("Unsupported GPT image model: %s", model)
            return None
        if not prompt or not prompt.strip():
            logger.error("GPT Image prompt is required")
            return None
        if len(prompt) > 20000:
            prompt = prompt[:20000]
        if aspect_ratio not in self.SUPPORTED_ASPECT_RATIOS:
            logger.warning(
                "Unsupported GPT aspect ratio %s, fallback to auto", aspect_ratio
            )
            aspect_ratio = "auto"

        payload = {
            "model": model,
            "input": {
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "nsfw_checker": nsfw_checker,
            },
        }
        if callBackUrl:
            payload["callBackUrl"] = callBackUrl
        return await self._kie_post("/api/v1/jobs/createTask", payload)

    async def generate_image_to_image(
        self,
        prompt: str,
        input_urls: List[str],
        *,
        aspect_ratio: str = "auto",
        nsfw_checker: bool = False,
        callBackUrl: Optional[str] = None,
        model: str = SUPPORTED_IMAGE_MODEL,
    ) -> Optional[Dict]:
        if model != self.SUPPORTED_IMAGE_MODEL:
            logger.error("Unsupported GPT image-to-image model: %s", model)
            return None
        if not prompt or not prompt.strip():
            logger.error("GPT Image i2i prompt is required")
            return None
        if len(prompt) > 20000:
            prompt = prompt[:20000]
        if not input_urls:
            logger.error("GPT Image i2i requires at least one input URL")
            return None
        if aspect_ratio not in self.SUPPORTED_ASPECT_RATIOS:
            logger.warning(
                "Unsupported GPT aspect ratio %s, fallback to auto", aspect_ratio
            )
            aspect_ratio = "auto"

        payload = {
            "model": model,
            "input": {
                "prompt": prompt,
                "input_urls": input_urls[:16],
                "aspect_ratio": aspect_ratio,
                "nsfw_checker": nsfw_checker,
            },
        }
        if callBackUrl:
            payload["callBackUrl"] = callBackUrl
        return await self._kie_post("/api/v1/jobs/createTask", payload)


gpt_image_service = GPTImageService(kie_key=config.KIE_AI_API_KEY)
