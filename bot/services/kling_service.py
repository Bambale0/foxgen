"""Kling/Kie.ai service with explicit capability routing.

Supported families:
- Kling 3.0 video: std, pro and 4K; 3-15 seconds; audio; multi-shot;
  multi-prompt; image references; Kling Elements.
- Kling 2.5 Turbo Pro: text/image-to-video, negative prompt and cfg scale.
- Kling AI Avatar Standard/Pro.
- Kling Motion Control 2.6 and 3.0 at 720p/1080p.

The service deliberately rejects non-Kling models so provider routing bugs are
visible instead of silently falling back to another model.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)

_KLING_ELEMENT_ALIAS_RE = re.compile(r"@(?P<name>element_[A-Za-z0-9_-]+)\b")


class KlingService:
    KIE_BASE_URL = "https://api.kie.ai"
    CREATE_TASK_ENDPOINT = "/api/v1/jobs/createTask"
    RECORD_INFO_ENDPOINT = "/api/v1/jobs/recordInfo"
    CREATE_TASK_TIMEOUT_SECONDS = 90

    ASPECT_RATIOS = {"16:9", "9:16", "1:1"}
    KLING_3_MODES = {"std", "pro", "4k"}
    KLING_25_DURATIONS = {5, 10}
    KLING_25_CFG_MIN = 0.0
    KLING_25_CFG_MAX = 1.0
    MOTION_MODELS_BY_KEY = {
        "motion_control": "kling-2.6/motion-control",
        "motion_control_v26": "kling-2.6/motion-control",
        "kling-2.6/motion-control": "kling-2.6/motion-control",
        "motion_control_v30": "kling-3.0/motion-control",
        "kling-3.0/motion-control": "kling-3.0/motion-control",
    }
    KLING_3_MODE_BY_KEY = {
        "v3_std": "std",
        "kling_v3": "std",
        "v3_pro": "pro",
        "kling_3": "pro",
        "kling_3_pro": "pro",
        "v3_4k": "4k",
        "kling_3_4k": "4k",
        "kling-3.0-4k": "4k",
    }
    KLING_25_MODELS = {"v26_pro", "kling_25_turbo_pro"}
    AVATAR_MODELS = {
        "avatar_std": "kling/ai-avatar-standard",
        "kling_avatar_std": "kling/ai-avatar-standard",
        "avatar_pro": "kling/ai-avatar-pro",
        "kling_avatar_pro": "kling/ai-avatar-pro",
    }
    GLOW_MODELS = {"glow"}
    NON_KLING_MODELS = {
        "grok_imagine",
        "grok_imagine_v15",
        "seedance_2",
        "grok_imagine_i2i",
        "banana_pro",
        "banana_2",
        "seedream_edit",
        "seedream_5_pro",
        "flux_pro",
        "gpt_image_2",
        "nano_banana_pro",
        "nano_banana_2",
        "veo3",
        "veo3_fast",
        "veo3_lite",
        "gemini_omni",
        "gemini_omni_video",
    }

    def __init__(self, kie_key: Optional[str] = None):
        self.kie_key = kie_key or os.getenv("KIE_AI_API_KEY")
        self.kie_headers = (
            {
                "Authorization": f"Bearer {self.kie_key}",
                "Content-Type": "application/json",
            }
            if self.kie_key
            else None
        )

    async def _kie_post(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.kie_headers:
            return self._build_error(
                "missing_api_key", "Kie.ai API key is not configured"
            )
        url = f"{self.KIE_BASE_URL}{endpoint}"
        try:
            async with aiohttp.ClientSession(trust_env=False) as session:
                async with session.post(
                    url,
                    json=payload,
                    headers=self.kie_headers,
                    timeout=aiohttp.ClientTimeout(
                        total=self.CREATE_TASK_TIMEOUT_SECONDS
                    ),
                ) as response:
                    return self._parse_kie_create_response(await response.text())
        except Exception as exc:
            logger.exception("Kie.ai request error: %s", exc)
            return self._build_error("network_error", f"Network error: {exc}")

    async def _kie_get(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        if not self.kie_headers:
            return None
        url = f"{self.KIE_BASE_URL}{endpoint}"
        headers = {k: v for k, v in self.kie_headers.items() if k != "Content-Type"}
        try:
            async with aiohttp.ClientSession(trust_env=False) as session:
                async with session.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as response:
                    text = await response.text()
                    data = json.loads(text)
                    if response.status >= 400:
                        logger.error("Kie.ai GET error %s: %s", response.status, data)
                        return None
                    return data if isinstance(data, dict) else None
        except Exception as exc:
            logger.exception("Kie.ai GET error: %s", exc)
            return None

    def _parse_kie_create_response(self, text: str) -> Dict[str, Any]:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            return self._build_error("invalid_json", f"JSON decode error: {exc}")
        if not isinstance(data, dict):
            return self._build_error(
                "invalid_response_type", f"Expected dict, got {type(data).__name__}"
            )
        if data.get("code") != 200:
            return self._build_error(
                "api_error",
                data.get("msg") or data.get("message") or "Unknown Kie.ai error",
                status_code=int(data.get("code") or 0),
                extra={"raw": data},
            )
        inner = data.get("data")
        if not isinstance(inner, dict):
            return self._build_error(
                "invalid_data_structure",
                "Kie.ai response data field is not a dict",
                status_code=200,
                extra={"raw": data},
            )
        task_id = inner.get("taskId") or inner.get("task_id")
        if not task_id:
            return self._build_error(
                "no_task_id", "Task ID missing from Kie.ai response", extra={"raw": data}
            )
        return {"task_id": task_id, "status": "pending", "raw": data}

    @staticmethod
    def _build_error(
        error: str,
        message: str,
        *,
        status_code: int = 0,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "error": error,
            "message": message,
            "status_code": status_code,
        }
        if extra:
            result.update(extra)
        return result

    def _safe_aspect_ratio(self, value: str) -> str:
        return value if value in self.ASPECT_RATIOS else "16:9"

    def _safe_kling_3_mode(self, value: str) -> str:
        normalized = str(value or "std").strip().lower().replace("4K", "4k")
        return normalized if normalized in self.KLING_3_MODES else "std"

    @staticmethod
    def _safe_kling_3_duration(value: int) -> int:
        return max(3, min(int(value), 15))

    def _safe_duration_25(self, value: int) -> int:
        return 10 if int(value) == 10 else 5

    def _safe_cfg_scale(self, value: float) -> float:
        return round(
            max(self.KLING_25_CFG_MIN, min(self.KLING_25_CFG_MAX, float(value))),
            1,
        )

    async def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        if not task_id:
            return None
        data = await self._kie_get(self.RECORD_INFO_ENDPOINT, {"taskId": task_id})
        if not data:
            return None
        task_data = data.get("data") or {}
        return {
            "data": {
                "task_id": task_id,
                "status": str(
                    task_data.get("status") or task_data.get("state") or "unknown"
                ).lower(),
                "output": self._extract_output(task_data),
            },
            "raw": data,
        }

    async def get_kie_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        return await self.get_task_status(task_id)

    async def get_v3_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        return await self.get_task_status(task_id)

    async def get_omni_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        return await self.get_task_status(task_id)

    async def get_r2v_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        return await self.get_task_status(task_id)

    @staticmethod
    def _extract_output(task_data: Dict[str, Any]) -> Optional[Any]:
        for field in (
            "output",
            "resultUrl",
            "result_url",
            "videoUrl",
            "imageUrl",
            "fullResultUrls",
        ):
            value = task_data.get(field)
            if value:
                return value
        result_json = task_data.get("resultJson") or task_data.get("result_json")
        if isinstance(result_json, str):
            try:
                result_json = json.loads(result_json)
            except json.JSONDecodeError:
                return None
        if not isinstance(result_json, dict):
            return None
        for key in (
            "resultUrls",
            "fullResultUrls",
            "result_urls",
            "urls",
            "videos",
            "images",
        ):
            value = result_json.get(key)
            if value:
                return value[0] if isinstance(value, list) else value
        return None

    async def generate_kling_3_video(
        self,
        prompt: str,
        *,
        mode: str = "std",
        duration: int = 5,
        aspect_ratio: str = "16:9",
        image_urls: Optional[List[str]] = None,
        sound: bool = True,
        multi_shots: bool = False,
        multi_prompt: Optional[List[Dict[str, Any]]] = None,
        kling_elements: Optional[List[Dict[str, Any]]] = None,
        webhook: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not prompt or not prompt.strip():
            return self._build_error("prompt_required", "Prompt is required")
        input_data: Dict[str, Any] = {
            "prompt": prompt.strip()[:2500],
            "sound": bool(sound),
            "duration": str(self._safe_kling_3_duration(duration)),
            "aspect_ratio": self._safe_aspect_ratio(aspect_ratio),
            "mode": self._safe_kling_3_mode(mode),
            "multi_shots": bool(multi_shots),
        }
        refs = list(dict.fromkeys(url for url in image_urls or [] if url))
        if refs:
            input_data["image_urls"] = refs
        if kling_elements:
            input_data["kling_elements"] = kling_elements[:3]
        if multi_shots and multi_prompt:
            input_data["multi_prompt"] = multi_prompt[:6]
        payload: Dict[str, Any] = {"model": "kling-3.0/video", "input": input_data}
        if webhook:
            payload["callBackUrl"] = webhook
        return await self._kie_post(self.CREATE_TASK_ENDPOINT, payload)

    async def generate_kling_25_turbo_video(
        self,
        prompt: str,
        *,
        duration: int = 5,
        aspect_ratio: str = "16:9",
        image_url: Optional[str] = None,
        negative_prompt: Optional[str] = None,
        cfg_scale: float = 0.5,
        webhook: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not prompt or not prompt.strip():
            return self._build_error("prompt_required", "Prompt is required")
        model = (
            "kling/v2-5-turbo-image-to-video-pro"
            if image_url
            else "kling/v2-5-turbo-text-to-video-pro"
        )
        input_data: Dict[str, Any] = {
            "prompt": prompt.strip()[:2500],
            "duration": str(self._safe_duration_25(duration)),
            "aspect_ratio": self._safe_aspect_ratio(aspect_ratio),
            "cfg_scale": self._safe_cfg_scale(cfg_scale),
        }
        if image_url:
            input_data["image_url"] = image_url
        if negative_prompt:
            input_data["negative_prompt"] = negative_prompt[:500]
        payload: Dict[str, Any] = {"model": model, "input": input_data}
        if webhook:
            payload["callBackUrl"] = webhook
        return await self._kie_post(self.CREATE_TASK_ENDPOINT, payload)

    async def generate_kling_ai_avatar(
        self,
        *,
        image_url: str,
        audio_url: str,
        prompt: str = "",
        model: str = "kling/ai-avatar-standard",
        webhook: Optional[str] = None,
    ) -> Dict[str, Any]:
        if model not in {"kling/ai-avatar-standard", "kling/ai-avatar-pro"}:
            return self._build_error(
                "unsupported_avatar_model", f"Unsupported avatar model: {model}"
            )
        if not image_url:
            return self._build_error("image_required", "Avatar image is required")
        if not audio_url:
            return self._build_error("audio_required", "Avatar audio is required")
        payload: Dict[str, Any] = {
            "model": model,
            "input": {
                "image_url": image_url,
                "audio_url": audio_url,
                "prompt": (prompt or "")[:5000],
            },
        }
        if webhook:
            payload["callBackUrl"] = webhook
        return await self._kie_post(self.CREATE_TASK_ENDPOINT, payload)

    async def create_kie_motion_task(
        self,
        input_data: Dict[str, Any],
        webhook: Optional[str] = None,
        model: str = "kling-2.6/motion-control",
    ) -> Dict[str, Any]:
        if model not in set(self.MOTION_MODELS_BY_KEY.values()):
            return self._build_error(
                "unsupported_motion_model", f"Unsupported Motion Control model: {model}"
            )
        payload: Dict[str, Any] = {"model": model, "input": input_data}
        if webhook:
            payload["callBackUrl"] = webhook
        return await self._kie_post(self.CREATE_TASK_ENDPOINT, payload)

    async def generate_motion_control(
        self,
        *,
        image_url: str,
        video_urls: Optional[List[str]] = None,
        preset_motion: Optional[str] = None,
        prompt: Optional[str] = None,
        motion_direction: str = "video",
        mode: str = "720p",
        motion_model: str = "kling-2.6/motion-control",
        webhook_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not image_url:
            return self._build_error(
                "image_required", "Motion Control requires image_url"
            )
        videos = list(dict.fromkeys(url for url in video_urls or [] if url))
        if not videos and not preset_motion:
            return self._build_error(
                "video_url_required",
                "Motion Control requires a movement video or preset",
            )
        resolved_model = self.MOTION_MODELS_BY_KEY.get(motion_model, motion_model)
        if resolved_model not in set(self.MOTION_MODELS_BY_KEY.values()):
            return self._build_error(
                "unsupported_motion_model",
                f"Unsupported Motion Control model: {motion_model}",
            )
        orientation = (
            motion_direction if motion_direction in {"video", "image"} else "video"
        )
        quality = "1080p" if str(mode).lower() in {"pro", "1080p"} else "720p"
        input_data: Dict[str, Any] = {
            "prompt": (prompt or "")[:2500],
            "input_urls": [image_url],
            "character_orientation": orientation,
            "mode": quality,
            "aspect_ratio": "1:1",
        }
        if videos:
            input_data["video_urls"] = videos[:1]
        if preset_motion:
            input_data["preset_motion"] = preset_motion
        return await self.create_kie_motion_task(
            input_data, webhook_url, model=resolved_model
        )

    async def generate_video(
        self,
        prompt: str,
        model: str = "v3_std",
        duration: int = 5,
        aspect_ratio: str = "16:9",
        webhook_url: Optional[str] = None,
        image_url: Optional[str] = None,
        video_urls: Optional[List[str]] = None,
        end_image_url: Optional[str] = None,
        elements: Optional[List[Dict[str, Any]]] = None,
        negative_prompt: Optional[str] = None,
        cfg_scale: float = 0.5,
        generate_audio: bool = True,
        multi_shots: Optional[Any] = None,
        image_input: Optional[List[str]] = None,
        motion_direction: str = "video",
        motion_mode: str = "720p",
        sound: Optional[bool] = None,
        mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        model = model or "v3_std"
        if sound is not None:
            generate_audio = bool(sound)
        if mode:
            motion_mode = mode
        if model in self.NON_KLING_MODELS:
            return self._build_error(
                "wrong_provider_route",
                f"Model '{model}' must not be handled by KlingService",
                extra={"model": model},
            )
        if model in self.MOTION_MODELS_BY_KEY or "motion" in model.lower():
            return await self.generate_motion_control(
                image_url=image_url or "",
                video_urls=video_urls,
                prompt=prompt,
                motion_direction=motion_direction,
                mode=motion_mode,
                motion_model=model,
                webhook_url=webhook_url,
            )
        if model in self.KLING_3_MODE_BY_KEY:
            image_urls = self._collect_image_urls(
                image_url, end_image_url, image_input
            )
            kling_elements, enhanced_prompt = self._build_kling_elements(
                elements, prompt
            )
            multi_prompt = multi_shots if isinstance(multi_shots, list) else None
            return await self.generate_kling_3_video(
                prompt=enhanced_prompt,
                mode=self.KLING_3_MODE_BY_KEY[model],
                duration=duration,
                aspect_ratio=aspect_ratio,
                image_urls=image_urls,
                sound=generate_audio,
                multi_shots=bool(multi_shots),
                multi_prompt=multi_prompt,
                kling_elements=kling_elements,
                webhook=webhook_url,
            )
        if model in self.KLING_25_MODELS:
            return await self.generate_kling_25_turbo_video(
                prompt=prompt,
                duration=duration,
                aspect_ratio=aspect_ratio,
                image_url=image_url,
                negative_prompt=negative_prompt,
                cfg_scale=cfg_scale,
                webhook=webhook_url,
            )
        if model in self.AVATAR_MODELS:
            return await self.generate_kling_ai_avatar(
                image_url=image_url or "",
                audio_url=(video_urls or [""])[0],
                prompt=prompt,
                model=self.AVATAR_MODELS[model],
                webhook=webhook_url,
            )
        if model in self.GLOW_MODELS:
            return await self.generate_motion_control(
                image_url=image_url or "",
                video_urls=video_urls,
                prompt=prompt or "Apply glow-style motion to the character",
                webhook_url=webhook_url,
            )
        return self._build_error(
            "unsupported_model",
            f"Unsupported Kling model: {model}",
            extra={"model": model},
        )

    @staticmethod
    def _collect_image_urls(
        image_url: Optional[str],
        end_image_url: Optional[str],
        image_input: Optional[List[str]],
    ) -> List[str]:
        result: List[str] = []
        for url in image_input or []:
            if url and url not in result:
                result.append(url)
        if image_url and image_url not in result:
            result.insert(0, image_url)
        if end_image_url and end_image_url not in result:
            result.append(end_image_url)
        return result

    @staticmethod
    def _build_kling_elements(
        elements: Optional[List[Dict[str, Any]]], prompt: str
    ) -> tuple[List[Dict[str, Any]], str]:
        if not elements:
            return [], prompt
        built: List[Dict[str, Any]] = []
        enhanced_prompt = prompt
        prompt_aliases = list(
            dict.fromkeys(
                match.group("name")
                for match in _KLING_ELEMENT_ALIAS_RE.finditer(prompt)
            )
        )
        for element in elements:
            if len(built) >= 3:
                break
            urls = list(element.get("reference_image_urls") or [])
            if element.get("frontal_image_url"):
                urls.append(element["frontal_image_url"])
            urls = list(dict.fromkeys(url for url in urls if url))[:4]
            if len(urls) < 2:
                continue
            name = (
                prompt_aliases[len(built)]
                if len(built) < len(prompt_aliases)
                else f"element_{len(built)}"
            )
            built.append(
                {
                    "name": name,
                    "description": element.get(
                        "description", f"reference element {len(built) + 1}"
                    ),
                    "element_input_urls": urls,
                }
            )
            if f"@{name}" not in enhanced_prompt:
                enhanced_prompt += f" use @{name} as reference"
        return built, enhanced_prompt

    async def wait_for_completion(
        self, task_id: str, max_attempts: int = 60, delay: int = 5
    ) -> Optional[Dict[str, Any]]:
        for _ in range(max_attempts):
            status = await self.get_task_status(task_id)
            if status:
                task_status = status.get("data", {}).get("status", "").lower()
                if task_status in {"completed", "succeeded", "success", "failed", "error"}:
                    return status
            await asyncio.sleep(delay)
        return None


from bot.config import config

kling_service = KlingService(kie_key=config.KIE_AI_API_KEY)
