import logging
import base64
from typing import Dict, List, Optional

import aiohttp

from bot.config import config
from bot.services.media_input_utils import (
    image_sources_to_data_uris,
    image_sources_to_supported_image_urls,
    is_local_upload_source,
)
from bot.services.kie_file_upload_service import kie_file_upload_service
from bot.services.nexus_image_provider import NexusImageProvider

logger = logging.getLogger(__name__)
MAX_IMAGE_INPUTS = 8
RESOLUTION_ALIASES = {
    "BASIC": "2K",
    "HIGH": "4K",
    "1K": "1K",
    "2K": "2K",
    "4K": "4K",
}


def _extract_image_bytes_from_gemini_response(
    response: Dict,
) -> tuple[Optional[bytes], Dict[str, int]]:
    candidates = response.get("candidates", [])
    if not isinstance(candidates, list):
        return None, {"candidates": 0, "parts": 0, "text_parts": 0, "thought_parts": 0}

    stats = {
        "candidates": len(candidates),
        "parts": 0,
        "text_parts": 0,
        "thought_parts": 0,
    }

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content", {})
        if not isinstance(content, dict):
            continue
        parts = content.get("parts", [])
        if not isinstance(parts, list):
            continue

        for part in parts:
            if not isinstance(part, dict):
                continue
            stats["parts"] += 1
            if part.get("text"):
                stats["text_parts"] += 1
            if part.get("thought"):
                stats["thought_parts"] += 1

            inline = part.get("inlineData") or part.get("inline_data")
            if not isinstance(inline, dict):
                continue
            img_b64 = inline.get("data")
            if not img_b64:
                continue
            try:
                return base64.b64decode(img_b64), stats
            except Exception:
                logger.warning(
                    "Nano Banana Pro Gemini provider: invalid inline image payload"
                )
                return None, stats

    return None, stats


def _normalize_resolution(resolution: str) -> str:
    raw = str(resolution or "2K").strip().upper()
    normalized = RESOLUTION_ALIASES.get(raw, raw)
    if normalized not in {"1K", "2K", "4K"}:
        logger.warning(
            "Nano Banana Pro unsupported resolution %s, fallback to 2K",
            resolution,
        )
        return "2K"
    if normalized != raw:
        logger.info(
            "Nano Banana Pro resolution normalized: %s -> %s", raw, normalized
        )
    return normalized


