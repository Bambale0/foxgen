from __future__ import annotations

import html
import logging
from typing import Any

from bot.database import (
    get_approved_prompts,
    get_popular_prompts,
    get_prompt_by_id,
    get_top_prompts,
)
from bot.max_api import callback_button, inline_keyboard, link_button
from bot.max_assistant import max_ai_assistant_service
from bot.max_channel import _format_cost, _message_text
from bot.max_seedance25 import MaxSeedance25ChannelService
from bot.max_store import clear_max_session, get_max_balance, get_max_session, save_max_session
from bot.max_ui import (
    back_home_menu,
    image_model_menu,
    main_menu,
    topup_menu,
    video_type_menu,
)

logger = logging.getLogger(__name__)

_PROMPT_MODES = {"top", "popular", "new"}
_PROMPT_LIMIT = 24


def _short(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)].rstrip()}…"


def _prompt_mode_label(mode: str) -> str:
    return {
        "top": "Лучшие",
        "popular": "Популярные",
        "new": "Новые",
    }.get(mode, "Лучшие")


async def _load_prompts(mode: str) -> list[dict]:
    if mode == "popular":
        return await get_popular_prompts(_PROMPT_LIMIT)
    if mode == "new":
        return await get_approved_prompts(limit=_PROMPT_LIMIT)
    return await get_top_prompts(_PROMPT_LIMIT)


def _assistant_menu() -> list[dict[str, Any]]:
    return [
        inline_keyboard(
            [
                [
                    callback_button("🖼 Создать фото", "max:create_image"),
                    callback_button("🎬 Создать видео", "max:create_video"),
                ],
                [
                    callback_button("✨ Промпты", "max:prompts"),
                    callback_button("❓ Что умеет бот", "max:help"),
                ],
                [callback_button("🏠 Главное меню", "max:home")],
            ]
        )
    ]


def _support_menu(support_contact: str, mini_app_url: str) -> list[dict[str, Any]]:
    rows: list[list[dict[str, Any]]] = [
        [callback_button("🤖 Спросить AI-помощника", "max:assistant")],
        [
            callback_button("🐾 Проверить баланс", "max:balance"),
            callback_button("❓ Инструкция", "max:help"),
        ],
    ]
    contact = str(support_contact or "").strip()
    if contact.startswith("https://"):
        rows.append([link_button("💬 Написать оператору", contact)])
    if mini_app_url:
        rows.append([link_button("🚀 Открыть Mini App", mini_app_url)])
    rows.append([callback_button("🏠 Главное меню", "max:home")])
    return [inline_keyboard(rows)]


def _prompt_menu(
    *,
    mode: str,
    index: int,
    total: int,
    prompt_id: int,
    mini_app_url: str,
) -> list[dict[str, Any]]:
    prev_index = (index - 1) % total
    next_index = (index + 1) % total
    rows: list[list[dict[str, Any]]] = [
        [
            callback_button("◀️", f"max:prompt:nav:{mode}:{prev_index}"),
            callback_button(f"{index + 1}/{total}", f"max:prompt:nav:{mode}:{index}"),
            callback_button("▶️", f"max:prompt:nav:{mode}:{next_index}"),
        ],
        [
            callback_button("⭐ Лучшие", "max:prompt:nav:top:0"),
            callback_button("🔥 Популярные", "max:prompt:nav:popular:0"),
            callback_button("🆕 Новые", "max:prompt:nav:new:0"),
        ],
        [callback_button("📄 Показать prompt", f"max:prompt:full:{prompt_id}")],
        [
            callback_button("🖼 Создать фото", "max:create_image"),
            callback_button("🎬 Создать видео", "max:create_video"),
        ],
    ]
    if mini_app_url:
        rows.append([link_button("🚀 Библиотека в Mini App", mini_app_url)])
    rows.append([callback_button("🏠 Главное меню", "max:home")])
    return [inline_keyboard(rows)]


