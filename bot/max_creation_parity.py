from __future__ import annotations

import html
import logging
from typing import Any

from bot.max_api import MaxApiError, callback_button, inline_keyboard
from bot.max_channel import _format_cost, _media_urls, _message_text
from bot.max_generation import enqueue_max_generation
from bot.max_parity_channel import MaxTelegramParityChannelService
from bot.max_store import (
    MaxInsufficientBalanceError,
    clear_max_session,
    get_max_balance,
    get_max_session,
    save_max_session,
)
from bot.max_ui import (
    IMAGE_LABELS,
    VIDEO_LABELS,
    back_home_menu,
    generation_confirm_menu,
    image_model_menu,
    topup_menu,
    video_model_selection_menu,
    video_type_menu,
)

logger = logging.getLogger(__name__)

_IMAGE_REFERENCE_REQUIRED = frozenset({"seedream_edit", "grok_imagine_i2i"})
_IMAGE_COUNTS = (1, 2, 4, 6)
_IMAGE_RATIOS_DEFAULT = (
    "1:1",
    "16:9",
    "9:16",
    "4:3",
    "3:4",
    "4:5",
    "5:4",
    "3:2",
    "2:3",
    "21:9",
)
_IMAGE_RATIOS = {
    "flux_pro": ("auto", "1:1", "9:16", "16:9", "4:3", "3:4", "2:3"),
    "seedream_edit": ("1:1", "4:3", "3:4", "16:9", "9:16", "2:3", "3:2", "21:9"),
    "seedream_5_pro": ("1:1", "4:3", "3:4", "16:9", "9:16", "2:3", "3:2", "21:9"),
}
_VIDEO_RATIOS = {
    "v3_std": ("16:9", "9:16", "1:1"),
    "v3_pro": ("16:9", "9:16", "1:1"),
    "v26_pro": ("16:9", "9:16", "1:1"),
    "grok_imagine": ("16:9", "9:16", "1:1", "3:2", "2:3"),
    "grok_imagine_v15": ("auto", "16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3"),
    "seedance_2": ("16:9", "9:16", "1:1"),
    "glow": ("16:9", "9:16", "1:1"),
    "veo3": ("16:9", "9:16", "Auto"),
    "veo3_fast": ("16:9", "9:16", "Auto"),
    "veo3_lite": ("16:9", "9:16", "Auto"),
    "gemini_omni": ("16:9", "9:16"),
}
_DEFAULT_VIDEO_DURATION = {
    "grok_imagine": 6,
    "grok_imagine_v15": 8,
    "gemini_omni": 6,
    "veo3": 6,
    "veo3_fast": 6,
    "veo3_lite": 6,
}


def _chunked(buttons: list[dict[str, Any]], width: int) -> list[list[dict[str, Any]]]:
    return [buttons[index : index + width] for index in range(0, len(buttons), width)]


def _ratio_payload(prefix: str, ratio: str) -> str:
    return f"{prefix}:{ratio.replace(':', 'x')}"


def _decode_ratio(value: str) -> str:
    if value in {"auto", "Auto"}:
        return value
    return value.replace("x", ":")


def _image_default_quality(model: str) -> str:
    if model in {"seedream_edit", "seedream_5_pro"}:
        return "high"
    return "2K"


def _image_refs_from_session(state: str, data: dict[str, Any]) -> list[str]:
    if not str(state or "").startswith("parity:image:"):
        return []

    raw_refs: Any
    if state == "parity:image:confirm":
        input_data = data.get("input_data") or {}
        raw_refs = input_data.get("image_urls") if isinstance(input_data, dict) else []
    else:
        raw_refs = data.get("image_urls")

    refs: list[str] = []
    if isinstance(raw_refs, list):
        for value in raw_refs:
            url = str(value or "").strip()
            if url.startswith("https://") and url not in refs:
                refs.append(url)
            if len(refs) >= 9:
                break
    return refs


def _image_reference_menu(count: int, *, max_count: int = 9) -> list[dict[str, Any]]:
    return [
        inline_keyboard(
            [
                [callback_button(f"Загружено: {count}/{max_count}", "max:image:refs:noop")],
                [
                    callback_button("⏭ Пропустить", "max:image:refs:skip"),
                    callback_button("✅ Продолжить", "max:image:refs:continue"),
                ],
                [callback_button("📚 Мои сохранённые рефы", "max:image:saved_refs")],
                [callback_button("🔄 Перезагрузить", "max:image:refs:reload")],
                [callback_button("🔙 Назад", "max:create_image")],
                [callback_button("🏠 Главное меню", "max:home")],
            ]
        )
    ]


