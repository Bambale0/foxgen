import asyncio
import base64
import json
import logging
from typing import Any, Dict, List, Optional

import aiohttp

from bot.config import config
from bot.services.kie_file_upload_service import kie_file_upload_service
from bot.services.kie_market_service import kie_market_service
from bot.services.media_input_utils import (
    image_sources_to_data_uris,
    image_sources_to_supported_image_urls,
)
from bot.services.nexus_image_provider import NexusImageProvider

logger = logging.getLogger(__name__)

MAX_IMAGE_INPUTS = 8
NANO_BANANA_2_LITE_MODEL_IDS = {
    "nano-banana-2-lite",
    "nano_banana_2_lite",
    "banana_2_lite",
}
RESOLUTION_ALIASES = {
    "BASIC": "2K",
    "HIGH": "4K",
    "1K": "1K",
    "2K": "2K",
    "4K": "4K",
}

# Gemini 3.1 Flash Image is the production/GA model behind Nano Banana 2.
# Keep an environment-backed override for emergency provider migrations without
# hard-coding another source-level change.
DEFAULT_APIYI_MODEL = "gemini-3.1-flash-image"
APIYI_MODEL = (
    str(getattr(config, "NANOBANANA2_APIYI_MODEL", "") or "").strip()
    or DEFAULT_APIYI_MODEL
)

# Explicitly match the least restrictive configurable Gemini safety setup.
# Provider-level, non-configurable policy checks still apply and are reported
# separately instead of being disguised as a technical failure.
APIYI_SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "OFF"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "OFF"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "OFF"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "OFF"},
]

# Legacy bot-side prompt engineering markers. Nano Banana 2 must receive the
# user's request, not these wrappers. They are removed defensively here so all
# callers (Telegram, Mini App, repeat/batch flows and Kie fallback) behave alike.
_LEGACY_EDIT_PREFIX = "EDIT REQUEST (highest priority):"
_LEGACY_REFERENCE_MARKER = "\n\nReference guidance:"
_LEGACY_REFERENCE_ONLY_PREFIX = "Reference guidance:"
_LEGACY_VARIANT_MARKER = "\n\nFor this single output:"
_REFERENCE_ONLY_PROMPT = ""

_POLICY_FINISH_REASONS = {
    "SAFETY",
    "IMAGE_SAFETY",
    "PROHIBITED_CONTENT",
    "BLOCKLIST",
    "RECITATION",
    "SPII",
}


def _normalize_resolution(resolution: str) -> str:
    raw = str(resolution or "2K").strip().upper()
    normalized = RESOLUTION_ALIASES.get(raw, raw)
    if normalized not in {"1K", "2K", "4K"}:
        logger.warning(
            "Nano Banana 2 unsupported resolution %s, fallback to 2K",
            resolution,
        )
        return "2K"
    if normalized != raw:
        logger.info(
            "Nano Banana 2 resolution normalized: %s -> %s",
            raw,
            normalized,
        )
    return normalized


def _normalize_apiyi_prompt(prompt: str) -> tuple[str, bool]:
    """Return the original user request without legacy bot additions."""

    value = str(prompt or "").strip()
    if not value:
        return "", False

    changed = False

    if value.startswith(_LEGACY_EDIT_PREFIX):
        value = value[len(_LEGACY_EDIT_PREFIX) :].lstrip()
        changed = True
        if _LEGACY_REFERENCE_MARKER in value:
            value = value.split(_LEGACY_REFERENCE_MARKER, 1)[0].rstrip()

    elif value.startswith(_LEGACY_REFERENCE_ONLY_PREFIX):
        # Image-only requests are sent without a fabricated text instruction.
        return _REFERENCE_ONLY_PROMPT, True

    if _LEGACY_VARIANT_MARKER in value:
        value = value.split(_LEGACY_VARIANT_MARKER, 1)[0].rstrip()
        changed = True

    return value, changed


