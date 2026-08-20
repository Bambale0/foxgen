"""Unified text/photo/voice to prompt service.

This service intentionally returns only Russian and English prompts. It does not
request negative prompts, model recommendations, transcripts, or Gemini Omni
payloads so the provider spends tokens on the two user-facing results only.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any, Dict, Optional

import aiohttp

from bot.config import config

logger = logging.getLogger(__name__)

GPT55_MAX_ATTEMPTS = 3
GPT55_RETRYABLE_BODY_CODES = {429}
CLAUDE_MAX_ATTEMPTS = 2

SYSTEM_PROMPT = """
You are a senior prompt engineer for AI image generation.

The user may provide any combination of:
- a rough text description or scattered creative thoughts;
- a reference image;
- a voice message;
- text or voice together with a reference image.

Create exactly two complete, production-ready prompts:
1. "prompt_ru" — a detailed natural Russian generation prompt.
2. "prompt_en" — a faithful, equally detailed English version optimized for
   image-generation models.

Rules:
- Preserve the user's intent, subject, action, mood, style, composition, lighting,
  color palette, setting, camera angle, and constraints when they are provided.
- When an image is attached, describe only visible details and combine them with
  the user's text or voice direction without contradicting the reference.
- For photo reconstruction, cover every useful visible detail: subject appearance,
  facial features without identifying the person, hair, clothing, pose, hands,
  expression, objects, environment, composition, framing, perspective, lens/look,
  depth of field, lighting direction and quality, shadows, materials, textures,
  color palette, grading, atmosphere, and photographic style.
- Preserve small distinctive visual details that materially affect similarity.
- When only rough text or voice is provided, turn it into a coherent standalone
  visual prompt. Add useful visual specificity, but do not replace the user's idea
  or invent sensitive personal facts.
- Write each prompt as one cohesive paragraph, not a checklist.
- Prefer completeness over brevity. For an information-rich reference, normally
  write 900-1800 characters per language; use less only when the source is simple.
- Do not add negative prompts, model recommendations, commentary, transcripts,
  analysis notes, headings, markdown, or extra fields.
- Do not identify real people. Do not guess names, ethnicity, nationality, private
  attributes, or exact age.
- Return valid JSON only.

