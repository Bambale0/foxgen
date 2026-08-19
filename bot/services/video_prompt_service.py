"""Video to prompt service via Kie GPT 5.5 Responses API."""

import asyncio
import base64
import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

import aiohttp

from bot.config import config
from bot.services.photo_prompt_service import (
    GPT_MAX_ATTEMPTS as GPT55_MAX_ATTEMPTS,
    GPT_RETRYABLE_BODY_CODES as GPT55_RETRYABLE_BODY_CODES,
    _extract_output_text,
    _is_fast_fallback_application_error,
)

logger = logging.getLogger(__name__)

VIDEO_PROMPT_FRAME_COUNT = 6
VIDEO_PROMPT_FRAME_TIMEOUT_SECONDS = 60


VIDEO_SYSTEM_PROMPT = """
You are a senior prompt analyst for photorealistic AI video generation.

Your task:
Analyze the attached reference video file and create a polished prompt for generating a visually similar video. Focus on what a video generation model needs: subject/action, shot size, camera movement, temporal rhythm, scene transitions, environment, lighting, color, motion physics, visual style, and mood.

Primary output style:
- The user-facing "prompt_ru" is the main result. Write it in Russian as one natural, dense cinematic/video prompt, similar to a fashion/editorial reference description but adapted for motion.
- Use one cohesive paragraph, not a bullet list and not a technical checklist.
- Target length for "prompt_ru": 1100-2200 characters when the video has enough detail.
- Follow this rhythm when applicable: opening frame and shot size, subject/objects and visible appearance, action over time, pose/gaze/gestures, camera path and lens feel, pacing and timing, environment/background, lighting changes, color palette, depth of field/focus behavior, atmosphere, final frame.
- Preserve the motion language: handheld/static, dolly, push-in, pull-out, orbit, pan, tilt, tracking, slow motion, speed ramp, natural body/object movement, reflections, occlusion, foreground/background separation.
- Do not add generic filler such as "8k", "masterpiece", "ultra detailed", "best quality" unless the visible style clearly calls for a short quality phrase.
- Do not use forensic, pixel-by-pixel, biometric, identity-preservation, medical, or anatomical jargon.

Prompt fields:
- "prompt_ru": polished Russian video generation prompt in the style above.
- "prompt_en": faithful English version optimized for video generation models, also one cohesive paragraph.
- "negative_prompt": concise English list of video defects to avoid.
- "camera_movement_ru": short Russian summary of camera movement and framing.
- "timeline_ru": 3-6 short Russian beats that describe the clip over time.
- "visual_style_ru": short Russian summary of style, light, color and mood.
- "audio_notes_ru": short Russian note about audible elements if they matter, or empty string.
- "model_hint": short Russian recommendation of the best model/workflow.
- "key_details": 4-8 short visible/motion details that most affect similarity.

Strict safety rules:
- Do not identify any person.
- Do not guess names, ethnicity, nationality, private attributes, or exact age.
- You may use broad visible age presentation only if visually obvious, such as "young adult" / "молодой взрослый человек"; never provide a number.
- Describe only visible visual features, motion, environment, style and user-provided creative instructions.
- Return only valid JSON. No markdown. No explanation.

JSON schema:
{
  "prompt_en": "Detailed English video generation prompt",
  "prompt_ru": "Natural Russian cinematic video prompt for the user",
  "negative_prompt": "Common video defects to avoid",
  "camera_movement_ru": "Camera movement and framing summary",
  "timeline_ru": ["beat 1", "beat 2", "beat 3"],
  "visual_style_ru": "Style, lighting, color and mood summary",
  "audio_notes_ru": "Audio note, or empty string",
  "model_hint": "Short Russian recommendation which model to use",
  "key_details": ["detail 1", "detail 2", "detail 3", "detail 4"]
}
""".strip()


