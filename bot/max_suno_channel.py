from __future__ import annotations

import html
from typing import Any

from bot.max_api import callback_button, inline_keyboard
from bot.max_channel import _format_cost, _message_text
from bot.max_omni_channel import MaxOmniChannelService
from bot.max_store import (
    MaxInsufficientBalanceError,
    clear_max_session,
    get_max_balance,
    get_max_session,
    save_max_session,
)
from bot.max_ui import back_home_menu, main_menu, topup_menu
from bot.suno_jobs import enqueue_suno_job, get_suno_job, list_suno_jobs
from bot.suno_pricing import SUNO_MODELS, SUNO_OPERATION_LABELS, get_suno_price

_MODEL_LABELS = {
    "V5_5": "Suno V5.5",
    "V5": "Suno V5",
    "V4_5PLUS": "Suno V4.5+",
    "V4_5": "Suno V4.5",
    "V4_5ALL": "Suno V4.5 All",
    "V4": "Suno V4",
}
_UPLOAD_OPERATIONS = {"upload_extend", "upload_cover", "add_vocals", "add_instrumental"}


async def _suno_menu() -> list[dict[str, Any]]:
    generate = await get_suno_price("max", "generate", "V5_5")
    lyrics = await get_suno_price("max", "lyrics")
    cover = await get_suno_price("max", "upload_cover", "V5_5")
    stems = await get_suno_price("max", "separate_vocal")
    sounds = await get_suno_price("max", "sounds")
    voice = await get_suno_price("max", "voice_validate")
    return [
        inline_keyboard(
            [
                [callback_button(f"🎵 Создать · {_format_cost(generate)} 🐾", "max:suno:generate")],
                [
                    callback_button(f"✍️ Lyrics · {_format_cost(lyrics)} 🐾", "max:suno:lyrics"),
                    callback_button(f"🎛 Cover · {_format_cost(cover)} 🐾", "max:suno:op:upload_cover"),
                ],
                [
                    callback_button("➕ Загрузить / продолжить", "max:suno:uploads"),
                    callback_button(f"🎚 Tools · {_format_cost(stems)} 🐾", "max:suno:tools"),
                ],
                [
                    callback_button(f"🌊 Sounds · {_format_cost(sounds)} 🐾", "max:suno:sounds"),
                    callback_button(f"🎙 Voice · {_format_cost(voice)} 🐾", "max:suno:voice"),
                ],
                [callback_button("🕘 История Suno", "max:suno:history")],
                [callback_button("🏠 Главное меню", "max:home")],
            ]
        )
    ]


async def _model_menu(operation: str) -> list[dict[str, Any]]:
    rows: list[list[dict[str, str]]] = []
    price_operation = "generate" if operation == "generate_custom" else operation
    for model in SUNO_MODELS:
        price = await get_suno_price("max", price_operation, model)
        rows.append(
            [
                callback_button(
                    f"{_MODEL_LABELS.get(model, model)} · {_format_cost(price)} 🐾",
                    f"max:suno:model:{operation}:{model}",
                )
            ]
        )
    rows.append([callback_button("⬅️ Suno", "max:music")])
    return [inline_keyboard(rows)]


