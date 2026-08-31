from __future__ import annotations

import copy
import html
import logging
from typing import Any

from bot.max_api import MaxApiError, callback_button, inline_keyboard
from bot.max_channel import (
    MaxChannelService,
    _format_cost,
    _media_urls,
    _message_body,
    _message_text,
)
from bot.max_creator_client import MaxCreatorClient
from bot.max_creator_generation import (
    MOTION_MODELS,
    enqueue_max_motion_generation,
    motion_cost,
)
from bot.max_store import (
    MaxInsufficientBalanceError,
    clear_max_session,
    get_max_balance,
    get_max_session,
    save_max_session,
)
from bot.max_ui import back_home_menu, generation_confirm_menu, main_menu, topup_menu

logger = logging.getLogger(__name__)

_MOTION_MODEL_LABELS = {
    "motion_control_v26": "Kling 2.6 Motion Control",
    "motion_control_v30": "Kling 3.0 Motion Control",
}


def _motion_model_menu() -> list[dict[str, Any]]:
    return [
        inline_keyboard(
            [
                [
                    callback_button(
                        "🎯 Kling 3.0",
                        "max:motion:model:motion_control_v30",
                    )
                ],
                [
                    callback_button(
                        "🎯 Kling 2.6",
                        "max:motion:model:motion_control_v26",
                    )
                ],
                [callback_button("🏠 Главное меню", "max:home")],
            ]
        )
    ]


def _motion_orientation_menu() -> list[dict[str, Any]]:
    return [
        inline_keyboard(
            [
                [
                    callback_button(
                        "🎬 Ориентация из видео",
                        "max:motion:orientation:video",
                    )
                ],
                [
                    callback_button(
                        "🖼 Ориентация из фото",
                        "max:motion:orientation:image",
                    )
                ],
                [callback_button("🏠 Главное меню", "max:home")],
            ]
        )
    ]


def _motion_quality_menu() -> list[dict[str, Any]]:
    return [
        inline_keyboard(
            [
                [
                    callback_button("720p", "max:motion:quality:720p"),
                    callback_button("1080p", "max:motion:quality:1080p"),
                ],
                [callback_button("🏠 Главное меню", "max:home")],
            ]
        )
    ]