def _extract_inline_image(result: Dict[str, Any]) -> tuple[bytes, str] | None:
    candidates = result.get("candidates") or []
    if not isinstance(candidates, list):
        return None

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content") or {}
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict):
                continue
            inline_data = part.get("inlineData") or part.get("inline_data")
            if not isinstance(inline_data, dict):
                continue
            encoded = inline_data.get("data")
            if not isinstance(encoded, str) or not encoded:
                continue
            try:
                return (
                    base64.b64decode(encoded),
                    str(
                        inline_data.get("mimeType")
                        or inline_data.get("mime_type")
                        or "unknown"
                    ),
                )
            except Exception:
                logger.exception(
                    "Nano Banana 2 APIYI returned invalid base64 image data"
                )
    return None


def _extract_apiyi_failure(result: Dict[str, Any]) -> tuple[str, list[dict]]:
    """Extract the provider/model refusal reason without logging image payloads."""

    reasons: list[str] = []
    ratings: list[dict] = []

    prompt_feedback = result.get("promptFeedback") or result.get("prompt_feedback")
    if isinstance(prompt_feedback, dict):
        block_reason = prompt_feedback.get("blockReason") or prompt_feedback.get(
            "block_reason"
        )
        if block_reason:
            reasons.append(str(block_reason).upper())
        feedback_ratings = prompt_feedback.get("safetyRatings") or prompt_feedback.get(
            "safety_ratings"
        )
        if isinstance(feedback_ratings, list):
            ratings.extend(item for item in feedback_ratings if isinstance(item, dict))

    candidates = result.get("candidates") or []
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            finish_reason = candidate.get("finishReason") or candidate.get(
                "finish_reason"
            )
            if finish_reason:
                reasons.append(str(finish_reason).upper())
            candidate_ratings = candidate.get("safetyRatings") or candidate.get(
                "safety_ratings"
            )
            if isinstance(candidate_ratings, list):
                ratings.extend(
                    item for item in candidate_ratings if isinstance(item, dict)
                )

    unique_reasons = list(dict.fromkeys(reason for reason in reasons if reason))
    return ",".join(unique_reasons), ratings


def _is_policy_failure(reason: str) -> bool:
    values = {part.strip().upper() for part in str(reason or "").split(",")}
    return bool(values & _POLICY_FINISH_REASONS)


def _build_apiyi_payload(
    *,
    prompt: str,
    reference_parts: List[Dict[str, Any]],
    aspect_ratio: str,
    resolution: str,
) -> Dict[str, Any]:
    parts: List[Dict[str, Any]] = []
    if prompt:
        parts.append({"text": prompt})
    parts.extend(reference_parts)

    return {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
            "imageConfig": {
                "aspectRatio": aspect_ratio,
                "imageSize": resolution,
            },
        },
        "safetySettings": [dict(item) for item in APIYI_SAFETY_SETTINGS],
    }