class MaxSunoChannelService(MaxOmniChannelService):
    async def _enqueue(
        self,
        user_id: int,
        *,
        operation: str,
        request: dict[str, Any],
        model: str | None = None,
        callback_id: str = "",
    ) -> bool:
        try:
            job = await enqueue_suno_job(
                "max",
                user_id,
                operation=operation,
                request_data=request,
                model=model,
            )
        except MaxInsufficientBalanceError:
            await self._respond(
                user_id,
                "🐾 Баланса MAX не хватает для этой Suno-задачи.",
                attachments=topup_menu(self.catalog),
                callback_id=callback_id,
            )
            return False
        except (TypeError, ValueError, RuntimeError) as exc:
            await self._respond(
                user_id,
                f"Не удалось запустить Suno: {html.escape(str(exc)[:300])}",
                attachments=await _suno_menu(),
                callback_id=callback_id,
            )
            return False
        await clear_max_session(user_id)
        balance = await get_max_balance(user_id)
        await self._respond(
            user_id,
            "🚀 <b>Suno уже работает</b>\n\n"
            f"Задача: <code>{job.id[:12]}</code>\n"
            f"Списано: <b>{_format_cost(job.cost)} 🐾</b>\n"
            f"Осталось: <b>{_format_cost(balance)} 🐾</b>\n\n"
            "Результат придёт сюда автоматически. Новую генерацию можно запускать сразу.",
            attachments=await _suno_menu(),
            callback_id=callback_id,
        )
        return True

    async def _prepare_generation_from_message(self, user_id: int, update: dict[str, Any]) -> bool:
        session = await get_max_session(user_id)
        data = dict(session.data)
        text = _message_text(update).strip()

        if session.state == "suno:simple":
            if not text:
                await self._respond(user_id, "Опишите будущий трек текстом.", attachments=back_home_menu())
                return True
            model = str(data.get("model") or "V5_5")
            return await self._enqueue(
                user_id,
                operation="generate",
                request={
                    "prompt": text[:3000],
                    "customMode": False,
                    "instrumental": bool(data.get("instrumental")),
                    "model": model,
                },
                model=model,
            )

        if session.state == "suno:custom":
            lines = text.splitlines()
            instrumental = bool(data.get("instrumental"))
            if len(lines) < 2 or (not instrumental and len(lines) < 3):
                await self._respond(
                    user_id,
                    "Для Custom пришлите название, стиль и текст песни с новой строки. Для инструментала достаточно первых двух строк.",
                    attachments=back_home_menu(),
                )
                return True
            model = str(data.get("model") or "V5_5")
            request: dict[str, Any] = {
                "customMode": True,
                "instrumental": instrumental,
                "style": lines[1].strip()[:1000],
                "title": lines[0].strip()[:80],
                "model": model,
            }
            if not instrumental:
                request["prompt"] = "\n".join(lines[2:]).strip()[:5000]
            return await self._enqueue(user_id, operation="generate", request=request, model=model)

        if session.state == "suno:lyrics":
            if not text:
                await self._respond(user_id, "Опишите тему будущего текста.")
                return True
            return await self._enqueue(user_id, operation="lyrics", request={"prompt": text[:3000]})

        if session.state == "suno:sounds":
            if not text:
                await self._respond(user_id, "Опишите звук или атмосферу.")
                return True
            return await self._enqueue(
                user_id,
                operation="sounds",
                request={"prompt": text[:3000], "model": "V5", "soundLoop": True},
            )

        if session.state == "suno:upload_url":
            if not text.startswith("https://"):
                await self._respond(
                    user_id,
                    "Пришлите публичную HTTPS-ссылку на аудио. Для уже созданных здесь треков удобнее использовать кнопки под результатом.",
                    attachments=back_home_menu(),
                )
                return True
            data["upload_url"] = text
            await save_max_session(user_id, "suno:upload_params", data)
            operation = str(data.get("operation") or "")
            if operation == "upload_extend":
                prompt = "Опишите, как продолжить трек."
            elif operation == "upload_cover":
                prompt = "Опишите новый стиль cover."
            elif operation == "add_vocals":
                prompt = "Пришлите 3 строки: название, стиль, текст вокала."
            else:
                prompt = "Пришлите 2 строки: название и стиль инструментала."
            await self._respond(user_id, prompt, attachments=back_home_menu())
            return True

        if session.state == "suno:upload_params":
            if not text:
                await self._respond(user_id, "Добавьте параметры текстом.")
                return True
            operation = str(data.get("operation") or "")
            model = str(data.get("model") or "V5_5")
            request: dict[str, Any] = {"uploadUrl": str(data.get("upload_url") or ""), "model": model}
            if operation == "upload_extend":
                request.update({"defaultParamFlag": True, "prompt": text[:5000], "style": "Original continuation", "title": "Extended", "continueAt": 0})
            elif operation == "upload_cover":
                request.update({"prompt": text[:500], "customMode": False, "instrumental": False})
            elif operation == "add_vocals":
                lines = text.splitlines()
                if len(lines) < 3:
                    await self._respond(user_id, "Нужно 3 строки: название, стиль, текст вокала.")
                    return True
                request.update({"title": lines[0][:80], "style": lines[1][:1000], "prompt": "\n".join(lines[2:])[:5000]})
            elif operation == "add_instrumental":
                lines = text.splitlines()
                if len(lines) < 2:
                    await self._respond(user_id, "Нужно 2 строки: название и стиль.")
                    return True
                request.update({"title": lines[0][:80], "tags": lines[1][:1000]})
            return await self._enqueue(user_id, operation=operation, request=request, model=model)

        if session.state == "suno:id_pair":
            parts = text.split()
            if len(parts) < 2:
                await self._respond(user_id, "Пришлите Task ID и Audio ID через пробел.")
                return True
            return await self._enqueue(
                user_id,
                operation=str(data.get("operation") or ""),
                request={"taskId": parts[0][:200], "audioId": parts[1][:200]},
            )

        if session.state == "suno:persona":
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if len(lines) < 3:
                await self._respond(user_id, "Нужно 3 строки: имя Persona, описание и стиль.")
                return True
            return await self._enqueue(
                user_id,
                operation="persona",
                request={
                    "taskId": str(data.get("task_id") or ""),
                    "audioId": str(data.get("audio_id") or ""),
                    "name": lines[0][:100],
                    "description": lines[1][:1000],
                    "style": lines[2][:1000],
                    "vocalStart": 0,
                    "vocalEnd": 30,
                },
            )

        return await super()._prepare_generation_from_message(user_id, update)

    async def _handle_callback(self, user_id: int, callback_id: str, payload: str) -> None:
        if payload == "max:music":
            await clear_max_session(user_id)
            await self._respond(
                user_id,
                "🎵 <b>Suno Studio в MAX</b>\n\nСоздавайте музыку и обрабатывайте готовые треки прямо в чате.",
                attachments=await _suno_menu(),
                callback_id=callback_id,
            )
            return

        if payload == "max:suno:generate":
            await self._respond(
                user_id,
                "🎼 <b>Как создаём?</b>",
                attachments=[
                    inline_keyboard(
                        [
                            [
                                callback_button("⚡ С вокалом", "max:suno:genmode:simple:vocals"),
                                callback_button("🎹 Инструментал", "max:suno:genmode:simple:instrumental"),
                            ],
                            [callback_button("🎚 Custom", "max:suno:genmode:custom:vocals")],
                            [callback_button("⬅️ Suno", "max:music")],
                        ]
                    )
                ],
                callback_id=callback_id,
            )
            return

        if payload.startswith("max:suno:genmode:"):
            parts = payload.split(":")
            custom = len(parts) > 3 and parts[3] == "custom"
            instrumental = parts[-1] == "instrumental"
            await save_max_session(user_id, "suno:choosing_model", {"custom_mode": custom, "instrumental": instrumental})
            await self._respond(
                user_id,
                "🧠 <b>Выберите версию Suno</b>",
                attachments=await _model_menu("generate_custom" if custom else "generate"),
                callback_id=callback_id,
            )
            return

        if payload.startswith("max:suno:model:"):
            parts = payload.split(":", 4)
            if len(parts) != 5:
                await self._respond(user_id, "Кнопка устарела.", callback_id=callback_id)
                return
            operation, model = parts[3], parts[4]
            if model not in SUNO_MODELS:
                await self._respond(user_id, "Эта версия Suno недоступна.", callback_id=callback_id)
                return
            session = await get_max_session(user_id)
            data = dict(session.data)
            data.update({"model": model, "operation": ("generate" if operation == "generate_custom" else operation)})
            if operation in {"generate", "generate_custom"}:
                state = "suno:custom" if bool(data.get("custom_mode")) else "suno:simple"
                await save_max_session(user_id, state, data)
                prompt = "Пришлите название, стиль и текст песни с новой строки." if state == "suno:custom" else "Опишите будущий трек обычным сообщением."
            else:
                await save_max_session(user_id, "suno:upload_url", data)
                prompt = "Пришлите публичную HTTPS-ссылку на аудио."
            await self._respond(user_id, prompt, attachments=back_home_menu(), callback_id=callback_id)
            return

        if payload == "max:suno:lyrics":
            await save_max_session(user_id, "suno:lyrics", {"operation": "lyrics"})
            await self._respond(user_id, "✍️ Опишите тему, историю и настроение текста песни.", attachments=back_home_menu(), callback_id=callback_id)
            return

        if payload == "max:suno:sounds":
            await save_max_session(user_id, "suno:sounds", {"operation": "sounds"})
            await self._respond(user_id, "🌊 Опишите звук, атмосферу или музыкальный loop.", attachments=back_home_menu(), callback_id=callback_id)
            return

        if payload == "max:suno:uploads":
            await self._respond(
                user_id,
                "🎧 <b>Работа со своим аудио</b>",
                attachments=[
                    inline_keyboard(
                        [
                            [callback_button("➕ Upload + Extend", "max:suno:op:upload_extend")],
                            [callback_button("🎛 Upload + Cover", "max:suno:op:upload_cover")],
                            [callback_button("🎤 Add Vocals", "max:suno:op:add_vocals")],
                            [callback_button("🎹 Add Instrumental", "max:suno:op:add_instrumental")],
                            [callback_button("⬅️ Suno", "max:music")],
                        ]
                    )
                ],
                callback_id=callback_id,
            )
            return

        if payload.startswith("max:suno:op:"):
            operation = payload.split(":", 3)[3]
            if operation not in _UPLOAD_OPERATIONS:
                await self._respond(user_id, "Операция недоступна.", callback_id=callback_id)
                return
            await save_max_session(user_id, "suno:choosing_model", {"operation": operation})
            await self._respond(user_id, "🧠 Выберите модель.", attachments=await _model_menu(operation), callback_id=callback_id)
            return

        if payload == "max:suno:tools":
            await self._respond(
                user_id,
                "🧰 <b>Suno Tools</b>\n\nПод готовым треком есть быстрые кнопки. Для ручного запуска укажите Task ID + Audio ID.",
                attachments=[
                    inline_keyboard(
                        [
                            [callback_button("🎚 Вокал / инструментал", "max:suno:ids:separate_vocal")],
                            [callback_button("🧩 Полные стемы", "max:suno:ids:split_stem")],
                            [callback_button("🎧 WAV", "max:suno:ids:wav")],
                            [callback_button("🎬 Music Video", "max:suno:ids:music_video")],
                            [callback_button("📝 Таймкоды", "max:suno:ids:timestamped_lyrics")],
                            [callback_button("⬅️ Suno", "max:music")],
                        ]
                    )
                ],
                callback_id=callback_id,
            )
            return

        if payload.startswith("max:suno:ids:"):
            operation = payload.split(":", 3)[3]
            await save_max_session(user_id, "suno:id_pair", {"operation": operation})
            await self._respond(user_id, "Пришлите одной строкой: <code>TaskID AudioID</code>", attachments=back_home_menu(), callback_id=callback_id)
            return

        if payload == "max:suno:voice":
            await self._respond(
                user_id,
                "🎙 <b>Suno Voice</b>\n\nСоздание Voice ID требует аудиозаписи проверочной фразы. В MAX сейчас безопаснее использовать публичную ссылку на запись.",
                attachments=[inline_keyboard([[callback_button("1️⃣ Получить фразу", "max:suno:voice_validate")], [callback_button("⬅️ Suno", "max:music")]])],
                callback_id=callback_id,
            )
            return

        if payload == "max:suno:voice_validate":
            await self._enqueue(user_id, operation="voice_validate", request={}, callback_id=callback_id)
            return

        if payload.startswith("max:suno:from:"):
            parts = payload.split(":")
            if len(parts) != 6:
                await self._respond(user_id, "Кнопка устарела.", callback_id=callback_id)
                return
            operation, job_id, raw_index = parts[3], parts[4], parts[5]
            source = await get_suno_job(job_id)
            if source is None or source.channel != "max" or source.user_id != user_id:
                await self._respond(user_id, "Исходный трек не найден.", callback_id=callback_id)
                return
            try:
                track = (source.result_data.get("tracks") or [])[int(raw_index)]
            except (ValueError, IndexError, TypeError):
                await self._respond(user_id, "Трек не найден.", callback_id=callback_id)
                return
            audio_id = str(track.get("audio_id") or "").strip()
            if not audio_id or not source.provider_task_id:
                await self._respond(user_id, "У трека нет нужных Suno ID.", callback_id=callback_id)
                return
            if operation == "persona":
                await save_max_session(user_id, "suno:persona", {"task_id": source.provider_task_id, "audio_id": audio_id})
                await self._respond(user_id, "🎭 Пришлите 3 строки: имя Persona, описание, стиль.", callback_id=callback_id)
                return
            model: str | None = None
            request: dict[str, Any] = {"taskId": source.provider_task_id, "audioId": audio_id}
            if operation == "extend":
                model = source.model or "V5_5"
                request = {"audioId": audio_id, "defaultParamFlag": False, "model": model}
            await self._enqueue(user_id, operation=operation, request=request, model=model, callback_id=callback_id)
            return

        if payload == "max:suno:history":
            jobs = await list_suno_jobs("max", user_id, limit=8)
            lines = ["🕘 <b>Последние Suno-задачи</b>"]
            if not jobs:
                lines.append("Пока пусто.")
            for job in jobs:
                lines.append(
                    f"• {html.escape(SUNO_OPERATION_LABELS.get(job.operation, job.operation))} · "
                    f"<code>{html.escape(job.status)}</code> · {_format_cost(job.cost)} 🐾 · <code>{job.id[:10]}</code>"
                )
            await self._respond(user_id, "\n".join(lines), attachments=await _suno_menu(), callback_id=callback_id)
            return

        await super()._handle_callback(user_id, callback_id, payload)
