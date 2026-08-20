"""Photo-to-prompt service via Kie GPT-5.4 with GPT-5.2 and Claude fallback."""

import asyncio
import base64
import json
import logging
from typing import Any, Dict, Optional

import aiohttp

from bot.config import config
from bot.services.photo_analysis_media import image_source_to_analysis_input

logger = logging.getLogger(__name__)

PRIMARY_MODEL = "gpt-5-4"
FALLBACK_MODEL = "gpt-5-2"
GPT_MAX_ATTEMPTS = 3
GPT_RETRYABLE_BODY_CODES = {429}
CLAUDE_MAX_ATTEMPTS = 2


SYSTEM_PROMPT = """
You are a senior prompt analyst for photorealistic AI image generation.

Your task:
Analyze the attached reference image and/or voice prompt, then create a polished generation prompt.
If both image and audio are attached, listen to the audio in the same analysis pass and combine it with the reference image.
If only audio is attached, turn the spoken request into a strong standalone prompt without inventing image-specific facts not requested by the user.

Primary output style:
- The user-facing "prompt_ru" is the main result. Write it in Russian as one natural, dense editorial/photo prompt, similar to a fashion or commercial reference description.
- Use one cohesive paragraph, not a bullet list and not a technical checklist.
- Target length for "prompt_ru": 900-1600 characters when an image has enough detail; 500-1000 characters for sparse images or audio-only requests.
- Follow this rhythm when applicable: shot size and subject, hair/face/expression, pose and gaze, clothing and accessories with materials/textures, framing and camera angle, focus/depth of field, background/environment, lighting, color palette, contrast, visual mood, genre/style.
- Prefer concrete visual language: "средний кадр", "от чуть выше колен", "легкий низкий ракурс", "малая глубина резкости", "резкий фокус на модели", "искусственное драматичное освещение", "насыщенные неоновые акценты", when those ideas match the reference.
- Preserve the scene's real visual relationships: foreground/background separation, occlusion, visible materials, light direction, reflections, color accents, atmosphere.
- Do not add generic filler such as "8k", "masterpiece", "ultra detailed", "best quality" unless the visible style clearly calls for a short quality phrase.
- Do not use forensic, pixel-by-pixel, medical, anatomical, or identity-preservation jargon.

Prompt fields:
- "prompt_ru": polished Russian prompt in the style above.
- "prompt_en": faithful English version optimized for image generation models, also one cohesive paragraph.
- "negative_prompt": concise English list of defects to avoid.
- "model_hint": short Russian recommendation of the best model/workflow.
- "key_details": 3-7 short visible details that most affect similarity.

Strict safety rules:
- Do not identify any person or speaker.
- Do not guess names, ethnicity, nationality, private attributes, or exact age.
- You may use a broad visible age presentation only if it is visually obvious, such as "young adult" / "молодой взрослый человек"; never provide a number.
- Describe only visible visual features and user-provided creative instructions.
- Preserve subject appearance visually through neutral descriptions: face shape, hair, pose, clothing, proportions, accessories, but do not claim who the person is.
- If audio is attached, transcribe/summarize only the user's creative request and neutral voice qualities such as tone, pace and emotion.
- Also create a Gemini Omni prompt when audio is attached or when it is useful for video/image workflows.
- Return only valid JSON. No markdown. No explanation.

JSON schema:
{
  "prompt_en": "Detailed English image generation prompt",
  "prompt_ru": "Natural Russian editorial-style prompt for the user",
  "negative_prompt": "Common defects to avoid",
  "model_hint": "Short Russian recommendation which model to use",
  "key_details": ["detail 1", "detail 2", "detail 3"],
  "voice_transcript": "Transcript of attached voice/audio prompt, or empty string",
  "voice_prompt_summary_ru": "Short Russian summary of the attached voice/audio prompt, or empty string",
  "voice_description_ru": "Neutral Russian description of voice/tone/pace/emotion, or empty string",
  "gemini_omni_prompt": "Optional polished prompt for Gemini Omni video/image workflows when voice context asks for it"
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


def _extract_claude_text(data: dict[str, Any]) -> str:
    parts: list[str] = []
    for block in data.get("content", []) or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            if text:
                parts.append(str(text))
    return "\n".join(parts).strip()


def _parse_json_object(raw_text: str) -> Dict[str, Any]:
    raw_text = (raw_text or "").strip()

    try:
        parsed = json.loads(raw_text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(raw_text[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    return {
        "prompt_en": raw_text,
        "prompt_ru": "Не удалось разобрать структурированный ответ. Используйте английский prompt выше.",
        "negative_prompt": "blurry, low quality, distorted face, bad anatomy, extra fingers, bad hands, watermark, text, logo, overexposed, underexposed, plastic skin, unnatural eyes, asymmetry",
        "model_hint": "Для похожей генерации попробуйте Nano Banana Pro. Для редактирования по исходнику — Seedream 4.5 Edit.",
        "key_details": [],
    }


def _is_fast_fallback_application_error(data: Dict[str, Any]) -> bool:
    """KIE sometimes returns HTTP 200 with body code 500 for upstream outages."""
    try:
        body_code = int(data.get("code", 0) or 0)
    except (TypeError, ValueError):
        body_code = 0

    message = str(data.get("msg") or data.get("message") or "").lower()
    return (
        body_code >= 500
        or "server exception" in message
        or "try again later" in message
    )


def _build_result(parsed: Dict[str, Any], *, provider: str = "") -> Dict[str, Any]:
    prompt_en = str(parsed.get("prompt_en") or "").strip()
    prompt_ru = str(parsed.get("prompt_ru") or "").strip()
    negative_prompt = str(parsed.get("negative_prompt") or "").strip()
    model_hint = str(parsed.get("model_hint") or "").strip()
    gemini_omni_prompt = str(parsed.get("gemini_omni_prompt") or "").strip()
    voice_transcript = str(parsed.get("voice_transcript") or "").strip()
    voice_prompt_summary_ru = str(parsed.get("voice_prompt_summary_ru") or "").strip()
    voice_description_ru = str(parsed.get("voice_description_ru") or "").strip()
    key_details = parsed.get("key_details") or []

    if not prompt_en:
        raise RuntimeError("prompt_en пустой")

    if not negative_prompt:
        negative_prompt = (
            "blurry, low quality, distorted face, bad anatomy, extra fingers, "
            "bad hands, watermark, text, logo, overexposed, underexposed, "
            "plastic skin, unnatural eyes, asymmetry"
        )

    if not model_hint:
        model_hint = (
            "Nano Banana Pro — для похожей генерации. "
            "Seedream 4.5 Edit — для редактирования по исходнику."
        )

    return {
        "prompt_en": prompt_en,
        "prompt_ru": prompt_ru,
        "negative_prompt": negative_prompt,
        "model_hint": model_hint,
        "gemini_omni_prompt": gemini_omni_prompt,
        "voice_transcript": voice_transcript,
        "voice_prompt_summary_ru": voice_prompt_summary_ru,
        "voice_description_ru": voice_description_ru,
        "key_details": key_details if isinstance(key_details, list) else [],
        "provider": provider,
        "raw": parsed,
    }


def _build_gpt_audio_content(
    *,
    audio_bytes: bytes,
    audio_format: str,
) -> Dict[str, Any]:
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


def _build_claude_image_source(image_url: str) -> dict[str, str]:
    """Build Claude image input for the final image-only fallback."""
    if image_url.startswith("data:image/") and "," in image_url:
        header, encoded = image_url.split(",", 1)
        media_type = header.removeprefix("data:").split(";", 1)[0]
        return {
            "type": "base64",
            "media_type": media_type,
            "data": encoded,
        }
    return {"type": "url", "url": image_url}


class PhotoPromptService:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        fallback_model: Optional[str] = None,
    ):
        self.api_key = api_key or config.KIE_AI_API_KEY
        # Keep this route deterministic: production .env must not silently switch
        # the prompt-analysis model back to an older value.
        self.model = model or PRIMARY_MODEL
        self.fallback_model = fallback_model or FALLBACK_MODEL
        self.base_url = config.KIE_BASE_URL

    async def _analyze_with_gpt(
        self,
        *,
        model: str,
        image_url: str,
        user_instruction: str,
        headers: Dict[str, str],
        audio_bytes: bytes | None = None,
        audio_format: str = "",
    ) -> Dict[str, Any]:
        payload = {
            "model": model,
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
            "reasoning": {"effort": "high"},
        }

        timeout = aiohttp.ClientTimeout(total=120)
        data: Optional[Dict[str, Any]] = None

        for attempt in range(GPT_MAX_ATTEMPTS):
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    f"{self.base_url}/codex/v1/responses",
                    json=payload,
                    headers=headers,
                ) as response:
                    text = await response.text()

                    if response.status >= 500:
                        logger.info(
                            "%s HTTP 5xx: status=%s body=%s attempt=%d",
                            model,
                            response.status,
                            text[:500],
                            attempt,
                        )
                        if audio_bytes and attempt < GPT_MAX_ATTEMPTS - 1:
                            await asyncio.sleep(2**attempt)
                            continue
                        raise RuntimeError(
                            f"{model} недоступен. Код: {response.status}"
                        )

                    if response.status == 429:
                        logger.warning(
                            "%s rate limited: status=%s body=%s attempt=%d",
                            model,
                            response.status,
                            text[:500],
                            attempt,
                        )
                        if attempt < GPT_MAX_ATTEMPTS - 1:
                            await asyncio.sleep(2**attempt)
                            continue
                        raise RuntimeError(f"{model} временно ограничил запросы")

                    if response.status >= 400:
                        raise RuntimeError(
                            f"{model} ошибка. Код: {response.status}"
                        )

                    try:
                        data = json.loads(text)
                    except Exception as exc:
                        raise RuntimeError(
                            f"{model} вернул некорректный JSON"
                        ) from exc

                    raw_body_code = data.get("code") if isinstance(data, dict) else None
                    try:
                        body_code = int(raw_body_code or 0)
                    except (TypeError, ValueError):
                        body_code = 0

                    if _is_fast_fallback_application_error(data):
                        if audio_bytes and attempt < GPT_MAX_ATTEMPTS - 1:
                            logger.warning(
                                "%s application upstream error for audio, retrying: %s attempt=%d",
                                model,
                                data,
                                attempt,
                            )
                            await asyncio.sleep(2**attempt)
                            data = None
                            continue
                        logger.info(
                            "%s application upstream error, switching model: %s",
                            model,
                            data,
                        )
                        raise RuntimeError(f"{model} upstream error: {body_code}")

                    if body_code >= 400:
                        logger.warning(
                            "%s application error in body: %s attempt=%d",
                            model,
                            data,
                            attempt,
                        )
                        if (
                            body_code in GPT_RETRYABLE_BODY_CODES
                            and attempt < GPT_MAX_ATTEMPTS - 1
                        ):
                            await asyncio.sleep(2**attempt)
                            data = None
                            continue
                        raise RuntimeError(f"{model} вернул ошибку: {body_code}")
            break

        if data is None:
            raise RuntimeError(f"{model} не вернул данных после всех попыток")

        raw_output = _extract_output_text(data)
        parsed = _parse_json_object(raw_output)
        # Existing Telegram formatter treats any non-empty provider as a fallback
        # note. Keep the primary provider empty; expose only the actual fallback.
        provider = "" if model == self.model else model
        return _build_result(parsed, provider=provider)

    async def _analyze_with_gpt55(
        self,
        *,
        image_url: str,
        user_instruction: str,
        headers: dict[str, str],
        audio_bytes: bytes | None = None,
        audio_format: str = "",
    ) -> dict[str, Any]:
        """Compatibility entrypoint that now runs GPT-5.4 -> GPT-5.2.

        Older callers/tests use the historical method name. Keeping the seam
        avoids bypassing mocks and integrations while preserving the current
        production model order.
        """
        primary_error: Exception | None = None
        try:
            return await self._analyze_with_gpt(
                model=self.model,
                image_url=image_url,
                user_instruction=user_instruction,
                headers=headers,
                audio_bytes=audio_bytes,
                audio_format=audio_format,
            )
        except Exception as exc:  # noqa: BLE001 - provider fallback boundary
            primary_error = exc
            logger.warning(
                "Photo prompt primary model %s failed; trying %s: %s",
                self.model,
                self.fallback_model,
                exc,
            )

        if not self.fallback_model or self.fallback_model == self.model:
            raise RuntimeError(
                f"Не удалось разобрать запрос через {self.model}: {primary_error}"
            ) from primary_error

        try:
            return await self._analyze_with_gpt(
                model=self.fallback_model,
                image_url=image_url,
                user_instruction=user_instruction,
                headers=headers,
                audio_bytes=audio_bytes,
                audio_format=audio_format,
            )
        except Exception as fallback_exc:
            raise RuntimeError(
                f"{self.model}: {primary_error}; "
                f"{self.fallback_model}: {fallback_exc}"
            ) from fallback_exc

    async def _analyze_with_claude(
        self,
        *,
        image_url: str,
        user_instruction: str,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        """Final image-only fallback after both GPT models fail."""
        payload = {
            "model": "claude-haiku-4-5",
            "stream": False,
            "max_tokens": 2048,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": SYSTEM_PROMPT + "\n\n" + user_instruction,
                        },
                        {
                            "type": "image",
                            "source": _build_claude_image_source(image_url),
                        },
                    ],
                }
            ],
        }

        timeout = aiohttp.ClientTimeout(total=90)
        data: dict[str, Any] | None = None
        for attempt in range(CLAUDE_MAX_ATTEMPTS):
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.post(
                    f"{self.base_url}/claude/v1/messages",
                    json=payload,
                    headers=headers,
                ) as response,
            ):
                text = await response.text()

                if response.status >= 500:
                    logger.warning(
                        "Claude Haiku fallback HTTP 5xx: status=%s body=%s attempt=%d",
                        response.status,
                        text[:1000],
                        attempt,
                    )
                    if attempt < CLAUDE_MAX_ATTEMPTS - 1:
                        await asyncio.sleep(2**attempt)
                        continue
                    raise RuntimeError(
                        f"Claude Haiku недоступен. Код: {response.status}"
                    )

                if response.status >= 400:
                    logger.error(
                        "Claude Haiku fallback failed: status=%s body=%s",
                        response.status,
                        text[:2000],
                    )
                    raise RuntimeError(
                        f"Claude Haiku недоступен. Код: {response.status}"
                    )

                try:
                    data = json.loads(text)
                except Exception as exc:
                    raise RuntimeError(
                        "Claude Haiku вернул некорректный JSON"
                    ) from exc
            break

        if data is None:
            raise RuntimeError("Claude Haiku не вернул данных после всех попыток")

        raw_output = _extract_claude_text(data)
        if not raw_output:
            raise RuntimeError("Claude Haiku вернул пустой ответ")

        parsed = _parse_json_object(raw_output)
        return _build_result(parsed, provider="claude-haiku-4-5")

    async def analyze_photo(
        self,
        *,
        image_url: str,
        preserve: str = "",
        goal: str = "",
        user_note: str = "",
        audio_bytes: bytes | None = None,
        audio_format: str = "",
    ) -> Dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("KIE_AI_API_KEY is not configured")

        image_url = (image_url or "").strip()
        if image_url:
            image_url = image_source_to_analysis_input(image_url)
        has_image = bool(image_url)
        has_audio = bool(audio_bytes)
        if not has_image and not has_audio:
            raise ValueError("image_url or audio_bytes is required")

        extra_blocks: list[str] = []
        if user_note:
            extra_blocks.append(f"Additional text instruction from user:\n{user_note}")
        if audio_bytes:
            if has_image:
                audio_instruction = (
                    "Listen to the audio prompt directly in this same request. "
                    "Use it as the user's creative direction, include its transcript/summary "
                    "in the JSON fields, and combine it with the reference photo."
                )
            else:
                audio_instruction = (
                    "Listen to the attached audio prompt directly in this request. "
                    "Turn the spoken idea into a polished standalone generation prompt, "
                    "include its transcript/summary in the JSON fields, and create a useful "
                    "Gemini Omni prompt from the voice context."
                )
            extra_blocks.append(
                "Attached audio prompt:\n"
                f"{audio_instruction}"
            )
        extra_instruction = "\n\n".join(extra_blocks)

        if has_image:
            task = (
                "Analyze this image and create a precise prompt for generating a "
                "visually similar image."
            )
            default_goal = "Generate a visually similar image based on the reference."
            default_preserve = (
                "Subject appearance, composition, lighting, style, colors, pose, "
                "background, and camera feel."
            )
        else:
            task = (
                "Listen to the attached audio prompt and create a precise prompt for "
                "generating the image or scene requested by the user."
            )
            default_goal = (
                "Create a polished image/video generation prompt from the user's "
                "spoken idea."
            )
            default_preserve = (
                "The user's requested subject, mood, style, action, camera movement, "
                "setting, and constraints."
            )

        user_instruction = (
            f"{task}\n\n"
            f"User goal:\n{goal or default_goal}\n\n"
            f"Important details to preserve:\n{preserve or default_preserve}\n\n"
            f"{extra_instruction + chr(10) + chr(10) if extra_instruction else ''}"
            f"Return valid JSON only according to the required schema."
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        gpt_error: Exception | None = None
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
                target = "фото и голос" if has_image else "голос"
                raise RuntimeError(
                    f"Не удалось разобрать {target} через GPT-цепочку: {exc}"
                ) from exc

        try:
            result = await self._analyze_with_claude(
                image_url=image_url,
                user_instruction=user_instruction,
                headers=headers,
            )
            logger.info(
                "Photo prompt GPT chain failed (%s); Claude Haiku fallback succeeded",
                gpt_error,
            )
            return result
        except Exception as fallback_exc:
            logger.error(
                "Claude Haiku fallback failed after GPT chain failure (%s): %s",
                gpt_error,
                fallback_exc,
            )
            raise RuntimeError(
                f"Не удалось разобрать фото через fallback: {fallback_exc}"
            ) from fallback_exc


photo_prompt_service = PhotoPromptService()
