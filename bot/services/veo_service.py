"""Veo 3.1 service via Kie.ai API."""

import json
import logging
import re
from typing import Dict, List, Optional

from bot.config import config
from bot.services.kling_service import KlingService

logger = logging.getLogger(__name__)

VEO_SUPPORTED_DURATIONS = (4, 6, 8)


def _normalize_veo_duration(duration: int) -> int:
    value = int(duration)
    if value in VEO_SUPPORTED_DURATIONS:
        return value
    return min(VEO_SUPPORTED_DURATIONS, key=lambda item: (abs(item - value), item))


class VeoService(KlingService):
    """Wrapper for Veo 3.1 endpoints hosted by Kie.ai."""

    async def generate_video(
        self,
        prompt: str,
        model: str = "veo3_fast",
        duration: int = 8,
        generation_type: Optional[str] = None,
        image_urls: Optional[List[str]] = None,
        aspect_ratio: str = "16:9",
        enable_translation: bool = True,
        watermark: Optional[str] = None,
        resolution: str = "720p",
        seeds: Optional[int] = None,
        callBackUrl: Optional[str] = None,
    ) -> Optional[Dict]:
        payload = {
            "prompt": prompt,
            "model": model,
            "duration": _normalize_veo_duration(duration),
            "aspect_ratio": aspect_ratio,
            "enableTranslation": enable_translation,
            "resolution": resolution,
        }
        if generation_type:
            payload["generationType"] = generation_type
        if image_urls:
            payload["imageUrls"] = image_urls
        if watermark:
            payload["watermark"] = watermark
        if seeds is not None:
            payload["seeds"] = seeds
        if callBackUrl:
            payload["callBackUrl"] = callBackUrl
        return await self._kie_post("/api/v1/veo/generate", payload)

    async def extend_video(
        self,
        task_id: str,
        prompt: str,
        model: str = "fast",
        seeds: Optional[int] = None,
        watermark: Optional[str] = None,
        callBackUrl: Optional[str] = None,
    ) -> Optional[Dict]:
        payload = {
            "taskId": task_id,
            "prompt": prompt,
            "model": model,
        }
        if seeds is not None:
            payload["seeds"] = seeds
        if watermark:
            payload["watermark"] = watermark
        if callBackUrl:
            payload["callBackUrl"] = callBackUrl
        return await self._kie_post("/api/v1/veo/extend", payload)

    async def get_video_details(self, task_id: str) -> Optional[Dict]:
        return await self._kie_get(
            "/api/v1/veo/record-info", params={"taskId": task_id}
        )

    async def get_1080p_video(self, task_id: str, index: int = 0) -> Optional[Dict]:
        return await self._kie_get(
            "/api/v1/veo/get-1080p-video",
            params={"taskId": task_id, "index": index},
        )

    async def get_4k_video(
        self, task_id: str, index: int = 0, callBackUrl: Optional[str] = None
    ) -> Optional[Dict]:
        payload = {
            "taskId": task_id,
            "index": index,
        }
        if callBackUrl:
            payload["callBackUrl"] = callBackUrl
        return await self._kie_post("/api/v1/veo/get-4k-video", payload)

    @staticmethod
    def extract_result_urls(payload: Dict) -> List[str]:
        """Normalize Veo callback/detail result URLs into a plain list."""
        if not isinstance(payload, dict):
            return []

        candidates = []
        data = payload.get("data", payload)
        response = data.get("response") if isinstance(data, dict) else None
        info = data.get("info") if isinstance(data, dict) else None

        for key in ("resultUrls", "fullResultUrls", "originUrls"):
            if isinstance(data, dict):
                candidates.append(data.get(key))
            if isinstance(response, dict):
                candidates.append(response.get(key))
            if isinstance(info, dict):
                candidates.append(info.get(key))

        urls: List[str] = []
        for value in candidates:
            if not value:
                continue
            if isinstance(value, list):
                urls.extend([str(item) for item in value if item])
                continue
            if isinstance(value, str):
                value = value.strip()
                parsed = None
                try:
                    parsed = json.loads(value)
                except Exception:
                    parsed = None
                if isinstance(parsed, list):
                    urls.extend([str(item) for item in parsed if item])
                elif value.startswith("http"):
                    urls.append(value)
                else:
                    urls.extend(re.findall(r"https?://[^\s,\]\"']+", value))

        return urls


veo_service = VeoService(kie_key=config.KIE_AI_API_KEY)