def _parse_video_json_object(raw_text: str) -> Dict[str, Any]:
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
        "negative_prompt": "blurry, low quality, flicker, jitter, warped motion, distorted face, bad anatomy, bad hands, temporal inconsistency, duplicated objects, watermark, text, logo, overexposed, underexposed",
        "camera_movement_ru": "",
        "timeline_ru": [],
        "visual_style_ru": "",
        "audio_notes_ru": "",
        "model_hint": "Для похожего видео попробуйте Gemini Omni Video, Seedance 2.0 или Grok Imagine 1.5 в зависимости от нужного режима.",
        "key_details": [],
    }


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _build_video_result(parsed: Dict[str, Any], *, provider: str = "") -> Dict[str, Any]:
    prompt_en = str(parsed.get("prompt_en") or "").strip()
    prompt_ru = str(parsed.get("prompt_ru") or "").strip()
    negative_prompt = str(parsed.get("negative_prompt") or "").strip()
    camera_movement_ru = str(parsed.get("camera_movement_ru") or "").strip()
    visual_style_ru = str(parsed.get("visual_style_ru") or "").strip()
    audio_notes_ru = str(parsed.get("audio_notes_ru") or "").strip()
    model_hint = str(parsed.get("model_hint") or "").strip()
    timeline_ru = _as_string_list(parsed.get("timeline_ru"))
    key_details = _as_string_list(parsed.get("key_details"))

    if not prompt_ru and not prompt_en:
        raise RuntimeError("video prompt пустой")
    if not prompt_ru:
        prompt_ru = "Используйте английский prompt ниже как основу для генерации похожего видео."
    if not prompt_en:
        prompt_en = prompt_ru

    if not negative_prompt:
        negative_prompt = (
            "blurry, low quality, flicker, jitter, warped motion, distorted face, "
            "bad anatomy, bad hands, temporal inconsistency, duplicated objects, "
            "watermark, text, logo, overexposed, underexposed"
        )

    if not model_hint:
        model_hint = (
            "Gemini Omni Video — для работы с видео-референсом. Seedance 2.0 — "
            "для похожего движения/камеры. Grok Imagine 1.5 — для коротких I2V-сцен."
        )

    return {
        "prompt_en": prompt_en,
        "prompt_ru": prompt_ru,
        "negative_prompt": negative_prompt,
        "camera_movement_ru": camera_movement_ru,
        "timeline_ru": timeline_ru,
        "visual_style_ru": visual_style_ru,
        "audio_notes_ru": audio_notes_ru,
        "model_hint": model_hint,
        "key_details": key_details,
        "provider": provider,
        "raw": parsed,
    }


def _build_gpt_video_user_content(
    *,
    user_instruction: str,
    video_url: str,
    filename: str,
) -> list[Dict[str, Any]]:
    return [
        {"type": "input_text", "text": user_instruction},
        {
            "type": "input_file",
            "file_url": video_url,
            "filename": filename or "reference_video.mp4",
        },
    ]


def _build_gpt_frame_user_content(
    *,
    user_instruction: str,
    frame_data_urls: list[str],
) -> list[Dict[str, Any]]:
    content: list[Dict[str, Any]] = [{"type": "input_text", "text": user_instruction}]
    for index, frame_url in enumerate(frame_data_urls, start=1):
        content.append(
            {
                "type": "input_image",
                "image_url": frame_url,
            }
        )
    return content