JSON schema:
{
  "prompt_ru": "Полный промпт на русском языке",
  "prompt_en": "Complete prompt in English"
}
""".strip()


def _extract_output_text(data: Dict[str, Any]) -> str:
    parts: list[str] = []
    for item in data.get("output", []) or []:
        if isinstance(item, dict) and item.get("type") == "message":
            for content in item.get("content", []) or []:
                if isinstance(content, dict):
                    text = content.get("text")
                    if text:
                        parts.append(str(text))
    if parts:
        return "\n".join(parts).strip()
    if isinstance(data.get("output_text"), str):
        return data["output_text"].strip()
    if isinstance(data.get("text"), str):
        return data["text"].strip()
    return json.dumps(data, ensure_ascii=False)


def _extract_claude_text(data: Dict[str, Any]) -> str:
    parts: list[str] = []
    for block in data.get("content", []) or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if text:
                parts.append(str(text))
    return "\n".join(parts).strip()


def _parse_json_object(raw_text: str) -> Dict[str, Any]:
    raw_text = (raw_text or "").strip()
    try:
        parsed = json.loads(raw_text)
        if isinstance(parsed, dict):
            return parsed
    except (TypeError, ValueError, json.JSONDecodeError):
        pass

    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(raw_text[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except (TypeError, ValueError, json.JSONDecodeError):
            pass

    raise RuntimeError("Модель вернула ответ не в JSON-формате")


def _build_result(parsed: Dict[str, Any], *, provider: str = "") -> Dict[str, Any]:
    prompt_ru = str(parsed.get("prompt_ru") or "").strip()
    prompt_en = str(parsed.get("prompt_en") or "").strip()
    if not prompt_ru:
        raise RuntimeError("prompt_ru пустой")
    if not prompt_en:
        raise RuntimeError("prompt_en пустой")
    return {
        "prompt_ru": prompt_ru,
        "prompt_en": prompt_en,
        "provider": provider,
        "raw": parsed,
    }


def _build_gpt_audio_content(*, audio_bytes: bytes, audio_format: str) -> Dict[str, Any]:
    return {
        "type": "input_audio",
        "input_audio": {
            "data": base64.b64encode(audio_bytes).decode("ascii"),
            "format": audio_format,
        },
    }


def _build_gpt_user_content(
    *,
    user_instruction: str,
    image_url: str = "",
    audio_bytes: bytes | None = None,
    audio_format: str = "",
) -> list[Dict[str, Any]]:
    content: list[Dict[str, Any]] = [
        {"type": "input_text", "text": user_instruction},
    ]
    if image_url:
        content.append({"type": "input_image", "image_url": image_url})
    if audio_bytes:
        content.append(
            _build_gpt_audio_content(
                audio_bytes=audio_bytes,
                audio_format=audio_format or "ogg",
            )
        )
    return content


def _is_fast_fallback_application_error(data: Dict[str, Any]) -> bool:
    try:
        body_code = int(data.get("code", 0) or 0)
    except (TypeError, ValueError):
        body_code = 0
    message = str(data.get("msg") or data.get("message") or "").lower()
    return body_code >= 500 or "server exception" in message or "try again later" in message


class PromptAnalyzerV2Service:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or config.KIE_AI_API_KEY
        self.model = model or config.PHOTO_PROMPT_MODEL
        self.base_url = config.KIE_BASE_URL

    async def _analyze_with_gpt55(
        self,
        *,
        image_url: str,
        user_instruction: str,
        headers: Dict[str, str],
        audio_bytes: bytes | None = None,
        audio_format: str = "",
    ) -> Dict[str, Any]:
        payload = {
            "model": self.model,
            "stream": False,
            "input": [
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": SYSTEM_PROMPT}],
                },
                {
                    "role": "user",
                    "content": _build_gpt_user_content(
                        user_instruction=user_instruction,
                        image_url=image_url,
                        audio_bytes=audio_bytes,
                        audio_format=audio_format,
                    ),
                },
            ],
            "reasoning": {"effort": "medium"},
        }

        timeout = aiohttp.ClientTimeout(total=120)
        data: Optional[Dict[str, Any]] = None
        for attempt in range(GPT55_MAX_ATTEMPTS):
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    f"{self.base_url}/codex/v1/responses",
                    json=payload,
                    headers=headers,
                ) as response:
                    text = await response.text()
                    if response.status >= 500:
                        logger.info(
                            "GPT-5.5 prompt analyzer HTTP 5xx: status=%s body=%s",
                            response.status,
                            text[:500],
                        )
                        if attempt < GPT55_MAX_ATTEMPTS - 1:
                            await asyncio.sleep(2**attempt)
                            continue
                        raise RuntimeError(f"GPT-5.5 недоступен. Код: {response.status}")
                    if response.status == 429:
                        if attempt < GPT55_MAX_ATTEMPTS - 1:
                            await asyncio.sleep(2**attempt)
                            continue
                        raise RuntimeError("GPT-5.5 временно ограничил запросы")
                    if response.status >= 400:
                        raise RuntimeError(f"GPT-5.5 ошибка. Код: {response.status}")

                    try:
                        data = json.loads(text)
                    except json.JSONDecodeError as exc:
                        raise RuntimeError("GPT-5.5 вернул некорректный JSON") from exc

                    try:
                        body_code = int(data.get("code", 0) or 0)
                    except (TypeError, ValueError):
                        body_code = 0
                    if _is_fast_fallback_application_error(data):
                        if attempt < GPT55_MAX_ATTEMPTS - 1:
                            await asyncio.sleep(2**attempt)
                            data = None
                            continue
                        raise RuntimeError(f"GPT-5.5 upstream error: {body_code}")
                    if body_code >= 400:
                        if body_code in GPT55_RETRYABLE_BODY_CODES and attempt < GPT55_MAX_ATTEMPTS - 1:
                            await asyncio.sleep(2**attempt)
                            data = None
                            continue
                        raise RuntimeError(f"GPT-5.5 вернул ошибку: {body_code}")
            break

        if data is None:
            raise RuntimeError("GPT-5.5 не вернул данных после всех попыток")
        return _build_result(
            _parse_json_object(_extract_output_text(data)),
            provider="gpt-5.5",
        )

    async def _analyze_with_claude(
        self,
        *,
        image_url: str,
        user_instruction: str,
        headers: Dict[str, str],
    ) -> Dict[str, Any]:
        content: list[Dict[str, Any]] = [
            {"type": "text", "text": SYSTEM_PROMPT + "\n\n" + user_instruction},
        ]
        if image_url:
            content.append(
                {
                    "type": "image",
                    "source": {"type": "url", "url": image_url},
                }
            )

        payload = {
            "model": "claude-haiku-4-5",
            "stream": False,
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": content}],
        }
        timeout = aiohttp.ClientTimeout(total=90)
        data: Optional[Dict[str, Any]] = None
        for attempt in range(CLAUDE_MAX_ATTEMPTS):
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    f"{self.base_url}/claude/v1/messages",
                    json=payload,
                    headers=headers,
                ) as response:
                    text = await response.text()
                    if response.status >= 500:
                        if attempt < CLAUDE_MAX_ATTEMPTS - 1:
                            await asyncio.sleep(2**attempt)
                            continue
                        raise RuntimeError(f"Claude Haiku недоступен. Код: {response.status}")
                    if response.status >= 400:
                        raise RuntimeError(f"Claude Haiku недоступен. Код: {response.status}")
                    try:
                        data = json.loads(text)
                    except json.JSONDecodeError as exc:
                        raise RuntimeError("Claude Haiku вернул некорректный JSON") from exc
            break

        if data is None:
            raise RuntimeError("Claude Haiku не вернул данных после всех попыток")
        raw_output = _extract_claude_text(data)
        if not raw_output:
            raise RuntimeError("Claude Haiku вернул пустой ответ")
        return _build_result(_parse_json_object(raw_output), provider="claude-haiku-4-5")

    async def analyze_prompt(
        self,
        *,
        text: str = "",
        image_url: str = "",
        audio_bytes: bytes | None = None,
        audio_format: str = "",
    ) -> Dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("KIE_AI_API_KEY is not configured")

        text = (text or "").strip()
        image_url = (image_url or "").strip()
        has_audio = bool(audio_bytes)
        if not text and not image_url and not has_audio:
            raise ValueError("text, image_url or audio_bytes is required")

        input_notes: list[str] = []
        if text:
            input_notes.append(
                "User text description. Treat it as the primary creative intent:\n" + text
            )
        if image_url:
            input_notes.append(
                "A reference image is attached. Preserve its visible subject, composition, "
                "lighting, palette, style, pose, background, and camera feel unless the user "
                "explicitly asks to change something."
            )
        if has_audio:
            input_notes.append(
                "A voice message is attached. Listen to it directly and treat the spoken idea "
                "as creative direction. Do not output a transcript or voice analysis."
            )

        user_instruction = (
            "Create a polished image-generation prompt from the supplied inputs.\n\n"
            + "\n\n".join(input_notes)
            + "\n\nReturn only prompt_ru and prompt_en according to the JSON schema."
        )
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        gpt_error: Optional[Exception] = None
        try:
            return await self._analyze_with_gpt55(
                image_url=image_url,
                user_instruction=user_instruction,
                headers=headers,
                audio_bytes=audio_bytes,
                audio_format=audio_format,
            )
        except Exception as exc:
            gpt_error = exc
            if has_audio:
                raise RuntimeError(f"Не удалось разобрать голосовой запрос: {exc}") from exc

        try:
            result = await self._analyze_with_claude(
                image_url=image_url,
                user_instruction=user_instruction,
                headers=headers,
            )
            logger.info(
                "GPT-5.5 prompt analyzer failed (%s); Claude Haiku fallback succeeded",
                gpt_error,
            )
            return result
        except Exception as fallback_exc:
            logger.error(
                "Prompt analyzer fallback failed after GPT-5.5 failure (%s): %s",
                gpt_error,
                fallback_exc,
            )
            raise RuntimeError(
                f"Не удалось составить промпт через fallback: {fallback_exc}"
            ) from fallback_exc


prompt_analyzer_v2_service = PromptAnalyzerV2Service()
