"""Use the exact VK photo-analysis request for ordinary Telegram photos.

Only the internal provider call changes. Telegram handlers, buttons, FSM and
result layout remain untouched. Photo+voice and voice-only requests keep using
the existing richer Telegram pipeline.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import os
from functools import wraps
from pathlib import Path
from typing import Any

import aiohttp

from bot.services.media_input_utils import resolve_local_upload_path

logger = logging.getLogger(__name__)

VK_PHOTO_ANALYSIS_PROMPT = (
    "Составь подробный промпт для создания максимально похожего фото в Banana Pro. "
    "Сохрани все мелкие детали, лицо, одежду, позу, освещение, стиль, цвета. "
    "На русском языке."
)
VK_PHOTO_ANALYSIS_INSTRUCTIONS = (
    "Ты эксперт по промптам для генерации изображений. "
    "Отвечай только готовым промптом без вводных фраз."
)
VK_MAX_OUTPUT_TOKENS = 1200
VK_DEFAULT_VISION_MODEL = "gpt-5.5"
VK_DEFAULT_FALLBACK_MODELS: tuple[str, ...] = ()


def build_vk_photo_analysis_payload(*, model: str, image_url: str) -> dict[str, Any]:
    """Build the same Responses payload used by the VK bot."""
    return {
        "model": model,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": VK_PHOTO_ANALYSIS_PROMPT},
                    {
                        "type": "input_image",
                        "image_url": image_url,
                        "detail": "high",
                    },
                ],
            }
        ],
        "instructions": VK_PHOTO_ANALYSIS_INSTRUCTIONS,
        "max_output_tokens": VK_MAX_OUTPUT_TOKENS,
    }


def _configured_models() -> list[str]:
    primary = os.getenv("APIYI_VISION_MODEL", VK_DEFAULT_VISION_MODEL).strip()
    fallbacks = [
        value.strip()
        for value in os.getenv(
            "APIYI_VISION_FALLBACK_MODELS",
            ",".join(VK_DEFAULT_FALLBACK_MODELS),
        ).split(",")
        if value.strip()
    ]
    models: list[str] = []
    for model in [primary, *fallbacks]:
        if model and model not in models:
            models.append(model)
    return models


def _apiyi_base_url() -> str:
    return os.getenv("APIYI_BASE_URL", "https://api.apiyi.com/v1").rstrip("/")


def _apiyi_api_key() -> str:
    for name in (
        "APIYI_API_KEY",
        "NANO_BANANA_PRO_FALLBACK_API_KEY",
        "NANOBANANA2_FALLBACK_API_KEY",
    ):
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _content_type_for_path(path: Path) -> str:
    guessed = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return guessed if guessed.startswith("image/") else "image/jpeg"


async def _inline_image_url(photo_url: str) -> str:
    """Inline the photo as a data URL, matching the VK implementation."""
    if photo_url.startswith("data:image/"):
        return photo_url

    local_path = resolve_local_upload_path(photo_url)
    if local_path:
        path = Path(local_path)
        payload = path.read_bytes()
        if not payload:
            raise ValueError(f"empty image payload for {photo_url}")
        encoded = base64.b64encode(payload).decode("ascii")
        return f"data:{_content_type_for_path(path)};base64,{encoded}"

    timeout = aiohttp.ClientTimeout(total=20)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session, session.get(
            photo_url
        ) as response:
            if response.status != 200:
                raise ValueError(
                    f"image download failed with status {response.status} for {photo_url}"
                )
            content_type = (
                response.headers.get("Content-Type", "image/jpeg")
                .split(";", 1)[0]
                .strip()
            )
            if not content_type.startswith("image/"):
                raise ValueError(
                    f"unexpected content type {content_type} for {photo_url}"
                )
            payload = await response.read()
            if not payload:
                raise ValueError(f"empty image payload for {photo_url}")
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError) as exc:
        logger.warning("Could not inline image for APIYI vision, using URL: %s", exc)
        return photo_url

    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def _extract_responses_output_text(result: dict[str, Any]) -> str:
    if result.get("output_text"):
        return str(result["output_text"]).strip()

    chunks: list[str] = []
    for item in result.get("output", []) or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []) or []:
            if (
                isinstance(content, dict)
                and content.get("type") == "output_text"
                and content.get("text")
            ):
                chunks.append(str(content["text"]))
    return "\n".join(chunks).strip()


def _extract_legacy_choice_text(result: dict[str, Any]) -> str:
    choices = result.get("choices") or []
    if not choices:
        return ""

    content = ((choices[0] or {}).get("message") or {}).get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
            elif isinstance(item, dict) and item.get("text"):
                chunks.append(str(item["text"]))
        return "\n".join(
            chunk.strip() for chunk in chunks if str(chunk).strip()
        ).strip()
    return ""


async def analyze_photo_exactly_as_vk(photo_url: str) -> tuple[str, str]:
    """Return ``(prompt, model)`` using the exact VK prompt and model chain."""
    if not photo_url:
        raise ValueError("Photo URL is required for analysis")

    api_key = _apiyi_api_key()
    if not api_key:
        raise RuntimeError(
            "APIYI_API_KEY is not configured; exact VK photo analysis is unavailable"
        )

    image_url = await _inline_image_url(photo_url)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    last_error: Exception | None = None

    for model in _configured_models():
        try:
            payload = build_vk_photo_analysis_payload(
                model=model,
                image_url=image_url,
            )
            async with aiohttp.ClientSession() as session, session.post(
                f"{_apiyi_base_url()}/responses",
                headers=headers,
                json=payload,
            ) as response:
                text = await response.text()
                if response.status != 200:
                    raise ValueError(
                        f"APIYI vision error {response.status}: {text}"
                    )
                try:
                    result = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Invalid JSON response from APIYI: {text[:200]}"
                    ) from exc
                if not isinstance(result, dict):
                    raise TypeError(
                        f"Unexpected non-object APIYI response: {result}"
                    )

            output_text = _extract_responses_output_text(result)
            if output_text:
                return output_text, model

            legacy_text = _extract_legacy_choice_text(result)
            if legacy_text:
                return legacy_text, model

            raise ValueError(f"Unexpected APIYI response structure: {result}")
        except (TypeError, ValueError) as exc:
            last_error = exc
            logger.warning(
                "APIYI photo analysis failed with model %s: %s",
                model,
                exc,
            )
        except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError) as exc:
            last_error = exc
            logger.warning(
                "APIYI photo analysis transport error with model %s: %s",
                model,
                exc,
            )
            await asyncio.sleep(0.5)

    raise ValueError(
        f"APIYI photo analysis failed for all configured models: {last_error}"
    )


def _telegram_result_from_vk_prompt(prompt: str, model: str) -> dict[str, Any]:
    """Adapt the VK string to the established Telegram result screen only."""
    return {
        "prompt_en": "",
        "prompt_ru": prompt,
        "negative_prompt": "",
        "model_hint": "Banana Pro",
        "key_details": [],
        "voice_transcript": "",
        "voice_prompt_summary_ru": "",
        "voice_description_ru": "",
        "provider": "",
        "raw": {
            "prompt_ru": prompt,
            "analysis_model": model,
            "analysis_contract": "vk_exact",
        },
    }


def install_vk_photo_prompt_instructions() -> None:
    """Route ordinary photo-only analysis through the exact VK implementation."""
    from bot.services import photo_prompt_service as module

    if getattr(module, "_vk_photo_prompt_exact_installed", False):
        return

    original_analyze_photo = module.photo_prompt_service.analyze_photo

    @wraps(original_analyze_photo)
    async def analyze_photo_with_exact_vk_contract(
        *,
        image_url: str,
        preserve: str = "",
        goal: str = "",
        user_note: str = "",
        audio_bytes: bytes | None = None,
        audio_format: str = "",
    ) -> dict[str, Any]:
        if image_url and not audio_bytes:
            try:
                prompt, model = await analyze_photo_exactly_as_vk(image_url)
                return _telegram_result_from_vk_prompt(prompt, model)
            except Exception as exc:
                logger.warning(
                    "Exact VK photo analysis failed; falling back to Telegram "
                    "photo prompt service: %s",
                    exc,
                )

        return await original_analyze_photo(
            image_url=image_url,
            preserve=preserve,
            goal=goal,
            user_note=user_note,
            audio_bytes=audio_bytes,
            audio_format=audio_format,
        )

    module.photo_prompt_service.analyze_photo = analyze_photo_with_exact_vk_contract
    module._vk_photo_prompt_exact_installed = True