def _image_settings_menu(data: dict[str, Any]) -> list[dict[str, Any]]:
    model = str(data.get("model") or "banana_pro")
    ratio = str(data.get("aspect_ratio") or "1:1")
    count = int(data.get("count") or 1)
    quality = str(data.get("quality") or _image_default_quality(model))
    refs = list(data.get("image_urls") or [])

    rows: list[list[dict[str, Any]]] = [
        [callback_button("🤖 Сменить модель", "max:create_image")]
    ]
    ratios = _IMAGE_RATIOS.get(model, _IMAGE_RATIOS_DEFAULT)
    ratio_buttons = [
        callback_button(
            f"{'◉' if value == ratio else '○'} {value.replace(':', '∶')}",
            _ratio_payload("max:image:ratio", value),
        )
        for value in ratios
    ]
    rows.extend(_chunked(ratio_buttons, 3))

    if model in {"banana_pro", "banana_2", "nano-banana-2-lite"}:
        rows.append(
            [
                callback_button(
                    f"{'◉' if quality.upper() == value else '○'} {value}",
                    f"max:image:quality:{value.lower()}",
                )
                for value in ("1K", "2K", "4K")
            ]
        )
    if model in {"seedream_edit", "seedream_5_pro"}:
        rows.append(
            [
                callback_button(
                    f"{'◉' if quality == value else '○'} {value.title()}",
                    f"max:image:quality:{value}",
                )
                for value in ("basic", "high")
            ]
        )

    count_buttons = [
        callback_button(
            f"{'◉' if value == count else '○'} {value}x",
            f"max:image:count:{value}",
        )
        for value in _IMAGE_COUNTS
    ]
    rows.extend(_chunked(count_buttons, 2))
    rows.append([callback_button(f"🖼 Референсы: {len(refs)}", "max:image:refs:edit")])
    rows.append([callback_button("🏠 Главное меню", "max:home")])
    return [inline_keyboard(rows)]


def _video_media_menu(data: dict[str, Any]) -> list[dict[str, Any]]:
    generation_type = str(data.get("generation_type") or "text")
    model = str(data.get("model") or "")
    images = list(data.get("image_urls") or [])
    videos = list(data.get("video_urls") or [])
    rows: list[list[dict[str, Any]]] = []
    if generation_type == "imgtxt" or model == "glow":
        rows.append([callback_button(f"🖼 Фото: {len(images)}", "max:video:media:noop")])
    if generation_type == "video":
        rows.append([callback_button(f"📹 Видео: {len(videos)}/5", "max:video:media:noop")])
    rows.extend(
        [
            [callback_button("▶️ К настройкам", "max:video:media:continue")],
            [callback_button("🤖 Сменить модель", "max:create_video")],
            [callback_button("🏠 Главное меню", "max:home")],
        ]
    )
    return [inline_keyboard(rows)]


def _video_duration_values(catalog, model: str) -> tuple[int, ...]:
    pricing_key = "gemini_omni_video" if model == "gemini_omni" else model
    raw = (
        catalog.get_price_config()
        .get("costs_reference", {})
        .get("video_models", {})
        .get(pricing_key, {})
    )
    duration_costs = raw.get("duration_costs", {}) if isinstance(raw, dict) else {}
    values: list[int] = []
    for value in duration_costs:
        try:
            values.append(int(value))
        except (TypeError, ValueError):
            continue
    if values:
        return tuple(sorted(set(values)))
    return (_DEFAULT_VIDEO_DURATION.get(model, 5),)


def _video_resolutions(model: str) -> tuple[str, ...]:
    if model == "grok_imagine_v15":
        return ("480p", "720p")
    if model.startswith("veo3") or model == "gemini_omni":
        return ("720p", "1080p", "4k")
    return ()


