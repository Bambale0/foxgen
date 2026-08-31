from __future__ import annotations

import html
from typing import Any
from urllib.parse import quote, unquote

from bot.max_api import MaxApiError, callback_button, inline_keyboard
from bot.max_channel import _format_cost, _media_urls, _message_text
from bot.max_creator_channel import MaxCreatorChannelService
from bot.max_omni_audio import enqueue_max_omni_audio, omni_audio_cost
from bot.max_store import (
    MaxInsufficientBalanceError,
    clear_max_session,
    get_max_balance,
    get_max_session,
    list_max_history,
    save_max_session,
)
from bot.max_ui import back_home_menu, main_menu, topup_menu
from bot.services.gemini_omni_service import gemini_omni_service

_AUDIO_VOICES = (
    "achernar",
    "aoede",
    "charon",
    "fenrir",
    "kore",
    "puck",
    "schedar",
    "zephyr",
)


def _audio_voice_menu() -> list[dict[str, Any]]:
    rows = [
        [
            callback_button(voice.title(), f"max:audio:voice:{voice}")
            for voice in _AUDIO_VOICES[index : index + 2]
        ]
        for index in range(0, len(_AUDIO_VOICES), 2)
    ]
    rows.append([callback_button("🏠 Главное меню", "max:home")])
    return [inline_keyboard(rows)]


def _audio_confirm_menu() -> list[dict[str, Any]]:
    return [
        inline_keyboard(
            [
                [callback_button("🚀 Создать Audio ID", "max:generate")],
                [callback_button("💬 Добавить пример реплики", "max:audio:example")],
                [callback_button("🏠 Главное меню", "max:home")],
            ]
        )
    ]


