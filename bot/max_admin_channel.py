from __future__ import annotations

import html
from typing import Any

from bot.database import get_admin_stats
from bot.max_admin_store import claim_max_admin_invite, is_max_admin, list_max_admins
from bot.max_api import callback_button, inline_keyboard
from bot.max_channel import _format_cost, _message_text, _user_id, _user_names
from bot.max_product_channel import MaxProductChannelService
from bot.max_store import clear_max_session, ensure_max_user, get_max_balance
from bot.max_ui import main_menu


def _admin_main_menu(balance: float, *, mini_app_url: str) -> list[dict[str, Any]]:
    attachments = main_menu(balance, mini_app_url=mini_app_url)
    rows = attachments[0]["payload"]["buttons"]
    rows.append([callback_button("🔧 Админ-панель", "max:admin")])
    return attachments


def _admin_panel_menu() -> list[dict[str, Any]]:
    return [
        inline_keyboard(
            [
                [callback_button("🔄 Обновить", "max:admin")],
                [callback_button("🏠 Главное меню", "max:home")],
            ]
        )
    ]


class MaxAdminChannelService(MaxProductChannelService):
    """MAX product channel with explicit database-backed administrator roles."""

    async def _home(
        self,
        user_id: int,
        *,
        callback_id: str = "",
        clear: bool = True,
    ) -> None:
        if not await is_max_admin(user_id):
            await super()._home(user_id, callback_id=callback_id, clear=clear)
            return

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
            "🔧 <b>Роль:</b> администратор\n"
            "<i>Выберите нужный экран ниже.</i>",
            attachments=_admin_main_menu(
                balance,
                mini_app_url=self.settings.mini_app_url,
            ),
            callback_id=callback_id,
        )

    async def _show_admin(self, user_id: int, *, callback_id: str = "") -> None:
        if not await is_max_admin(user_id):
            await self._respond(
                user_id,
                "⛔ У этого MAX-аккаунта нет доступа к админ-панели.",
                callback_id=callback_id,
            )
            return

        stats = await get_admin_stats()
        admins = await list_max_admins()
        names = ", ".join(
            html.escape(str(item.get("display_name") or item.get("first_name") or item["max_user_id"]))
            for item in admins
        ) or "—"
        await self._respond(
            user_id,
            "🔧 <b>Админ-панель MAX</b>\n\n"
            f"👥 Пользователей HappyFox: <b>{int(stats.get('total_users') or 0)}</b>\n"
            f"🎨 Генераций: <b>{int(stats.get('total_generations') or 0)}</b>\n"
            f"💳 Транзакций: <b>{int(stats.get('total_transactions') or 0)}</b>\n"
            f"💰 Выручка: <b>{float(stats.get('total_revenue') or 0):.0f} ₽</b>\n\n"
            f"🔐 Админы MAX: <b>{len(admins)}</b>\n"
            f"{names}\n\n"
            "Права берутся из отдельной таблицы MAX по стабильному MAX user_id — "
            "имя профиля само по себе доступ не даёт.",
            attachments=_admin_panel_menu(),
            callback_id=callback_id,
        )

    async def _handle_callback(
        self,
        user_id: int,
        callback_id: str,
        payload: str,
    ) -> None:
        if payload == "max:admin":
            await self._show_admin(user_id, callback_id=callback_id)
            return
        await super()._handle_callback(user_id, callback_id, payload)

    async def handle_update(self, update: dict[str, Any]) -> None:
        user_id = _user_id(update)
        update_type = str(update.get("update_type") or "")

        if user_id > 0 and update_type == "bot_started":
            payload = str(update.get("payload") or "").strip()
            if payload.startswith("admin_"):
                username, first_name, last_name = _user_names(update)
                await ensure_max_user(
                    user_id,
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                )
                claimed = await claim_max_admin_invite(user_id, payload.removeprefix("admin_"))
                await self._home(user_id)
                if claimed:
                    await self.client.send_message(
                        user_id,
                        "🔐 <b>Права администратора MAX активированы.</b>\n\n"
                        "Кнопка «Админ-панель» теперь доступна в главном меню.",
                    )
                else:
                    await self.client.send_message(
                        user_id,
                        "⛔ Ссылка администратора недействительна или уже использована другим MAX-аккаунтом.",
                    )
                return

        if user_id > 0 and update_type == "message_created":
            text = _message_text(update).strip().lower()
            if text in {"/admin", "админ", "админка"}:
                username, first_name, last_name = _user_names(update)
                await ensure_max_user(
                    user_id,
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                )
                await self._show_admin(user_id)
                return

        await super().handle_update(update)
