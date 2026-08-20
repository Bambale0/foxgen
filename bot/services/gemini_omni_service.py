"""Gemini Omni service via external generation APIs."""

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional

import aiohttp

from bot.config import config
from bot.services.kling_service import KlingService
from bot.utils.user_facing_errors import make_user_friendly_generation_error

logger = logging.getLogger(__name__)


class GeminiOmniService(KlingService):
    """Wrapper for Gemini Omni video, audio and character endpoints."""

    VIDEO_MODEL = "gemini-omni-video"
    AUDIO_ENDPOINT = "/api/v1/omni/audio/create"
    CHARACTER_ENDPOINT = "/api/v1/omni/character/create"

    DURATIONS = {4, 6, 8, 10}
    ASPECT_RATIOS = {"16:9", "9:16"}
    RESOLUTIONS = {"720p", "1080p", "4k"}
    MAX_IMAGE_SLOTS = 7
    MAX_VIDEO_INPUTS = 1
    MAX_AUDIO_IDS = 1
    MAX_CHARACTER_IDS = 3
    MAX_CHARACTER_IMAGES = 1
    MAX_CHARACTER_AUDIO_IDS = 1
    SEED_MIN = 0
    SEED_MAX = 2_147_483_647
    CREATE_MAX_ATTEMPTS = 4
    CREATE_RETRY_DELAYS = (1, 2, 4)
    ASSET_POLL_ATTEMPTS = 6
    ASSET_POLL_DELAY = 2
    TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
    TRANSIENT_MESSAGE_MARKERS = (
        "system load",
        "too high",
        "try again later",
        "server exception",
        "temporarily",
        "temporary",
        "rate limit",
        "busy",
        "overload",
    )

    BASE_VOICES = {
        "achernar",
        "achird",
        "algenib",
        "algieba",
        "alnilam",
        "aoede",
        "autonoe",
        "callirrhoe",
        "charon",
        "despina",
        "enceladus",
        "erinome",
        "fenrir",
        "gacrux",
        "iapetus",
        "kore",
        "laomedeia",
        "leda",
        "orus",
        "puck",
        "pulcherrima",
        "rasalgethi",
        "sadachbia",
        "sadaltager",
        "schedar",
        "sulafat",
        "umbriel",
        "vindemiatrix",
        "zephyr",
        "zubenelgenubi",
    }

    async def _kie_post_raw(
        self,
        endpoint: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        last_data: Dict[str, Any] = {}
        for attempt in range(self.CREATE_MAX_ATTEMPTS):
            data = await self._kie_post_once(endpoint, payload)
            last_data = data
            if not self._is_transient_kie_response(data):
                return data
            if attempt >= self.CREATE_MAX_ATTEMPTS - 1:
                break
            delay = self.CREATE_RETRY_DELAYS[
                min(attempt, len(self.CREATE_RETRY_DELAYS) - 1)
            ]
            logger.warning(
                "Gemini Omni transient provider error, retrying in %ss: endpoint=%s status=%s message=%s attempt=%s",
                delay,
                endpoint,
                data.get("status_code") or data.get("code"),
                self._extract_api_message(data) or data.get("error"),
                attempt + 1,
            )
            await asyncio.sleep(delay)

        message = make_user_friendly_generation_error(
            self._extract_api_message(last_data)
        )
        return self._build_error(
            "temporarily_unavailable",
            message
            or "Сервис генерации сейчас перегружен. Попробуйте ещё раз через минуту.",
            status_code=self._status_code_value(
                last_data.get("status_code") or last_data.get("code")
            ),
            extra={"raw": last_data, "retryable": True},
        )

    async def _kie_post_once(
        self,
        endpoint: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not self.kie_headers:
            logger.error("Gemini Omni API key not configured")
            return {
                "error": "missing_api_key",
                "message": "Сервис генерации временно недоступен. Мы уже видим проблему на нашей стороне.",
                "status_code": 0,
            }

        url = f"{self.KIE_BASE_URL}{endpoint}"
        async with aiohttp.ClientSession(trust_env=False) as session:
            try:
                async with session.post(
                    url,
                    json=payload,
                    headers=self.kie_headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    text = await resp.text()
                    try:
                        data = json.loads(text)
                    except json.JSONDecodeError as exc:
                        logger.error("Gemini Omni invalid JSON: %s", text[:500])
                        return {
                            "error": "invalid_json",
                            "message": "Сервис генерации вернул неожиданный ответ. Попробуйте ещё раз.",
                            "status_code": resp.status,
                        }
                    if resp.status >= 400:
                        log_method = (
                            logger.warning
                            if resp.status in self.TRANSIENT_STATUS_CODES
                            else logger.error
                        )
                        log_method(
                            "Gemini Omni HTTP error status=%s response=%s",
                            resp.status,
                            data,
                        )
                        return {
                            "error": "api_error",
                            "message": self._extract_api_message(data)
                            or "Ошибка сервиса генерации",
                            "status_code": resp.status,
                            "raw": data,
                        }
                    if isinstance(data, dict):
                        data.setdefault("status_code", resp.status)
                        return data
                    return {"raw": data, "status_code": resp.status}
            except Exception as exc:
                logger.exception("Gemini Omni request error: %s", exc)
                return {
                    "error": "network_error",
                    "message": "Сервис генерации временно недоступен. Попробуйте ещё раз через минуту.",
                    "status_code": 0,
                }

    @staticmethod
    def _clean_list(values: Optional[List[Any]], *, max_count: int) -> List[str]:
        cleaned: List[str] = []
        seen: set[str] = set()
        for value in values or []:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
            if len(cleaned) >= max_count:
                break
        return cleaned

    @staticmethod
    def _clean_unique_values(values: Optional[List[Any]]) -> List[str]:
        cleaned: List[str] = []
        seen: set[str] = set()
        for value in values or []:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
        return cleaned

    def _safe_duration(self, duration: int) -> int:
        value = int(duration)
        if value in self.DURATIONS:
            return value
        return min(
            self.DURATIONS, key=lambda candidate: (abs(candidate - value), candidate)
        )

    def _safe_resolution(self, resolution: str) -> str:
        value = str(resolution or "720p").lower()
        return value if value in self.RESOLUTIONS else "720p"

    def _safe_seed(self, seed: Optional[int]) -> Optional[int]:
        if seed in (None, ""):
            return None
        try:
            value = int(seed)
        except (TypeError, ValueError):
            return None
        return max(self.SEED_MIN, min(self.SEED_MAX, value))

    def _safe_audio_id(self, audio_id: str) -> str:
        value = str(audio_id or "achernar").strip().lower()
        return value if value in self.BASE_VOICES else "achernar"

    @staticmethod
    def _is_success_code(code: Any) -> bool:
        return code in {0, 200, "0", "200"}

    @classmethod
    def _is_success_response(cls, data: Dict[str, Any]) -> bool:
        code = data.get("code")
        if cls._is_success_code(code):
            return True
        status_code = cls._status_code_value(data.get("status_code"))
        return code in (None, "") and 200 <= status_code < 300

    @staticmethod
    def _status_code_value(code: Any) -> int:
        try:
            return int(code)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _first_present(data: Dict[str, Any], keys: List[str]) -> Optional[Any]:
        for key in keys:
            value = data.get(key)
            if value:
                return value
        return None

    @classmethod
    def _extract_api_message(cls, data: Any) -> str:
        if isinstance(data, dict):
            for key in ("msg", "message", "detail"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            error = data.get("error")
            if isinstance(error, str) and error.strip():
                return error.strip()
            if isinstance(error, dict):
                nested = cls._extract_api_message(error)
                if nested:
                    return nested
            raw = data.get("raw")
            if raw is not data:
                nested = cls._extract_api_message(raw)
                if nested:
                    return nested
            for value in data.values():
                if isinstance(value, (dict, list)):
                    nested = cls._extract_api_message(value)
                    if nested:
                        return nested
        elif isinstance(data, list):
            for item in data:
                nested = cls._extract_api_message(item)
                if nested:
                    return nested
        return ""

    @classmethod
    def _find_nested(cls, data: Any, keys: List[str]) -> Optional[Any]:
        if isinstance(data, dict):
            direct = cls._first_present(data, keys)
            if direct:
                return direct
            for value in data.values():
                found = cls._find_nested(value, keys)
                if found:
                    return found
        elif isinstance(data, list):
            for item in data:
                found = cls._find_nested(item, keys)
                if found:
                    return found
        return None

    @classmethod
    def _is_transient_kie_response(cls, data: Dict[str, Any]) -> bool:
        status_code = cls._status_code_value(data.get("status_code"))
        body_code = cls._status_code_value(data.get("code"))
        if status_code in cls.TRANSIENT_STATUS_CODES:
            return True
        if body_code in cls.TRANSIENT_STATUS_CODES or body_code >= 500:
            return True
        if data.get("error") == "network_error":
            return True
        message = cls._extract_api_message(data).lower()
        return any(marker in message for marker in cls.TRANSIENT_MESSAGE_MARKERS)

    @classmethod
    def _extract_task_id(cls, data: Dict[str, Any]) -> Optional[str]:
        task_id = cls._find_nested(data, ["taskId", "task_id"])
        return str(task_id) if task_id else None

    @classmethod
    def _extract_asset_id(cls, data: Dict[str, Any], asset_kind: str) -> Optional[str]:
        result_data = data.get("data") if isinstance(data.get("data"), dict) else data
        if asset_kind == "audio":
            direct_keys = [
                "kieAudioId",
                "kieAudioID",
                "audioId",
                "audioID",
                "audio_id",
                "id",
            ]
            nested_keys = direct_keys[:-1]
        else:
            direct_keys = [
                "kieCharacterId",
                "kieCharacterID",
                "characterId",
                "characterID",
                "character_id",
                "id",
            ]
            nested_keys = direct_keys[:-1]

        asset_id = cls._first_present(result_data, direct_keys)
        if asset_id:
            return str(asset_id)

        asset_id = cls._find_nested(data, nested_keys)
        if asset_id:
            return str(asset_id)

        result_json = cls._find_nested(data, ["resultJson", "result_json"])
        if isinstance(result_json, str) and result_json.strip():
            try:
                parsed = json.loads(result_json)
            except json.JSONDecodeError:
                parsed = None
            if parsed:
                return cls._extract_asset_id(parsed, asset_kind)
        return None

    async def _wait_for_asset_task(
        self,
        *,
        task_id: str,
        asset_kind: str,
    ) -> Optional[Dict[str, Any]]:
        for attempt in range(self.ASSET_POLL_ATTEMPTS):
            await asyncio.sleep(self.ASSET_POLL_DELAY)
            data = await self._kie_get(
                "/api/v1/jobs/recordInfo",
                params={"taskId": task_id},
            )
            if not isinstance(data, dict):
                continue

            asset_id = self._extract_asset_id(data, asset_kind)
            if asset_id:
                logger.info(
                    "Gemini Omni %s asset resolved from async task: task_id=%s asset_id=%s",
                    asset_kind,
                    task_id,
                    asset_id,
                )
                return {
                    "status": "done",
                    "task_id": str(asset_id),
                    "asset_id": str(asset_id),
                    "asset_kind": asset_kind,
                    "raw": data,
                }

            state = str(
                self._find_nested(data, ["state", "status"]) or ""
            ).lower()
            if state in {"fail", "failed", "error"}:
                return self._build_error(
                    f"{asset_kind}_task_failed",
                    self._extract_api_message(data)
                    or "Сервис генерации не смог завершить задачу. Попробуйте ещё раз.",
                    extra={"raw": data},
                )
            logger.debug(
                "Gemini Omni %s async task still pending: task_id=%s attempt=%s",
                asset_kind,
                task_id,
                attempt + 1,
            )
        return None

    def _normalize_video_list(
        self,
        video_list: Optional[List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        seen_urls: set[str] = set()
        for item in video_list or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or item.get("video_url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            try:
                start = max(0, int(item.get("start", item.get("start_time", 0)) or 0))
            except (TypeError, ValueError):
                start = 0
            try:
                ends = int(item.get("ends", item.get("duration", 10)) or 10)
            except (TypeError, ValueError):
                ends = 10
            ends = max(start + 1, min(20, ends))
            normalized.append({"url": url, "start": start, "ends": ends})
        return normalized

    async def generate_video(
        self,
        *,
        prompt: str,
        duration: int = 6,
        aspect_ratio: str = "16:9",
        resolution: str = "720p",
        image_urls: Optional[List[str]] = None,
        audio_ids: Optional[List[str]] = None,
        video_list: Optional[List[Dict[str, Any]]] = None,
        character_ids: Optional[List[str]] = None,
        seed: Optional[int] = None,
        callBackUrl: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not prompt or not prompt.strip():
            return self._build_error("prompt_required", "Введите промпт для видео")

        cleaned_video_list = self._normalize_video_list(video_list)
        cleaned_audio_ids = self._clean_unique_values(audio_ids)
        cleaned_character_ids = self._clean_unique_values(character_ids)
        cleaned_image_urls = self._clean_unique_values(image_urls)

        if len(cleaned_video_list) > self.MAX_VIDEO_INPUTS:
            return self._build_error(
                "too_many_video_references",
                "Gemini Omni принимает только один видео-референс. Удалите текущий или замените его.",
            )
        if len(cleaned_audio_ids) > self.MAX_AUDIO_IDS:
            return self._build_error(
                "too_many_audio_ids",
                "Gemini Omni Video принимает один Audio ID за запуск.",
            )
        if len(cleaned_character_ids) > self.MAX_CHARACTER_IDS:
            return self._build_error(
                "too_many_character_ids",
                "Gemini Omni принимает максимум 3 Character ID.",
            )

        used_slots = (
            len(cleaned_image_urls)
            + len(cleaned_video_list) * 2
            + len(cleaned_character_ids)
        )
        if used_slots > self.MAX_IMAGE_SLOTS:
            return self._build_error(
                "too_many_references",
                "Слишком много входов для Gemini Omni. Лимит: фото + видео*2 + Character ID <= 7.",
            )

        input_data: Dict[str, Any] = {
            "prompt": prompt[:4000],
            "duration": str(self._safe_duration(duration)),
            "aspect_ratio": (
                aspect_ratio if aspect_ratio in self.ASPECT_RATIOS else "16:9"
            ),
            "resolution": self._safe_resolution(resolution),
        }

        safe_seed = self._safe_seed(seed)
        if safe_seed is not None:
            input_data["seed"] = safe_seed
        if cleaned_image_urls:
            input_data["image_urls"] = cleaned_image_urls
        if cleaned_audio_ids:
            input_data["audio_ids"] = cleaned_audio_ids
        if cleaned_video_list:
            input_data["video_list"] = cleaned_video_list
        if cleaned_character_ids:
            input_data["character_ids"] = cleaned_character_ids

        payload: Dict[str, Any] = {
            "model": self.VIDEO_MODEL,
            "input": input_data,
        }
        if callBackUrl:
            payload["callBackUrl"] = callBackUrl

        logger.info(
            "Gemini Omni video create_task: duration=%s ratio=%s resolution=%s images=%s videos=%s audio_ids=%s character_ids=%s",
            input_data["duration"],
            input_data["aspect_ratio"],
            input_data["resolution"],
            len(cleaned_image_urls),
            len(cleaned_video_list),
            len(cleaned_audio_ids),
            len(cleaned_character_ids),
        )
        return await self._kie_post(self.CREATE_TASK_ENDPOINT, payload)

    async def create_audio(
        self,
        *,
        audio_id: str = "achernar",
        name: str,
        voice_description: str = "",
        example_dialogue: str = "",
    ) -> Dict[str, Any]:
        if not name or not name.strip():
            return self._build_error("name_required", "Введите имя для Audio ID")

        payload: Dict[str, Any] = {
            "audio_id": self._safe_audio_id(audio_id),
            "name": name.strip()[:20],
        }
        if voice_description:
            payload["voice_description"] = voice_description[:2000]
        if example_dialogue:
            payload["example_dialogue"] = example_dialogue[:2000]

        logger.info(
            "Gemini Omni audio create: base_voice=%s name=%s has_description=%s has_dialogue=%s",
            payload["audio_id"],
            payload["name"],
            bool(payload.get("voice_description")),
            bool(payload.get("example_dialogue")),
        )
        data = await self._kie_post_raw(self.AUDIO_ENDPOINT, payload)
        if data.get("error"):
            return data

        code = data.get("code")
        if not self._is_success_response(data):
            return self._build_error(
                "api_error",
                self._extract_api_message(data)
                or "Не получилось создать Audio ID. Попробуйте ещё раз.",
                status_code=self._status_code_value(data.get("status_code") or code),
                extra={"raw": data},
            )

        asset_id = self._extract_asset_id(data, "audio")
        if not asset_id:
            task_id = self._extract_task_id(data)
            if task_id:
                logger.info("Gemini Omni audio queued: task_id=%s", task_id)
                resolved = await self._wait_for_asset_task(
                    task_id=str(task_id),
                    asset_kind="audio",
                )
                if resolved:
                    return resolved
                return {
                    "status": "pending",
                    "task_id": str(task_id),
                    "asset_kind": "audio",
                    "raw": data,
                }
        if not asset_id:
            logger.error("Gemini Omni audio response has no audio id: %r", data)
            return self._build_error(
                "no_audio_id",
                "Сервис генерации не вернул готовый Audio ID. Попробуйте ещё раз.",
                status_code=self._status_code_value(data.get("status_code") or code),
                extra={"raw": data},
            )

        logger.info("Gemini Omni audio asset created: %s", asset_id)
        return {
            "status": "done",
            "task_id": str(asset_id),
            "asset_id": str(asset_id),
            "asset_kind": "audio",
            "raw": data,
        }

    async def create_character(
        self,
        *,
        description: str,
        image_urls: List[str],
        character_name: str,
        audio_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        if not description or not description.strip():
            return self._build_error(
                "description_required", "Введите описание персонажа"
            )

        cleaned_images = self._clean_list(
            image_urls,
            max_count=self.MAX_CHARACTER_IMAGES,
        )
        if not cleaned_images:
            return self._build_error(
                "image_required", "Загрузите изображение персонажа"
            )

        payload: Dict[str, Any] = {
            "descriptions": description[:2000],
            "image_urls": cleaned_images,
            "character_name": (character_name or "Character").strip()[:20],
        }

        cleaned_audio_ids = self._clean_list(
            audio_ids,
            max_count=self.MAX_CHARACTER_AUDIO_IDS,
        )
        if cleaned_audio_ids:
            payload["audio_ids"] = cleaned_audio_ids

        logger.info(
            "Gemini Omni character create: images=%s audio_ids=%s name=%s",
            len(cleaned_images),
            len(cleaned_audio_ids),
            payload["character_name"],
        )
        data = await self._kie_post_raw(self.CHARACTER_ENDPOINT, payload)
        if data.get("error"):
            return data

        code = data.get("code")
        if not self._is_success_response(data):
            return self._build_error(
                "api_error",
                self._extract_api_message(data)
                or "Не получилось создать Character ID. Попробуйте ещё раз.",
                status_code=self._status_code_value(data.get("status_code") or code),
                extra={"raw": data},
            )

        result_data = data.get("data") if isinstance(data.get("data"), dict) else {}
        asset_id = self._extract_asset_id(data, "character")
        if not asset_id:
            task_id = self._extract_task_id(data)
            if task_id:
                logger.info("Gemini Omni character queued: task_id=%s", task_id)
                resolved = await self._wait_for_asset_task(
                    task_id=str(task_id),
                    asset_kind="character",
                )
                if resolved:
                    return resolved
                return {
                    "status": "pending",
                    "task_id": str(task_id),
                    "asset_kind": "character",
                    "raw": data,
                }
        if not asset_id:
            logger.error(
                "Gemini Omni character response has no character id: %r",
                data,
            )
            return self._build_error(
                "no_character_id",
                "Сервис генерации не вернул готовый Character ID. Попробуйте ещё раз.",
                status_code=self._status_code_value(data.get("status_code") or code),
                extra={"raw": data},
            )

        logger.info("Gemini Omni character asset created: %s", asset_id)
        return {
            "status": "done",
            "task_id": str(asset_id),
            "asset_id": str(asset_id),
            "asset_kind": "character",
            "image_url": result_data.get("imageUrl") or result_data.get("image_url"),
            "raw": data,
        }


gemini_omni_service = GeminiOmniService(
    kie_key=config.KIE_AI_API_KEY or os.getenv("KIE_AI_API_KEY"),
)
