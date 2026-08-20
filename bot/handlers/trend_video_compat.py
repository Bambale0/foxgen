from __future__ import annotations

import html
import logging
from pathlib import Path
from typing import Any

from aiogram import F, Router, types
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaVideo,
)

from bot import database
from bot.config import config
from bot.services.reference_storage_service import save_reference_file
from bot.utils.validators import detect_explicit_prompt_policy_violation

logger = logging.getLogger(__name__)
router = Router(name="admin_video_trends")

TREND_TAG = "trend"
TREND_VIDEO_TAG = "trend-video"
TREND_VIDEO_MAX_BYTES = 20 * 1024 * 1024
TREND_VIDEO_MODELS: tuple[tuple[str, str], ...] = (
    ("v3_pro", "Kling 3.0 Pro"),
    ("v3_std", "Kling 3.0 Standard"),
    ("v26_pro", "Kling 2.5 Turbo Pro"),
    ("grok_imagine", "Grok Imagine"),
    ("grok_imagine_v15", "Grok Imagine 1.5"),
    ("seedance_2", "Seedance 2.0"),
    ("veo3", "Veo 3.1 Quality"),
    ("veo3_fast", "Veo 3.1 Fast"),
    ("veo3_lite", "Veo 3.1 Lite"),
    ("gemini_omni_video", "Gemini Omni Video"),
    ("glow", "Kling Glow"),
)
_VIDEO_MODEL_LABELS = dict(TREND_VIDEO_MODELS)
_VIDEO_MODEL_IDS = frozenset(_VIDEO_MODEL_LABELS)
_TRENDS_MODULE: Any | None = None
_INSTALLED = False


class TrendVideoUploadStates(StatesGroup):
    waiting_title = State()
    waiting_description = State()
    waiting_model = State()
    waiting_preview = State()
    waiting_prompt = State()
    confirming = State()


def _build_video_generation_settings(model: str) -> dict[str, Any]:
    normalized_model = str(model or "v3_pro").strip() or "v3_pro"
    return {
        "kind": "video",
        "user_input": "photo",
        "model": normalized_model,
        "scenario": "imgtxt",
        "ratio": "16:9",
        "duration": 5,
        "grok_mode": "normal",
        "grok_resolution": "480p",
        "veo_generation_type": "IMAGE_2_VIDEO",
        "veo_translation": True,
        "veo_resolution": "720p",
        "veo_seed": None,
        "veo_watermark": "",
        "kling_negative_prompt": "",
        "kling_cfg_scale": 0.5,
        "omni_resolution": "720p",
        "omni_seed": None,
        "omni_audio_ids": [],
        "omni_character_ids": [],
        "omni_base_voice": "achernar",
        "omni_voice_name": "",
        "omni_voice_description": "",
        "omni_example_dialogue": "",
        "omni_character_name": "",
        "omni_character_audio_ids": [],
    }


def is_video_trend(prompt: dict[str, Any] | None) -> bool:
    if not prompt:
        return False
    tags = {str(item or "").strip().lower() for item in prompt.get("tags", []) or []}
    model = str(prompt.get("model") or "").strip()
    category = str(prompt.get("category") or "").strip().lower()
    return (
        TREND_VIDEO_TAG in tags
        or category == "video"
        or model in _VIDEO_MODEL_IDS
    )


def _is_admin_user(user: types.User | None) -> bool:
    return bool(user and config.is_admin(user.id))


async def _reject_non_admin_message(
    message: types.Message,
    state: FSMContext,
) -> bool:
    if _is_admin_user(message.from_user):
        return False
    await state.clear()
    await message.answer("Эта функция доступна только администратору.")
    return True


def _cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✖️ Отменить",
                    callback_data="trend_video_add_cancel",
                )
            ]
        ]
    )


def _description_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Пропустить описание",
                    callback_data="trend_video_desc_skip",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✖️ Отменить",
                    callback_data="trend_video_add_cancel",
                )
            ],
        ]
    )


def _video_model_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    current: list[InlineKeyboardButton] = []
    for model_id, label in TREND_VIDEO_MODELS:
        current.append(
            InlineKeyboardButton(
                text=label,
                callback_data=f"trend_video_model:{model_id}",
            )
        )
        if len(current) == 2:
            rows.append(current)
            current = []
    if current:
        rows.append(current)
    rows.append(
        [
            InlineKeyboardButton(
                text="✖️ Отменить",
                callback_data="trend_video_add_cancel",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Опубликовать видео-тренд",
                    callback_data="trend_video_publish_confirm",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✖️ Отменить",
                    callback_data="trend_video_add_cancel",
                )
            ],
        ]
    )


