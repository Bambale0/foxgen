from __future__ import annotations

from typing import Any

from bot.max_api import callback_button, inline_keyboard
from bot.max_channel import _message_text
from bot.max_suno_channel import MaxSunoChannelService
from bot.max_store import get_max_session, save_max_session
from bot.max_ui import back_home_menu


class MaxSunoFullChannelService(MaxSunoChannelService):
    async def _prepare_generation_from_message(self, user_id: int, update: dict[str, Any]) -> bool:
        session = await get_max_session(user_id)
        data = dict(session.data)
        text = _message_text(update).strip()

        if session.state == "suno:voice_url":
            if not text.startswith("https://"):
                await self._respond(
                    user_id,
                    "Пришлите публичную HTTPS-ссылку на запись проверочной фразы.",
                    attachments=back_home_menu(),
                )
                return True
            await save_max_session(user_id, "suno:voice_name", {"upload_url": text})
            await self._respond(
                user_id,
                "🎙 Теперь пришлите имя будущего голоса.",
                attachments=back_home_menu(),
            )
            return True

        if session.state == "suno:voice_name":
            if not text:
                await self._respond(user_id, "Пришлите имя голоса.")
                return True
            return await self._enqueue(
                user_id,
                operation="voice_generate",
                request={
                    "uploadUrl": str(data.get("upload_url") or ""),
                    "name": text[:80],
                },
            )

        if session.state == "suno:advanced_id_pair":
            parts = text.split()
            if len(parts) < 2:
                await self._respond(user_id, "Нужны Task ID и Audio ID через пробел.")
                return True
            return await self._enqueue(
                user_id,
                operation=str(data.get("operation") or ""),
                request={"taskId": parts[0][:200], "audioId": parts[1][:200]},
            )

        return await super()._prepare_generation_from_message(user_id, update)

    async def _handle_callback(self, user_id: int, callback_id: str, payload: str) -> None:
        if payload == "max:suno:voice":
            await self._respond(
                user_id,
                "🎙 <b>Suno Voice</b>\n\n"
                "Сначала получите проверочную фразу, запишите её, затем создайте собственный Voice ID.",
                attachments=[
                    inline_keyboard(
                        [
                            [callback_button("1️⃣ Получить фразу", "max:suno:voice_validate")],
                            [callback_button("2️⃣ Создать Voice ID", "max:suno:voice_generate")],
                            [callback_button("⬅️ Suno", "max:music")],
                        ]
                    )
                ],
                callback_id=callback_id,
            )
            return

        if payload == "max:suno:voice_generate":
            await save_max_session(user_id, "suno:voice_url", {"operation": "voice_generate"})
            await self._respond(
                user_id,
                "🎙 Пришлите публичную HTTPS-ссылку на запись проверочной фразы.",
                attachments=back_home_menu(),
                callback_id=callback_id,
            )
            return

        if payload == "max:suno:tools":
            await self._respond(
                user_id,
                "🧰 <b>Suno Tools</b>\n\n"
                "Под готовым треком доступны быстрые действия. Здесь можно запустить инструмент вручную по Task ID + Audio ID.",
                attachments=[
                    inline_keyboard(
                        [
                            [callback_button("🎚 Вокал / инструментал", "max:suno:advanced:separate_vocal")],
                            [callback_button("🧩 Полные стемы", "max:suno:advanced:split_stem")],
                            [callback_button("🎯 Точный стем", "max:suno:advanced:split_stem_advanced")],
                            [callback_button("🎹 MIDI из стемов", "max:suno:advanced:midi")],
                            [callback_button("🎧 WAV", "max:suno:advanced:wav")],
                            [callback_button("🎬 Music Video", "max:suno:advanced:music_video")],
                            [callback_button("📝 Таймкоды", "max:suno:advanced:timestamped_lyrics")],
                            [callback_button("⬅️ Suno", "max:music")],
                        ]
                    )
                ],
                callback_id=callback_id,
            )
            return

        if payload.startswith("max:suno:advanced:"):
            operation = payload.split(":", 3)[3]
            allowed = {
                "separate_vocal",
                "split_stem",
                "split_stem_advanced",
                "midi",
                "wav",
                "music_video",
                "timestamped_lyrics",
            }
            if operation not in allowed:
                await self._respond(user_id, "Операция недоступна.", callback_id=callback_id)
                return
            await save_max_session(
                user_id,
                "suno:advanced_id_pair",
                {"operation": operation},
            )
            await self._respond(
                user_id,
                "Пришлите одной строкой: <code>TaskID AudioID</code>",
                attachments=back_home_menu(),
                callback_id=callback_id,
            )
            return

        await super()._handle_callback(user_id, callback_id, payload)