def _video_settings_menu(data: dict[str, Any], catalog) -> list[dict[str, Any]]:
    model = str(data.get("model") or "")
    options = dict(data.get("options") or {})
    duration = int(options.get("duration") or _DEFAULT_VIDEO_DURATION.get(model, 5))
    ratio = str(options.get("aspect_ratio") or "16:9")
    resolution = str(options.get("resolution") or "720p")
    rows: list[list[dict[str, Any]]] = [
        [callback_button("🤖 Сменить модель", "max:create_video")]
    ]

    durations = _video_duration_values(catalog, model)
    if durations:
        buttons = [
            callback_button(
                f"{'◉' if value == duration else '○'} {value}с",
                f"max:video:duration:{value}",
            )
            for value in durations
        ]
        rows.extend(_chunked(buttons, 4))

    ratios = _VIDEO_RATIOS.get(model, ("16:9", "9:16", "1:1"))
    ratio_buttons = [
        callback_button(
            f"{'◉' if value == ratio else '○'} {value.replace(':', '∶')}",
            _ratio_payload("max:video:ratio", value),
        )
        for value in ratios
    ]
    rows.extend(_chunked(ratio_buttons, 3))

    resolutions = _video_resolutions(model)
    if resolutions:
        rows.append(
            [
                callback_button(
                    f"{'◉' if value == resolution else '○'} {value}",
                    f"max:video:resolution:{value}",
                )
                for value in resolutions
            ]
        )

    rows.append([callback_button("🏠 Главное меню", "max:home")])
    return [inline_keyboard(rows)]


def _video_defaults(model: str) -> dict[str, Any]:
    return {
        "duration": _DEFAULT_VIDEO_DURATION.get(model, 5),
        "aspect_ratio": "16:9",
        "resolution": "720p",
        "generate_audio": True,
    }


