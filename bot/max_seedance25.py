from __future__ import annotations

import contextlib
import json
import uuid
from typing import Any

from bot.max_api import callback_button, inline_keyboard
from bot.max_catalog import MaxPresetManager, max_preset_manager
from bot.max_channel import _message_body, _message_text
from bot.max_generation import (
    MaxGenerationJob,
    MaxGenerationRetry,
    _activate_job,
    _insert_job,
    _mark_delivered,
    _mark_job_failed,
    _mark_job_succeeded,
    _mark_provider_task,
    _mark_result,
    get_max_generation_job,
)
from bot.max_omni_audio import MaxOmniGenerationService
from bot.max_store import (
    MaxInsufficientBalanceError,
    apply_max_balance_delta,
    clear_max_session,
    get_max_balance,
    get_max_session,
    record_max_generation,
    save_max_session,
)
from bot.max_suno_full_channel import MaxSunoFullChannelService
from bot.max_ui import back_home_menu, generation_confirm_menu, main_menu, topup_menu
from bot.services.seedance_25_service import seedance_25_service

MODEL_KEY = "seedance_2_5"
SCENARIOS = frozenset({"text", "first_frame", "first_last", "multimodal"})
RATIOS = ("adaptive", "16:9", "9:16", "1:1", "4:3", "3:4", "21:9")
RESOLUTIONS = frozenset({"480p", "720p"})
_SUCCESS = frozenset({"success", "succeeded", "completed", "done", "finished"})
_FAILURE = frozenset({"fail", "failed", "error", "cancelled", "canceled"})
_DONE_WORDS = frozenset({"готово", "done", "готов", "finish", "дальше", "continue"})


def _format_cost(value: float) -> str:
    amount = float(value)
    return str(int(amount)) if amount.is_integer() else f"{amount:g}"


def _scenario_label(value: str) -> str:
    return {
        "text": "Текст → видео",
        "first_frame": "Первый кадр → видео",
        "first_last": "Первый + последний кадр",
        "multimodal": "Фото / видео / аудио референсы",
    }.get(value, value)


def _default_config(origin_type: str = "text") -> dict[str, Any]:
    scenario = {
        "text": "text",
        "imgtxt": "first_frame",
        "video": "multimodal",
    }.get(str(origin_type or "text"), "text")
    return {
        "kind": "video",
        "model": MODEL_KEY,
        "generation_type": origin_type if origin_type in {"text", "imgtxt", "video"} else "text",
        "seedance25_scenario": scenario,
        "duration": 5,
        "resolution": "720p",
        "aspect_ratio": "adaptive",
        "generate_audio": True,
        "return_last_frame": False,
        "image_urls": [],
        "video_urls": [],
        "audio_urls": [],
    }