class ProviderClient:
    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=120)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def _post(self, endpoint: str, payload: Dict) -> Optional[Dict]:
        session = await self._get_session()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with session.post(
                f"{self.base_url}{endpoint}", headers=headers, json=payload
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    error = await resp.text()
                    logger.warning(
                        "Nano Banana Pro POST failed on provider %s: %s - %s",
                        self.base_url,
                        resp.status,
                        error,
                    )
                    return None
        except Exception as e:
            logger.warning("Nano Banana Pro POST error on provider %s: %s", self.base_url, e)
            return None

    async def _get(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        session = await self._get_session()
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with session.get(
                f"{self.base_url}{endpoint}", headers=headers, params=params
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    error = await resp.text()
                    if resp.status != 404:
                        logger.warning(
                            "Nano Banana Pro GET failed on provider %s: %s - %s",
                            self.base_url,
                            resp.status,
                            error,
                        )
                    else:
                        logger.debug(
                            "Nano Banana Pro GET 404 on provider %s (expected for non-existent task)",
                            self.base_url,
                        )
                    return None
        except Exception as e:
            logger.warning("Nano Banana Pro GET error on provider %s: %s", self.base_url, e)
            return None

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()


class NanoBananaProService:
    def __init__(
        self,
        primary_provider: ProviderClient,
        fallback_provider: Optional = None,
    ):
        self.primary_provider = primary_provider
        self.fallback_provider = fallback_provider

    async def _post(self, endpoint: str, payload: Dict) -> Optional[Dict]:
        resp = None
        if hasattr(self.primary_provider, "_post"):
            resp = await self.primary_provider._post(endpoint, payload)
        if resp is not None:
            return resp
        if self.fallback_provider is not None and hasattr(self.fallback_provider, "_post"):
            logger.info("Falling back to secondary provider for Nano Banana Pro POST %s", endpoint)
            return await self.fallback_provider._post(endpoint, payload)
        return None

    async def _get(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        resp = None
        if hasattr(self.primary_provider, "_get"):
            resp = await self.primary_provider._get(endpoint, params)
        if resp is not None:
            return resp
        if self.fallback_provider is not None and hasattr(self.fallback_provider, "_get"):
            logger.info("Falling back to secondary provider for Nano Banana Pro GET %s", endpoint)
            return await self.fallback_provider._get(endpoint, params)
        return None

    async def create_task(
        self,
        prompt: str,
        image_input: List[str] = None,
        aspect_ratio: str = "1:1",
        resolution: str = "2K",
        output_format: str = "png",
        callback_url: str = None,
    ) -> Optional[str]:
        if not prompt and not image_input:
            logger.warning("Nano Banana Pro create_task: no prompt and no image_input")
            return None

        uploaded_image_urls = await kie_file_upload_service.upload_local_image_sources(
            image_input or []
        )
        supported_image_urls = image_sources_to_supported_image_urls(uploaded_image_urls)

        if supported_image_urls:
            normalized_image_input = supported_image_urls
        elif image_input:
            normalized_image_input = image_sources_to_data_uris(image_input)
        else:
            normalized_image_input = []

        normalized_resolution = _normalize_resolution(resolution)
        payload = {
            "model": "nano-banana-pro",
            "input": {
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "resolution": normalized_resolution,
                "output_format": output_format,
            },
        }
        if normalized_image_input:
            payload["input"]["image_input"] = normalized_image_input
        if callback_url:
            payload["callBackUrl"] = callback_url

        transport = (
            "kie_file_upload_urls"
            if uploaded_image_urls != supported_image_urls
            else "image_input_urls"
        )
        logger.info(
            "Nano Banana Pro create_task: refs=%s aspect_ratio=%s resolution=%s transport=%s model=%s",
            len(normalized_image_input),
            aspect_ratio,
            resolution,
            transport if normalized_image_input else "none",
            payload["model"],
        )

        resp = await self._post("/api/v1/jobs/createTask", payload)
        if not resp or not isinstance(resp, dict):
            logger.error(f"Nano Banana Pro create_task failed, resp: {resp}")
            return None
        data = resp.get("data")
        if not isinstance(data, dict):
            logger.error(f"Nano Banana Pro invalid data: {data} (full resp: {resp})")
            return None
        task_id = data.get("taskId")
        if not task_id:
            logger.error(f"No taskId in response: {resp}")
        return task_id

    async def get_task_status(self, task_id: str) -> Optional[Dict]:
        if hasattr(self.primary_provider, "get_task_status"):
            primary_status = await self.primary_provider.get_task_status(task_id)
            if primary_status is not None:
                return primary_status
        resp = await self._get("/api/v1/jobs/recordInfo", params={"taskId": task_id})
        if not resp or not isinstance(resp, dict):
            return None
        data = resp.get("data")
        if not isinstance(data, dict):
            logger.warning(f"Nano Banana Pro status invalid data: {data}")
            return None
        return data

    async def generate_image(
        self,
        prompt: str,
        aspect_ratio: str = "1:1",
        resolution: str = "4K",
        image_input: List[str] = None,
        output_format: str = "png",
        callback_url: str = None,
    ) -> Optional[Dict]:
        if hasattr(self.primary_provider, "generate_image"):
            result = await self.primary_provider.generate_image(
                prompt, aspect_ratio, resolution, image_input, output_format
            )
            if result is not None:
                if isinstance(result, (bytes, bytearray)):
                    return {"image_bytes": bytes(result)}
                if isinstance(result, dict) and result.get("task_id"):
                    return result
                return result
            logger.info(
                "Nano Banana Pro: primary sync provider failed, trying queued provider path"
            )

        task_id = await self.create_task(
            prompt, image_input, aspect_ratio, resolution, output_format, callback_url
        )
        if task_id:
            return {"task_id": task_id}

        if self.fallback_provider is not None and hasattr(self.fallback_provider, "generate_image"):
            logger.info(
                "Nano Banana Pro: falling back to secondary provider generate_image "
                "(primary create_task failed)"
            )
            result = await self.fallback_provider.generate_image(
                prompt, aspect_ratio, resolution, image_input, output_format
            )
            if isinstance(result, dict):
                return result
            if isinstance(result, (bytes, bytearray)):
                return {"image_bytes": bytes(result)}
            if result is not None:
                return result
        return None

    async def wait_for_completion(
        self, task_id: str, max_attempts: int = 60, delay: float = 5.0
    ) -> Optional[Dict]:
        import asyncio
        import json

        consecutive_failures = 0
        for attempt in range(max_attempts):
            status = await self.get_task_status(task_id)
            if status is None:
                consecutive_failures += 1
                if consecutive_failures >= 5:
                    logger.error(
                        f"Task {task_id} not found/failed after {consecutive_failures} consecutive errors"
                    )
                    return None
                await asyncio.sleep(delay)
                continue
            consecutive_failures = 0
            task_state = status.get("state", "").lower()
            if task_state == "success":
                return status
            elif task_state == "fail":
                logger.error(
                    f"Task {task_id} failed: {status.get('failMsg', 'Unknown')}"
                )
                return None
            await asyncio.sleep(delay)
        logger.warning(f"Task {task_id} timeout after {max_attempts} attempts")
        return None

    async def close(self):
        await self.primary_provider.close()
        if self.fallback_provider is not None:
            await self.fallback_provider.close()


class NanoBananaProGeminiProvider:
    """Gemini-совместимый fallback провайдер для Nano Banana Pro (api.apiyi.com).

    Использует проприетарный imageConfig для управления разрешением.
    """

    DETAIL_ENHANCER_PROMPT = """
ULTRA DETAIL & QUALITY BOOST:
• Ultra-detailed high resolution, crystal clear image
• Intricate textures, fine details everywhere
• Sharp focus, natural lighting, depth of field
• Photorealistic quality, precise features
• Professional photography quality, high bitrate
"""

    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=120)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def generate_image(
        self,
        prompt: str,
        aspect_ratio: str = "1:1",
        resolution: str = "4K",
        image_input: List[str] = None,
        output_format: str = "png",
    ) -> Optional[bytes]:
        session = await self._get_session()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        enhanced_prompt = f"{prompt}\n\n{self.DETAIL_ENHANCER_PROMPT}"
        parts = [{"text": enhanced_prompt}]
        if image_input:
            for source in image_input:
                if isinstance(source, str) and source.startswith("data:image/"):
                    try:
                        header, b64data = source.split(",", 1)
                        mime_type = header.replace("data:", "").split(";")[0]
                        parts.append({
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": b64data,
                            }
                        })
                    except Exception:
                        logger.warning("Nano Banana Pro Gemini provider: failed to parse data URI")
                elif isinstance(source, str) and source.startswith(("http://", "https://")):
                    try:
                        async with session.get(source) as img_resp:
                            if img_resp.status == 200:
                                img_data = await img_resp.read()
                                import base64
                                b64data = base64.b64encode(img_data).decode("utf-8")
                                mime_type = img_resp.content_type or "image/jpeg"
                                parts.append({
                                    "inlineData": {
                                        "mimeType": mime_type,
                                        "data": b64data,
                                    }
                                })
                            else:
                                logger.warning(
                                    "Nano Banana Pro Gemini provider: failed to fetch remote reference %s",
                                    source,
                                )
                    except Exception:
                        logger.warning(
                            "Nano Banana Pro Gemini provider: failed to fetch remote reference %s",
                            source,
                        )

        normalized_resolution = _normalize_resolution(resolution)
        image_size = normalized_resolution  # "1K", "2K" или "4K"

        # api.apiyi.com использует imageConfig (НЕ стандартный Gemini imageSize)
        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "responseModalities": ["IMAGE"],
                "imageConfig": {
                    "aspectRatio": aspect_ratio,
                    "imageSize": image_size,
                },
            },
        }

        model = "gemini-3-pro-image-preview"
        url = f"{self.base_url}/models/{model}:generateContent"

        try:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    img_bytes, stats = _extract_image_bytes_from_gemini_response(data)
                    if img_bytes is not None:
                        logger.info(
                            "Nano Banana Pro Gemini provider: image %d bytes, size=%s, candidates=%s, parts=%s",
                            len(img_bytes),
                            image_size,
                            stats["candidates"],
                            stats["parts"],
                        )
                        return img_bytes
                    logger.warning(
                        "Nano Banana Pro Gemini provider: no image part in response "
                        "(candidates=%s, parts=%s, text_parts=%s, thought_parts=%s)",
                        stats["candidates"],
                        stats["parts"],
                        stats["text_parts"],
                        stats["thought_parts"],
                    )
                    return None
                else:
                    error = await resp.text()
                    logger.warning(
                        "Nano Banana Pro Gemini provider POST failed: %s - %s",
                        resp.status,
                        error,
                    )
                    return None
        except Exception as e:
            logger.warning("Nano Banana Pro Gemini provider error: %s", e)
            return None

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()