class MaxCreationParityChannelService(MaxTelegramParityChannelService):
    """Mirror Telegram creator wizard order while preserving MAX transport/ledger."""

    async def _open_image_models(self, user_id: int, *, callback_id: str = "") -> None:
        session = await get_max_session(user_id)
        refs = _image_refs_from_session(session.state, dict(session.data))
        if refs:
            await save_max_session(
                user_id,
                "parity:image:select_model",
                {"image_urls": refs},
            )
            text = (
                "🖼 <b>Создать фото</b>\n\n"
                f"Референсы сохранены: <b>{len(refs)}</b>. Выберите модель."
            )
        else:
            await clear_max_session(user_id)
            text = "🖼 <b>Создать фото</b>\n\nВыберите модель."

        await self._respond(
            user_id,
            text,
            attachments=image_model_menu(self.catalog),
            callback_id=callback_id,
        )

    async def _select_image_model_parity(
        self,
        user_id: int,
        model: str,
        *,
        callback_id: str,
    ) -> None:
        if model not in self.catalog.image_models():
            await self._respond(
                user_id,
                "Эта модель фото сейчас недоступна.",
                attachments=image_model_menu(self.catalog),
                callback_id=callback_id,
            )
            return
        session = await get_max_session(user_id)
        refs = _image_refs_from_session(session.state, dict(session.data))
        data = {
            "kind": "image",
            "model": model,
            "image_urls": refs,
            "aspect_ratio": "1:1",
            "quality": _image_default_quality(model),
            "count": 1,
        }
        if refs:
            await self._show_image_settings(
                user_id,
                data,
                callback_id=callback_id,
            )
            return

        await save_max_session(user_id, "parity:image:refs", data)
        required = (
            " Референс обязателен для этой модели."
            if model in _IMAGE_REFERENCE_REQUIRED
            else ""
        )
        await self._respond(
            user_id,
            f"🖼 <b>{html.escape(IMAGE_LABELS.get(model, model))}</b>\n\n"
            "Пришлите изображения-референсы одним или несколькими сообщениями."
            f"{required}",
            attachments=_image_reference_menu(0),
            callback_id=callback_id,
        )

    async def _show_image_settings(
        self,
        user_id: int,
        data: dict[str, Any],
        *,
        callback_id: str = "",
    ) -> None:
        await save_max_session(user_id, "parity:image:settings_prompt", data)
        await self._respond(
            user_id,
            "⚙️ <b>Настройки фото</b>\n\n"
            "Выберите формат, качество и количество, затем отправьте prompt обычным сообщением.",
            attachments=_image_settings_menu(data),
            callback_id=callback_id,
        )

    async def _image_refs_continue(
        self,
        user_id: int,
        *,
        callback_id: str,
        allow_empty: bool,
    ) -> None:
        session = await get_max_session(user_id)
        if session.state != "parity:image:refs":
            await self._open_image_models(user_id, callback_id=callback_id)
            return
        data = dict(session.data)
        refs = list(data.get("image_urls") or [])
        model = str(data.get("model") or "")
        if not refs and model in _IMAGE_REFERENCE_REQUIRED:
            await self._respond(
                user_id,
                "Для этой модели нужен хотя бы один референс.",
                attachments=_image_reference_menu(0),
                callback_id=callback_id,
            )
            return
        if not refs and not allow_empty:
            await self._respond(
                user_id,
                "Референсы пока не загружены. Можно добавить фото или нажать «Пропустить».",
                attachments=_image_reference_menu(0),
                callback_id=callback_id,
            )
            return
        await self._show_image_settings(user_id, data, callback_id=callback_id)

    async def _render_image_settings_from_session(
        self,
        user_id: int,
        *,
        callback_id: str,
    ) -> dict[str, Any] | None:
        session = await get_max_session(user_id)
        if session.state != "parity:image:settings_prompt":
            await self._open_image_models(user_id, callback_id=callback_id)
            return None
        return dict(session.data)

    async def _prepare_image_message(
        self,
        user_id: int,
        update: dict[str, Any],
        *,
        state: str,
        data: dict[str, Any],
    ) -> bool:
        images, _ = _media_urls(update)
        if state == "parity:image:refs":
            if not images:
                await self._respond(
                    user_id,
                    "Пришлите изображения-референсы или используйте кнопки «Пропустить» / «Продолжить».",
                    attachments=_image_reference_menu(len(data.get("image_urls") or [])),
                )
                return True
            refs = list(data.get("image_urls") or [])
            for url in images:
                if url not in refs and len(refs) < 9:
                    refs.append(url)
            data["image_urls"] = refs
            await save_max_session(user_id, state, data)
            await self._respond(
                user_id,
                f"Референсы приняты: <b>{len(refs)}/9</b>.",
                attachments=_image_reference_menu(len(refs)),
            )
            return True

        prompt = _message_text(update).strip()
        if not prompt:
            await self._respond(
                user_id,
                "Отправьте текстовый prompt. Настройки можно менять кнопками ниже.",
                attachments=_image_settings_menu(data),
            )
            return True
        model = str(data.get("model") or "")
        count = int(data.get("count") or 1)
        unit_cost = float(self.catalog.image_cost(model))
        prepared = {
            "kind": "image",
            "generation_type": "image",
            "model": model,
            "prompt": prompt,
            "input_data": {"image_urls": list(data.get("image_urls") or []), "video_urls": []},
            "options": {
                "aspect_ratio": str(data.get("aspect_ratio") or "1:1"),
                "quality": str(data.get("quality") or _image_default_quality(model)),
                "count": count,
            },
            "cost": unit_cost * count,
            "unit_cost": unit_cost,
            "count": count,
        }
        await save_max_session(user_id, "parity:image:confirm", prepared)
        await self._respond(
            user_id,
            "✨ <b>Готово к запуску</b>\n\n"
            f"Модель: <b>{html.escape(IMAGE_LABELS.get(model, model))}</b>\n"
            f"Формат: <b>{html.escape(str(prepared['options']['aspect_ratio']))}</b>\n"
            f"Качество: <b>{html.escape(str(prepared['options']['quality']))}</b>\n"
            f"Количество: <b>{count}</b>\n"
            f"Стоимость: <b>{_format_cost(unit_cost * count)} 🍌</b>\n\n"
            f"Промпт: {html.escape(prompt[:900])}",
            attachments=generation_confirm_menu(),
        )
        return True

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
        if model not in self.catalog.video_models(generation_type):
            await self._respond(
                user_id,
                "Этот тип исходника недоступен для выбранной модели.",
                attachments=video_type_menu(model=model, catalog=self.catalog),
                callback_id=callback_id,
            )
            return True

        # Preserve the richer dedicated Seedance 2.5 wizard already present in MAX.
        if model == "seedance_2_5":
            await super()._handle_callback(
                user_id,
                callback_id,
                f"max:video:{generation_type}:{model}",
            )
            return True

        data = {
            "kind": "video",
            "model": model,
            "generation_type": generation_type,
            "image_urls": [],
            "video_urls": [],
            "options": _video_defaults(model),
        }
        if generation_type == "text":
            await self._show_video_settings(user_id, data, callback_id=callback_id)
        else:
            await save_max_session(user_id, "parity:video:media", data)
            if generation_type == "imgtxt":
                instruction = "Пришлите стартовое фото."
            elif model == "glow":
                instruction = "Пришлите изображение и видео-референс."
            else:
                instruction = "Пришлите видео-референс."
            await self._respond(
                user_id,
                f"🎬 <b>{html.escape(VIDEO_LABELS.get(model, model))}</b>\n\n{instruction}",
                attachments=_video_media_menu(data),
                callback_id=callback_id,
            )
        return True

    async def _show_video_settings(
        self,
        user_id: int,
        data: dict[str, Any],
        *,
        callback_id: str = "",
    ) -> None:
        await save_max_session(user_id, "parity:video:settings_prompt", data)
        await self._respond(
            user_id,
            "⚙️ <b>Настройки видео</b>\n\n"
            "Выберите длительность, формат и качество, затем отправьте prompt обычным сообщением.",
            attachments=_video_settings_menu(data, self.catalog),
            callback_id=callback_id,
        )

    async def _video_media_continue(self, user_id: int, *, callback_id: str) -> None:
        session = await get_max_session(user_id)
        if session.state != "parity:video:media":
            await self._open_video_model_selection(user_id, callback_id=callback_id)
            return
        data = dict(session.data)
        generation_type = str(data.get("generation_type") or "")
        model = str(data.get("model") or "")
        images = list(data.get("image_urls") or [])
        videos = list(data.get("video_urls") or [])
        if generation_type == "imgtxt" and not images:
            message = "Для «Фото → Видео» сначала загрузите фотографию."
        elif generation_type == "video" and not videos:
            message = "Для «Видео → Видео» сначала загрузите видео."
        elif model == "glow" and (not images or not videos):
            message = "Для Kling Glow нужны и изображение, и видео-референс."
        else:
            await self._show_video_settings(user_id, data, callback_id=callback_id)
            return
        await self._respond(
            user_id,
            message,
            attachments=_video_media_menu(data),
            callback_id=callback_id,
        )

    async def _prepare_video_message(
        self,
        user_id: int,
        update: dict[str, Any],
        *,
        state: str,
        data: dict[str, Any],
    ) -> bool:
        if state == "parity:video:media":
            try:
                resolver = getattr(self, "_resolve_video_attachments", None)
                if callable(resolver):
                    update = await resolver(update)
            except MaxApiError:
                logger.exception("MAX parity video token resolution failed")
                await self._respond(
                    user_id,
                    "Не удалось прочитать видео из MAX. Пришлите файл ещё раз.",
                    attachments=_video_media_menu(data),
                )
                return True
            images, videos = _media_urls(update)
            stored_images = list(data.get("image_urls") or [])
            stored_videos = list(data.get("video_urls") or [])
            for url in images:
                if url not in stored_images and len(stored_images) < 9:
                    stored_images.append(url)
            for url in videos:
                if url not in stored_videos and len(stored_videos) < 5:
                    stored_videos.append(url)
            if not images and not videos:
                await self._respond(
                    user_id,
                    "Пришлите нужный фото/видео-референс или используйте кнопки ниже.",
                    attachments=_video_media_menu(data),
                )
                return True
            data["image_urls"] = stored_images
            data["video_urls"] = stored_videos
            await save_max_session(user_id, state, data)
            await self._respond(
                user_id,
                "Медиа принято. Можно добавить ещё или перейти к настройкам.",
                attachments=_video_media_menu(data),
            )
            return True

        prompt = _message_text(update).strip()
        if not prompt:
            await self._respond(
                user_id,
                "Отправьте текстовый prompt. Настройки можно менять кнопками ниже.",
                attachments=_video_settings_menu(data, self.catalog),
            )
            return True
        model = str(data.get("model") or "")
        generation_type = str(data.get("generation_type") or "")
        options = dict(data.get("options") or {})
        duration = int(options.get("duration") or _DEFAULT_VIDEO_DURATION.get(model, 5))
        quality = str(options.get("resolution") or "720p")
        pricing_quality = quality if model.startswith("veo3") or model == "gemini_omni" else None
        cost = float(
            self.catalog.video_cost(
                model,
                duration=duration,
                quality=pricing_quality,
            )
        )
        prepared = {
            "kind": "video",
            "generation_type": generation_type,
            "model": model,
            "prompt": prompt,
            "input_data": {
                "image_urls": list(data.get("image_urls") or []),
                "video_urls": list(data.get("video_urls") or []),
            },
            "options": options,
            "cost": cost,
        }
        await save_max_session(user_id, "video:confirm", prepared)
        await self._respond(
            user_id,
            "✨ <b>Готово к запуску</b>\n\n"
            f"Модель: <b>{html.escape(VIDEO_LABELS.get(model, model))}</b>\n"
            f"Длительность: <b>{duration}с</b>\n"
            f"Формат: <b>{html.escape(str(options.get('aspect_ratio') or '16:9'))}</b>\n"
            f"Стоимость: <b>{_format_cost(cost)} 🍌</b>\n\n"
            f"Промпт: {html.escape(prompt[:900])}",
            attachments=generation_confirm_menu(),
        )
        return True

    async def _prepare_generation_from_message(
        self,
        user_id: int,
        update: dict[str, Any],
    ) -> bool:
        session = await get_max_session(user_id)
        if session.state in {"parity:image:refs", "parity:image:settings_prompt"}:
            return await self._prepare_image_message(
                user_id,
                update,
                state=session.state,
                data=dict(session.data),
            )
        if session.state in {"parity:video:media", "parity:video:settings_prompt"}:
            return await self._prepare_video_message(
                user_id,
                update,
                state=session.state,
                data=dict(session.data),
            )
        return await super()._prepare_generation_from_message(user_id, update)

    async def _launch_generation(self, user_id: int, *, callback_id: str) -> None:
        session = await get_max_session(user_id)
        if session.state != "parity:image:confirm":
            await super()._launch_generation(user_id, callback_id=callback_id)
            return

        data = dict(session.data)
        count = max(1, min(int(data.get("count") or 1), 6))
        total_cost = float(data.get("unit_cost") or 0) * count
        balance = await get_max_balance(user_id)
        if balance + 1e-9 < total_cost:
            await self._respond(
                user_id,
                "🍌 Баланса не хватает. Подготовленный prompt сохранён.",
                attachments=topup_menu(self.catalog),
                callback_id=callback_id,
            )
            return

        await save_max_session(user_id, "parity:image:launching", data)
        jobs = []
        try:
            for _ in range(count):
                jobs.append(
                    await enqueue_max_generation(
                        user_id,
                        kind="image",
                        generation_type="image",
                        model=str(data["model"]),
                        prompt=str(data["prompt"]),
                        input_data=dict(data.get("input_data") or {}),
                        options=dict(data.get("options") or {}),
                        catalog=self.catalog,
                    )
                )
        except MaxInsufficientBalanceError:
            logger.warning("MAX image batch lost balance race: user=%s", user_id)
        except Exception:
            logger.exception("MAX image parity batch enqueue failed: user=%s", user_id)

        await clear_max_session(user_id)
        if not jobs:
            await self._respond(
                user_id,
                "Не удалось поставить генерацию в очередь. Баланс не списан за незапущенные задачи.",
                attachments=back_home_menu(),
                callback_id=callback_id,
            )
            return

        balance = await get_max_balance(user_id)
        await self._respond(
            user_id,
            "🚀 <b>Генерация запущена</b>\n\n"
            f"Задач: <b>{len(jobs)}</b>\n"
            f"Списано: <b>{_format_cost(sum(job.cost for job in jobs))} 🍌</b>\n"
            f"Осталось: <b>{_format_cost(balance)} 🍌</b>\n\n"
            "Результаты придут сюда автоматически.",
            attachments=back_home_menu(),
            callback_id=callback_id,
        )

    async def _handle_callback(
        self,
        user_id: int,
        callback_id: str,
        payload: str,
    ) -> None:
        if payload == "max:create_image":
            await self._open_image_models(user_id, callback_id=callback_id)
            return
        if payload.startswith("max:image:") and payload.count(":") == 2:
            await self._select_image_model_parity(
                user_id,
                payload.split(":", 2)[2],
                callback_id=callback_id,
            )
            return
        if payload == "max:image:refs:skip":
            await self._image_refs_continue(
                user_id,
                callback_id=callback_id,
                allow_empty=True,
            )
            return
        if payload == "max:image:refs:continue":
            await self._image_refs_continue(
                user_id,
                callback_id=callback_id,
                allow_empty=False,
            )
            return
        if payload == "max:image:refs:edit":
            session = await get_max_session(user_id)
            data = dict(session.data)
            await save_max_session(user_id, "parity:image:refs", data)
            await self._respond(
                user_id,
                "Добавьте референсы или продолжите с текущими.",
                attachments=_image_reference_menu(len(data.get("image_urls") or [])),
                callback_id=callback_id,
            )
            return
        if payload == "max:image:refs:reload":
            session = await get_max_session(user_id)
            await self._respond(
                user_id,
                "Экран референсов обновлён.",
                attachments=_image_reference_menu(len(session.data.get("image_urls") or [])),
                callback_id=callback_id,
            )
            return
        if payload in {"max:image:refs:noop", "max:image:saved_refs"}:
            session = await get_max_session(user_id)
            text = (
                "Сохранённые референсы в MAX будут доступны после привязки MAX-профиля к общей библиотеке. "
                "Сейчас можно использовать загруженные в этом сценарии изображения."
                if payload == "max:image:saved_refs"
                else "Референсы можно добавить следующим сообщением."
            )
            await self._respond(
                user_id,
                text,
                attachments=_image_reference_menu(len(session.data.get("image_urls") or [])),
                callback_id=callback_id,
            )
            return
        if payload.startswith("max:image:ratio:"):
            data = await self._render_image_settings_from_session(user_id, callback_id=callback_id)
            if data is not None:
                data["aspect_ratio"] = _decode_ratio(payload.rsplit(":", 1)[1])
                await self._show_image_settings(user_id, data, callback_id=callback_id)
            return
        if payload.startswith("max:image:quality:"):
            data = await self._render_image_settings_from_session(user_id, callback_id=callback_id)
            if data is not None:
                raw = payload.rsplit(":", 1)[1]
                data["quality"] = raw.upper() if raw in {"1k", "2k", "4k"} else raw
                await self._show_image_settings(user_id, data, callback_id=callback_id)
            return
        if payload.startswith("max:image:count:"):
            data = await self._render_image_settings_from_session(user_id, callback_id=callback_id)
            if data is not None:
                try:
                    value = int(payload.rsplit(":", 1)[1])
                except ValueError:
                    value = 1
                if value in _IMAGE_COUNTS:
                    data["count"] = value
                await self._show_image_settings(user_id, data, callback_id=callback_id)
            return
        if payload == "max:video:media:continue":
            await self._video_media_continue(user_id, callback_id=callback_id)
            return
        if payload == "max:video:media:noop":
            session = await get_max_session(user_id)
            await self._respond(
                user_id,
                "Добавьте нужные медиа следующим сообщением или перейдите к настройкам.",
                attachments=_video_media_menu(dict(session.data)),
                callback_id=callback_id,
            )
            return
        if payload.startswith("max:video:duration:"):
            session = await get_max_session(user_id)
            if session.state == "parity:video:settings_prompt":
                data = dict(session.data)
                options = dict(data.get("options") or {})
                try:
                    value = int(payload.rsplit(":", 1)[1])
                except ValueError:
                    value = int(options.get("duration") or 5)
                if value in _video_duration_values(self.catalog, str(data.get("model") or "")):
                    options["duration"] = value
                data["options"] = options
                await self._show_video_settings(user_id, data, callback_id=callback_id)
            return
        if payload.startswith("max:video:ratio:"):
            session = await get_max_session(user_id)
            if session.state == "parity:video:settings_prompt":
                data = dict(session.data)
                options = dict(data.get("options") or {})
                options["aspect_ratio"] = _decode_ratio(payload.rsplit(":", 1)[1])
                data["options"] = options
                await self._show_video_settings(user_id, data, callback_id=callback_id)
            return
        if payload.startswith("max:video:resolution:"):
            session = await get_max_session(user_id)
            if session.state == "parity:video:settings_prompt":
                data = dict(session.data)
                options = dict(data.get("options") or {})
                options["resolution"] = payload.rsplit(":", 1)[1]
                data["options"] = options
                await self._show_video_settings(user_id, data, callback_id=callback_id)
            return
        await super()._handle_callback(user_id, callback_id, payload)