def _add_video_upload_button(markup: InlineKeyboardMarkup) -> InlineKeyboardMarkup:
    rows = [list(row) for row in markup.inline_keyboard]
    if any(
        button.callback_data == "trend_video_add"
        for row in rows
        for button in row
    ):
        return markup

    insert_at = min(2, len(rows))
    rows.insert(
        insert_at,
        [
            InlineKeyboardButton(
                text="🎬 Загрузить видео-тренд",
                callback_data="trend_video_add",
            )
        ],
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _empty_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Загрузить фото-тренд",
                    callback_data="trend_add",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎬 Загрузить видео-тренд",
                    callback_data="trend_video_add",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏠 Главное меню",
                    callback_data="back_main",
                )
            ],
        ]
    )


def _video_file_metadata(message: types.Message) -> tuple[str, str, str] | None:
    if message.video:
        filename = str(message.video.file_name or "trend-preview.mp4").strip()
        suffix = Path(filename).suffix.lower().lstrip(".") or "mp4"
        content_type = str(message.video.mime_type or "video/mp4").lower()
        return suffix if suffix in {"mp4", "webm", "mov"} else "mp4", content_type, filename

    document = message.document
    if not document:
        return None

    content_type = str(document.mime_type or "").lower()
    filename = str(document.file_name or "trend-preview").strip()
    suffix = Path(filename).suffix.lower().lstrip(".")
    mime_extensions = {
        "video/mp4": "mp4",
        "video/webm": "webm",
        "video/quicktime": "mov",
    }
    extension = mime_extensions.get(content_type, suffix)
    if extension not in {"mp4", "webm", "mov"}:
        return None
    if content_type not in mime_extensions:
        content_type = {
            "mp4": "video/mp4",
            "webm": "video/webm",
            "mov": "video/quicktime",
        }[extension]
    return extension, content_type, filename


async def _save_video_preview(message: types.Message) -> str | None:
    metadata = _video_file_metadata(message)
    if not metadata or not message.from_user:
        return None

    extension, content_type, filename = metadata
    media = message.video or message.document
    if media is None:
        return None

    try:
        telegram_file = await message.bot.get_file(media.file_id)
        if not telegram_file.file_path:
            return None
        stream = await message.bot.download_file(telegram_file.file_path)
        file_bytes = stream.read()
    except Exception:
        logger.exception("Unable to download video trend preview from Telegram")
        return None

    if not file_bytes or len(file_bytes) > TREND_VIDEO_MAX_BYTES:
        return None

    public_url, _reference = await save_reference_file(
        message.from_user.id,
        file_bytes,
        file_ext=extension,
        kind="video",
        original_filename=filename,
        content_type=content_type,
        source="trend_admin_text_bot",
    )
    return public_url


async def _show_model_step(message: types.Message, state: FSMContext) -> None:
    await state.set_state(TrendVideoUploadStates.waiting_model)
    await message.answer(
        "<b>Шаг 3/5. Выберите видео-модель</b>\n\n"
        "Пользователю автоматически подставится именно эта нейросеть.",
        reply_markup=_video_model_keyboard(),
        parse_mode="HTML",
    )


async def _show_confirmation(message: types.Message, data: dict[str, Any]) -> None:
    title = html.escape(str(data.get("title") or "Видео-тренд"))
    description = html.escape(str(data.get("description") or ""))
    model_id = str(data.get("model") or "v3_pro")
    model_label = html.escape(_VIDEO_MODEL_LABELS.get(model_id, model_id))
    prompt_text = str(data.get("prompt_text") or "")
    prompt_preview = html.escape(prompt_text[:700])
    description_line = f"\n{description}" if description else ""
    caption = (
        "<b>Проверьте видео-тренд перед публикацией</b>\n\n"
        f"<b>{title}</b>{description_line}\n\n"
        f"Нейросеть: <code>{model_label}</code>\n"
        "Тип: <code>Видео</code>\n\n"
        f"Скрытый prompt:\n<pre>{prompt_preview}</pre>"
    )
    if len(prompt_text) > 700:
        caption += "\n<i>Показано начало prompt.</i>"

    preview_url = str(data.get("preview_url") or "")
    try:
        await message.answer_video(
            preview_url,
            caption=caption,
            reply_markup=_confirm_keyboard(),
            parse_mode="HTML",
            supports_streaming=True,
        )
    except Exception:
        logger.exception("Unable to show video trend confirmation preview")
        await message.answer(
            caption,
            reply_markup=_confirm_keyboard(),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "trend_video_add")