# --- Инициализация: Kie.ai primary, Nexus fallback ---

_kie_provider = ProviderClient(
    api_key=config.KIE_AI_API_KEY or config.NANOBANANA_API_KEY,
    base_url="https://api.kie.ai",
)

nexus_api_key = str(getattr(config, "NEXUS_API_KEY", "") or "").strip()
_nexus_provider = (
    NexusImageProvider(
        api_key=nexus_api_key,
        model_name="nano-banana-pro",
        base_url=getattr(config, "NEXUS_API_BASE_URL", "https://nexusapi.dev"),
        timeout_seconds=getattr(config, "NEXUS_API_TIMEOUT_SECONDS", 600),
        poll_interval_seconds=getattr(config, "NEXUS_API_POLL_INTERVAL_SECONDS", 5),
        max_references=MAX_IMAGE_INPUTS,
    )
    if nexus_api_key
    else None
)

if _nexus_provider:
    logger.info("Nano Banana Pro: using Kie.ai as primary, Nexus as fallback")
    nano_banana_pro_service = NanoBananaProService(
        primary_provider=_kie_provider,
        fallback_provider=_nexus_provider,
    )
else:
    logger.info("Nano Banana Pro: Nexus is not configured; using Kie.ai only")
    nano_banana_pro_service = NanoBananaProService(
        primary_provider=_kie_provider,
        fallback_provider=None,
    )