class ProviderClient:
    """Queued Kie.ai client used as the technical fallback for APIYI."""

    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=120)
            )
        return self._session

    async def _post(self, endpoint: str, payload: Dict) -> Optional[Dict]:
        session = await self._get_session()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with session.post(
                f"{self.base_url}{endpoint}",
                headers=headers,
                json=payload,
            ) as response:
                body = await response.text()
                if response.status == 200:
                    try:
                        parsed = json.loads(body)
                    except json.JSONDecodeError:
                        logger.warning("Nano Banana 2 Kie response is not JSON")
                        return None
                    return parsed if isinstance(parsed, dict) else None

                logger.warning(
                    "Nano Banana 2 POST failed on provider %s: %s - %s",
                    self.base_url,
                    response.status,
                    body[:1000],
                )
                return None
        except Exception as exc:
            logger.warning(
                "Nano Banana 2 POST error on provider %s: %s",
                self.base_url,
                exc,
            )
            return None

    async def _get(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        session = await self._get_session()
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with session.get(
                f"{self.base_url}{endpoint}",
                headers=headers,
                params=params,
            ) as response:
                body = await response.text()
                if response.status == 200:
                    try:
                        parsed = json.loads(body)
                    except json.JSONDecodeError:
                        logger.warning(
                            "Nano Banana 2 Kie status response is not JSON"
                        )
                        return None
                    return parsed if isinstance(parsed, dict) else None

                if response.status != 404:
                    logger.warning(
                        "Nano Banana 2 GET failed on provider %s: %s - %s",
                        self.base_url,
                        response.status,
                        body[:1000],
                    )
                else:
                    logger.debug(
                        "Nano Banana 2 GET 404 on provider %s",
                        self.base_url,
                    )
                return None
        except Exception as exc:
            logger.warning(
                "Nano Banana 2 GET error on provider %s: %s",
                self.base_url,
                exc,
            )
            return None

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


class NanoBanana2Service:
    def __init__(
        self,
        primary_provider: Any,
        fallback_provider: Optional[Any] = None,
    ):
        self.primary_provider = primary_provider
        self.fallback_provider = fallback_provider

    async def _post(self, endpoint: str, payload: Dict) -> Optional[Dict]:
        response = None
        if hasattr(self.primary_provider, "_post"):
            response = await self.primary_provider._post(endpoint, payload)
        if response is not None:
            return response
        if self.fallback_provider is not None and hasattr(
            self.fallback_provider, "_post"
        ):
            logger.info(
                "Falling back to secondary provider for Nano Banana 2 POST %s",
                endpoint,
            )
            return await self.fallback_provider._post(endpoint, payload)
        return None

    async def _get(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        response = None
        if hasattr(self.primary_provider, "_get"):
            response = await self.primary_provider._get(endpoint, params)
        if response is not None:
            return response
        if self.fallback_provider is not None and hasattr(
            self.fallback_provider, "_get"
        ):
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
        model: str = "nano-banana-2",
    ) -> Optional[str]:
        clean_prompt, _ = _normalize_apiyi_prompt(prompt)
        if not clean_prompt and not image_input:
            logger.warning("Nano Banana 2 create_task: no prompt and no image_input")
            return None

        uploaded_image_urls = await kie_file_upload_service.upload_local_image_sources(
            image_input or []
        )
        supported_image_urls = image_sources_to_supported_image_urls(
            uploaded_image_urls
        )

        if supported_image_urls:
            normalized_image_input = supported_image_urls
        elif image_input:
            normalized_image_input = image_sources_to_data_uris(image_input)
        else:
            normalized_image_input = []

        if str(model or "").strip() in NANO_BANANA_2_LITE_MODEL_IDS:
            try:
                logger.info(
                    "Nano Banana 2 Lite create_task: refs=%s aspect_ratio=%s model=nano-banana-2-lite prompt_len=%s",
                    len(normalized_image_input),
                    aspect_ratio,
                    len(clean_prompt),
                )
                return await kie_market_service.create_nano_banana_2_lite_task(
                    prompt=clean_prompt,
                    image_urls=normalized_image_input[:10],
                    aspect_ratio=aspect_ratio or "auto",
                    callback_url=callback_url,
                )
            except Exception as exc:
                logger.error("Nano Banana 2 Lite create_task failed: %s", exc)
                return None

        normalized_resolution = _normalize_resolution(resolution)
        payload = {
            "model": "nano-banana-2",
            "input": {
                "prompt": clean_prompt,
                "aspect_ratio": aspect_ratio,
                "resolution": normalized_resolution,
                "output_format": output_format,
            },
        }
        if normalized_image_input:
            payload["input"]["image_input"] = normalized_image_input
        if callback_url:
            payload["callBackUrl"] = callback_url

        logger.info(
            "Nano Banana 2 Kie fallback task: refs=%s aspect_ratio=%s resolution=%s prompt_len=%s model=%s",
            len(normalized_image_input),
            aspect_ratio,
            normalized_resolution,
            len(clean_prompt),
            payload["model"],
        )

        response = await self._post("/api/v1/jobs/createTask", payload)
        if not response or not isinstance(response, dict):
            logger.error("Nano Banana 2 create_task failed, response=%s", response)
            return None
        data = response.get("data")
        if not isinstance(data, dict):
            logger.error(
                "Nano Banana 2 invalid data: %s (full response: %s)",
                data,
                response,
            )
            return None
        task_id = data.get("taskId")
        if not task_id:
            logger.error("No taskId in Nano Banana 2 response: %s", response)
        return task_id

    async def get_task_status(self, task_id: str) -> Optional[Dict]:
        if hasattr(self.primary_provider, "get_task_status"):
            primary_status = await self.primary_provider.get_task_status(task_id)
            if primary_status is not None:
                return primary_status
        response = await self._get(
            "/api/v1/jobs/recordInfo",
            params={"taskId": task_id},
        )
        if not response or not isinstance(response, dict):
            return None
        data = response.get("data")
        if not isinstance(data, dict):
            logger.warning("Nano Banana 2 status invalid data: %s", data)
            return None
        return data

    async def generate_image(
        self,
        prompt: str,
        aspect_ratio: str = "auto",
        resolution: str = "4K",
        image_input: List[str] = None,
        output_format: str = "png",
        callback_url: str = None,
        model: str = "nano-banana-2",
    ) -> Optional[Dict]:
        clean_prompt, stripped = _normalize_apiyi_prompt(prompt)
        if stripped:
            logger.info(
                "Nano Banana 2 removed bot-side prompt additions before provider call"
            )

        if str(model or "").strip() in NANO_BANANA_2_LITE_MODEL_IDS:
            task_id = await self.create_task(
                clean_prompt,
                image_input,
                aspect_ratio,
                resolution,
                output_format,
                callback_url,
                model=model,
            )
            return (
                {
                    "task_id": task_id,
                    "provider": "kie_market",
                    "provider_model": "nano-banana-2-lite",
                }
                if task_id
                else None
            )

        primary_result: Optional[Dict] = None
        if hasattr(self.primary_provider, "generate_image"):
            raw_result = await self.primary_provider.generate_image(
                clean_prompt,
                aspect_ratio,
                resolution,
                image_input,
                output_format,
            )
            if isinstance(raw_result, dict):
                primary_result = raw_result
                if raw_result.get("image_bytes"):
                    return raw_result
                if raw_result.get("task_id"):
                    return raw_result
                if not raw_result.get("retryable", True):
                    # A completed provider response (for example a model policy
                    # refusal) is not a transport failure and must not silently
                    # switch the user to a different model/provider behavior.
                    return raw_result
            elif isinstance(raw_result, (bytes, bytearray)):
                return {
                    "image_bytes": bytes(raw_result),
                    "provider": "apiyi",
                    "provider_model": APIYI_MODEL,
                }
            elif raw_result is not None:
                return raw_result

            logger.info(
                "Nano Banana 2 APIYI technical failure; trying Kie queued fallback"
            )

        task_id = await self.create_task(
            clean_prompt,
            image_input,
            aspect_ratio,
            resolution,
            output_format,
            callback_url,
            model=model,
        )
        if task_id:
            return {
                "task_id": task_id,
                "provider": "kie",
                "provider_model": "nano-banana-2",
            }

        if self.fallback_provider is not None and hasattr(
            self.fallback_provider, "generate_image"
        ):
            logger.info(
                "Nano Banana 2: Kie primary failed; trying Nexus fallback"
            )
            fallback_result = await self.fallback_provider.generate_image(
                clean_prompt,
                aspect_ratio,
                resolution,
                image_input,
                output_format,
            )
            if isinstance(fallback_result, dict):
                return fallback_result
            if isinstance(fallback_result, (bytes, bytearray)):
                return {"image_bytes": bytes(fallback_result)}
            if fallback_result is not None:
                return fallback_result

        return primary_result

    async def wait_for_completion(
        self,
        task_id: str,
        max_attempts: int = 60,
        delay: float = 5.0,
    ) -> Optional[Dict]:
        consecutive_failures = 0
        for _attempt in range(max_attempts):
            status = await self.get_task_status(task_id)
            if status is None:
                consecutive_failures += 1
                if consecutive_failures >= 5:
                    logger.error(
                        "Task %s unavailable after %s consecutive errors",
                        task_id,
                        consecutive_failures,
                    )
                    return None
                await asyncio.sleep(delay)
                continue

            consecutive_failures = 0
            task_state = str(status.get("state") or "").lower()
            if task_state == "success":
                return status
            if task_state == "fail":
                logger.error(
                    "Task %s failed: %s",
                    task_id,
                    status.get("failMsg", "Unknown"),
                )
                return None
            await asyncio.sleep(delay)

        logger.warning("Task %s timed out after %s attempts", task_id, max_attempts)
        return None

    async def close(self) -> None:
        if hasattr(self.primary_provider, "close"):
            await self.primary_provider.close()
        if self.fallback_provider is not None and hasattr(
            self.fallback_provider, "close"
        ):
            await self.fallback_provider.close()


class NanoBanana2GeminiProvider:
    """APIYI Gemini-compatible primary provider for Nano Banana 2."""

    MODEL = APIYI_MODEL

    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=120)
            )
        return self._session

    async def _reference_part(
        self,
        session: aiohttp.ClientSession,
        source: str,
        index: int,
    ) -> Optional[Dict[str, Any]]:
        if source.startswith("data:image/"):
            try:
                header, encoded = source.split(",", 1)
                mime_type = header.replace("data:", "").split(";", 1)[0]
                raw_size = len(base64.b64decode(encoded, validate=False))
                logger.info(
                    "Nano Banana 2 APIYI reference ready: index=%s bytes=%s mime=%s transport=data_uri",
                    index,
                    raw_size,
                    mime_type,
                )
                return {
                    "inlineData": {
                        "mimeType": mime_type,
                        "data": encoded,
                    }
                }
            except Exception:
                logger.exception(
                    "Nano Banana 2 APIYI failed to parse data URI reference index=%s",
                    index,
                )
                return None

        if not source.startswith(("http://", "https://")):
            logger.warning(
                "Nano Banana 2 APIYI unsupported reference source index=%s",
                index,
            )
            return None

        try:
            async with session.get(
                source,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as image_response:
                if image_response.status != 200:
                    logger.warning(
                        "Nano Banana 2 APIYI reference download failed: index=%s status=%s",
                        index,
                        image_response.status,
                    )
                    return None
                image_data = await image_response.read()
                if not image_data:
                    logger.warning(
                        "Nano Banana 2 APIYI reference is empty: index=%s",
                        index,
                    )
                    return None
                mime_type = image_response.content_type or "image/jpeg"
                encoded = base64.b64encode(image_data).decode("ascii")
                logger.info(
                    "Nano Banana 2 APIYI reference ready: index=%s bytes=%s mime=%s transport=url",
                    index,
                    len(image_data),
                    mime_type,
                )
                return {
                    "inlineData": {
                        "mimeType": mime_type,
                        "data": encoded,
                    }
                }
        except Exception:
            logger.exception(
                "Nano Banana 2 APIYI failed to download reference index=%s",
                index,
            )
            return None

    async def generate_image(
        self,
        prompt: str,
        aspect_ratio: str = "auto",
        resolution: str = "4K",
        image_input: List[str] = None,
        output_format: str = "png",
    ) -> Dict[str, Any]:
        session = await self._get_session()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        provider_prompt, stripped_legacy_wrapper = _normalize_apiyi_prompt(prompt)
        requested_references = [
            source.strip()
            for source in (image_input or [])[:MAX_IMAGE_INPUTS]
            if isinstance(source, str) and source.strip()
        ]

        reference_parts: List[Dict[str, Any]] = []
        for index, source in enumerate(requested_references, start=1):
            part = await self._reference_part(session, source, index)
            if part is None:
                if index == 1:
                    logger.error(
                        "Nano Banana 2 APIYI primary reference unavailable; aborting primary request"
                    )
                    return {
                        "error": "APIYI could not load the primary reference image",
                        "provider": "apiyi",
                        "provider_model": self.MODEL,
                        "retryable": True,
                    }
                logger.warning(
                    "Nano Banana 2 APIYI skipped unavailable extra reference index=%s",
                    index,
                )
                continue
            reference_parts.append(part)

        if requested_references and not reference_parts:
            return {
                "error": "APIYI could not load reference images",
                "provider": "apiyi",
                "provider_model": self.MODEL,
                "retryable": True,
            }
        if not provider_prompt and not reference_parts:
            return {
                "error": "Nano Banana 2 request has neither prompt nor reference image",
                "provider": "apiyi",
                "provider_model": self.MODEL,
                "retryable": False,
            }

        normalized_resolution = _normalize_resolution(resolution)
        payload = _build_apiyi_payload(
            prompt=provider_prompt,
            reference_parts=reference_parts,
            aspect_ratio=aspect_ratio,
            resolution=normalized_resolution,
        )
        url = f"{self.base_url}/models/{self.MODEL}:generateContent"

        logger.info(
            "Nano Banana 2 APIYI request: model=%s refs=%s/%s aspect_ratio=%s resolution=%s output_format=%s prompt_len=%s legacy_wrapper_stripped=%s safety=OFF",
            self.MODEL,
            len(reference_parts),
            len(requested_references),
            aspect_ratio,
            normalized_resolution,
            output_format,
            len(provider_prompt),
            stripped_legacy_wrapper,
        )

        try:
            async with session.post(url, headers=headers, json=payload) as response:
                body = await response.text()
                if response.status != 200:
                    retryable = response.status in {
                        408,
                        409,
                        425,
                        429,
                        500,
                        502,
                        503,
                        504,
                    }
                    logger.warning(
                        "Nano Banana 2 APIYI POST failed: status=%s retryable=%s body=%s",
                        response.status,
                        retryable,
                        body[:1000],
                    )
                    return {
                        "error": f"APIYI HTTP {response.status}",
                        "provider": "apiyi",
                        "provider_model": self.MODEL,
                        "http_status": response.status,
                        "retryable": retryable,
                    }

                try:
                    data = json.loads(body)
                except json.JSONDecodeError:
                    logger.warning("Nano Banana 2 APIYI response is not JSON")
                    return {
                        "error": "APIYI returned an invalid JSON response",
                        "provider": "apiyi",
                        "provider_model": self.MODEL,
                        "retryable": True,
                    }

                extracted = _extract_inline_image(data)
                if extracted is not None:
                    image_bytes, mime_type = extracted
                    finish_reason, ratings = _extract_apiyi_failure(data)
                    logger.info(
                        "Nano Banana 2 APIYI image ready: bytes=%s resolution=%s mime=%s finish_reason=%s ratings=%s",
                        len(image_bytes),
                        normalized_resolution,
                        mime_type,
                        finish_reason or "none",
                        len(ratings),
                    )
                    return {
                        "image_bytes": image_bytes,
                        "mime_type": mime_type,
                        "provider": "apiyi",
                        "provider_model": self.MODEL,
                        "finish_reason": finish_reason or None,
                        "retryable": False,
                    }

                finish_reason, ratings = _extract_apiyi_failure(data)
                policy_failure = _is_policy_failure(finish_reason)
                logger.warning(
                    "Nano Banana 2 APIYI returned no image: finish_reason=%s policy_failure=%s ratings=%s",
                    finish_reason or "unknown",
                    policy_failure,
                    len(ratings),
                )
                return {
                    "error": (
                        f"APIYI generation blocked by model policy: {finish_reason}"
                        if policy_failure
                        else f"APIYI returned no image: {finish_reason or 'unknown reason'}"
                    ),
                    "provider": "apiyi",
                    "provider_model": self.MODEL,
                    "finish_reason": finish_reason or None,
                    "safety_ratings": ratings,
                    "retryable": not policy_failure,
                }
        except Exception as exc:
            logger.warning("Nano Banana 2 APIYI provider error: %s", exc)
            return {
                "error": f"APIYI transport error: {type(exc).__name__}",
                "provider": "apiyi",
                "provider_model": self.MODEL,
                "retryable": True,
            }

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


# Kie.ai stays primary. Nexus is a technical fallback only.
_kie_provider = ProviderClient(
    api_key=config.KIE_AI_API_KEY or config.NANOBANANA_API_KEY,
    base_url="https://api.kie.ai",
)

nexus_api_key = str(getattr(config, "NEXUS_API_KEY", "") or "").strip()
_nexus_provider = (
    NexusImageProvider(
        api_key=nexus_api_key,
        model_name="nano-banana-2",
        base_url=getattr(config, "NEXUS_API_BASE_URL", "https://nexusapi.dev"),
        timeout_seconds=getattr(config, "NEXUS_API_TIMEOUT_SECONDS", 600),
        poll_interval_seconds=getattr(config, "NEXUS_API_POLL_INTERVAL_SECONDS", 5),
        max_references=MAX_IMAGE_INPUTS,
    )
    if nexus_api_key
    else None
)

if _nexus_provider:
    logger.info("Nano Banana 2: using Kie.ai as primary, Nexus as technical fallback")
    nano_banana_2_service = NanoBanana2Service(
        primary_provider=_kie_provider,
        fallback_provider=_nexus_provider,
    )
else:
    logger.info("Nano Banana 2: Nexus is not configured; using Kie.ai only")
    nano_banana_2_service = NanoBanana2Service(
        primary_provider=_kie_provider,
        fallback_provider=None,
    )