async def start_video_trend_upload(
    callback: types.CallbackQuery,
    state: FSMContext,
) -> None:
    if not _is_admin_user(callback.from_user):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.clear()
    await state.set_state(TrendVideoUploadStates.waiting_title)
    if callback.message:
        await callback.message.answer(
            "<b>Шаг 1/5. Название видео-тренда</b>\n\n"
            "Отправьте короткое название до 80 символов.",
            reply_markup=_cancel_keyboard(),
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(TrendVideoUploadStates.waiting_title)
async def receive_video_trend_title(
    message: types.Message,
    state: FSMContext,
) -> None:
    if await _reject_non_admin_message(message, state):
        return
    title = str(message.text or "").strip()
    if not title:
        await message.answer("Отправьте название обычным текстом.")
        return
    if len(title) > 80:
        await message.answer("Название слишком длинное. Максимум 80 символов.")
        return

    await state.update_data(title=title)
    await state.set_state(TrendVideoUploadStates.waiting_description)
    await message.answer(
        "<b>Шаг 2/5. Короткое описание</b>\n\n"
        "Напишите, что получится и какие исходники понадобятся. "
        "Максимум 240 символов.",
        reply_markup=_description_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(
    StateFilter(TrendVideoUploadStates.waiting_description),
    F.data == "trend_video_desc_skip",
)
async def skip_video_trend_description(
    callback: types.CallbackQuery,
    state: FSMContext,
) -> None:
    if not _is_admin_user(callback.from_user):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.update_data(description="")
    if callback.message:
        await _show_model_step(callback.message, state)
    await callback.answer("Описание пропущено")


@router.message(TrendVideoUploadStates.waiting_description)
async def receive_video_trend_description(
    message: types.Message,
    state: FSMContext,
) -> None:
    if await _reject_non_admin_message(message, state):
        return
    description = str(message.text or "").strip()
    if not description:
        await message.answer(
            "Отправьте описание текстом или нажмите «Пропустить описание».",
            reply_markup=_description_keyboard(),
        )
        return
    if len(description) > 240:
        await message.answer("Описание слишком длинное. Максимум 240 символов.")
        return
    await state.update_data(description=description)
    await _show_model_step(message, state)


@router.callback_query(
    StateFilter(TrendVideoUploadStates.waiting_model),
    F.data.startswith("trend_video_model:"),
)
async def select_video_trend_model(
    callback: types.CallbackQuery,
    state: FSMContext,
) -> None:
    if not _is_admin_user(callback.from_user):
        await callback.answer("Нет доступа", show_alert=True)
        return
    model_id = str(callback.data or "").partition(":")[2]
    if model_id not in _VIDEO_MODEL_IDS:
        await callback.answer("Неизвестная модель", show_alert=True)
        return

    await state.update_data(model=model_id)
    await state.set_state(TrendVideoUploadStates.waiting_preview)
    if callback.message:
        await callback.message.answer(
            "<b>Шаг 4/5. Видео-пример тренда</b>\n\n"
            "Отправьте готовый ролик как видео или файл MP4, WEBM либо MOV. "
            "Лимит — 20 МБ.",
            reply_markup=_cancel_keyboard(),
            parse_mode="HTML",
        )
    await callback.answer(_VIDEO_MODEL_LABELS[model_id])


@router.message(TrendVideoUploadStates.waiting_preview)
async def receive_video_trend_preview(
    message: types.Message,
    state: FSMContext,
) -> None:
    if await _reject_non_admin_message(message, state):
        return
    if not _video_file_metadata(message):
        await message.answer(
            "Отправьте видео MP4, WEBM или MOV как ролик либо документ.",
            reply_markup=_cancel_keyboard(),
        )
        return

    status = await message.answer("Загружаю видео-пример…")
    preview_url = await _save_video_preview(message)
    if not preview_url:
        await status.edit_text(
            "Не удалось сохранить видео. Проверьте формат и размер файла."
        )
        return

    await state.update_data(preview_url=preview_url)
    await state.set_state(TrendVideoUploadStates.waiting_prompt)
    await status.edit_text(
        "<b>Шаг 5/5. Скрытый prompt</b>\n\n"
        "Отправьте готовый prompt видео-шаблона. Пользователь не увидит его "
        "в карточке, но он подставится после нажатия «Повторить шаблон».",
        reply_markup=_cancel_keyboard(),
        parse_mode="HTML",
    )


@router.message(TrendVideoUploadStates.waiting_prompt)
async def receive_video_trend_prompt(
    message: types.Message,
    state: FSMContext,
) -> None:
    if await _reject_non_admin_message(message, state):
        return
    prompt_text = str(message.text or "").strip()
    if not prompt_text:
        await message.answer("Отправьте prompt обычным текстом.")
        return
    if len(prompt_text) > 8000:
        await message.answer("Prompt слишком длинный. Максимум 8000 символов.")
        return

    policy_error = detect_explicit_prompt_policy_violation(prompt_text)
    if policy_error:
        await message.answer(policy_error)
        return

    await state.update_data(prompt_text=prompt_text)
    await state.set_state(TrendVideoUploadStates.confirming)
    await _show_confirmation(message, await state.get_data())


@router.callback_query(
    StateFilter(TrendVideoUploadStates.confirming),
    F.data == "trend_video_publish_confirm",
)
async def publish_video_trend(
    callback: types.CallbackQuery,
    state: FSMContext,
) -> None:
    if not _is_admin_user(callback.from_user):
        await callback.answer("Нет доступа", show_alert=True)
        return

    data = await state.get_data()
    required = ("title", "model", "preview_url", "prompt_text")
    if any(not str(data.get(key) or "").strip() for key in required):
        await callback.answer(
            "Данные мастера устарели. Начните загрузку заново.",
            show_alert=True,
        )
        await state.clear()
        return

    user = await database.get_or_create_user(callback.from_user.id)
    prompt = await database.create_prompt(
        author_id=user.id,
        prompt_text=str(data["prompt_text"]),
        title=str(data["title"]),
        description=str(data.get("description") or "").strip() or None,
        category="video",
        preview_url=str(data["preview_url"]),
        model=str(data["model"]),
        tags=[TREND_TAG, TREND_VIDEO_TAG],
        generation_settings=_build_video_generation_settings(str(data["model"])),
        is_public=True,
    )
    if not prompt:
        await callback.answer("Не удалось создать видео-тренд", show_alert=True)
        return

    approved = await database.approve_prompt(prompt["id"])
    if not approved:
        await callback.answer("Не удалось опубликовать видео-тренд", show_alert=True)
        return

    await state.clear()
    await callback.answer("Видео-тренд опубликован")
    if callback.message:
        await callback.message.answer(
            "✅ <b>Видео-тренд опубликован</b>\n\n"
            "Он уже доступен пользователям в текстовом боте и Mini App.",
            parse_mode="HTML",
        )
        if _TRENDS_MODULE is not None:
            await _TRENDS_MODULE._render_trends(
                callback.message,
                index=0,
                admin_telegram_id=callback.from_user.id,
            )


@router.callback_query(F.data == "trend_video_add_cancel")
async def cancel_video_trend_upload(
    callback: types.CallbackQuery,
    state: FSMContext,
) -> None:
    if not _is_admin_user(callback.from_user):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    await callback.answer("Создание отменено")
    if callback.message:
        await callback.message.answer(
            "Создание видео-тренда отменено.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🔥 Вернуться к трендам",
                            callback_data="menu_trends",
                        )
                    ]
                ]
            ),
        )


