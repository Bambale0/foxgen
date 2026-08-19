"""Kie.ai adapter for Bytedance Seedance 2.5.

Implements the released Kie Market OpenAPI contract for
``bytedance/seedance-2-5``. The media scenarios are deliberately kept
mutually exclusive:

1. text-to-video (no media inputs),
2. first-frame / first+last-frame image-to-video,
3. multimodal reference-to-video (images, videos and/or audio).
"""

from __future__ import annotations

import logging
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

from bot.config import config
from bot.services.kling_service import KlingService

logger = logging.getLogger(__name__)


def get_seedance25_callback_url() -> str:
    """Return a dedicated callback URL for Seedance 2.5.

    Seedance 2.5 can return more than one result (video + requested last frame)
    and can return MOV. A dedicated webhook lets us preserve those outputs
    without changing the established generic Kie webhook behaviour.
    """
    legacy = str(getattr(config, "kie_notification_url", "") or "").strip()
    if legacy:
        parts = urlsplit(legacy)
        if parts.scheme and parts.netloc:
            return urlunsplit(
                (
                    parts.scheme,
                    parts.netloc,
                    "/webhook/kie_seedance25",
                    "",
                    "",
                )
            )

    host = str(getattr(config, "WEBHOOK_HOST", "") or "").strip().rstrip("/")
    if not host:
        return ""
    if host.startswith(("http://", "https://")):
        return f"{host}/webhook/kie_seedance25"
    return f"https://{host}/webhook/kie_seedance25"