def _extract_frame_data_urls_sync(
    video_bytes: bytes,
    *,
    duration_seconds: int | float = 0,
    max_frames: int = VIDEO_PROMPT_FRAME_COUNT,
) -> list[str]:
    if not video_bytes:
        raise RuntimeError("video bytes are required for frame fallback")

    max_frames = max(1, int(max_frames or VIDEO_PROMPT_FRAME_COUNT))
    duration = float(duration_seconds or 0)
    fps = max_frames / duration if duration > 0 else 1.0
    fps = max(0.05, min(2.0, fps))

    with tempfile.TemporaryDirectory(prefix="video_prompt_") as temp_dir:
        temp_path = Path(temp_dir)
        input_path = temp_path / "input_video"
        input_path.write_bytes(video_bytes)
        output_pattern = str(temp_path / "frame_%03d.jpg")

        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(input_path),
            "-vf",
            f"fps={fps:.4f},scale=768:-2:force_original_aspect_ratio=decrease",
            "-frames:v",
            str(max_frames),
            "-q:v",
            "5",
            output_pattern,
        ]
        try:
            subprocess.run(
                command,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=VIDEO_PROMPT_FRAME_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Не удалось извлечь кадры из видео: timeout") from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or b"").decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Не удалось извлечь кадры из видео: {stderr[:300]}"
            ) from exc

        frame_urls: list[str] = []
        for frame_path in sorted(temp_path.glob("frame_*.jpg"))[:max_frames]:
            encoded = base64.b64encode(frame_path.read_bytes()).decode("ascii")
            frame_urls.append(f"data:image/jpeg;base64,{encoded}")

    if not frame_urls:
        raise RuntimeError("Не удалось извлечь кадры из видео")
    return frame_urls


