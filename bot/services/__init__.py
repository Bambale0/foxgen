#!/usr/bin/env python3
# ruff: noqa: I001

"""
Services for the Telegram bot.
"""

import logging
import os

from bot.config import config

logger = logging.getLogger(__name__)

# Legacy APIYI routing stays disabled for Nano Banana 2. This feature branch
# explicitly owns provider selection below: Kie primary -> Nexus fallback.
config.NANOBANANA2_FALLBACK_API_KEY = ""
config.NANOBANANA2_FALLBACK_BASE_URL = ""

from .cryptobot_service import CryptoBotService, cryptobot_service
from .gpt_image_service import GPTImageService, gpt_image_service
from .gemini_omni_service import GeminiOmniService, gemini_omni_service
from .kling_service import KlingService, kling_service
from .kie_market_service import KieMarketService, kie_market_service
from .nano_banana_2_service import NanoBanana2Service, nano_banana_2_service
from .nano_banana_pro_service import NanoBananaProService, nano_banana_pro_service
from .nexus_image_provider import NexusImageProvider
from .seedream_service import SeedreamService, seedream_service
from .veo_service import VeoService, veo_service
from .photo_prompt_vk_compat import install_vk_photo_prompt_instructions


def _configure_nexus_nanobanana_routing() -> None:
    """Keep Kie.ai primary and use Nexus only as Nano Banana 2/Pro fallback.

    Nano Banana 2 Lite is intentionally untouched and keeps its dedicated Kie
    Market route inside NanoBanana2Service.
    """

    nexus_api_key = os.getenv("NEXUS_API_KEY", "").strip()
    nexus_base_url = os.getenv("NEXUS_API_BASE_URL", "https://nexusapi.dev").strip().rstrip("/")
    try:
        timeout_seconds = max(30, int(os.getenv("NEXUS_API_TIMEOUT_SECONDS", "180")))
    except ValueError:
        timeout_seconds = 180
    try:
        poll_interval_seconds = max(0.5, float(os.getenv("NEXUS_API_POLL_INTERVAL_SECONDS", "1")))
    except ValueError:
        poll_interval_seconds = 1.0

    # Module-level services may already carry the old Nexus-primary wiring.
    # Preserve the known Kie client and make it primary again.
    banana2_kie = nano_banana_2_service.primary_provider
    if isinstance(banana2_kie, NexusImageProvider):
        banana2_kie = nano_banana_2_service.fallback_provider

    banana_pro_kie = nano_banana_pro_service.primary_provider
    if isinstance(banana_pro_kie, NexusImageProvider):
        banana_pro_kie = nano_banana_pro_service.fallback_provider

    if banana2_kie is None or banana_pro_kie is None:
        raise RuntimeError("Kie.ai Nano Banana provider wiring is unavailable")

    nano_banana_2_service.primary_provider = banana2_kie
    nano_banana_pro_service.primary_provider = banana_pro_kie

    if not nexus_api_key:
        nano_banana_2_service.fallback_provider = None
        nano_banana_pro_service.fallback_provider = None
        logger.warning(
            "NEXUS_API_KEY is not configured; Nano Banana 2/Pro use Kie.ai only"
        )
        return

    nano_banana_2_service.fallback_provider = NexusImageProvider(
        api_key=nexus_api_key,
        model_name="nano-banana-2",
        base_url=nexus_base_url,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        max_references=8,
    )
    nano_banana_pro_service.fallback_provider = NexusImageProvider(
        api_key=nexus_api_key,
        model_name="nano-banana-pro",
        base_url=nexus_base_url,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        max_references=8,
    )

    logger.info(
        "Nano Banana routing: Kie.ai primary (2 + Pro), Nexus fallback; Lite unchanged"
    )


_configure_nexus_nanobanana_routing()

# Keep Telegram photo analysis aligned with the prompt that produces the best
# results in the VK bot. The patch preserves Telegram's structured JSON output,
# voice mode and provider fallback chain.
install_vk_photo_prompt_instructions()

__all__ = [
    "CryptoBotService",
    "GPTImageService",
    "GeminiOmniService",
    "KieMarketService",
    "KlingService",
    "NanoBanana2Service",
    "NanoBananaProService",
    "NexusImageProvider",
    "SeedreamService",
    "VeoService",
    "cryptobot_service",
    "gemini_omni_service",
    "gpt_image_service",
    "kie_market_service",
    "kling_service",
    "nano_banana_2_service",
    "nano_banana_pro_service",
    "seedream_service",
    "veo_service",
]
