from __future__ import annotations

import html
import logging
from typing import Any

from bot.database import get_feed_generations
from bot.max_api import MaxApiError, callback_button, inline_keyboard, open_app_button
from bot.max_channel import _format_cost, _media_urls, _message_text
from bot.max_product_channel import MaxProductChannelService
from bot.max_store import (
    MaxInsufficientBalanceError,
    apply_max_balance_delta,
    clear_max_session,
    get_max_balance,
    get_max_session,
    max_event_key,
    save_max_session,
)
from bot.max_ui import (
    back_home_menu,
    main_menu,
    more_menu,
    topup_menu,
    video_model_selection_menu,
    video_type_menu,
)
from bot.services.photo_prompt_service import photo_prompt_service
from bot.services.video_prompt_service import video_prompt_service

logger = logging.getLogger(__name__)


def _service_price(catalog, key: str, *, default: float = 0) -> float:
    raw = catalog.get_price_config().get("service_prices", {}) or {}
    try:
        return float(raw.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _photo_prompt_cost(catalog) -> float:
    config = catalog.get_price_config()
    service = config.get("service_prices", {}) or {}
    try:
        rub = float(service.get("photo_prompt_rub", 1))
        rub_per_credit = float(config.get("credit_rub_value", 10))
    except (TypeError, ValueError):
        return 0.1
    if rub_per_credit <= 0:
        return 0.1
    return rub / rub_per_credit


def _balance_menu(balance: float) -> list[dict[str, Any]]:
    return [
        inline_keyboard(
            [
                [callback_button(f"У тебя: {_format_cost(balance)} 🍌", "max:home")],
                [
                    callback_button("💰 Пополнить", "max:topup"),
                    callback_button("📋 История", "max:history"),
                ],
            ]
        )
    ]


def _prompt_result_menu(kind: str, price: float = 0) -> list[dict[str, Any]]:
    if kind == "video":
        label = f"🆕 Новый видео-промпт • {_format_cost(price)}🍌"
        payload = "max:video_prompt"
    else:
        label = "🆕 Новый промпт"
        payload = "max:photo_prompt"
    return [
        inline_keyboard(
            [
                [callback_button(label, payload)],
                [callback_button("🏠 Главное меню", "max:home")],
            ]
        )
    ]


def _format_photo_prompt_result(result: dict[str, Any]) -> str:
    prompt_ru = html.escape(str(result.get("prompt_ru") or "—").strip())
    prompt_en = html.escape(str(result.get("prompt_en") or "—").strip())
    negative = html.escape(str(result.get("negative_prompt") or "—").strip())
    return (
        "✅ <b>Промпт по фото готов</b>\n\n"
        "<b>Prompt RU:</b>\n"
        f"<pre>{prompt_ru[:1500]}</pre>\n\n"
        "<b>Prompt EN:</b>\n"
        f"<pre>{prompt_en[:1000]}</pre>\n\n"
        "<b>Negative prompt:</b>\n"
        f"<pre>{negative[:450]}</pre>"
    )


def _format_video_prompt_result(result: dict[str, Any]) -> str:
    prompt_ru = html.escape(str(result.get("prompt_ru") or "—").strip())
    prompt_en = html.escape(str(result.get("prompt_en") or "—").strip())
    camera = html.escape(str(result.get("camera_movement_ru") or "—").strip())
    style = html.escape(str(result.get("visual_style_ru") or "—").strip())
    negative = html.escape(str(result.get("negative_prompt") or "—").strip())
    return (
        "✅ <b>Промпт по видео готов</b>\n\n"
        "<b>Prompt RU:</b>\n"
        f"<pre>{prompt_ru[:1200]}</pre>\n\n"
        "<b>Prompt EN:</b>\n"
        f"<pre>{prompt_en[:850]}</pre>\n\n"
        "<b>Камера:</b>\n"
        f"{camera[:250]}\n\n"
        "<b>Стиль:</b>\n"
        f"{style[:250]}\n\n"
        "<b>Negative prompt:</b>\n"
        f"<pre>{negative[:350]}</pre>"
    )


def _feed_media_url(card: dict[str, Any]) -> str:
    direct = str(card.get("result_url") or "").strip()
    if direct.startswith("https://"):
        return direct
    urls = card.get("result_urls") or []
    if isinstance(urls, list):
        for value in urls:
            candidate = str(value or "").strip()
            if candidate.startswith("https://"):
                return candidate
    return ""


def _feed_menu(
    index: int,
    total: int,
    *,
    mini_app_url: str = "",
    mini_app_bot_name: str = "",
) -> list[dict[str, Any]]:
    rows: list[list[dict[str, Any]]] = []
    if total > 1:
        rows.append(
            [
                callback_button("◀️", f"max:feed:{(index - 1) % total}"),
                callback_button(f"{index + 1}/{total}", f"max:feed:{index}"),
                callback_button("▶️", f"max:feed:{(index + 1) % total}"),
            ]
        )
    if mini_app_url:
        rows.append([open_app_button("🚀 Открыть в Mini App", web_app=mini_app_bot_name)])
    rows.append([callback_button("🏠 Главное меню", "max:home")])
    return [inline_keyboard(rows)]


class MaxTelegramParityChannelService(MaxProductChannelService):
    """Telegram UX contract adapted to MAX transport and isolated MAX state."""

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
            "🦊 <b>HappyFox</b>\n\n"
            "Создавайте фото, видео и промпты — все основные сценарии доступны кнопками ниже.",
            attachments=main_menu(
                balance,
                mini_app_url=self.settings.mini_app_url,
                mini_app_bot_name=self.bot_name,
                catalog=self.catalog,
            ),
            callback_id=callback_id,
        )

    async def _balance(self, user_id: int, *, callback_id: str) -> None:
        balance = await get_max_balance(user_id)
        await self._respond(
            user_id,
            "🍌 <b>Баланс</b>\n\n"
            f"У тебя: <b>{_format_cost(balance)} 🍌</b>",
            attachments=_balance_menu(balance),
            callback_id=callback_id,
        )

    async def _open_video_model_selection(
        self,
        user_id: int,
        *,
        callback_id: str = "",
    ) -> None:
        await clear_max_session(user_id)
        await self._respond(
            user_id,
            "🎬 <b>Создать видео</b>\n\nВыберите модель.",
            attachments=video_model_selection_menu(self.catalog),
            callback_id=callback_id,
        )

    async def _select_video_first(
        self,
        user_id: int,
        model: str,
        *,
        callback_id: str,
    ) -> None:
        if model not in self.catalog.video_models():
            await self._respond(
                user_id,
                "Эта видео-модель сейчас недоступна.",
                attachments=video_model_selection_menu(self.catalog),
                callback_id=callback_id,
            )
            return
        await save_max_session(
            user_id,
            "video:select_type",
            {"kind": "video", "model": model},
        )
        await self._respond(
            user_id,
            f"🎬 <b>{html.escape(model)}</b>\n\nВыберите исходник для видео.",
            attachments=video_type_menu(model=model, catalog=self.catalog),
            callback_id=callback_id,
        )

    async def _select_video_type_after_model(
        self,
        user_id: int,
        generation_type: str,
        *,
        callback_id: str,
    ) -> bool:
        session = await get_max_session(user_id)
        if session.state != "video:select_type":
            return False
        model = str(session.data.get("model") or "")
        await self._select_video_model(
            user_id,
            generation_type,
            model,
            callback_id=callback_id,
        )
        return True

    async def _open_photo_prompt(self, user_id: int, *, callback_id: str) -> None:
        await clear_max_session(user_id)
        await save_max_session(user_id, "prompt:photo:waiting_media", {})
        await self._respond(
            user_id,
            "✍️ <b>Промпт по описанию</b>\n\n"
            "Пришлите фотографию. Я разберу композицию, свет, стиль и детали "
            "и соберу готовый prompt на русском и английском.",
            attachments=back_home_menu(),
            callback_id=callback_id,
        )

    async def _open_video_prompt(self, user_id: int, *, callback_id: str) -> None:
        await clear_max_session(user_id)
        price = _service_price(self.catalog, "video_prompt", default=3)
        await save_max_session(user_id, "prompt:video:waiting_media", {})
        await self._respond(
            user_id,
            "🎞 <b>Промпт по видео</b>\n\n"
            f"Стоимость анализа: <b>{_format_cost(price)}🍌</b>.\n"
            "Пришлите видео — я разберу движение камеры, темп, композицию, свет и стиль.",
            attachments=back_home_menu(),
            callback_id=callback_id,
        )

    async def _analyze_photo_prompt(
        self,
        user_id: int,
        update: dict[str, Any],
    ) -> bool:
        images, _ = _media_urls(update)
        if not images:
            await self._respond(
                user_id,
                "Пришлите фотографию как вложение MAX.",
                attachments=back_home_menu(),
            )
            return True

        cost = _photo_prompt_cost(self.catalog)
        key = max_event_key(update)
        debit_key = f"max:photo-prompt:{key}"
        try:
            await apply_max_balance_delta(
                user_id,
                -cost,
                tx_type="photo_prompt",
                idempotency_key=debit_key,
                metadata={"channel": "max"},
            )
        except MaxInsufficientBalanceError:
            await self._respond(
                user_id,
                "🍌 Баланса не хватает для анализа фотографии.",
                attachments=topup_menu(self.catalog),
            )
            return True

        try:
            result = await photo_prompt_service.analyze_photo(
                image_url=images[0],
                user_note=_message_text(update),
            )
        except Exception:
            logger.exception("MAX photo prompt analysis failed")
            await apply_max_balance_delta(
                user_id,
                cost,
                tx_type="photo_prompt_refund",
                idempotency_key=f"{debit_key}:refund",
                metadata={"channel": "max", "reason": "analysis_failed"},
            )
            await self._respond(
                user_id,
                "Не удалось разобрать фотографию. Списание возвращено, можно попробовать ещё раз.",
                attachments=_prompt_result_menu("photo"),
            )
            return True

        await clear_max_session(user_id)
        await self._respond(
            user_id,
            _format_photo_prompt_result(result),
            attachments=_prompt_result_menu("photo"),
        )
        return True

    async def _analyze_video_prompt(
        self,
        user_id: int,
        update: dict[str, Any],
    ) -> bool:
        try:
            resolver = getattr(self, "_resolve_video_attachments", None)
            if callable(resolver):
                update = await resolver(update)
        except MaxApiError:
            logger.exception("MAX video prompt token resolution failed")
            await self._respond(
                user_id,
                "Не удалось прочитать это видео из MAX. Пришлите файл ещё раз.",
                attachments=back_home_menu(),
            )
            return True

        _, videos = _media_urls(update)
        if not videos:
            await self._respond(
                user_id,
                "Пришлите видео как вложение MAX.",
                attachments=back_home_menu(),
            )
            return True

        cost = _service_price(self.catalog, "video_prompt", default=3)
        key = max_event_key(update)
        debit_key = f"max:video-prompt:{key}"
        try:
            await apply_max_balance_delta(
                user_id,
                -cost,
                tx_type="video_prompt",
                idempotency_key=debit_key,
                metadata={"channel": "max"},
            )
        except MaxInsufficientBalanceError:
            await self._respond(
                user_id,
                "🍌 Баланса не хватает для анализа видео.",
                attachments=topup_menu(self.catalog),
            )
            return True

        try:
            result = await video_prompt_service.analyze_video(
                video_url=videos[0],
                user_note=_message_text(update),
            )
        except Exception:
            logger.exception("MAX video prompt analysis failed")
            await apply_max_balance_delta(
                user_id,
                cost,
                tx_type="video_prompt_refund",
                idempotency_key=f"{debit_key}:refund",
                metadata={"channel": "max", "reason": "analysis_failed"},
            )
            await self._respond(
                user_id,
                "Не удалось разобрать видео. Списание возвращено, можно попробовать ещё раз.",
                attachments=_prompt_result_menu("video", cost),
            )
            return True

        await clear_max_session(user_id)
        await self._respond(
            user_id,
            _format_video_prompt_result(result),
            attachments=_prompt_result_menu("video", cost),
        )
        return True

    async def _show_feed(
        self,
        user_id: int,
        *,
        index: int = 0,
        callback_id: str = "",
    ) -> None:
        await clear_max_session(user_id)
        try:
            cards = await get_feed_generations(
                limit=24,
                source="r",
                viewer_user_id=None,
            )
        except Exception:
            logger.exception("MAX feed load failed")
            cards = []

        if not cards:
            await self._respond(
                user_id,
                "🖼 <b>Лента</b>\n\nПока нет опубликованных работ.",
                attachments=back_home_menu(),
                callback_id=callback_id,
            )
            return

        total = len(cards)
        index = int(index) % total
        card = cards[index]
        model = html.escape(str(card.get("model") or ""))
        prompt = html.escape(str(card.get("prompt") or "").strip())
        caption = (
            f"🖼 <b>Лента</b> <code>{index + 1}/{total}</code>\n\n"
            f"Модель: <b>{model or '—'}</b>\n"
            f"❤️ {int(card.get('likes') or 0)}"
        )
        if prompt:
            caption += f"\n\n{prompt[:900]}"
        media_url = _feed_media_url(card)
        if media_url:
            caption += f"\n\n<a href=\"{html.escape(media_url)}\">Открыть результат</a>"
        await self._respond(
            user_id,
            caption,
            attachments=_feed_menu(
                index,
                total,
                mini_app_url=self.settings.mini_app_url,
                mini_app_bot_name=self.bot_name,
            ),
            callback_id=callback_id,
        )

    async def _prepare_generation_from_message(
        self,
        user_id: int,
        update: dict[str, Any],
    ) -> bool:
        session = await get_max_session(user_id)
        if session.state == "prompt:photo:waiting_media":
            return await self._analyze_photo_prompt(user_id, update)
        if session.state == "prompt:video:waiting_media":
            return await self._analyze_video_prompt(user_id, update)
        if session.state == "video:select_type":
            await self._respond(
                user_id,
                "Выберите тип исходника кнопками ниже.",
                attachments=video_type_menu(
                    model=str(session.data.get("model") or ""),
                    catalog=self.catalog,
                ),
            )
            return True
        return await super()._prepare_generation_from_message(user_id, update)

    async def _handle_callback(
        self,
        user_id: int,
        callback_id: str,
        payload: str,
    ) -> None:
        if payload == "max:create_video":
            await self._open_video_model_selection(user_id, callback_id=callback_id)
            return
        if payload.startswith("max:video_model:"):
            await self._select_video_first(
                user_id,
                payload.split(":", 2)[2],
                callback_id=callback_id,
            )
            return
        if payload.startswith("max:vtype:"):
            generation_type = payload.split(":", 2)[2]
            if await self._select_video_type_after_model(
                user_id,
                generation_type,
                callback_id=callback_id,
            ):
                return
        if payload == "max:photo_prompt":
            await self._open_photo_prompt(user_id, callback_id=callback_id)
            return
        if payload == "max:video_prompt":
            await self._open_video_prompt(user_id, callback_id=callback_id)
            return
        if payload == "max:feed":
            await self._show_feed(user_id, callback_id=callback_id)
            return
        if payload.startswith("max:feed:"):
            try:
                index = int(payload.rsplit(":", 1)[1])
            except ValueError:
                index = 0
            await self._show_feed(user_id, index=index, callback_id=callback_id)
            return
        if payload == "max:more":
            await clear_max_session(user_id)
            await self._respond(
                user_id,
                "⋯ <b>Ещё</b>",
                attachments=more_menu(),
                callback_id=callback_id,
            )
            return
        await super()._handle_callback(user_id, callback_id, payload)