class MaxProductChannelService(MaxSeedance25ChannelService):
    """Final MAX product layer: complete top-level screens without touching generation FSMs."""

    async def _home(
        self,
        user_id: int,
        *,
        callback_id: str = "",
        clear: bool = True,
    ) -> None:
        if clear:
            await clear_max_session(user_id)
        balance = await get_max_balance(user_id)
        await self._respond(
            user_id,
            "🦊 <b>HappyFox в MAX</b>\n\n"
            "Создавайте контент прямо в чате — без команд и длинных настроек.\n\n"
            "<b>Что здесь есть</b>\n"
            "🖼 Фото — генерация и редактирование по референсам\n"
            "🎬 Видео — текст → видео, фото → видео и видео → видео\n"
            "🎯 Motion Control — перенос движения из ролика на персонажа\n"
            "🎙 Озвучка — Gemini Omni Audio ID\n"
            "🎵 Suno — музыка, lyrics, cover и аудио-инструменты\n"
            "✨ Промпты — готовая библиотека прямо в MAX\n"
            "🤖 AI-помощник — выбор модели, промпта и настроек\n\n"
            f"🐾 <b>Баланс MAX:</b> {_format_cost(balance)}\n"
            "<i>Выберите нужный экран ниже.</i>",
            attachments=main_menu(balance, mini_app_url=self.settings.mini_app_url),
            callback_id=callback_id,
        )

    async def _balance(self, user_id: int, *, callback_id: str) -> None:
        balance = await get_max_balance(user_id)
        await self._respond(
            user_id,
            "🐾 <b>Баланс MAX</b>\n\n"
            f"Доступно: <b>{_format_cost(balance)} 🐾</b>\n"
            "1 🐾 используется только внутри MAX и не смешивается с балансом Telegram.\n\n"
            "Стоимость конкретной генерации всегда показывается до запуска. "
            "Ниже можно сразу выбрать пакет пополнения.",
            attachments=topup_menu(self.catalog),
            callback_id=callback_id,
        )

    async def _partners(self, user_id: int, *, callback_id: str) -> None:
        # Keep the isolated MAX referral accounting from the base implementation,
        # but prepend a practical explanation through the same screen contract.
        await super()._partners(user_id, callback_id=callback_id)

    async def _show_topup(self, user_id: int, *, callback_id: str) -> None:
        if not self.payments.enabled:
            await self._respond(
                user_id,
                "💳 <b>Тарифы MAX</b>\n\n"
                "Пакеты уже настроены, но платёжный шлюз MAX сейчас недоступен. "
                "Баланс и генерации продолжат работать с текущим остатком.",
                attachments=back_home_menu(),
                callback_id=callback_id,
            )
            return
        await self._respond(
            user_id,
            "💳 <b>Тарифы MAX</b>\n\n"
            "Выберите пакет 🐾. Счёт создаётся только после выбора пакета, "
            "а начисление идёт в отдельный MAX-баланс после подтверждения оплаты.\n\n"
            "<i>Перед оплатой вы увидите сумму и количество 🐾.</i>",
            attachments=topup_menu(self.catalog),
            callback_id=callback_id,
        )

    async def _show_assistant(self, user_id: int, *, callback_id: str) -> None:
        await clear_max_session(user_id)
        await save_max_session(user_id, "assistant:waiting_message", {})
        balance = await get_max_balance(user_id)
        await self._respond(
            user_id,
            "🤖 <b>AI-помощник HappyFox</b>\n\n"
            "Пишите обычным сообщением — я помогу выбрать модель, улучшить prompt "
            "и подобрать настройки под задачу.\n\n"
            "<b>Можно спросить, например:</b>\n"
            "• что лучше для реалистичного product-фото\n"
            "• какую модель взять для видео из одной фотографии\n"
            "• перепиши мой prompt под fashion-рекламу\n"
            "• какой формат выбрать для Reels / Shorts\n"
            "• сколько 🐾 стоит нужная модель в MAX\n\n"
            f"🐾 Сейчас на балансе: <b>{_format_cost(balance)}</b>\n"
            "<i>Отправьте вопрос следующим сообщением.</i>",
            attachments=_assistant_menu(),
            callback_id=callback_id,
        )

    async def _answer_assistant_message(self, user_id: int, update: dict[str, Any]) -> bool:
        text = _message_text(update).strip()
        if not text:
            await self._respond(
                user_id,
                "Напишите вопрос текстом. Например: «какую модель выбрать для видео из фото?»",
                attachments=_assistant_menu(),
            )
            return True

        balance = await get_max_balance(user_id)
        available_models = ", ".join(
            [*self.catalog.image_models().keys(), *self.catalog.video_models().keys()]
        )
        context = {
            "user_credits": balance,
            "menu_location": "AI-помощник",
            "available_models": available_models,
        }
        try:
            answer = await max_ai_assistant_service.get_assistant_response(
                user_message=text,
                context=context,
            )
        except Exception:
            logger.exception("MAX AI assistant request failed")
            answer = None

        if answer:
            rendered = html.escape(str(answer).strip())
            await self._respond(
                user_id,
                f"🤖 <b>HappyFox AI</b>\n\n{rendered}",
                attachments=_assistant_menu(),
            )
        else:
            await self._respond(
                user_id,
                "😕 AI-помощник сейчас не ответил. Можно повторить вопрос или открыть поддержку — "
                "остальные MAX-сценарии продолжают работать.",
                attachments=_support_menu(self.support_contact, self.settings.mini_app_url),
            )
        return True

    async def _show_help(self, user_id: int, *, callback_id: str) -> None:
        await clear_max_session(user_id)
        await self._respond(
            user_id,
            "❓ <b>Как пользоваться HappyFox в MAX</b>\n\n"
            "<b>Фото</b> — выберите модель → пришлите prompt и, если нужно, референс → подтвердите запуск.\n\n"
            "<b>Видео</b> — сначала выберите сценарий (текст / фото / видео), затем модель и отправьте нужные материалы.\n\n"
            "<b>Motion Control</b> — фото персонажа → видео движения → ориентация → качество → запуск.\n\n"
            "<b>Озвучка</b> — создайте Gemini Omni Audio ID и используйте его в поддерживаемых сценариях.\n\n"
            "<b>Suno</b> — создавайте треки, тексты, cover, sounds и обрабатывайте готовое аудио.\n\n"
            "<b>Промпты</b> — листайте готовые примеры прямо в MAX; полный prompt открывается отдельной кнопкой.\n\n"
            "<b>AI-помощник</b> — спросите, какую модель и настройки выбрать.\n\n"
            "Стоимость всегда показывается до запуска, а результат приходит в этот же чат.",
            attachments=_assistant_menu(),
            callback_id=callback_id,
        )

    async def _show_support(self, user_id: int, *, callback_id: str) -> None:
        await clear_max_session(user_id)
        contact = self.support_contact.strip()
        if contact:
            operator_line = f"\n\n<b>Оператор:</b> {html.escape(contact)}"
        else:
            operator_line = (
                "\n\nКонтакт оператора не задан в конфигурации. "
                "До его настройки используйте AI-помощника и встроенные экраны диагностики."
            )
        await self._respond(
            user_id,
            "💬 <b>Поддержка HappyFox</b>\n\n"
            "Если не получается генерация, оплата или выбор модели, сначала напишите AI-помощнику — "
            "он видит актуальные модели, отдельный MAX-баланс и MAX-прайс.\n\n"
            "Для обращения человеку удобно сразу прислать: что нажали, модель, примерное время ошибки "
            "и Task ID, если он появился."
            f"{operator_line}",
            attachments=_support_menu(contact, self.settings.mini_app_url),
            callback_id=callback_id,
        )

    async def _show_prompts(
        self,
        user_id: int,
        *,
        mode: str = "top",
        index: int = 0,
        callback_id: str = "",
    ) -> None:
        await clear_max_session(user_id)
        mode = mode if mode in _PROMPT_MODES else "top"
        try:
            prompts = await _load_prompts(mode)
        except Exception:
            logger.exception("MAX prompt library load failed: mode=%s", mode)
            prompts = []

        if not prompts:
            rows: list[list[dict[str, Any]]] = []
            if self.settings.mini_app_url:
                rows.append([link_button("🚀 Открыть Mini App", self.settings.mini_app_url)])
            rows.append([callback_button("🏠 Главное меню", "max:home")])
            await self._respond(
                user_id,
                "✨ <b>Промпты</b>\n\n"
                "Сейчас в публичной библиотеке нет доступных карточек. "
                "Можно попросить AI-помощника собрать prompt под задачу.",
                attachments=[inline_keyboard(rows)],
                callback_id=callback_id,
            )
            return

        total = len(prompts)
        index = max(0, min(int(index), total - 1))
        prompt = prompts[index]
        prompt_id = int(prompt.get("id") or 0)
        title = html.escape(str(prompt.get("title") or "Промпт"))
        description = html.escape(_short(prompt.get("description"), 260))
        model = html.escape(str(prompt.get("model") or "любой"))
        category = html.escape(str(prompt.get("category") or "другое"))
        tags = [
            html.escape(str(tag))
            for tag in (prompt.get("tags") or [])
            if str(tag).strip()
        ][:5]
        tags_line = f"\nТеги: <code>{', '.join(tags)}</code>" if tags else ""
        preview = html.escape(_short(prompt.get("prompt_text"), 800))
        await self._respond(
            user_id,
            f"✨ <b>Промпты · {_prompt_mode_label(mode)}</b> "
            f"<code>{index + 1}/{total}</code>\n\n"
            f"<b>{title}</b>\n"
            f"{description}\n\n"
            f"Категория: <code>{category}</code> · Модель: <code>{model}</code>"
            f"{tags_line}\n"
            f"❤️ {int(prompt.get('likes') or 0)} · Использований: {int(prompt.get('uses_count') or 0)}\n\n"
            f"<pre>{preview}</pre>",
            attachments=_prompt_menu(
                mode=mode,
                index=index,
                total=total,
                prompt_id=prompt_id,
                mini_app_url=self.settings.mini_app_url,
            ),
            callback_id=callback_id,
        )

    async def _show_full_prompt(self, user_id: int, prompt_id: int, *, callback_id: str) -> None:
        try:
            prompt = await get_prompt_by_id(prompt_id, approved_public_only=True)
        except Exception:
            logger.exception("MAX prompt detail load failed: id=%s", prompt_id)
            prompt = None
        if not prompt:
            await self._respond(
                user_id,
                "Промпт не найден или больше не опубликован.",
                attachments=back_home_menu(),
                callback_id=callback_id,
            )
            return

        raw_prompt = str(prompt.get("prompt_text") or "").strip()
        title = html.escape(str(prompt.get("title") or "Промпт"))
        if not raw_prompt:
            rendered = "У этой карточки пока нет текста prompt."
        else:
            visible = raw_prompt[:3000]
            suffix = "\n\n<i>Текст сокращён до лимита сообщения MAX.</i>" if len(raw_prompt) > len(visible) else ""
            rendered = f"<pre>{html.escape(visible)}</pre>{suffix}"
        await self._respond(
            user_id,
            f"📄 <b>{title}</b>\n\n{rendered}",
            attachments=[
                inline_keyboard(
                    [
                        [
                            callback_button("🖼 Создать фото", "max:create_image"),
                            callback_button("🎬 Создать видео", "max:create_video"),
                        ],
                        [callback_button("✨ К промптам", "max:prompts")],
                        [callback_button("🏠 Главное меню", "max:home")],
                    ]
                )
            ],
            callback_id=callback_id,
        )

    async def _prepare_generation_from_message(
        self,
        user_id: int,
        update: dict[str, Any],
    ) -> bool:
        session = await get_max_session(user_id)
        if session.state == "assistant:waiting_message":
            return await self._answer_assistant_message(user_id, update)
        return await super()._prepare_generation_from_message(user_id, update)

    async def _handle_callback(
        self,
        user_id: int,
        callback_id: str,
        payload: str,
    ) -> None:
        if payload == "max:assistant":
            await self._show_assistant(user_id, callback_id=callback_id)
            return
        if payload == "max:prompts":
            await self._show_prompts(user_id, callback_id=callback_id)
            return
        if payload.startswith("max:prompt:nav:"):
            parts = payload.split(":", 4)
            if len(parts) == 5:
                try:
                    index = int(parts[4])
                except ValueError:
                    index = 0
                await self._show_prompts(
                    user_id,
                    mode=parts[3],
                    index=index,
                    callback_id=callback_id,
                )
                return
        if payload.startswith("max:prompt:full:"):
            try:
                prompt_id = int(payload.rsplit(":", 1)[1])
            except ValueError:
                prompt_id = 0
            await self._show_full_prompt(user_id, prompt_id, callback_id=callback_id)
            return
        if payload == "max:support":
            await self._show_support(user_id, callback_id=callback_id)
            return
        if payload == "max:help":
            await self._show_help(user_id, callback_id=callback_id)
            return
        if payload == "max:create_image":
            await clear_max_session(user_id)
            await self._respond(
                user_id,
                "🖼 <b>Создать фото</b>\n\n"
                "Выберите модель. Цена указана прямо на кнопке. После выбора пришлите prompt; "
                "референс можно приложить в том же сообщении, а для edit-моделей он обязателен.",
                attachments=image_model_menu(self.catalog),
                callback_id=callback_id,
            )
            return
        if payload == "max:create_video":
            await clear_max_session(user_id)
            await self._respond(
                user_id,
                "🎬 <b>Создать видео</b>\n\n"
                "Сначала выберите исходник: только текст, фото или готовое видео. "
                "Дальше покажу только совместимые модели и их стоимость.",
                attachments=video_type_menu(),
                callback_id=callback_id,
            )
            return
        if payload == "max:gemini_omni":
            await clear_max_session(user_id)
            await self._respond(
                user_id,
                "🔷 <b>Gemini Omni</b>\n\n"
                "Мультимодальный раздел HappyFox: видео, озвучка и работа с голосовыми профилями.\n\n"
                "• для видео выберите обычный экран «Создать видео» и Gemini Omni\n"
                "• для Audio ID откройте «Создать озвучку»",
                attachments=[
                    inline_keyboard(
                        [
                            [
                                callback_button("🎬 Gemini Omni Video", "max:video:text:gemini_omni"),
                                callback_button("🎙 Audio ID", "max:omni_audio"),
                            ],
                            [callback_button("🏠 Главное меню", "max:home")],
                        ]
                    )
                ],
                callback_id=callback_id,
            )
            return
        await super()._handle_callback(user_id, callback_id, payload)