def _settings_menu(data: dict[str, Any], catalog: MaxPresetManager) -> list[dict[str, Any]]:
    scenario = str(data.get("seedance25_scenario") or "text")
    duration = max(4, min(30, int(data.get("duration") or 5)))
    resolution = str(data.get("resolution") or "720p")
    ratio = "adaptive" if scenario in {"first_frame", "first_last"} else str(data.get("aspect_ratio") or "adaptive")
    cost = catalog.video_cost(MODEL_KEY, duration=duration, quality=resolution)

    rows: list[list[dict[str, Any]]] = [
        [
            callback_button(("✅ " if scenario == "text" else "") + "✍️ Текст", "max:s25:scenario:text"),
            callback_button(("✅ " if scenario == "first_frame" else "") + "🖼 Фото", "max:s25:scenario:first_frame"),
        ],
        [
            callback_button(("✅ " if scenario == "first_last" else "") + "🎞 2 кадра", "max:s25:scenario:first_last"),
            callback_button(("✅ " if scenario == "multimodal" else "") + "🧩 Референсы", "max:s25:scenario:multimodal"),
        ],
        [
            callback_button(("✅ " if resolution == "480p" else "") + "480p", "max:s25:res:480p"),
            callback_button(("✅ " if resolution == "720p" else "") + "720p", "max:s25:res:720p"),
        ],
        [
            callback_button("➖ 1с", "max:s25:dur:minus"),
            callback_button(f"⏱ {duration}с", "max:s25:noop"),
            callback_button("➕ 1с", "max:s25:dur:plus"),
        ],
    ]
    if scenario not in {"first_frame", "first_last"}:
        ratio_buttons = [
            callback_button(
                ("✅ " if ratio == value else "") + ("Авто" if value == "adaptive" else value),
                f"max:s25:ratio:{value.replace(':', 'x')}",
            )
            for value in RATIOS
        ]
        rows.extend([ratio_buttons[:3], ratio_buttons[3:6], ratio_buttons[6:]])
    else:
        rows.append([callback_button("📐 Формат по исходному кадру", "max:s25:noop")])
    rows.extend(
        [
            [
                callback_button(
                    f"🔊 Звук: {'вкл' if data.get('generate_audio', True) else 'выкл'}",
                    "max:s25:audio",
                ),
                callback_button(
                    f"🖼 Финальный кадр: {'да' if data.get('return_last_frame') else 'нет'}",
                    "max:s25:last",
                ),
            ],
            [callback_button(f"➡️ Продолжить · {_format_cost(cost)} 🐾", "max:s25:continue")],
            [callback_button("⬅️ К видео", "max:create_video")],
        ]
    )
    return [inline_keyboard(rows)]