def _install_miniapp_video_submit(miniapp_module: Any) -> None:
    async def miniapp_trend_submit(request: Any):
        try:
            body = await miniapp_module._miniapp_payload(request)
            init_data = body.get("init_data", "")
            telegram_id, ctx = await miniapp_module._get_user_context(
                request.app,
                init_data,
                body.get("start_param_fallback"),
            )
            if not config.is_admin(telegram_id):
                return miniapp_module.web.json_response(
                    {"ok": False, "error": "Тренды может публиковать только администратор"},
                    status=403,
                )

            title = str(body.get("title", "") or "").strip()
            prompt_text = str(body.get("prompt_text", "") or body.get("prompt", "") or "").strip()
            preview_url = str(body.get("preview_url", "") or "").strip()
            model = str(body.get("model", "") or "").strip()
            requested_tags = {
                str(item or "").strip().lower()
                for item in body.get("tags", []) or []
            }
            is_video = (
                TREND_VIDEO_TAG in requested_tags
                or model in _VIDEO_MODEL_IDS
            )
            if not title or not prompt_text or not preview_url or not model:
                return miniapp_module.web.json_response(
                    {
                        "ok": False,
                        "error": "Для тренда нужны название, preview, нейросеть и prompt",
                    },
                    status=400,
                )

            policy_error = detect_explicit_prompt_policy_violation(prompt_text)
            if policy_error:
                return miniapp_module.web.json_response(
                    {"ok": False, "error": policy_error},
                    status=400,
                )

            tags = [TREND_TAG]
            if is_video:
                tags.append(TREND_VIDEO_TAG)
            for tag in body.get("tags", []) or []:
                normalized_tag = str(tag or "").strip().lower()
                if normalized_tag.startswith(("trend-scenario:", "trend-duration:")):
                    tags.append(normalized_tag)
            raw_generation_settings = body.get("generation_settings")
            generation_settings = (
                dict(raw_generation_settings)
                if isinstance(raw_generation_settings, dict) and raw_generation_settings
                else (
                    _build_video_generation_settings(model)
                    if is_video
                    else {}
                )
            )
            prompt = await database.create_prompt(
                author_id=ctx["user"].id,
                prompt_text=prompt_text,
                title=title,
                description=str(body.get("description", "") or "").strip() or None,
                category="video" if is_video else "photo",
                preview_url=preview_url,
                model=model,
                tags=tags,
                generation_settings=generation_settings,
                is_public=True,
            )
            if prompt:
                prompt = await database.approve_prompt(prompt["id"])
            return miniapp_module.web.json_response({"ok": True, "prompt": prompt})
        except Exception as error:  # noqa: BLE001 - Mini App API boundary
            return miniapp_module._miniapp_error_response(
                error,
                log_message="Mini App trend submit failed",
            )

    miniapp_module.miniapp_prompt_submit = miniapp_trend_submit


