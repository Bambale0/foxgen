from __future__ import annotations

import html
import logging
import re
from typing import Any

from bot.max_api import MaxApiError, MaxClient, MaxSettings, callback_button, inline_keyboard, link_button
from bot.max_catalog import MAX_VIDEO_TYPES, MaxPresetManager, max_preset_manager
from bot.max_generation import MaxGenerationJob, enqueue_max_generation
from bot.max_payments import (
    MaxYooKassaService,
    get_max_referral_stats,
    register_max_referral,
)
from bot.max_store import (
    MaxInsufficientBalanceError,
    clear_max_session,
    ensure_max_user,
    get_max_balance,
    get_max_session,
    list_max_history,
    save_max_session,
)
from bot.max_ui import (
    back_home_menu,
    generation_confirm_menu,
    image_model_menu,
    main_menu,
    topup_menu,
    video_model_menu,
    video_type_menu,
)

logger = logging.getLogger(__name__)

_REFERRAL_PAYLOAD_RE = re.compile(r"^ref_(\d{1,20})$")
_DEFAULT_VIDEO_DURATIONS = {
    "grok_imagine": 6,
    "grok_imagine_v15": 8,
    "gemini_omni": 6,
    "veo3": 6,
    "veo3_fast": 6,
    "veo3_lite": 6,
}
_IMAGE_REFERENCE_REQUIRED = frozenset({"seedream_edit", "grok_imagine_i2i"})


def _user_payload(update: dict[str, Any]) -> dict[str, Any]:
    update_type = str(update.get("update_type") or "")
    if update_type == "bot_started":
        return update.get("user") if isinstance(update.get("user"), dict) else {}
    if update_type == "message_callback":
        callback = update.get("callback") or {}
        if isinstance(callback, dict) and isinstance(callback.get("user"), dict):
            return callback["user"]
    message = update.get("message") or {}
    if isinstance(message, dict) and isinstance(message.get("sender"), dict):
        return message["sender"]
    return {}


def _user_id(update: dict[str, Any]) -> int:
    user = _user_payload(update)
    raw = user.get("user_id") or user.get("id") or 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _user_names(update: dict[str, Any]) -> tuple[str, str, str]:
    user = _user_payload(update)
    username = str(user.get("username") or "").strip().lstrip("@")
    first_name = str(user.get("first_name") or user.get("name") or "").strip()
    last_name = str(user.get("last_name") or "").strip()
    return username, first_name, last_name


def _callback(update: dict[str, Any]) -> tuple[str, str]:
    callback = update.get("callback") or {}
    if not isinstance(callback, dict):
        return "", ""
    return (
        str(callback.get("callback_id") or "").strip(),
        str(callback.get("payload") or "").strip(),
    )


def _message_body(update: dict[str, Any]) -> dict[str, Any]:
    message = update.get("message") or {}
    if not isinstance(message, dict):
        return {}
    body = message.get("body") or {}
    return body if isinstance(body, dict) else {}


def _message_text(update: dict[str, Any]) -> str:
    return str(_message_body(update).get("text") or "").strip()


def _first_https_url(value: Any) -> str:
    if isinstance(value, str):
        return value.strip() if value.strip().startswith("https://") else ""
    if isinstance(value, list):
        for item in value:
            found = _first_https_url(item)
            if found:
                return found
        return ""
    if isinstance(value, dict):
        direct = value.get("url")
        if isinstance(direct, str) and direct.strip().startswith("https://"):
            return direct.strip()
        for nested in value.values():
            found = _first_https_url(nested)
            if found:
                return found
    return ""


def _media_urls(update: dict[str, Any]) -> tuple[list[str], list[str]]:
    images: list[str] = []
    videos: list[str] = []
    attachments = _message_body(update).get("attachments") or []
    if not isinstance(attachments, list):
        return images, videos
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        media_type = str(attachment.get("type") or "").strip().lower()
        url = _first_https_url(attachment.get("payload") or {})
        if not url:
            continue
        if media_type == "image" and url not in images:
            images.append(url)
        elif media_type == "video" and url not in videos:
            videos.append(url)
    return images, videos