def _attachment_urls(update: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    images: list[str] = []
    videos: list[str] = []
    audios: list[str] = []
    attachments = _message_body(update).get("attachments") or []
    if not isinstance(attachments, list):
        return images, videos, audios
    for item in attachments:
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


def _marked_urls(text: str) -> tuple[list[str], list[str], list[str]]:
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
        key = label.strip().lower()
        target = images if key in {"image", "img", "photo", "фото"} else videos if key in {"video", "vid", "видео"} else audios if key in {"audio", "voice", "аудио"} else None
        if target is not None and url not in target:
            target.append(url)
    return images, videos, audios


def _source_url(update: dict[str, Any]) -> str:
    images, _videos, _audios = _attachment_urls(update)
    if images:
        return images[0]
    text = _message_text(update).strip()
    return text if text.startswith("https://") else ""


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
        raw = value.strip()
        with contextlib.suppress(json.JSONDecodeError):
            return _last_frame_url(json.loads(raw))
        return ""
    if isinstance(value, list):
        for item in value:
            found = _last_frame_url(item)
            if found:
                return found
        return ""
    if isinstance(value, dict):
        normalized = {str(key).replace("_", "").lower(): item for key, item in value.items()}
        for key in ("lastframeurl", "lastframe", "finallframeurl", "finalframeurl"):
            candidate = normalized.get(key)
            if isinstance(candidate, str) and candidate.strip().startswith("https://"):
                return candidate.strip()
        for item in value.values():
            found = _last_frame_url(item)
            if found:
                return found
    return ""


async def enqueue_max_seedance25(
    max_user_id: int,
    *,
    prompt: str,
    scenario: str,
    image_urls: list[str],
    video_urls: list[str],
    audio_urls: list[str],
    duration: int,
    resolution: str,
    aspect_ratio: str,
    generate_audio: bool,
    return_last_frame: bool,
    catalog: MaxPresetManager = max_preset_manager,
) -> MaxGenerationJob:
    scenario_key = str(scenario or "").strip().lower()
    if scenario_key not in SCENARIOS:
        raise ValueError("Некорректный сценарий Seedance 2.5")
    seconds = int(duration)
    if not 4 <= seconds <= 30:
        raise ValueError("Seedance 2.5 поддерживает 4–30 секунд")
    quality = str(resolution or "720p").lower()
    if quality not in RESOLUTIONS:
        raise ValueError("Seedance 2.5 поддерживает 480p или 720p")
    ratio = str(aspect_ratio or "adaptive").lower()
    if ratio not in RATIOS:
        raise ValueError("Некорректный формат кадра Seedance 2.5")
    if scenario_key in {"first_frame", "first_last"}:
        ratio = "adaptive"
    if scenario_key == "text" and not str(prompt or "").strip():
        raise ValueError("Для Text → Video нужен промпт")
    if scenario_key in {"first_frame", "first_last"} and not image_urls:
        raise ValueError("Нужен первый кадр")
    if scenario_key == "first_last" and len(image_urls) < 2:
        raise ValueError("Нужны первый и последний кадры")
    if scenario_key == "multimodal" and not (image_urls or video_urls or audio_urls):
        raise ValueError("Добавьте хотя бы один референс")
    if len(image_urls) > 30 or len(video_urls) > 10 or len(audio_urls) > 10:
        raise ValueError("Слишком много референсов Seedance 2.5")

    generation_type = "text" if scenario_key == "text" else "imgtxt" if scenario_key in {"first_frame", "first_last"} else "video"
    cost = float(catalog.video_cost(MODEL_KEY, duration=seconds, quality=quality))
    job = MaxGenerationJob(
        id=uuid.uuid4().hex,
        max_user_id=int(max_user_id),
        kind="video",
        generation_type=generation_type,
        model=MODEL_KEY,
        prompt=str(prompt or "").strip(),
        cost=cost,
        input_data={
            "image_urls": list(image_urls),
            "video_urls": list(video_urls),
            "audio_urls": list(audio_urls),
        },
        options={
            "seedance25_scenario": scenario_key,
            "duration": seconds,
            "resolution": quality,
            "aspect_ratio": ratio,
            "generate_audio": bool(generate_audio),
            "return_last_frame": bool(return_last_frame),
        },
        status="prepared",
        provider_kind=None,
        provider_task_id=None,
        result_url=None,
        delivered_at_epoch=None,
        attempt_count=0,
    )
    await _insert_job(job)
    try:
        await apply_max_balance_delta(
            max_user_id,
            -cost,
            tx_type="generation",
            idempotency_key=f"maxgen:{job.id}:debit",
            metadata={"job_id": job.id, "kind": "video", "model": MODEL_KEY, "scenario": scenario_key},
        )
    except MaxInsufficientBalanceError:
        await _mark_job_failed(job.id, "insufficient_balance")
        raise
    except Exception:
        await _mark_job_failed(job.id, "billing_error")
        raise

    await record_max_generation(
        max_user_id,
        generation_key=job.id,
        kind="video",
        model=MODEL_KEY,
        prompt=job.prompt,
        status="queued",
        cost=cost,
        request_data={"input": job.input_data, "options": job.options, "generation_type": generation_type},
    )
    await _activate_job(job.id)
    return job


class MaxSeedance25ChannelService(MaxSunoFullChannelService):
    async def _show_seedance_settings(self, user_id: int, *, callback_id: str = "") -> None:
        session = await get_max_session(user_id)
        data = dict(session.data) if session.state == "seedance25:configure" else _default_config()
        scenario = str(data.get("seedance25_scenario") or "text")
        if scenario in {"first_frame", "first_last"}:
            data["aspect_ratio"] = "adaptive"
            await save_max_session(user_id, "seedance25:configure", data)
        cost = self.catalog.video_cost(
            MODEL_KEY,
            duration=int(data.get("duration") or 5),
            quality=str(data.get("resolution") or "720p"),
        )
        await self._respond(
            user_id,
            "🔥 <b>Seedance 2.5</b>\n\n"
            f"Сценарий: <b>{_scenario_label(scenario)}</b>\n"
            f"Качество: <b>{data.get('resolution', '720p')}</b> · "
            f"длительность: <b>{int(data.get('duration') or 5)}с</b>\n"
            f"Формат: <b>{data.get('aspect_ratio', 'adaptive')}</b> · "
            f"звук: <b>{'вкл' if data.get('generate_audio', True) else 'выкл'}</b>\n"
            f"Последний кадр: <b>{'да' if data.get('return_last_frame') else 'нет'}</b>\n\n"
            f"Стоимость: <b>{_format_cost(cost)} 🐾</b>.",
            attachments=_settings_menu(data, self.catalog),
            callback_id=callback_id,
        )

    async def _start_source_step(self, user_id: int, *, callback_id: str) -> None:
        session = await get_max_session(user_id)
        data = dict(session.data)
        scenario = str(data.get("seedance25_scenario") or "text")
        data["image_urls"] = []
        data["video_urls"] = []
        data["audio_urls"] = []
        if scenario == "text":
            state = "seedance25:waiting_prompt"
            text = "✍️ Пришлите промпт для Seedance 2.5 — до 5000 символов."
        elif scenario == "first_frame":
            state = "seedance25:waiting_first"
            text = "🖼 Пришлите первый кадр как фото. Можно также прислать публичную HTTPS-ссылку."
        elif scenario == "first_last":
            state = "seedance25:waiting_first"
            text = "🖼 Пришлите первый кадр. После него попрошу последний."
        else:
            state = "seedance25:waiting_refs"
            text = (
                "🧩 Пришлите фото, видео и/или аудио-референсы. Можно несколькими сообщениями.\n\n"
                "Если MAX не отдаёт ссылку на аудио-вложение, пришлите строку <code>audio=https://...</code>. "
                "Для URL также поддерживаются <code>image=</code> и <code>video=</code>.\n\n"
                "Когда референсы собраны, напишите <b>готово</b>."
            )
        await save_max_session(user_id, state, data)
        await self._respond(user_id, text, attachments=back_home_menu(), callback_id=callback_id)

    async def _prepare_confirmation(self, user_id: int, prompt: str) -> None:
        session = await get_max_session(user_id)
        data = dict(session.data)
        clean_prompt = str(prompt or "").strip()
        if not clean_prompt:
            await self._respond(user_id, "Пришлите текстовый промпт.")
            return
        if len(clean_prompt) > 5000:
            await self._respond(user_id, "Промпт Seedance 2.5 — максимум 5000 символов.")
            return
        duration = int(data.get("duration") or 5)
        resolution = str(data.get("resolution") or "720p")
        cost = self.catalog.video_cost(MODEL_KEY, duration=duration, quality=resolution)
        scenario = str(data.get("seedance25_scenario") or "text")
        prepared = {
            **data,
            "kind": "video",
            "model": MODEL_KEY,
            "generation_type": "text" if scenario == "text" else "imgtxt" if scenario in {"first_frame", "first_last"} else "video",
            "prompt": clean_prompt,
            "input_data": {
                "image_urls": list(data.get("image_urls") or []),
                "video_urls": list(data.get("video_urls") or []),
                "audio_urls": list(data.get("audio_urls") or []),
            },
            "options": {
                "seedance25_scenario": scenario,
                "duration": duration,
                "resolution": resolution,
                "aspect_ratio": "adaptive" if scenario in {"first_frame", "first_last"} else str(data.get("aspect_ratio") or "adaptive"),
                "generate_audio": bool(data.get("generate_audio", True)),
                "return_last_frame": bool(data.get("return_last_frame")),
            },
            "cost": float(cost),
        }
        await save_max_session(user_id, "video:confirm", prepared)
        refs = sum(len(prepared["input_data"][key]) for key in ("image_urls", "video_urls", "audio_urls"))
        await self._respond(
            user_id,
            "✨ <b>Seedance 2.5 готова к запуску</b>\n\n"
            f"Сценарий: <b>{_scenario_label(scenario)}</b>\n"
            f"{duration}с · {resolution} · {prepared['options']['aspect_ratio']}\n"
            f"Референсов: <b>{refs}</b> · цена: <b>{_format_cost(cost)} 🐾</b>\n\n"
            f"Промпт: {clean_prompt[:800]}",
            attachments=generation_confirm_menu(),
        )

    async def _prepare_generation_from_message(self, user_id: int, update: dict[str, Any]) -> bool:
        session = await get_max_session(user_id)
        if not session.state.startswith("seedance25:"):
            return await super()._prepare_generation_from_message(user_id, update)
        data = dict(session.data)
        text = _message_text(update).strip()

        if session.state == "seedance25:waiting_prompt":
            await self._prepare_confirmation(user_id, text)
            return True

        if session.state in {"seedance25:waiting_first", "seedance25:waiting_last"}:
            source = _source_url(update)
            if not source:
                await self._respond(user_id, "Пришлите фото или публичную HTTPS-ссылку на кадр.")
                return True
            images = list(data.get("image_urls") or [])
            if session.state == "seedance25:waiting_first":
                images = [source]
                data["image_urls"] = images
                if data.get("seedance25_scenario") == "first_last":
                    await save_max_session(user_id, "seedance25:waiting_last", data)
                    await self._respond(user_id, "✅ Первый кадр сохранён. Теперь пришлите последний кадр.")
                    return True
            else:
                images = images[:1] + [source]
                data["image_urls"] = images
            await save_max_session(user_id, "seedance25:waiting_prompt", data)
            await self._respond(user_id, "✅ Кадры готовы. Теперь пришлите промпт до 5000 символов.")
            return True

        if session.state == "seedance25:waiting_refs":
            if text.casefold() in _DONE_WORDS:
                if not (data.get("image_urls") or data.get("video_urls") or data.get("audio_urls")):
                    await self._respond(user_id, "Сначала добавьте хотя бы один референс.")
                    return True
                await save_max_session(user_id, "seedance25:waiting_prompt", data)
                await self._respond(user_id, "✅ Референсы собраны. Теперь пришлите промпт.")
                return True

            images, videos, audios = _attachment_urls(update)
            marked_images, marked_videos, marked_audios = _marked_urls(text)
            images.extend(marked_images)
            videos.extend(marked_videos)
            audios.extend(marked_audios)
            if not (images or videos or audios):
                await self._respond(
                    user_id,
                    "Пришлите референс или URL в формате image=https://…, video=https://… или audio=https://…. Потом напишите «готово».",
                )
                return True
            data["image_urls"] = list(dict.fromkeys([*list(data.get("image_urls") or []), *images]))[:30]
            data["video_urls"] = list(dict.fromkeys([*list(data.get("video_urls") or []), *videos]))[:10]
            data["audio_urls"] = list(dict.fromkeys([*list(data.get("audio_urls") or []), *audios]))[:10]
            await save_max_session(user_id, "seedance25:waiting_refs", data)
            await self._respond(
                user_id,
                "✅ Добавил референсы. Сейчас: "
                f"фото {len(data['image_urls'])}/30 · видео {len(data['video_urls'])}/10 · аудио {len(data['audio_urls'])}/10. "
                "Добавляйте ещё или напишите «готово».",
            )
            return True

        return await super()._prepare_generation_from_message(user_id, update)

    async def _launch_generation(self, user_id: int, *, callback_id: str) -> None:
        session = await get_max_session(user_id)
        data = dict(session.data)
        if session.state != "video:confirm" or str(data.get("model") or "") != MODEL_KEY:
            await super()._launch_generation(user_id, callback_id=callback_id)
            return
        options = dict(data.get("options") or {})
        inputs = dict(data.get("input_data") or {})
        try:
            job = await enqueue_max_seedance25(
                user_id,
                prompt=str(data.get("prompt") or ""),
                scenario=str(options.get("seedance25_scenario") or "text"),
                image_urls=list(inputs.get("image_urls") or []),
                video_urls=list(inputs.get("video_urls") or []),
                audio_urls=list(inputs.get("audio_urls") or []),
                duration=int(options.get("duration") or 5),
                resolution=str(options.get("resolution") or "720p"),
                aspect_ratio=str(options.get("aspect_ratio") or "adaptive"),
                generate_audio=bool(options.get("generate_audio", True)),
                return_last_frame=bool(options.get("return_last_frame")),
                catalog=self.catalog,
            )
        except MaxInsufficientBalanceError:
            await self._respond(
                user_id,
                "🐾 Баланса не хватает. Настройки и промпт сохранены.",
                attachments=topup_menu(self.catalog),
                callback_id=callback_id,
            )
            return
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            await self._respond(user_id, f"Не удалось запустить Seedance 2.5: {str(exc)[:300]}", attachments=back_home_menu(), callback_id=callback_id)
            return
        await clear_max_session(user_id)
        balance = await get_max_balance(user_id)
        await self._respond(
            user_id,
            "🚀 <b>Seedance 2.5 запущена</b>\n\n"
            f"Задача: <code>{job.id[:12]}</code>\n"
            f"Списано: <b>{_format_cost(job.cost)} 🐾</b> · осталось <b>{_format_cost(balance)} 🐾</b>.\n\n"
            "Видео придёт сюда автоматически.",
            attachments=main_menu(balance, mini_app_url=self.settings.mini_app_url),
            callback_id=callback_id,
        )

    async def _handle_callback(self, user_id: int, callback_id: str, payload: str) -> None:
        if payload.startswith("max:video:") and payload.endswith(f":{MODEL_KEY}"):
            parts = payload.split(":", 3)
            origin_type = parts[2] if len(parts) == 4 else "text"
            await save_max_session(user_id, "seedance25:configure", _default_config(origin_type))
            await self._show_seedance_settings(user_id, callback_id=callback_id)
            return

        if payload.startswith("max:s25:"):
            session = await get_max_session(user_id)
            if session.state != "seedance25:configure":
                await save_max_session(user_id, "seedance25:configure", _default_config())
                session = await get_max_session(user_id)
            data = dict(session.data)
            if payload.startswith("max:s25:scenario:"):
                scenario = payload.rsplit(":", 1)[-1]
                if scenario in SCENARIOS:
                    data["seedance25_scenario"] = scenario
                    if scenario in {"first_frame", "first_last"}:
                        data["aspect_ratio"] = "adaptive"
            elif payload.startswith("max:s25:res:"):
                resolution = payload.rsplit(":", 1)[-1]
                if resolution in RESOLUTIONS:
                    data["resolution"] = resolution
            elif payload == "max:s25:dur:minus":
                data["duration"] = max(4, int(data.get("duration") or 5) - 1)
            elif payload == "max:s25:dur:plus":
                data["duration"] = min(30, int(data.get("duration") or 5) + 1)
            elif payload.startswith("max:s25:ratio:"):
                ratio = payload.rsplit(":", 1)[-1].replace("x", ":")
                if ratio in RATIOS and data.get("seedance25_scenario") not in {"first_frame", "first_last"}:
                    data["aspect_ratio"] = ratio
            elif payload == "max:s25:audio":
                data["generate_audio"] = not bool(data.get("generate_audio", True))
            elif payload == "max:s25:last":
                data["return_last_frame"] = not bool(data.get("return_last_frame"))
            elif payload == "max:s25:continue":
                await save_max_session(user_id, "seedance25:configure", data)
                await self._start_source_step(user_id, callback_id=callback_id)
                return
            elif payload == "max:s25:noop":
                await self._respond(user_id, "Настройка уже выбрана.", callback_id=callback_id)
                return
            await save_max_session(user_id, "seedance25:configure", data)
            await self._show_seedance_settings(user_id, callback_id=callback_id)
            return

        await super()._handle_callback(user_id, callback_id, payload)


class MaxSeedance25GenerationService(MaxOmniGenerationService):
    async def _poll_seedance(self, job: MaxGenerationJob) -> tuple[str, str]:
        status = await seedance_25_service.get_task_status(str(job.provider_task_id or ""))
        if not isinstance(status, dict):
            raise MaxGenerationRetry("Seedance 2.5 status is temporarily unavailable")
        data = status.get("data") if isinstance(status.get("data"), dict) else {}
        state = str(data.get("status") or "").strip().lower()
        if state in _FAILURE:
            raise RuntimeError("Seedance 2.5 generation failed")
        if state not in _SUCCESS:
            raise MaxGenerationRetry("Seedance 2.5 is still processing")
        video_url = _first_https(data.get("output")) or _first_https(status.get("raw"))
        if not video_url:
            raise RuntimeError("Seedance 2.5 completed without a video URL")
        return video_url, _last_frame_url(status.get("raw"))

    async def _process(self, job: MaxGenerationJob) -> None:
        if job.model != MODEL_KEY:
            await super()._process(job)
            return

        current = job
        options = dict(current.options)
        inputs = dict(current.input_data)
        scenario = str(options.get("seedance25_scenario") or "text")
        image_urls = list(inputs.get("image_urls") or [])
        video_urls = list(inputs.get("video_urls") or [])
        audio_urls = list(inputs.get("audio_urls") or [])

        if not current.result_url and not current.provider_task_id:
            response = await seedance_25_service.generate_video(
                prompt=current.prompt,
                duration=int(options.get("duration") or 5),
                aspect_ratio=str(options.get("aspect_ratio") or "adaptive"),
                resolution=str(options.get("resolution") or "720p"),
                first_frame_url=image_urls[0] if scenario in {"first_frame", "first_last"} and image_urls else None,
                last_frame_url=image_urls[1] if scenario == "first_last" and len(image_urls) > 1 else None,
                reference_image_urls=image_urls if scenario == "multimodal" else None,
                reference_video_urls=video_urls if scenario == "multimodal" else None,
                reference_audio_urls=audio_urls if scenario == "multimodal" else None,
                return_last_frame=bool(options.get("return_last_frame")),
                generate_audio=bool(options.get("generate_audio", True)),
            )
            task_id = str(response.get("task_id") or "") if isinstance(response, dict) else ""
            if not task_id:
                raise RuntimeError(str((response or {}).get("error") if isinstance(response, dict) else "Seedance 2.5 returned no task"))
            await _mark_provider_task(current.id, "kie", task_id)
            current = await get_max_generation_job(current.id) or current

        last_frame = ""
        result_url = current.result_url
        if not result_url:
            result_url, last_frame = await self._poll_seedance(current)
            await _mark_result(current.id, result_url)
            current = await get_max_generation_job(current.id) or current
        elif bool(options.get("return_last_frame")) and current.provider_task_id:
            with contextlib.suppress(Exception):
                status = await seedance_25_service.get_task_status(current.provider_task_id)
                if isinstance(status, dict):
                    last_frame = _last_frame_url(status.get("raw"))

        if current.delivered_at_epoch is None:
            await self.client.send_media_url(
                current.max_user_id,
                media_type="video",
                url=result_url,
                text="Готово 🎬\n\nSeedance 2.5 сохранила видео в истории MAX.",
                filename=f"seedance25-{current.id}.mp4",
            )
            await _mark_delivered(current.id)
            if bool(options.get("return_last_frame")) and last_frame:
                with contextlib.suppress(Exception):
                    await self.client.send_media_url(
                        current.max_user_id,
                        media_type="image",
                        url=last_frame,
                        text="🖼 Последний кадр Seedance 2.5",
                        filename=f"seedance25-{current.id}-last-frame.png",
                    )

        await record_max_generation(
            current.max_user_id,
            generation_key=current.id,
            kind="video",
            model=MODEL_KEY,
            prompt=current.prompt,
            status="completed",
            cost=current.cost,
            provider_task_id=current.provider_task_id,
            result_url=result_url,
            request_data={"input": current.input_data, "options": current.options, "generation_type": current.generation_type},
        )
        await _mark_job_succeeded(current.id)