class VideoPromptService:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or config.KIE_AI_API_KEY
        self.model = model or config.PHOTO_PROMPT_MODEL
        self.base_url = config.KIE_BASE_URL

    async def _analyze_with_gpt55(
        self,
        *,
        video_url: str,
        user_instruction: str,
        headers: Dict[str, str],
        filename: str,
        max_attempts: int = GPT55_MAX_ATTEMPTS,
    ) -> Dict[str, Any]:
        payload = {
            "model": self.model,
            "stream": False,
            "input": [
                {
                    "role": "system",
                    "content": [
                        {"type": "input_text", "text": VIDEO_SYSTEM_PROMPT}
                    ],
                },
                {
                    "role": "user",
                    "content": _build_gpt_video_user_content(
                        user_instruction=user_instruction,
                        video_url=video_url,
                        filename=filename,
                    ),
                },
            ],
            "reasoning": {"effort": "high"},
        }

        timeout = aiohttp.ClientTimeout(total=180)
        data: Optional[Dict[str, Any]] = None

        max_attempts = max(1, int(max_attempts or GPT55_MAX_ATTEMPTS))
        for attempt in range(max_attempts):
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    f"{self.base_url}/codex/v1/responses",
                    json=payload,
                    headers=headers,
                ) as response:
                    text = await response.text()

                    if response.status >= 500:
                        logger.warning(
                            "Video prompt GPT-5.5 HTTP 5xx: status=%s body=%s attempt=%d",
                            response.status,
                            text[:800],
                            attempt,
                        )
                        if attempt < max_attempts - 1:
                            await asyncio.sleep(2**attempt)
                            continue
                        raise RuntimeError(
                            f"GPT-5.5 недоступен. Код: {response.status}"
                        )

                    if response.status == 429:
                        logger.warning(
                            "Video prompt GPT-5.5 rate limited: status=%s body=%s attempt=%d",
                            response.status,
                            text[:800],
                            attempt,
                        )
                        if attempt < max_attempts - 1:
                            await asyncio.sleep(2**attempt)
                            continue
                        raise RuntimeError("GPT-5.5 временно ограничил запросы")

                    if response.status >= 400:
                        raise RuntimeError(f"GPT-5.5 ошибка. Код: {response.status}")

                    try:
                        data = json.loads(text)
                    except Exception:
                        raise RuntimeError("GPT-5.5 вернул некорректный JSON")

                    raw_body_code = data.get("code") if isinstance(data, dict) else None
                    try:
                        body_code = int(raw_body_code or 0)
                    except (TypeError, ValueError):
                        body_code = 0

                    if _is_fast_fallback_application_error(data):
                        logger.warning(
                            "Video prompt GPT-5.5 application upstream error: %s attempt=%d",
                            data,
                            attempt,
                        )
                        if attempt < max_attempts - 1:
                            await asyncio.sleep(2**attempt)
                            data = None
                            continue
                        raise RuntimeError(f"GPT-5.5 upstream error: {body_code}")

                    if body_code >= 400:
                        logger.warning(
                            "Video prompt GPT-5.5 application error in body: %s attempt=%d",
                            data,
                            attempt,
                        )
                        if (
                            body_code in GPT55_RETRYABLE_BODY_CODES
                            and attempt < max_attempts - 1
                        ):
                            await asyncio.sleep(2**attempt)
                            data = None
                            continue
                        raise RuntimeError(f"GPT-5.5 вернул ошибку: {body_code}")
            break

        if data is None:
            raise RuntimeError("GPT-5.5 не вернул данных после всех попыток")

        raw_output = _extract_output_text(data)
        parsed = _parse_video_json_object(raw_output)
        return _build_video_result(parsed, provider="gpt-5.5")

    async def _analyze_frames_with_gpt55(
        self,
        *,
        frame_data_urls: list[str],
        user_instruction: str,
        headers: Dict[str, str],
    ) -> Dict[str, Any]:
        if not frame_data_urls:
            raise RuntimeError("video frame fallback has no frames")

        frame_instruction = (
            user_instruction
            + "\n\nNative video-file input was unavailable, so the attached images "
            "are representative frames sampled from the source video in chronological "
            "order. Analyze them as a temporal sequence and infer camera movement, "
            "motion rhythm and transitions from frame-to-frame differences. Be honest "
            "about visible information and do not invent unavailable audio."
        )
        payload = {
            "model": self.model,
            "stream": False,
            "input": [
                {
                    "role": "system",
                    "content": [
                        {"type": "input_text", "text": VIDEO_SYSTEM_PROMPT}
                    ],
                },
                {
                    "role": "user",
                    "content": _build_gpt_frame_user_content(
                        user_instruction=frame_instruction,
                        frame_data_urls=frame_data_urls,
                    ),
                },
            ],
            "reasoning": {"effort": "high"},
        }

        timeout = aiohttp.ClientTimeout(total=180)
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
                        logger.warning(
                            "Video frame prompt GPT-5.5 HTTP 5xx: status=%s body=%s attempt=%d",
                            response.status,
                            text[:800],
                            attempt,
                        )
                        if attempt < GPT55_MAX_ATTEMPTS - 1:
                            await asyncio.sleep(2**attempt)
                            continue
                        raise RuntimeError(
                            f"GPT-5.5 недоступен. Код: {response.status}"
                        )

                    if response.status == 429:
                        logger.warning(
                            "Video frame prompt GPT-5.5 rate limited: status=%s body=%s attempt=%d",
                            response.status,
                            text[:800],
                            attempt,
                        )
                        if attempt < GPT55_MAX_ATTEMPTS - 1:
                            await asyncio.sleep(2**attempt)
                            continue
                        raise RuntimeError("GPT-5.5 временно ограничил запросы")

                    if response.status >= 400:
                        raise RuntimeError(f"GPT-5.5 ошибка. Код: {response.status}")

                    try:
                        data = json.loads(text)
                    except Exception:
                        raise RuntimeError("GPT-5.5 вернул некорректный JSON")

                    raw_body_code = data.get("code") if isinstance(data, dict) else None
                    try:
                        body_code = int(raw_body_code or 0)
                    except (TypeError, ValueError):
                        body_code = 0

                    if _is_fast_fallback_application_error(data):
                        logger.warning(
                            "Video frame prompt GPT-5.5 application upstream error: %s attempt=%d",
                            data,
                            attempt,
                        )
                        if attempt < GPT55_MAX_ATTEMPTS - 1:
                            await asyncio.sleep(2**attempt)
                            data = None
                            continue
                        raise RuntimeError(f"GPT-5.5 upstream error: {body_code}")

                    if body_code >= 400:
                        logger.warning(
                            "Video frame prompt GPT-5.5 application error in body: %s attempt=%d",
                            data,
                            attempt,
                        )
                        if (
                            body_code in GPT55_RETRYABLE_BODY_CODES
                            and attempt < GPT55_MAX_ATTEMPTS - 1
                        ):
                            await asyncio.sleep(2**attempt)
                            data = None
                            continue
                        raise RuntimeError(f"GPT-5.5 вернул ошибку: {body_code}")
            break

        if data is None:
            raise RuntimeError("GPT-5.5 не вернул данных после всех попыток")

        raw_output = _extract_output_text(data)
        parsed = _parse_video_json_object(raw_output)
        return _build_video_result(parsed, provider="gpt-5.5-frames")

    async def _download_video_bytes(self, video_url: str) -> bytes:
        timeout = aiohttp.ClientTimeout(total=90)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(video_url) as response:
                if response.status >= 400:
                    raise RuntimeError(
                        f"Не удалось скачать видео для fallback. Код: {response.status}"
                    )
                content_length = int(response.headers.get("Content-Length") or 0)
                if (
                    content_length
                    and content_length > config.VIDEO_PROMPT_MAX_VIDEO_BYTES
                ):
                    raise RuntimeError("Видео слишком большое для frame fallback")
                video_bytes = await response.read()

        if len(video_bytes) > config.VIDEO_PROMPT_MAX_VIDEO_BYTES:
            raise RuntimeError("Видео слишком большое для frame fallback")
        return video_bytes

    async def analyze_video(
        self,
        *,
        video_url: str,
        user_note: str = "",
        duration_seconds: int | float = 0,
        filename: str = "reference_video.mp4",
        video_bytes: bytes | None = None,
    ) -> Dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("KIE_AI_API_KEY is not configured")

        video_url = (video_url or "").strip()
        if not video_url:
            raise ValueError("video_url is required")

        extra_blocks: list[str] = []
        if user_note:
            extra_blocks.append(f"Additional text instruction from user:\n{user_note}")
        if duration_seconds:
            extra_blocks.append(
                f"Telegram-reported clip duration: {duration_seconds} seconds."
            )
        extra_instruction = "\n\n".join(extra_blocks)

        user_instruction = (
            "Analyze this attached reference video file and create a detailed prompt "
            "for generating a visually similar video.\n\n"
            "User goal:\nGenerate a similar video that preserves the visible subject, "
            "action, camera movement, pacing, lighting, color, environment and mood.\n\n"
            "Important details to preserve:\nTemporal motion, camera trajectory, framing, "
            "shot rhythm, focus behavior, foreground/background relationships, lighting "
            "changes, style, color palette and final-frame feel.\n\n"
            f"{extra_instruction + chr(10) + chr(10) if extra_instruction else ''}"
            "Return valid JSON only according to the required schema."
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        native_error: Exception | None = None
        try:
            return await self._analyze_with_gpt55(
                video_url=video_url,
                user_instruction=user_instruction,
                headers=headers,
                filename=filename,
                max_attempts=1,
            )
        except Exception as exc:
            native_error = exc
            logger.warning(
                "Native GPT-5.5 video input failed, falling back to sampled frames: %s",
                exc,
            )

        if video_bytes is None:
            video_bytes = await self._download_video_bytes(video_url)

        frame_data_urls = await asyncio.to_thread(
            _extract_frame_data_urls_sync,
            video_bytes,
            duration_seconds=duration_seconds,
            max_frames=VIDEO_PROMPT_FRAME_COUNT,
        )
        try:
            return await self._analyze_frames_with_gpt55(
                frame_data_urls=frame_data_urls,
                user_instruction=user_instruction,
                headers=headers,
            )
        except Exception as frame_exc:
            raise RuntimeError(
                f"Не удалось разобрать видео: native={native_error}; frames={frame_exc}"
            ) from frame_exc


video_prompt_service = VideoPromptService()