class Seedance25Service(KlingService):
    MODEL_NAME = "bytedance/seedance-2-5"

    ALLOWED_RATIOS = {
        "1:1",
        "4:3",
        "3:4",
        "16:9",
        "9:16",
        "21:9",
        "adaptive",
    }
    ALLOWED_RESOLUTIONS = {"480p", "720p"}
    ALLOWED_OUTPUT_FORMATS = {"mp4", "mov"}

    MIN_DURATION = 4
    MAX_DURATION = 30
    AUTO_DURATION = -1
    MAX_PROMPT_LENGTH = 5000

    MAX_REFERENCE_IMAGES = 30
    MAX_REFERENCE_VIDEOS = 10
    MAX_REFERENCE_AUDIO = 10

    @staticmethod
    def _clean_urls(values: Iterable[str] | None) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in values or []:
            value = str(raw or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            cleaned.append(value)
        return cleaned

    @classmethod
    def _normalize_urls(
        cls,
        values: Iterable[str] | None,
        *,
        limit: int,
        label: str,
    ) -> list[str]:
        cleaned = cls._clean_urls(values)
        if len(cleaned) > limit:
            raise ValueError(f"Seedance 2.5 accepts at most {limit} {label}")
        return cleaned

    @classmethod
    def normalize_duration(cls, duration: int | str | None) -> int:
        try:
            value = int(duration if duration is not None else 5)
        except (TypeError, ValueError):
            value = 5
        if value == cls.AUTO_DURATION:
            return value
        if not cls.MIN_DURATION <= value <= cls.MAX_DURATION:
            raise ValueError(
                f"Seedance 2.5 duration must be {cls.MIN_DURATION}-{cls.MAX_DURATION} seconds or -1 (auto)"
            )
        return value

    @classmethod
    def validate_scenario(
        cls,
        *,
        first_frame_url: str | None,
        last_frame_url: str | None,
        reference_image_urls: list[str],
        reference_video_urls: list[str],
        reference_audio_urls: list[str],
    ) -> str:
        """Validate Kie's mutually-exclusive media scenarios.

        Returns one of ``text``, ``first_frame``, ``first_last`` or
        ``multimodal``.
        """
        first = str(first_frame_url or "").strip()
        last = str(last_frame_url or "").strip()
        has_refs = bool(
            reference_image_urls or reference_video_urls or reference_audio_urls
        )

        if last and not first:
            raise ValueError("last_frame_url requires first_frame_url")
        if first and has_refs:
            raise ValueError(
                "Seedance 2.5 first/last-frame mode cannot be combined with multimodal references"
            )
        if first and last:
            return "first_last"
        if first:
            return "first_frame"
        if has_refs:
            return "multimodal"
        return "text"

    async def generate_video(
        self,
        prompt: str,
        *,
        duration: int = 5,
        aspect_ratio: str = "adaptive",
        resolution: str = "720p",
        first_frame_url: str | None = None,
        last_frame_url: str | None = None,
        reference_image_urls: list[str] | None = None,
        reference_video_urls: list[str] | None = None,
        reference_audio_urls: list[str] | None = None,
        return_last_frame: bool = False,
        generate_audio: bool = True,
        output_format: str = "mp4",
        web_search: bool = False,
        nsfw_checker: bool = False,
        callBackUrl: str | None = None,
    ) -> dict[str, Any]:
        """Create a Seedance 2.5 task through Kie's unified jobs endpoint."""
        if not self.kie_key:
            return {"success": False, "error": "KIE_AI_API_KEY is not configured"}

        normalized_prompt = str(prompt or "").strip()
        if len(normalized_prompt) > self.MAX_PROMPT_LENGTH:
            return {
                "success": False,
                "error": f"Seedance 2.5 prompt exceeds {self.MAX_PROMPT_LENGTH} characters",
            }

        try:
            normalized_duration = self.normalize_duration(duration)
            image_urls = self._normalize_urls(
                reference_image_urls,
                limit=self.MAX_REFERENCE_IMAGES,
                label="image references",
            )
            video_urls = self._normalize_urls(
                reference_video_urls,
                limit=self.MAX_REFERENCE_VIDEOS,
                label="video references",
            )
            audio_urls = self._normalize_urls(
                reference_audio_urls,
                limit=self.MAX_REFERENCE_AUDIO,
                label="audio references",
            )
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

        normalized_ratio = str(aspect_ratio or "adaptive").strip().lower()
        if normalized_ratio not in self.ALLOWED_RATIOS:
            return {
                "success": False,
                "error": f"Unsupported Seedance 2.5 aspect ratio: {normalized_ratio}",
            }

        normalized_resolution = str(resolution or "720p").strip().lower()
        if normalized_resolution not in self.ALLOWED_RESOLUTIONS:
            return {
                "success": False,
                "error": f"Unsupported Seedance 2.5 resolution: {normalized_resolution}",
            }

        normalized_output = str(output_format or "mp4").strip().lower()
        if normalized_output not in self.ALLOWED_OUTPUT_FORMATS:
            return {
                "success": False,
                "error": f"Unsupported Seedance 2.5 output format: {normalized_output}",
            }

        first_frame = str(first_frame_url or "").strip() or None
        last_frame = str(last_frame_url or "").strip() or None

        try:
            scenario = self.validate_scenario(
                first_frame_url=first_frame,
                last_frame_url=last_frame,
                reference_image_urls=image_urls,
                reference_video_urls=video_urls,
                reference_audio_urls=audio_urls,
            )
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

        input_data: dict[str, Any] = {
            "prompt": normalized_prompt,
            "return_last_frame": bool(return_last_frame),
            "generate_audio": bool(generate_audio),
            "resolution": normalized_resolution,
            "aspect_ratio": normalized_ratio,
            "duration": normalized_duration,
            "output_format": normalized_output,
            "web_search": bool(web_search),
            "nsfw_checker": bool(nsfw_checker),
        }

        if first_frame:
            input_data["first_frame_url"] = first_frame
        if last_frame:
            input_data["last_frame_url"] = last_frame
        if image_urls:
            input_data["reference_image_urls"] = image_urls
        if video_urls:
            input_data["reference_video_urls"] = video_urls
        if audio_urls:
            input_data["reference_audio_urls"] = audio_urls

        payload: dict[str, Any] = {
            "model": self.MODEL_NAME,
            "input": input_data,
        }

        callback_url = str(callBackUrl or "").strip()
        legacy_callback = str(getattr(config, "kie_notification_url", "") or "").strip()
        if not callback_url or callback_url == legacy_callback:
            callback_url = get_seedance25_callback_url()
        if callback_url:
            payload["callBackUrl"] = callback_url

        logger.info(
            "Seedance 2.5 request: scenario=%s duration=%s ratio=%s resolution=%s "
            "refs(image=%s,video=%s,audio=%s) generated_audio=%s output=%s "
            "web_search=%s nsfw_checker=%s return_last_frame=%s callback=%s",
            scenario,
            normalized_duration,
            normalized_ratio,
            normalized_resolution,
            len(image_urls),
            len(video_urls),
            len(audio_urls),
            bool(generate_audio),
            normalized_output,
            bool(web_search),
            bool(nsfw_checker),
            bool(return_last_frame),
            callback_url or "polling-only",
        )
        result = await self._kie_post("/api/v1/jobs/createTask", payload)
        if isinstance(result, dict):
            result.setdefault("success", bool(result.get("task_id")))
            result.setdefault("scenario", scenario)
            result.setdefault("provider_model", self.MODEL_NAME)
        return result


seedance_25_service = Seedance25Service(kie_key=config.KIE_AI_API_KEY)