def install_trend_video_compat(trends_module: Any) -> None:
    global _INSTALLED, _TRENDS_MODULE
    if _INSTALLED:
        return

    _TRENDS_MODULE = trends_module
    original_keyboard = trends_module._trend_keyboard
    original_render = trends_module._render_trends

    def trend_keyboard_with_video_upload(
        prompt: dict[str, Any],
        *,
        index: int,
        total: int,
        is_admin: bool,
    ) -> InlineKeyboardMarkup:
        markup = original_keyboard(
            prompt,
            index=index,
            total=total,
            is_admin=is_admin,
        )
        return _add_video_upload_button(markup) if is_admin else markup

    async def render_trends_with_video(
        message: types.Message,
        *,
        index: int = 0,
        admin_telegram_id: int | None = None,
    ) -> None:
        trends = await trends_module._get_trends()
        if not trends and config.is_admin(admin_telegram_id):
            await message.answer(
                "🔥 <b>Тренды</b>\n\n"
                "Пока витрина пустая. Добавьте фото- или видео-шаблон "
                "прямо в текстовом боте.",
                reply_markup=_empty_admin_keyboard(),
                parse_mode="HTML",
            )
            return
        if not trends:
            await original_render(
                message,
                index=index,
                admin_telegram_id=admin_telegram_id,
            )
            return

        safe_index = max(0, min(index, len(trends) - 1))
        trend = trends[safe_index]
        if not is_video_trend(trend):
            await original_render(
                message,
                index=safe_index,
                admin_telegram_id=admin_telegram_id,
            )
            return

        preview_url = str(trend.get("preview_url") or "").strip()
        caption = trends_module._trend_caption(
            trend,
            index=safe_index,
            total=len(trends),
        )
        caption = caption.replace(
            "Нейросеть:",
            "Тип: <code>Видео</code>\nНейросеть:",
            1,
        )
        markup = trend_keyboard_with_video_upload(
            trend,
            index=safe_index,
            total=len(trends),
            is_admin=config.is_admin(admin_telegram_id),
        )

        if preview_url and getattr(message, "video", None):
            try:
                await message.edit_media(
                    InputMediaVideo(
                        media=preview_url,
                        caption=caption,
                        parse_mode="HTML",
                        supports_streaming=True,
                    ),
                    reply_markup=markup,
                )
                return
            except Exception:
                logger.debug("Unable to edit video trend media", exc_info=True)

        if preview_url:
            try:
                await message.answer_video(
                    preview_url,
                    caption=caption,
                    reply_markup=markup,
                    parse_mode="HTML",
                    supports_streaming=True,
                )
                return
            except Exception:
                logger.debug("Unable to send video trend preview", exc_info=True)

        await message.answer(caption, reply_markup=markup, parse_mode="HTML")

    trends_module._trend_keyboard = trend_keyboard_with_video_upload
    trends_module._render_trends = render_trends_with_video

    from bot import miniapp as miniapp_module

    _install_miniapp_video_submit(miniapp_module)
    _INSTALLED = True
