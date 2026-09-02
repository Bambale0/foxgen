from __future__ import annotations

import contextlib
import json
import uuid
from typing import Any

from bot import instagram_generation as generation
from bot.channel_identity import ChannelIdentity
from bot.database import add_credits, deduct_credits
from bot.instagram_api import InstagramEvent
from bot.instagram_i18n import resolve_instagram_language
from bot.instagram_model_contract import INSTAGRAM_VIDEO_MODEL, instagram_video_cost
from bot.instagram_seedream_generation import InstagramSeedream5ProService
from bot.instagram_video_i18n import LocalizedInstagramVideoGenerationService
from bot.services.seedance_25_service import (
    get_seedance25_callback_url,
    seedance_25_service,
)

_STAGE_PREFIX = "s25"
_SUCCESS = frozenset({"success", "succeeded", "completed", "done", "finished"})
_FAILURE = frozenset({"fail", "failed", "error", "cancelled", "canceled"})
_DONE = frozenset({"готово", "готов", "done", "finish", "continue", "дальше"})
_YES = frozenset({"да", "yes", "ok", "ок", "вкл", "on", "1"})
_NO = frozenset({"нет", "no", "off", "выкл", "0"})
_RATIOS = frozenset({"adaptive", "16:9", "9:16", "1:1", "4:3", "3:4", "21:9"})


def _stage(name: str) -> str:
    return f"{_STAGE_PREFIX}:{name}"


def _state_stage(value: str) -> str:
    raw = str(value or "")
    return raw.split(":", 1)[1] if raw.startswith(f"{_STAGE_PREFIX}:") else ""


def _default_config() -> dict[str, Any]:
    return {
        "contract": "seedance25_official",
        "scenario": "text",
        "resolution": "720p",
        "duration": 5,
        "aspect_ratio": "9:16",
        "generate_audio": True,
        "return_last_frame": False,
        "image_urls": [],
        "video_urls": [],
        "audio_urls": [],
    }