def _video_duration(model: str) -> int:
    return _DEFAULT_VIDEO_DURATIONS.get(model, 5)


def _format_cost(cost: float) -> str:
    amount = float(cost)
    return str(int(amount)) if amount.is_integer() else f"{amount:g}"


class MaxChannelService:
    """MAX delivery adapter: normalize Update objects and drive isolated use cases."""

    def __init__(
        self,
        *,
        settings: MaxSettings,
        client: MaxClient,
        payments: MaxYooKassaService,
        bot_name: str,
        support_contact: str = "",
        catalog: MaxPresetManager = max_preset_manager,
    ) -> None:
        self.settings = settings
        self.client = client
        self.payments = payments
        self.bot_name = str(bot_name or "").strip().lstrip("@")
        self.support_contact = str(support_contact or "").strip()
        self.catalog = catalog

    async def _respond(
        self,
        user_id: int,
        text: str,
        *,
        attachments: list[dict[str, Any]] | None = None,
        callback_id: str = "",
    ) -> None:
        if callback_id:
            message: dict[str, Any] = {"text": str(text)[:4000], "format": "html"}
            if attachments:
                message["attachments"] = attachments
            try:
                await self.client.answer_callback(callback_id, message=message)
                return
            except MaxApiError:
                logger.warning("MAX callback answer failed; falling back to new message")
        await self.client.send_message(user_id, text, attachments=attachments)

    async def _home(self, user_id: int, *, callback_id: str = "", clear: bool = True) -> None:
        if clear:
            await clear_max_session(user_id)
        balance = await get_max_balance(user_id)
        await self._respond(
            user_id,
            "🦊 <b>HappyFox в MAX</b>\n\nВыберите, что хотите создать.",
            attachments=main_menu(balance, mini_app_url=self.settings.mini_app_url),
            callback_id=callback_id,
        )

    async def _balance(self, user_id: int, *, callback_id: str) -> None:
        balance = await get_max_balance(user_id)
        await self._respond(
            user_id,
            f"🐾 <b>Баланс MAX</b>\n\nДоступно: <b>{_format_cost(balance)} 🐾</b>\n\n"
            "Баланс MAX отделён от Telegram.",
            attachments=topup_menu(self.catalog),
            callback_id=callback_id,
        )

    async def _history(self, user_id: int, *, callback_id: str) -> None:
        history = await list_max_history(user_id, limit=5)
        if not history:
            text = "🔗 <b>Ссылки на работы</b>\n\nЗдесь появятся ваши готовые генерации в MAX."
        else:
            lines = ["🔗 <b>Последние работы MAX</b>"]
            for item in history:
                model = html.escape(str(item.get("model") or "model"))
                status = html.escape(str(item.get("status") or ""))
                url = str(item.get("result_url") or "").strip()
                line = f"• {model} · {status}"
                if url.startswith("https://"):
                    line += f"\n  {html.escape(url)}"
                lines.append(line)
            text = "\n\n".join(lines)
        await self._respond(
            user_id,
            text,
            attachments=back_home_menu(),
            callback_id=callback_id,
        )

    async def _partners(self, user_id: int, *, callback_id: str) -> None:
        stats = await get_max_referral_stats(user_id)
        if not self.bot_name:
            invite = "Ссылка станет доступна после настройки MAX_BOT_NAME."
        else:
            invite = f"https://max.ru/{self.bot_name}?start=ref_{user_id}"
        partner = self.catalog.get_price_config().get("partner_program", {}) or {}
        l1 = _format_cost(float(partner.get("level1_percent") or 0))
        l2 = _format_cost(float(partner.get("level2_percent") or 0))
        await self._respond(
            user_id,
            "🤝 <b>Партнёрская программа MAX</b>\n\n"
            f"Приглашено: <b>{int(stats['referrals'])}</b>\n"
            f"Заработано: <b>{_format_cost(float(stats['earned_credits']))} 🐾</b>\n"
            f"Покупки: <b>{l1}%</b> с 1 уровня и <b>{l2}%</b> со 2 уровня.\n\n"
            f"Ваша ссылка:\n{html.escape(invite)}",
            attachments=back_home_menu(),
            callback_id=callback_id,
        )

    async def _show_topup(self, user_id: int, *, callback_id: str) -> None:
        if not self.payments.enabled:
            await self._respond(
                user_id,
                "💳 <b>Пополнение MAX</b>\n\nYooKassa пока не настроена для MAX.",
                attachments=back_home_menu(),
                callback_id=callback_id,
            )
            return
        await self._respond(
            user_id,
            "💳 <b>Пополнение MAX</b>\n\nВыберите пакет 🐾. Оплата проходит отдельно от Telegram.",
            attachments=topup_menu(self.catalog),
            callback_id=callback_id,
        )

    async def _create_payment(self, user_id: int, package_id: str, *, callback_id: str) -> None:
        try:
            order = await self.payments.create_checkout(user_id, package_id)
        except (RuntimeError, ValueError) as exc:
            logger.warning("MAX checkout creation failed: %s", exc)
            await self._respond(
                user_id,
                "Не удалось создать оплату. Попробуйте ещё раз чуть позже.",
                attachments=topup_menu(self.catalog),
                callback_id=callback_id,
            )
            return
        attachments = [
            inline_keyboard(
                [
                    [link_button("💳 Оплатить в YooKassa", str(order.checkout_url))],
                    [callback_button("🔄 Проверить оплату", f"max:payment:{order.order_id}")],
                    [callback_button("🏠 Главное меню", "max:home")],
                ]
            )
        ]
        await self._respond(
            user_id,
            "💳 <b>Счёт MAX создан</b>\n\n"
            f"Пакет: <b>{html.escape(order.package_id)}</b>\n"
            f"Начисление: <b>{_format_cost(order.credits)} 🐾</b>\n"
            f"Сумма: <b>{_format_cost(order.amount_rub)} ₽</b>\n\n"
            "После оплаты можно нажать «Проверить оплату». Фоновая сверка также начислит баланс автоматически.",
            attachments=attachments,
            callback_id=callback_id,
        )

    async def _check_payment(self, user_id: int, order_id: str, *, callback_id: str) -> None:
        result = await self.payments.complete_order(order_id)
        order = result.get("order")
        if order is not None and int(order.max_user_id) != int(user_id):
            await self._respond(user_id, "Этот счёт принадлежит другому пользователю.", callback_id=callback_id)
            return
        status = str(result.get("status") or "")
        if status == "completed":
            balance = await get_max_balance(user_id)
            await self._respond(
                user_id,
                f"✅ <b>Оплата подтверждена</b>\n\nБаланс MAX: <b>{_format_cost(balance)} 🐾</b>",
                attachments=main_menu(balance, mini_app_url=self.settings.mini_app_url),
                callback_id=callback_id,
            )
            return
        if status == "failed":
            text = "Платёж отменён или не прошёл. Можно создать новый счёт."
        elif status == "verification_failed":
            text = "Платёж найден, но его данные не совпали со счётом MAX. Начисление остановлено безопасно."
        else:
            text = "Платёж ещё не подтверждён. Если вы уже оплатили, повторите проверку через несколько секунд."
        await self._respond(
            user_id,
            text,
            attachments=back_home_menu(),
            callback_id=callback_id,
        )

    async def _select_image_model(self, user_id: int, model: str, *, callback_id: str) -> None:
        if model not in self.catalog.image_models():
            await self._respond(user_id, "Эта модель фото сейчас недоступна.", callback_id=callback_id)
            return
        await save_max_session(
            user_id,
            "image:waiting_input",
            {"kind": "image", "model": model},
        )
        reference_note = (
            " Для этой модели обязательно приложите изображение-референс."
            if model in _IMAGE_REFERENCE_REQUIRED
            else " Можно приложить изображение-референс в том же сообщении."
        )
        await self._respond(
            user_id,
            f"🖼 <b>{html.escape(model)}</b>\n\nОтправьте промпт одним сообщением.{reference_note}",
            attachments=back_home_menu(),
            callback_id=callback_id,
        )

    async def _select_video_model(
        self,
        user_id: int,
        generation_type: str,
        model: str,
        *,
        callback_id: str,
    ) -> None:
        if generation_type not in MAX_VIDEO_TYPES or model not in self.catalog.video_models(generation_type):
            await self._respond(user_id, "Эта видео-модель сейчас недоступна для выбранного сценария.", callback_id=callback_id)
            return
        await save_max_session(
            user_id,
            "video:waiting_input",
            {"kind": "video", "generation_type": generation_type, "model": model},
        )
        if generation_type == "text":
            media_note = "Отправьте текстовый промпт."
        elif generation_type == "imgtxt":
            media_note = "Отправьте промпт и изображение в одном сообщении."
        elif model == "glow":
            media_note = "Отправьте промпт, изображение и видео-референс."
        else:
            media_note = "Отправьте промпт и видео-референс."
        await self._respond(
            user_id,
            f"🎬 <b>{html.escape(model)}</b>\n\n{media_note}",
            attachments=back_home_menu(),
            callback_id=callback_id,
        )

    async def _prepare_generation_from_message(self, user_id: int, update: dict[str, Any]) -> bool:
        session = await get_max_session(user_id)
        if session.state not in {"image:waiting_input", "video:waiting_input"}:
            return False
        prompt = _message_text(update)
        images, videos = _media_urls(update)
        if not prompt:
            await self._respond(user_id, "Добавьте текстовый промпт к сообщению — без него генерацию не запускаю.")
            return True

        data = dict(session.data)
        kind = str(data.get("kind") or "")
        model = str(data.get("model") or "")
        input_data = {"image_urls": images, "video_urls": videos}
        options: dict[str, Any]
        if kind == "image":
            if model in _IMAGE_REFERENCE_REQUIRED and not images:
                await self._respond(user_id, "Для этой модели нужен референс. Пришлите изображение вместе с промптом.")
                return True
            cost = self.catalog.image_cost(model)
            options = {"aspect_ratio": "1:1", "quality": "2K"}
            generation_type = "image"
        else:
            generation_type = str(data.get("generation_type") or "")
            if generation_type == "imgtxt" and not images:
                await self._respond(user_id, "Для «Фото → Видео» приложите изображение вместе с промптом.")
                return True
            if generation_type == "video" and not videos:
                await self._respond(user_id, "Для «Видео → Видео» приложите видео-референс вместе с промптом.")
                return True
            if model == "glow" and (not images or not videos):
                await self._respond(user_id, "Kling Glow нужны и изображение, и видео-референс.")
                return True
            duration = _video_duration(model)
            resolution = "720p"
            quality = resolution if model.startswith("veo3") or model == "gemini_omni" else None
            cost = self.catalog.video_cost(model, duration=duration, quality=quality)
            options = {
                "duration": duration,
                "aspect_ratio": "16:9",
                "resolution": resolution,
                "generate_audio": True,
            }

        prepared = {
            **data,
            "prompt": prompt,
            "input_data": input_data,
            "options": options,
            "generation_type": generation_type,
            "cost": float(cost),
        }
        await save_max_session(user_id, f"{kind}:confirm", prepared)
        refs = len(images) + len(videos)
        await self._respond(
            user_id,
            f"✨ <b>Готово к запуску</b>\n\n"
            f"Модель: <b>{html.escape(model)}</b>\n"
            f"Стоимость: <b>{_format_cost(cost)} 🐾</b>\n"
            f"Референсов: <b>{refs}</b>\n\n"
            f"Промпт: {html.escape(prompt[:800])}",
            attachments=generation_confirm_menu(),
        )
        return True

    async def _launch_generation(self, user_id: int, *, callback_id: str) -> None:
        session = await get_max_session(user_id)
        if session.state not in {"image:confirm", "video:confirm"}:
            await self._respond(
                user_id,
                "Сценарий уже завершён или устарел. Выберите модель заново.",
                attachments=main_menu(await get_max_balance(user_id), mini_app_url=self.settings.mini_app_url),
                callback_id=callback_id,
            )
            return
        data = dict(session.data)
        try:
            job: MaxGenerationJob = await enqueue_max_generation(
                user_id,
                kind=str(data["kind"]),
                generation_type=str(data.get("generation_type") or ""),
                model=str(data["model"]),
                prompt=str(data["prompt"]),
                input_data=dict(data.get("input_data") or {}),
                options=dict(data.get("options") or {}),
                catalog=self.catalog,
            )
        except MaxInsufficientBalanceError:
            await self._respond(
                user_id,
                "🐾 Баланса не хватает. Пополните MAX-баланс — подготовленный промпт сохранён.",
                attachments=topup_menu(self.catalog),
                callback_id=callback_id,
            )
            return
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            logger.exception("MAX generation enqueue failed")
            await self._respond(
                user_id,
                f"Не удалось поставить генерацию в очередь: {html.escape(str(exc)[:300])}",
                attachments=back_home_menu(),
                callback_id=callback_id,
            )
            return

        await clear_max_session(user_id)
        balance = await get_max_balance(user_id)
        await self._respond(
            user_id,
            "🚀 <b>Генерация запущена</b>\n\n"
            f"Задача: <code>{html.escape(job.id[:12])}</code>\n"
            f"Списано: <b>{_format_cost(job.cost)} 🐾</b>\n"
            f"Осталось: <b>{_format_cost(balance)} 🐾</b>\n\n"
            "Результат придёт сюда автоматически.",
            attachments=main_menu(balance, mini_app_url=self.settings.mini_app_url),
            callback_id=callback_id,
        )

    async def _unsupported(self, user_id: int, feature: str, *, callback_id: str) -> None:
        await self._respond(
            user_id,
            f"{html.escape(feature)} уже есть в HappyFox, но отдельный MAX-сценарий ещё переносится. "
            "Фото, видео, баланс, оплата, история и партнёрская программа в MAX работают независимо.",
            attachments=back_home_menu(),
            callback_id=callback_id,
        )

    async def _handle_callback(self, user_id: int, callback_id: str, payload: str) -> None:
        if payload == "max:home":
            await self._home(user_id, callback_id=callback_id)
        elif payload == "max:balance":
            await self._balance(user_id, callback_id=callback_id)
        elif payload == "max:history":
            await self._history(user_id, callback_id=callback_id)
        elif payload == "max:partners":
            await self._partners(user_id, callback_id=callback_id)
        elif payload == "max:topup":
            await self._show_topup(user_id, callback_id=callback_id)
        elif payload == "max:create_image":
            await clear_max_session(user_id)
            await self._respond(
                user_id,
                "🖼 <b>Создать фото</b>\n\nВыберите модель.",
                attachments=image_model_menu(self.catalog),
                callback_id=callback_id,
            )
        elif payload.startswith("max:image:"):
            await self._select_image_model(user_id, payload.split(":", 2)[2], callback_id=callback_id)
        elif payload == "max:create_video":
            await clear_max_session(user_id)
            await self._respond(
                user_id,
                "🎬 <b>Создать видео</b>\n\nСначала выберите сценарий.",
                attachments=video_type_menu(),
                callback_id=callback_id,
            )
        elif payload.startswith("max:vtype:"):
            generation_type = payload.split(":", 2)[2]
            if generation_type not in MAX_VIDEO_TYPES:
                await self._respond(user_id, "Неизвестный тип видео.", callback_id=callback_id)
            else:
                await self._respond(
                    user_id,
                    "🎬 <b>Выберите видео-модель</b>",
                    attachments=video_model_menu(generation_type, self.catalog),
                    callback_id=callback_id,
                )
        elif payload.startswith("max:video:"):
            parts = payload.split(":", 3)
            if len(parts) == 4:
                await self._select_video_model(user_id, parts[2], parts[3], callback_id=callback_id)
        elif payload == "max:gemini_omni":
            await self._select_video_model(user_id, "text", "gemini_omni", callback_id=callback_id)
        elif payload == "max:generate":
            await self._launch_generation(user_id, callback_id=callback_id)
        elif payload == "max:cancel":
            await self._home(user_id, callback_id=callback_id)
        elif payload.startswith("max:package:"):
            await self._create_payment(user_id, payload.split(":", 2)[2], callback_id=callback_id)
        elif payload.startswith("max:payment:"):
            await self._check_payment(user_id, payload.split(":", 2)[2], callback_id=callback_id)
        elif payload == "max:support":
            contact = self.support_contact or "раздел поддержки HappyFox"
            await self._respond(
                user_id,
                f"💬 <b>Поддержка</b>\n\n{html.escape(contact)}",
                attachments=back_home_menu(),
                callback_id=callback_id,
            )
        elif payload == "max:prompts" and self.settings.mini_app_url:
            await self._respond(
                user_id,
                "✨ Библиотека промптов доступна в Mini App.",
                attachments=[
                    inline_keyboard(
                        [
                            [link_button("🚀 Открыть Mini App", self.settings.mini_app_url)],
                            [callback_button("🏠 Главное меню", "max:home")],
                        ]
                    )
                ],
                callback_id=callback_id,
            )
        else:
            labels = {
                "max:omni_audio": "🎙 Озвучка",
                "max:music": "🎵 Suno",
                "max:motion_control": "🎯 Motion Control",
                "max:assistant": "🤖 AI-помощник",
                "max:prompts": "✨ Промпты",
            }
            await self._unsupported(user_id, labels.get(payload, "Этот сценарий"), callback_id=callback_id)

    async def handle_update(self, update: dict[str, Any]) -> None:
        user_id = _user_id(update)
        if user_id <= 0:
            logger.info("Ignoring MAX update without a direct user: type=%s", update.get("update_type"))
            return
        username, first_name, last_name = _user_names(update)
        await ensure_max_user(
            user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
        )

        update_type = str(update.get("update_type") or "")
        if update_type == "bot_started":
            payload = str(update.get("payload") or "").strip()
            referral = _REFERRAL_PAYLOAD_RE.fullmatch(payload)
            bonus_applied = False
            if referral:
                bonus_applied = await register_max_referral(
                    user_id,
                    int(referral.group(1)),
                    catalog=self.catalog,
                )
            await self._home(user_id)
            if bonus_applied:
                balance = await get_max_balance(user_id)
                await self.client.send_message(
                    user_id,
                    f"🎁 Реферальный бонус MAX начислен. Баланс: {_format_cost(balance)} 🐾",
                )
            return

        if update_type == "message_callback":
            callback_id, payload = _callback(update)
            if not callback_id:
                return
            await self._handle_callback(user_id, callback_id, payload)
            return

        if update_type != "message_created":
            return

        if await self._prepare_generation_from_message(user_id, update):
            return

        text = _message_text(update).strip().lower()
        if text in {"/start", "start", "старт", "меню", "/menu"}:
            await self._home(user_id)
        elif text in {"фото", "создать фото"}:
            await self._respond(user_id, "🖼 <b>Создать фото</b>\n\nВыберите модель.", attachments=image_model_menu(self.catalog))
        elif text in {"видео", "создать видео"}:
            await self._respond(user_id, "🎬 <b>Создать видео</b>\n\nВыберите сценарий.", attachments=video_type_menu())
        elif text in {"баланс", "/balance"}:
            await self._balance(user_id, callback_id="")
        elif text in {"партнёры", "партнеры", "/ref"}:
            await self._partners(user_id, callback_id="")
        else:
            await self._respond(
                user_id,
                "Я не потерял сообщение. Выберите действие в меню — так быстрее дойти до результата.",
                attachments=main_menu(await get_max_balance(user_id), mini_app_url=self.settings.mini_app_url),
            )