def _video_token(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("token", "videoToken", "video_token"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    nested = payload.get("video")
    if isinstance(nested, dict):
        return _video_token(nested)
    return ""


def _video_duration(update: dict[str, Any]) -> int | None:
    attachments = _message_body(update).get("attachments") or []
    if not isinstance(attachments, list):
        return None
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        if str(attachment.get("type") or "").strip().lower() != "video":
            continue
        payload = attachment.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        for key in ("resolved_duration", "duration"):
            value = payload.get(key)
            if value in (None, ""):
                continue
            try:
                seconds = int(round(float(value)))
            except (TypeError, ValueError):
                continue
            if seconds > 0:
                return seconds
    return None


class MaxCreatorChannelService(MaxChannelService):
    """MAX creator flows layered over the stable base channel adapter."""

    def __init__(
        self,
        *args: Any,
        creator_client: MaxCreatorClient | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.creator_client = creator_client or MaxCreatorClient(self.client)

    async def _resolve_video_attachments(
        self,
        update: dict[str, Any],
    ) -> dict[str, Any]:
        body = _message_body(update)
        attachments = body.get("attachments") or []
        if not isinstance(attachments, list):
            return update

        resolved_update = copy.deepcopy(update)
        resolved_attachments = _message_body(resolved_update).get("attachments") or []
        for attachment in resolved_attachments:
            if not isinstance(attachment, dict):
                continue
            if str(attachment.get("type") or "").strip().lower() != "video":
                continue
            payload = attachment.get("payload")
            if not isinstance(payload, dict):
                continue
            if _media_urls(
                {"message": {"body": {"attachments": [attachment]}}}
            )[1]:
                continue
            token = _video_token(payload)
            if not token:
                continue
            resolved = await self.creator_client.resolve_video_attachment(token)
            payload["resolved_url"] = resolved.url
            if resolved.duration_seconds is not None:
                payload["resolved_duration"] = resolved.duration_seconds
        return resolved_update

    async def _select_motion_model(
        self,
        user_id: int,
        model: str,
        *,
        callback_id: str,
    ) -> None:
        if model not in MOTION_MODELS:
            await self._respond(
                user_id,
                "Эта версия Motion Control сейчас недоступна.",
                attachments=_motion_model_menu(),
                callback_id=callback_id,
            )
            return
        await save_max_session(
            user_id,
            "motion:waiting_image",
            {
                "kind": "video",
                "generation_type": "motion_control",
                "model": model,
            },
        )
        await self._respond(
            user_id,
            f"🎯 <b>{html.escape(_MOTION_MODEL_LABELS[model])}</b>\n\n"
            "Пришлите одно изображение персонажа. Можно добавить промпт подписью.",
            attachments=back_home_menu(),
            callback_id=callback_id,
        )

    async def _prepare_motion_from_message(
        self,
        user_id: int,
        update: dict[str, Any],
        *,
        state: str,
        data: dict[str, Any],
    ) -> bool:
        if state == "motion:waiting_image":
            images, _ = _media_urls(update)
            if not images:
                await self._respond(
                    user_id,
                    "Сначала пришлите изображение персонажа для Motion Control.",
                    attachments=back_home_menu(),
                )
                return True
            updated = dict(data)
            updated["image_url"] = images[0]
            prompt = _message_text(update)
            if prompt:
                updated["prompt"] = prompt
            await save_max_session(user_id, "motion:waiting_video", updated)
            await self._respond(
                user_id,
                "Фото принято 🖼\n\n"
                "Теперь пришлите видео с движением длительностью от 3 до 30 секунд.",
                attachments=back_home_menu(),
            )
            return True

        if state == "motion:waiting_video":
            try:
                resolved_update = await self._resolve_video_attachments(update)
            except MaxApiError:
                logger.exception("MAX Motion Control video token resolution failed")
                await self._respond(
                    user_id,
                    "Не удалось прочитать это видео из MAX. Пришлите ролик ещё раз "
                    "или выберите другой файл.",
                    attachments=back_home_menu(),
                )
                return True

            _, videos = _media_urls(resolved_update)
            if not videos:
                await self._respond(
                    user_id,
                    "Пришлите видео с движением как вложение MAX.",
                    attachments=back_home_menu(),
                )
                return True
            duration = _video_duration(resolved_update)
            if duration is None:
                await self._respond(
                    user_id,
                    "MAX не вернул длительность этого видео, поэтому безопасно "
                    "посчитать стоимость не получилось. Пришлите ролик ещё раз.",
                    attachments=back_home_menu(),
                )
                return True
            if not 3 <= duration <= 30:
                await self._respond(
                    user_id,
                    "Для Motion Control нужен ролик длительностью от 3 до 30 секунд.",
                    attachments=back_home_menu(),
                )
                return True

            updated = dict(data)
            updated["video_url"] = videos[0]
            updated["duration"] = duration
            prompt = _message_text(resolved_update)
            if prompt:
                updated["prompt"] = prompt
            await save_max_session(user_id, "motion:choose_orientation", updated)
            await self._respond(
                user_id,
                "Видео принято 🎬\n\n"
                "Выберите, откуда брать ориентацию персонажа.",
                attachments=_motion_orientation_menu(),
            )
            return True

        if state.startswith("motion:"):
            await self._respond(
                user_id,
                "Используйте кнопки ниже, чтобы закончить настройку Motion Control.",
                attachments=(
                    _motion_orientation_menu()
                    if state == "motion:choose_orientation"
                    else _motion_quality_menu()
                    if state == "motion:choose_quality"
                    else generation_confirm_menu()
                ),
            )
            return True
        return False

    async def _prepare_generation_from_message(
        self,
        user_id: int,
        update: dict[str, Any],
    ) -> bool:
        session = await get_max_session(user_id)
        if session.state.startswith("motion:"):
            return await self._prepare_motion_from_message(
                user_id,
                update,
                state=session.state,
                data=dict(session.data),
            )

        if session.state == "video:waiting_input":
            try:
                update = await self._resolve_video_attachments(update)
            except MaxApiError:
                logger.exception("MAX video token resolution failed")
                await self._respond(
                    user_id,
                    "Не удалось прочитать видео из MAX. Пришлите ролик ещё раз "
                    "или выберите другой файл.",
                    attachments=back_home_menu(),
                )
                return True
        return await super()._prepare_generation_from_message(user_id, update)

    async def _handle_callback(
        self,
        user_id: int,
        callback_id: str,
        payload: str,
    ) -> None:
        if payload == "max:motion_control":
            await clear_max_session(user_id)
            await self._respond(
                user_id,
                "🎯 <b>Motion Control</b>\n\n"
                "Перенесите движение из видео на персонажа с изображения. "
                "Выберите версию Kling.",
                attachments=_motion_model_menu(),
                callback_id=callback_id,
            )
            return

        if payload.startswith("max:motion:model:"):
            await self._select_motion_model(
                user_id,
                payload.split(":", 3)[3],
                callback_id=callback_id,
            )
            return

        if payload.startswith("max:motion:orientation:"):
            session = await get_max_session(user_id)
            if session.state != "motion:choose_orientation":
                await self._respond(
                    user_id,
                    "Сценарий Motion Control устарел. Начните его заново.",
                    attachments=_motion_model_menu(),
                    callback_id=callback_id,
                )
                return
            orientation = payload.split(":", 3)[3]
            if orientation not in {"video", "image"}:
                await self._respond(
                    user_id,
                    "Неизвестный режим ориентации.",
                    attachments=_motion_orientation_menu(),
                    callback_id=callback_id,
                )
                return
            data = dict(session.data)
            duration = int(data.get("duration") or 0)
            if orientation == "image" and duration > 10:
                await self._respond(
                    user_id,
                    "Ориентация из фото поддерживает ролики до 10 секунд. "
                    "Для этого видео выберите ориентацию из видео.",
                    attachments=_motion_orientation_menu(),
                    callback_id=callback_id,
                )
                return
            data["orientation"] = orientation
            await save_max_session(user_id, "motion:choose_quality", data)
            await self._respond(
                user_id,
                "Выберите качество итогового видео.",
                attachments=_motion_quality_menu(),
                callback_id=callback_id,
            )
            return

        if payload.startswith("max:motion:quality:"):
            session = await get_max_session(user_id)
            if session.state != "motion:choose_quality":
                await self._respond(
                    user_id,
                    "Сценарий Motion Control устарел. Начните его заново.",
                    attachments=_motion_model_menu(),
                    callback_id=callback_id,
                )
                return
            quality = payload.split(":", 3)[3].lower()
            data = dict(session.data)
            try:
                cost = motion_cost(
                    str(data.get("model") or ""),
                    duration=int(data.get("duration") or 0),
                    quality=quality,
                    catalog=self.catalog,
                )
            except (TypeError, ValueError):
                logger.exception("MAX Motion Control price calculation failed")
                await self._respond(
                    user_id,
                    "Не удалось рассчитать стоимость Motion Control. "
                    "Начните сценарий заново.",
                    attachments=_motion_model_menu(),
                    callback_id=callback_id,
                )
                return
            data["quality"] = quality
            data["cost"] = cost
            await save_max_session(user_id, "motion:confirm", data)
            model = str(data.get("model") or "")
            prompt = str(data.get("prompt") or "").strip()
            prompt_line = (
                f"\nПромпт: {html.escape(prompt[:500])}"
                if prompt
                else "\nПромпт: не задан — используется только движение референса."
            )
            await self._respond(
                user_id,
                "✨ <b>Motion Control готов к запуску</b>\n\n"
                f"Модель: <b>{html.escape(_MOTION_MODEL_LABELS.get(model, model))}</b>\n"
                f"Видео: <b>{int(data['duration'])} сек.</b>\n"
                f"Качество: <b>{html.escape(quality)}</b>\n"
                f"Стоимость: <b>{_format_cost(cost)} 🐾</b>"
                f"{prompt_line}",
                attachments=generation_confirm_menu(),
                callback_id=callback_id,
            )
            return

        await super()._handle_callback(user_id, callback_id, payload)

    async def _launch_generation(self, user_id: int, *, callback_id: str) -> None:
        session = await get_max_session(user_id)
        if session.state != "motion:confirm":
            await super()._launch_generation(user_id, callback_id=callback_id)
            return

        data = dict(session.data)
        try:
            job = await enqueue_max_motion_generation(
                user_id,
                model=str(data["model"]),
                image_url=str(data["image_url"]),
                video_url=str(data["video_url"]),
                duration=int(data["duration"]),
                quality=str(data["quality"]),
                orientation=str(data.get("orientation") or "video"),
                prompt=str(data.get("prompt") or ""),
                catalog=self.catalog,
            )
        except MaxInsufficientBalanceError:
            await self._respond(
                user_id,
                "🐾 Баланса не хватает. Пополните MAX-баланс — настройки "
                "Motion Control сохранены.",
                attachments=topup_menu(self.catalog),
                callback_id=callback_id,
            )
            return
        except (KeyError, TypeError, ValueError, RuntimeError):
            logger.exception("MAX Motion Control enqueue failed")
            await self._respond(
                user_id,
                "Не удалось запустить Motion Control. Настройки сохранены — "
                "можно повторить запуск.",
                attachments=generation_confirm_menu(),
                callback_id=callback_id,
            )
            return

        await clear_max_session(user_id)
        balance = await get_max_balance(user_id)
        await self._respond(
            user_id,
            "🚀 <b>Motion Control запущен</b>\n\n"
            f"Задача: <code>{html.escape(job.id[:12])}</code>\n"
            f"Списано: <b>{_format_cost(job.cost)} 🐾</b>\n"
            f"Осталось: <b>{_format_cost(balance)} 🐾</b>\n\n"
            "Результат придёт сюда автоматически.",
            attachments=main_menu(
                balance,
                mini_app_url=self.settings.mini_app_url,
            ),
            callback_id=callback_id,
        )