class MaxOmniChannelService(MaxCreatorChannelService):
    async def _show_audio_confirm(
        self,
        user_id: int,
        data: dict[str, Any],
        *,
        callback_id: str = "",
    ) -> None:
        example = str(data.get("example_dialogue") or "").strip()
        example_line = "добавлен" if example else "не задан"
        await self._respond(
            user_id,
            "🎙 <b>Audio ID готов к созданию</b>\n\n"
            f"Базовый голос: <b>{html.escape(str(data.get('base_voice') or ''))}</b>\n"
            f"Имя: <b>{html.escape(str(data.get('name') or ''))}</b>\n"
            f"Пример реплики: <b>{example_line}</b>\n"
            f"Стоимость: <b>{_format_cost(float(data.get('cost') or 0))} 🐾</b>",
            attachments=_audio_confirm_menu(),
            callback_id=callback_id,
        )

    async def _prepare_generation_from_message(
        self,
        user_id: int,
        update: dict[str, Any],
    ) -> bool:
        session = await get_max_session(user_id)
        data = dict(session.data)

        if session.state == "audio:waiting_profile":
            text = _message_text(update).strip()
            if not text:
                await self._respond(
                    user_id,
                    "Отправьте имя голоса первой строкой. Описание можно добавить со второй строки.",
                    attachments=back_home_menu(),
                )
                return True
            lines = [line.strip() for line in text.splitlines()]
            name = next((line for line in lines if line), "")
            if not name:
                await self._respond(user_id, "Имя голоса не должно быть пустым.")
                return True
            if len(name) > 20:
                await self._respond(
                    user_id,
                    "Имя Audio ID должно быть не длиннее 20 символов. Сократите первую строку.",
                    attachments=back_home_menu(),
                )
                return True
            first_index = lines.index(name)
            description = "\n".join(lines[first_index + 1 :]).strip()[:2000]
            data.update(
                {
                    "name": name,
                    "voice_description": description,
                    "example_dialogue": "",
                    "cost": omni_audio_cost(self.catalog),
                }
            )
            await save_max_session(user_id, "audio:confirm", data)
            await self._show_audio_confirm(user_id, data)
            return True

        if session.state == "audio:waiting_example":
            example = _message_text(update).strip()
            if not example:
                await self._respond(
                    user_id,
                    "Пришлите пример реплики текстом или вернитесь в главное меню.",
                    attachments=back_home_menu(),
                )
                return True
            data["example_dialogue"] = example[:2000]
            await save_max_session(user_id, "audio:confirm", data)
            await self._show_audio_confirm(user_id, data)
            return True

        if (
            session.state == "video:waiting_input"
            and str(data.get("model") or "") == "gemini_omni"
            and str(data.get("audio_id") or "").strip()
        ):
            prompt = _message_text(update).strip()
            if not prompt:
                await self._respond(
                    user_id,
                    "Добавьте текстовый промпт для Gemini Omni.",
                    attachments=back_home_menu(),
                )
                return True
            try:
                resolved_update = await self._resolve_video_attachments(update)
            except MaxApiError:
                await self._respond(
                    user_id,
                    "Не удалось прочитать видео-референс из MAX. Пришлите его ещё раз или продолжите без видео.",
                    attachments=back_home_menu(),
                )
                return True
            images, videos = _media_urls(resolved_update)
            audio_id = str(data["audio_id"]).strip()
            duration = 6
            resolution = "720p"
            cost = self.catalog.video_cost(
                "gemini_omni",
                duration=duration,
                quality=resolution,
            )
            data.update(
                {
                    "prompt": prompt,
                    "input_data": {
                        "image_urls": images,
                        "video_urls": videos,
                        "audio_ids": [audio_id],
                    },
                    "options": {
                        "duration": duration,
                        "aspect_ratio": "16:9",
                        "resolution": resolution,
                        "generate_audio": True,
                    },
                    "cost": float(cost),
                }
            )
            await save_max_session(user_id, "video:confirm", data)
            await self._respond(
                user_id,
                "✨ <b>Gemini Omni готов к запуску</b>\n\n"
                f"Audio ID: <code>{html.escape(audio_id)}</code>\n"
                f"Стоимость: <b>{_format_cost(cost)} 🐾</b>\n\n"
                f"Промпт: {html.escape(prompt[:800])}",
                attachments=[
                    inline_keyboard(
                        [
                            [callback_button("🚀 Запустить", "max:generate")],
                            [callback_button("🏠 Главное меню", "max:home")],
                        ]
                    )
                ],
            )
            return True

        return await super()._prepare_generation_from_message(user_id, update)

    async def _handle_callback(
        self,
        user_id: int,
        callback_id: str,
        payload: str,
    ) -> None:
        if payload == "max:omni_audio":
            await clear_max_session(user_id)
            cost = omni_audio_cost(self.catalog)
            await self._respond(
                user_id,
                "🎙 <b>Создать Audio ID для Gemini Omni</b>\n\n"
                "Выберите базовый голос. Дальше нужно будет одним сообщением прислать имя, а при желании — описание голоса.\n\n"
                f"Стоимость: <b>{_format_cost(cost)} 🐾</b>",
                attachments=_audio_voice_menu(),
                callback_id=callback_id,
            )
            return

        if payload.startswith("max:audio:voice:"):
            voice = payload.split(":", 3)[3].strip().lower()
            if voice not in gemini_omni_service.BASE_VOICES:
                await self._respond(
                    user_id,
                    "Этот базовый голос сейчас недоступен.",
                    attachments=_audio_voice_menu(),
                    callback_id=callback_id,
                )
                return
            await save_max_session(
                user_id,
                "audio:waiting_profile",
                {"base_voice": voice},
            )
            await self._respond(
                user_id,
                f"🎙 <b>{html.escape(voice.title())}</b>\n\n"
                "Пришлите профиль одним сообщением:\n"
                "1-я строка — имя голоса (до 20 символов).\n"
                "Со 2-й строки — описание голоса, если оно нужно.",
                attachments=back_home_menu(),
                callback_id=callback_id,
            )
            return

        if payload == "max:audio:example":
            session = await get_max_session(user_id)
            if session.state != "audio:confirm":
                await self._respond(
                    user_id,
                    "Сценарий Audio ID устарел. Начните его заново.",
                    attachments=_audio_voice_menu(),
                    callback_id=callback_id,
                )
                return
            await save_max_session(
                user_id,
                "audio:waiting_example",
                dict(session.data),
            )
            await self._respond(
                user_id,
                "💬 Пришлите одну примерную реплику для этого голоса.",
                attachments=back_home_menu(),
                callback_id=callback_id,
            )
            return

        if payload.startswith("max:omni:audio:"):
            encoded = payload.split(":", 3)[3]
            audio_id = unquote(encoded).strip()
            if not audio_id or len(audio_id) > 200:
                await self._respond(
                    user_id,
                    "Audio ID повреждён или слишком длинный. Создайте новый или скопируйте ID из истории.",
                    attachments=back_home_menu(),
                    callback_id=callback_id,
                )
                return
            await save_max_session(
                user_id,
                "video:waiting_input",
                {
                    "kind": "video",
                    "generation_type": "text",
                    "model": "gemini_omni",
                    "audio_id": audio_id,
                },
            )
            await self._respond(
                user_id,
                "🎬 <b>Gemini Omni + ваш Audio ID</b>\n\n"
                "Пришлите промпт для видео. Можно приложить фото или видео-референс в том же сообщении.",
                attachments=back_home_menu(),
                callback_id=callback_id,
            )
            return

        await super()._handle_callback(user_id, callback_id, payload)

    async def _launch_generation(self, user_id: int, *, callback_id: str) -> None:
        session = await get_max_session(user_id)
        if session.state != "audio:confirm":
            await super()._launch_generation(user_id, callback_id=callback_id)
            return

        data = dict(session.data)
        try:
            job = await enqueue_max_omni_audio(
                user_id,
                base_voice=str(data.get("base_voice") or ""),
                name=str(data.get("name") or ""),
                voice_description=str(data.get("voice_description") or ""),
                example_dialogue=str(data.get("example_dialogue") or ""),
                catalog=self.catalog,
            )
        except MaxInsufficientBalanceError:
            await self._respond(
                user_id,
                "🐾 Баланса не хватает. Пополните MAX-баланс — профиль голоса сохранён.",
                attachments=topup_menu(self.catalog),
                callback_id=callback_id,
            )
            return
        except (TypeError, ValueError, RuntimeError) as exc:
            await self._respond(
                user_id,
                f"Не удалось поставить Audio ID в очередь: {html.escape(str(exc)[:300])}",
                attachments=_audio_confirm_menu(),
                callback_id=callback_id,
            )
            return

        await clear_max_session(user_id)
        balance = await get_max_balance(user_id)
        await self._respond(
            user_id,
            "🚀 <b>Audio ID создаётся</b>\n\n"
            f"Задача: <code>{html.escape(job.id[:12])}</code>\n"
            f"Списано: <b>{_format_cost(job.cost)} 🐾</b>\n"
            f"Осталось: <b>{_format_cost(balance)} 🐾</b>\n\n"
            "Готовый Audio ID придёт сюда автоматически.",
            attachments=main_menu(
                balance,
                mini_app_url=self.settings.mini_app_url,
            ),
            callback_id=callback_id,
        )

    async def _history(self, user_id: int, *, callback_id: str) -> None:
        history = await list_max_history(user_id, limit=5)
        if not history:
            await super()._history(user_id, callback_id=callback_id)
            return

        lines = ["🔗 <b>Последние работы MAX</b>"]
        audio_rows: list[list[dict[str, Any]]] = []
        for item in history:
            model = html.escape(str(item.get("model") or "model"))
            status = html.escape(str(item.get("status") or ""))
            result = str(item.get("result_url") or "").strip()
            kind = str(item.get("kind") or "").strip()
            line = f"• {model} · {status}"
            if kind == "audio_id" and result:
                line += f"\n  Audio ID: <code>{html.escape(result)}</code>"
                payload = f"max:omni:audio:{quote(result, safe='')}"
                if len(payload) <= 220:
                    audio_rows.append(
                        [
                            callback_button(
                                f"🎬 Audio {result[:8]}",
                                payload,
                            )
                        ]
                    )
            elif result.startswith("https://"):
                line += f"\n  {html.escape(result)}"
            lines.append(line)

        audio_rows.append([callback_button("🏠 Главное меню", "max:home")])
        await self._respond(
            user_id,
            "\n\n".join(lines),
            attachments=[inline_keyboard(audio_rows)],
            callback_id=callback_id,
        )