def _decode_config(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return _default_config()
    if not isinstance(value, dict) or value.get("contract") != "seedance25_official":
        return _default_config()
    data = _default_config()
    data.update(value)
    return data


def _encode_config(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


async def _save_config(identity_id: int, data: dict[str, Any], state: str, *, prompt: str | None = None) -> None:
    await generation.save_instagram_image_draft(identity_id, _encode_config(data))
    await generation.update_instagram_draft(identity_id, state=state, prompt=prompt)


def _message_refs(event: InstagramEvent) -> tuple[list[str], list[str], list[str]]:
    images: list[str] = []
    videos: list[str] = []
    audios: list[str] = []
    message = event.payload.get("message") if isinstance(event.payload, dict) else None
    attachments = message.get("attachments") if isinstance(message, dict) else None
    for item in attachments if isinstance(attachments, list) else []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "").strip().lower()
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        url = str(payload.get("url") or "").strip()
        if not url.startswith("https://"):
            continue
        if kind == "image" and url not in images:
            images.append(url)
        elif kind == "video" and url not in videos:
            videos.append(url)
        elif kind in {"audio", "voice"} and url not in audios:
            audios.append(url)
    return images, videos, audios


def _marked_refs(text: str) -> tuple[list[str], list[str], list[str]]:
    images: list[str] = []
    videos: list[str] = []
    audios: list[str] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if "=" not in line:
            continue
        label, value = line.split("=", 1)
        url = value.strip()
        if not url.startswith("https://"):
            continue
        key = label.strip().casefold()
        target = images if key in {"image", "img", "photo", "фото"} else videos if key in {"video", "vid", "видео"} else audios if key in {"audio", "voice", "аудио"} else None
        if target is not None and url not in target:
            target.append(url)
    return images, videos, audios


def _direct_source(event: InstagramEvent) -> str:
    images, _videos, _audios = _message_refs(event)
    if images:
        return images[0]
    text = str(event.text or "").strip()
    return text if text.startswith("https://") else ""


def _scenario_from_text(text: str) -> str:
    value = " ".join(str(text or "").casefold().split())
    if value in {"1", "текст", "text", "текст видео", "text to video"}:
        return "text"
    if value in {"2", "фото", "image", "оживить фото", "first frame", "первый кадр"}:
        return "first_frame"
    if value in {"3", "два кадра", "2 кадра", "first last", "первый последний", "между кадрами"}:
        return "first_last"
    if value in {"4", "референсы", "refs", "multimodal", "мультимодал", "мультимодальный"}:
        return "multimodal"
    return ""


def _first_https(value: Any) -> str:
    if isinstance(value, str):
        raw = value.strip()
        if raw.startswith("https://"):
            return raw
        with contextlib.suppress(json.JSONDecodeError):
            return _first_https(json.loads(raw))
        return ""
    if isinstance(value, list):
        for item in value:
            found = _first_https(item)
            if found:
                return found
        return ""
    if isinstance(value, dict):
        for key in ("output", "videoUrl", "video_url", "resultUrl", "result_url", "url", "resultUrls", "urls", "data"):
            if key in value:
                found = _first_https(value[key])
                if found:
                    return found
        for item in value.values():
            found = _first_https(item)
            if found:
                return found
    return ""


def _last_frame_url(value: Any) -> str:
    if isinstance(value, str):
        with contextlib.suppress(json.JSONDecodeError):
            return _last_frame_url(json.loads(value))
        return ""
    if isinstance(value, list):
        for item in value:
            found = _last_frame_url(item)
            if found:
                return found
        return ""
    if isinstance(value, dict):
        normalized = {str(key).replace("_", "").lower(): item for key, item in value.items()}
        for key in ("lastframeurl", "lastframe", "finalframeurl"):
            candidate = normalized.get(key)
            if isinstance(candidate, str) and candidate.strip().startswith("https://"):
                return candidate.strip()
        for item in value.values():
            found = _last_frame_url(item)
            if found:
                return found
    return ""


def _bilingual(language: str, ru: str, en: str) -> str:
    return en if language == "en" else ru


class InstagramSeedance25OfficialService(LocalizedInstagramVideoGenerationService):
    """Full Seedance 2.5 DM flow using the same provider contract as Telegram/MAX."""

    async def _resume_after_topup(self, identity: ChannelIdentity, event: InstagramEvent) -> bool:
        billing = await generation._linked_billing_user(identity.id)
        cost = instagram_video_cost(duration=5, resolution="720p")
        if billing is None or billing[2] < cost:
            await self.enter_video_paywall(identity, event)
            return True
        language = await resolve_instagram_language(identity.id, event.text)
        await _save_config(identity.id, _default_config(), _stage("scenario"), prompt="")
        await self.client.send_text(
            event.account_id,
            event.sender_id,
            _bilingual(
                language,
                "🔥 Seedance 2.5\n\nВыбери сценарий:\n1 — видео по тексту\n2 — оживить первый кадр\n3 — первый + последний кадр\n4 — фото / видео / аудио референсы",
                "🔥 Seedance 2.5\n\nChoose a mode:\n1 — text to video\n2 — first frame\n3 — first + last frame\n4 — image / video / audio references",
            ),
        )
        return True

    async def _ask_resolution(self, identity: ChannelIdentity, event: InstagramEvent, data: dict[str, Any]) -> None:
        language = await resolve_instagram_language(identity.id, event.text)
        await _save_config(identity.id, data, _stage("resolution"))
        await self.client.send_text(event.account_id, event.sender_id, _bilingual(language, "Качество: 480p или 720p?", "Quality: 480p or 720p?"))

    async def _ask_duration(self, identity: ChannelIdentity, event: InstagramEvent, data: dict[str, Any]) -> None:
        language = await resolve_instagram_language(identity.id, event.text)
        await _save_config(identity.id, data, _stage("duration"))
        await self.client.send_text(event.account_id, event.sender_id, _bilingual(language, "Длительность — число от 4 до 30 секунд.", "Duration — a number from 4 to 30 seconds."))

    async def _ask_ratio_or_audio(self, identity: ChannelIdentity, event: InstagramEvent, data: dict[str, Any]) -> None:
        language = await resolve_instagram_language(identity.id, event.text)
        if data["scenario"] in {"first_frame", "first_last"}:
            data["aspect_ratio"] = "adaptive"
            await _save_config(identity.id, data, _stage("audio"))
            await self.client.send_text(event.account_id, event.sender_id, _bilingual(language, "Сгенерировать звук? Ответь ДА или НЕТ.", "Generate audio? Reply YES or NO."))
            return
        await _save_config(identity.id, data, _stage("ratio"))
        await self.client.send_text(event.account_id, event.sender_id, _bilingual(language, "Формат: adaptive, 16:9, 9:16, 1:1, 4:3, 3:4 или 21:9.", "Aspect ratio: adaptive, 16:9, 9:16, 1:1, 4:3, 3:4 or 21:9."))

    async def _ask_last_frame(self, identity: ChannelIdentity, event: InstagramEvent, data: dict[str, Any]) -> None:
        language = await resolve_instagram_language(identity.id, event.text)
        await _save_config(identity.id, data, _stage("return_last"))
        await self.client.send_text(event.account_id, event.sender_id, _bilingual(language, "Отдельно вернуть последний кадр? ДА или НЕТ.", "Return the final frame separately? YES or NO."))

    async def _start_sources(self, identity: ChannelIdentity, event: InstagramEvent, data: dict[str, Any]) -> None:
        language = await resolve_instagram_language(identity.id, event.text)
        data["image_urls"] = []
        data["video_urls"] = []
        data["audio_urls"] = []
        scenario = data["scenario"]
        if scenario == "text":
            state = _stage("prompt")
            text = _bilingual(language, "Теперь пришли промпт до 5000 символов.", "Now send a prompt up to 5000 characters.")
        elif scenario == "first_frame":
            state = _stage("first")
            text = _bilingual(language, "Пришли первый кадр как фото или HTTPS-ссылку.", "Send the first frame as an image or HTTPS URL.")
        elif scenario == "first_last":
            state = _stage("first")
            text = _bilingual(language, "Пришли первый кадр. Затем попрошу последний.", "Send the first frame. I will ask for the last frame next.")
        else:
            state = _stage("refs")
            text = _bilingual(
                language,
                "Пришли фото, видео и/или аудио-референсы. Можно несколькими сообщениями. Для ссылок используй image=https://…, video=https://… или audio=https://…. Когда всё добавлено — напиши «готово».",
                "Send image, video and/or audio references in one or more messages. For URLs use image=https://…, video=https://… or audio=https://…. When finished, reply DONE.",
            )
        await _save_config(identity.id, data, state)
        await self.client.send_text(event.account_id, event.sender_id, text)

    async def _offer(self, identity: ChannelIdentity, event: InstagramEvent, data: dict[str, Any], prompt: str) -> bool:
        language = await resolve_instagram_language(identity.id, event.text)
        clean = str(prompt or "").strip()
        if not clean:
            return True
        if len(clean) > 5000:
            await self.client.send_text(event.account_id, event.sender_id, _bilingual(language, "Промпт — максимум 5000 символов.", "Prompt limit is 5000 characters."))
            return True
        cost = instagram_video_cost(duration=int(data["duration"]), resolution=str(data["resolution"]))
        billing = await generation._linked_billing_user(identity.id)
        if billing is None or billing[2] < cost:
            await self.enter_video_paywall(identity, event)
            return True
        await _save_config(identity.id, data, _stage("confirm"), prompt=clean)
        await self.client.send_text(
            event.account_id,
            event.sender_id,
            _bilingual(
                language,
                f"Seedance 2.5 · {data['duration']}с · {data['resolution']} · {cost:g} 🐾.\n\nОтветь ДА для запуска или НЕТ для отмены.",
                f"Seedance 2.5 · {data['duration']}s · {data['resolution']} · {cost:g} 🐾.\n\nReply YES to start or NO to cancel.",
            ),
        )
        return True

    async def _enqueue_official(self, identity: ChannelIdentity, event: InstagramEvent, draft: generation.InstagramDraft, data: dict[str, Any]) -> bool:
        language = await resolve_instagram_language(identity.id, event.text)
        billing = await generation._linked_billing_user(identity.id)
        cost = instagram_video_cost(duration=int(data["duration"]), resolution=str(data["resolution"]))
        if billing is None or billing[2] < cost:
            await self.enter_video_paywall(identity, event)
            return True
        _user_id, telegram_id, _credits = billing
        job = generation.InstagramGenerationJob(
            id=uuid.uuid4().hex,
            identity_id=identity.id,
            account_id=event.account_id,
            recipient_id=event.sender_id,
            image_url=_encode_config(data),
            prompt=draft.prompt,
            model=f"{INSTAGRAM_VIDEO_MODEL.product_key}:official",
            cost=cost,
            billing_mode="credits",
            telegram_id=telegram_id,
            promotion_reservation_key=None,
            status="prepared",
            provider_task_id=None,
            result_url=None,
            delivered_at_epoch=None,
            attempt_count=0,
        )
        await generation._insert_job(job, status="prepared")
        if not await deduct_credits(telegram_id, cost):
            await generation._mark_job_failed(job.id, "insufficient_balance")
            await self.enter_video_paywall(identity, event)
            return True
        try:
            await generation._activate_job(job.id)
        except Exception:
            await add_credits(telegram_id, cost)
            await generation._mark_job_failed(job.id, "activation_failed")
            raise
        await _save_config(identity.id, data, _stage("generating"), prompt=draft.prompt)
        await self.client.send_text(event.account_id, event.sender_id, _bilingual(language, f"{cost:g} 🐾 списано ✅ Seedance 2.5 запущена.", f"{cost:g} 🐾 charged ✅ Seedance 2.5 started."))
        return True

    async def handle_video_message(self, identity: ChannelIdentity, event: InstagramEvent) -> bool:
        draft = await generation.get_instagram_draft(identity.id)
        state = str(draft.state if draft else "")
        stage = _state_stage(state)
        normalized = " ".join(str(event.text or "").casefold().strip().split())

        if not stage:
            return await super().handle_video_message(identity, event)
        if stage == "generating":
            language = await resolve_instagram_language(identity.id, event.text)
            await self.client.send_text(event.account_id, event.sender_id, _bilingual(language, "Seedance 2.5 уже создаёт видео. Результат придёт сюда автоматически.", "Seedance 2.5 is already generating. The result will arrive here automatically."))
            return True

        data = _decode_config(draft.image_url if draft else "")
        if stage == "scenario":
            scenario = _scenario_from_text(normalized)
            if not scenario:
                await self._resume_after_topup(identity, event)
                return True
            data["scenario"] = scenario
            await self._ask_resolution(identity, event, data)
            return True
        if stage == "resolution":
            resolution = normalized.lower()
            if resolution not in {"480p", "720p"}:
                await self._ask_resolution(identity, event, data)
                return True
            data["resolution"] = resolution
            await self._ask_duration(identity, event, data)
            return True
        if stage == "duration":
            with contextlib.suppress(ValueError):
                seconds = int(normalized.removesuffix("с").removesuffix("s").strip())
                if 4 <= seconds <= 30:
                    data["duration"] = seconds
                    await self._ask_ratio_or_audio(identity, event, data)
                    return True
            await self._ask_duration(identity, event, data)
            return True
        if stage == "ratio":
            if normalized not in _RATIOS:
                await self._ask_ratio_or_audio(identity, event, data)
                return True
            data["aspect_ratio"] = normalized
            await _save_config(identity.id, data, _stage("audio"))
            language = await resolve_instagram_language(identity.id, event.text)
            await self.client.send_text(event.account_id, event.sender_id, _bilingual(language, "Сгенерировать звук? ДА или НЕТ.", "Generate audio? YES or NO."))
            return True
        if stage == "audio":
            if normalized not in _YES | _NO:
                language = await resolve_instagram_language(identity.id, event.text)
                await self.client.send_text(event.account_id, event.sender_id, _bilingual(language, "Ответь ДА или НЕТ.", "Reply YES or NO."))
                return True
            data["generate_audio"] = normalized in _YES
            await self._ask_last_frame(identity, event, data)
            return True
        if stage == "return_last":
            if normalized not in _YES | _NO:
                await self._ask_last_frame(identity, event, data)
                return True
            data["return_last_frame"] = normalized in _YES
            await self._start_sources(identity, event, data)
            return True
        if stage in {"first", "last"}:
            source = _direct_source(event)
            language = await resolve_instagram_language(identity.id, event.text)
            if not source:
                await self.client.send_text(event.account_id, event.sender_id, _bilingual(language, "Пришли фото или HTTPS-ссылку на кадр.", "Send an image or HTTPS URL for the frame."))
                return True
            images = list(data.get("image_urls") or [])
            if stage == "first":
                images = [source]
                data["image_urls"] = images
                if data["scenario"] == "first_last":
                    await _save_config(identity.id, data, _stage("last"))
                    await self.client.send_text(event.account_id, event.sender_id, _bilingual(language, "Первый кадр сохранён ✅ Теперь пришли последний.", "First frame saved ✅ Now send the last frame."))
                    return True
            else:
                data["image_urls"] = images[:1] + [source]
            await _save_config(identity.id, data, _stage("prompt"))
            await self.client.send_text(event.account_id, event.sender_id, _bilingual(language, "Кадры готовы ✅ Теперь пришли промпт.", "Frames ready ✅ Now send the prompt."))
            return True
        if stage == "refs":
            language = await resolve_instagram_language(identity.id, event.text)
            if normalized in _DONE:
                if not (data.get("image_urls") or data.get("video_urls") or data.get("audio_urls")):
                    await self.client.send_text(event.account_id, event.sender_id, _bilingual(language, "Сначала добавь хотя бы один референс.", "Add at least one reference first."))
                    return True
                await _save_config(identity.id, data, _stage("prompt"))
                await self.client.send_text(event.account_id, event.sender_id, _bilingual(language, "Референсы готовы ✅ Теперь пришли промпт.", "References ready ✅ Now send the prompt."))
                return True
            images, videos, audios = _message_refs(event)
            mi, mv, ma = _marked_refs(str(event.text or ""))
            images.extend(mi); videos.extend(mv); audios.extend(ma)
            if not (images or videos or audios):
                await self.client.send_text(event.account_id, event.sender_id, _bilingual(language, "Пришли фото/видео/аудио или URL с префиксом image=, video=, audio=. Потом напиши «готово».", "Send image/video/audio or URL with image=, video=, audio=. Then reply DONE."))
                return True
            data["image_urls"] = list(dict.fromkeys([*data.get("image_urls", []), *images]))[:30]
            data["video_urls"] = list(dict.fromkeys([*data.get("video_urls", []), *videos]))[:10]
            data["audio_urls"] = list(dict.fromkeys([*data.get("audio_urls", []), *audios]))[:10]
            await _save_config(identity.id, data, _stage("refs"))
            await self.client.send_text(event.account_id, event.sender_id, _bilingual(language, f"Добавлено ✅ Фото {len(data['image_urls'])}/30 · видео {len(data['video_urls'])}/10 · аудио {len(data['audio_urls'])}/10. Добавляй ещё или напиши «готово».", f"Added ✅ Images {len(data['image_urls'])}/30 · videos {len(data['video_urls'])}/10 · audio {len(data['audio_urls'])}/10. Add more or reply DONE."))
            return True
        if stage == "prompt":
            return await self._offer(identity, event, data, str(event.text or ""))
        if stage == "confirm":
            if normalized in generation._CANCEL_WORDS:
                language = await resolve_instagram_language(identity.id, event.text)
                await _save_config(identity.id, data, _stage("prompt"), prompt="")
                await self.client.send_text(event.account_id, event.sender_id, _bilingual(language, "Отменил. Пришли новый промпт.", "Cancelled. Send a new prompt."))
                return True
            if normalized not in generation._CONFIRM_WORDS:
                language = await resolve_instagram_language(identity.id, event.text)
                await self.client.send_text(event.account_id, event.sender_id, _bilingual(language, "Ответь ДА для запуска или НЕТ для отмены.", "Reply YES to start or NO to cancel."))
                return True
            return await self._enqueue_official(identity, event, draft, data)
        return await super().handle_video_message(identity, event)

    async def _wait_official(self, task_id: str) -> tuple[str, str]:
        status = await seedance_25_service.get_task_status(task_id)
        if not isinstance(status, dict):
            raise generation.InstagramGenerationRetry("Seedance 2.5 status is temporarily unavailable")
        data = status.get("data") if isinstance(status.get("data"), dict) else {}
        state = str(data.get("status") or "").strip().lower()
        if state in _FAILURE:
            raise RuntimeError("Seedance 2.5 generation failed")
        if state not in _SUCCESS:
            raise generation.InstagramGenerationRetry("Seedance 2.5 is still processing")
        video_url = _first_https(data.get("output")) or _first_https(status.get("raw"))
        if not video_url:
            raise RuntimeError("Seedance 2.5 completed without a video URL")
        return video_url, _last_frame_url(status.get("raw"))

    async def _process_job(self, job: generation.InstagramGenerationJob) -> None:
        if not self._is_official_job(job):
            await super()._process_job(job)
            return
        data = _decode_config(job.image_url)
        task_id = str(job.provider_task_id or "").strip()
        try:
            if not task_id:
                scenario = str(data["scenario"])
                images = list(data.get("image_urls") or [])
                response = await seedance_25_service.generate_video(
                    prompt=job.prompt,
                    duration=int(data["duration"]),
                    aspect_ratio="adaptive" if scenario in {"first_frame", "first_last"} else str(data["aspect_ratio"]),
                    resolution=str(data["resolution"]),
                    first_frame_url=images[0] if scenario in {"first_frame", "first_last"} and images else None,
                    last_frame_url=images[1] if scenario == "first_last" and len(images) > 1 else None,
                    reference_image_urls=images if scenario == "multimodal" else None,
                    reference_video_urls=list(data.get("video_urls") or []) if scenario == "multimodal" else None,
                    reference_audio_urls=list(data.get("audio_urls") or []) if scenario == "multimodal" else None,
                    return_last_frame=bool(data.get("return_last_frame")),
                    generate_audio=bool(data.get("generate_audio", True)),
                    callBackUrl=get_seedance25_callback_url(),
                )
                task_id = str(response.get("task_id") or "") if isinstance(response, dict) else ""
                if not task_id:
                    raise RuntimeError(str(response.get("error") or response.get("message") or "Seedance 2.5 returned no task") if isinstance(response, dict) else "Seedance 2.5 returned no task")
                await generation._mark_job_provider_task(job.id, task_id)

            result_url = str(job.result_url or "").strip()
            last_frame = ""
            if not result_url:
                result_url, last_frame = await self._wait_official(task_id)
                await generation._mark_job_result(job.id, result_url, task_id)
            elif bool(data.get("return_last_frame")):
                with contextlib.suppress(Exception):
                    status = await seedance_25_service.get_task_status(task_id)
                    if isinstance(status, dict):
                        last_frame = _last_frame_url(status.get("raw"))

            if job.delivered_at_epoch is None:
                await self.client.send_media(job.account_id, job.recipient_id, "video", result_url)
                await generation._mark_job_delivered(job.id)
                if bool(data.get("return_last_frame")) and last_frame:
                    with contextlib.suppress(Exception):
                        await self.client.send_media(job.account_id, job.recipient_id, "image", last_frame)
            await self._finalize_success(job)
        except generation.InstagramGenerationRetry as error:
            await generation._retry_job(job.id, str(error))
        except (RuntimeError, ValueError, TypeError, KeyError, OSError) as error:
            await self._finalize_failure(job, error)

    async def _finalize_failure(self, job: generation.InstagramGenerationJob, error: Exception) -> None:
        if not self._is_official_job(job):
            await super()._finalize_failure(job, error)
            return
        await InstagramSeedream5ProService._finalize_failure(self, job, error)
        data = _decode_config(job.image_url)
        with contextlib.suppress(Exception):
            await _save_config(job.identity_id, data, _stage("prompt"), prompt="")

    @staticmethod
    def _is_official_job(job: generation.InstagramGenerationJob) -> bool:
        return job.model == f"{INSTAGRAM_VIDEO_MODEL.product_key}:official"
