from __future__ import annotations

import html
import logging
from pathlib import Path
from typing import Any

from aiogram import F, Router, types
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import database
from bot.config import config
from bot.services.reference_storage_service import save_reference_file
from bot.utils.validators import detect_explicit_prompt_policy_violation

logger = logging.getLogger(__name__)
router = Router(name="admin_trend_text_upload")

TREND_TAG = "trend"
TREND_PREVIEW_MAX_BYTES = 20 * 1024 * 1024
TREND_IMAGE_MODELS: tuple[tuple[str, str], ...] = (
    ("banana_pro", "Nano Banana Pro"),
    ("banana_2", "Nano Banana 2"),
    ("nano-banana-2-lite", "Nano Banana 2 Lite"),
    ("seedream_5_pro", "Seedream 5 Pro"),
    ("seedream_edit", "Seedream 4.5"),
    ("flux_pro", "GPT Image 2"),
    ("grok_imagine_i2i", "Grok Imagine"),
    ("wan_27", "Wan 2.7 Pro"),
)
_TREND_MODEL_LABELS = dict(TREND_IMAGE_MODELS)
_TRENDS_MODULE: Any | None = None
_INSTALLED = False


class TrendTextUploadStates(StatesGroup):
    waiting_title = State()
    waiting_description = State()
    waiting_model = State()
    waiting_preview = State()
    waiting_prompt = State()
    confirming = State()


def _build_image_generation_settings(model: str) -> dict[str, Any]:
    normalized_model = str(model or "banana_pro").strip() or "banana_pro"
    quality = "2K" if normalized_model in {"banana_pro", "banana_2"} else "basic"
    return {
        "kind": "image",
        "user_input": "photo",
        "model": normalized_model,
        "ratio": "1:1",
        "quality": quality,
        "count": 1,
        "nsfw_checker": False,
        "nsfw_enabled": False,
    }


def _cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✖️ Отменить",
                    callback_data="trend_add_cancel",
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
                    callback_data="trend_desc_skip",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✖️ Отменить",
                    callback_data="trend_add_cancel",
                )
            ],
        ]
    )


def _trend_model_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    current: list[InlineKeyboardButton] = []
    for model_id, label in TREND_IMAGE_MODELS:
        current.append(
            InlineKeyboardButton(
                text=label,
                callback_data=f"trend_model:{model_id}",
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
                callback_data="trend_add_cancel",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Опубликовать тренд",
                    callback_data="trend_publish_confirm",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✖️ Отменить",
                    callback_data="trend_add_cancel",
                )
            ],
        ]
    )


def _empty_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Загрузить тренд",
                    callback_data="trend_add",
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


def _add_admin_upload_button(markup: InlineKeyboardMarkup) -> InlineKeyboardMarkup:
    rows = [list(row) for row in markup.inline_keyboard]
    if any(
        button.callback_data == "trend_add"
        for row in rows
        for button in row
    ):
        return markup

    add_row = [
        InlineKeyboardButton(
            text="➕ Загрузить тренд",
            callback_data="trend_add",
        )
    ]
    insert_at = 1 if rows else 0
    rows.insert(insert_at, add_row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _preview_file_extension(message: types.Message) -> tuple[str, str, str] | None:
    if message.photo:
        return "jpg", "image/jpeg", "trend-preview.jpg"

    document = message.document
    if not document:
        return None

    content_type = str(document.mime_type or "").lower()
    filename = str(document.file_name or "trend-preview").strip()
    suffix = Path(filename).suffix.lower().lstrip(".")
    mime_extensions = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }
    extension = mime_extensions.get(content_type, suffix)
    if extension == "jpeg":
        extension = "jpg"
    if extension not in {"jpg", "png", "webp"}:
        return None
    if content_type not in mime_extensions:
        content_type = {
            "jpg": "image/jpeg",
            "png": "image/png",
            "webp": "image/webp",
        }[extension]
    return extension, content_type, filename


async def _save_preview_from_message(message: types.Message) -> str | None:
    metadata = _preview_file_extension(message)
    if not metadata or not message.from_user:
        return None

    extension, content_type, filename = metadata
    media = message.photo[-1] if message.photo else message.document
    if media is None:
        return None

    try:
        telegram_file = await message.bot.get_file(media.file_id)
        if not telegram_file.file_path:
            return None
        stream = await message.bot.download_file(telegram_file.file_path)
        file_bytes = stream.read()
    except Exception:
        logger.exception("Unable to download trend preview from Telegram")
        return None

    if not file_bytes or len(file_bytes) > TREND_PREVIEW_MAX_BYTES:
        return None

    public_url, _reference = await save_reference_file(
        message.from_user.id,
        file_bytes,
        file_ext=extension,
        kind="image",
        original_filename=filename,
        content_type=content_type,
        source="trend_admin_text_bot",
    )
    return public_url


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


async def _show_model_step(message: types.Message, state: FSMContext) -> None:
    await state.set_state(TrendTextUploadStates.waiting_model)
    await message.answer(
        "<b>Шаг 3/5. Выберите нейросеть</b>\n\n"
        "Пользователю автоматически подставится именно эта модель.",
        reply_markup=_trend_model_keyboard(),
        parse_mode="HTML",
    )


async def _show_confirmation(message: types.Message, data: dict[str, Any]) -> None:
    title = html.escape(str(data.get("title") or "Тренд"))
    description = html.escape(str(data.get("description") or ""))
    model_id = str(data.get("model") or "banana_pro")
    model_label = html.escape(_TREND_MODEL_LABELS.get(model_id, model_id))
    prompt_text = str(data.get("prompt_text") or "")
    prompt_preview = html.escape(prompt_text[:700])
    description_line = f"\n{description}" if description else ""
    caption = (
        "<b>Проверьте тренд перед публикацией</b>\n\n"
        f"<b>{title}</b>{description_line}\n\n"
        f"Нейросеть: <code>{model_label}</code>\n\n"
        f"Скрытый prompt:\n<pre>{prompt_preview}</pre>"
    )
    if len(prompt_text) > 700:
        caption += "\n<i>Показано начало prompt.</i>"

    preview_url = str(data.get("preview_url") or "")
    try:
        await message.answer_photo(
            preview_url,
            caption=caption,
            reply_markup=_confirm_keyboard(),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Unable to show trend confirmation preview")
        await message.answer(
            caption,
            reply_markup=_confirm_keyboard(),
            parse_mode="HTML",
        )


async def _render_trend_catalog(message: types.Message, telegram_id: int) -> None:
    if _TRENDS_MODULE is None:
        await message.answer("Тренд опубликован.")
        return
    await _TRENDS_MODULE._render_trends(
        message,
        index=0,
        admin_telegram_id=telegram_id,
    )


@router.callback_query(F.data == "trend_add")
async def start_trend_upload(
    callback: types.CallbackQuery,
    state: FSMContext,
) -> None:
    if not _is_admin_user(callback.from_user):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.clear()
    await state.set_state(TrendTextUploadStates.waiting_title)
    if callback.message:
        await callback.message.answer(
            "<b>Шаг 1/5. Название тренда</b>\n\n"
            "Отправьте короткое название до 80 символов.",
            reply_markup=_cancel_keyboard(),
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(TrendTextUploadStates.waiting_title)
async def receive_trend_title(
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
    await state.set_state(TrendTextUploadStates.waiting_description)
    await message.answer(
        "<b>Шаг 2/5. Короткое описание</b>\n\n"
        "Напишите, что получится и какое фото лучше загрузить. "
        "Максимум 240 символов.",
        reply_markup=_description_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(
    StateFilter(TrendTextUploadStates.waiting_description),
    F.data == "trend_desc_skip",
)
async def skip_trend_description(
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


@router.message(TrendTextUploadStates.waiting_description)
async def receive_trend_description(
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
    StateFilter(TrendTextUploadStates.waiting_model),
    F.data.startswith("trend_model:"),
)
async def select_trend_model(
    callback: types.CallbackQuery,
    state: FSMContext,
) -> None:
    if not _is_admin_user(callback.from_user):
        await callback.answer("Нет доступа", show_alert=True)
        return
    model_id = str(callback.data or "").partition(":")[2]
    if model_id not in _TREND_MODEL_LABELS:
        await callback.answer("Неизвестная модель", show_alert=True)
        return

    await state.update_data(model=model_id)
    await state.set_state(TrendTextUploadStates.waiting_preview)
    if callback.message:
        await callback.message.answer(
            "<b>Шаг 4/5. Preview тренда</b>\n\n"
            "Отправьте готовое изображение-пример как фото или файл "
            "JPEG, PNG либо WEBP. Лимит — 20 МБ.",
            reply_markup=_cancel_keyboard(),
            parse_mode="HTML",
        )
    await callback.answer(_TREND_MODEL_LABELS[model_id])


@router.message(TrendTextUploadStates.waiting_preview)
async def receive_trend_preview(
    message: types.Message,
    state: FSMContext,
) -> None:
    if await _reject_non_admin_message(message, state):
        return
    metadata = _preview_file_extension(message)
    if not metadata:
        await message.answer(
            "Отправьте изображение JPEG, PNG или WEBP как фото либо документ.",
            reply_markup=_cancel_keyboard(),
        )
        return

    status = await message.answer("Загружаю preview…")
    preview_url = await _save_preview_from_message(message)
    if not preview_url:
        await status.edit_text(
            "Не удалось сохранить preview. Проверьте формат и размер файла."
        )
        return

    await state.update_data(preview_url=preview_url)
    await state.set_state(TrendTextUploadStates.waiting_prompt)
    await status.edit_text(
        "<b>Шаг 5/5. Скрытый prompt</b>\n\n"
        "Отправьте готовый prompt шаблона. Пользователь не увидит его в "
        "карточке, но он подставится после нажатия «Повторить шаблон».",
        reply_markup=_cancel_keyboard(),
        parse_mode="HTML",
    )


@router.message(TrendTextUploadStates.waiting_prompt)
async def receive_trend_prompt(
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
    await state.set_state(TrendTextUploadStates.confirming)
    await _show_confirmation(message, await state.get_data())


@router.callback_query(
    StateFilter(TrendTextUploadStates.confirming),
    F.data == "trend_publish_confirm",
)
async def publish_trend_from_text_bot(
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
        category="photo",
        preview_url=str(data["preview_url"]),
        model=str(data["model"]),
        tags=[TREND_TAG],
        generation_settings=_build_image_generation_settings(str(data["model"])),
        is_public=True,
    )
    if not prompt:
        await callback.answer("Не удалось создать тренд", show_alert=True)
        return

    approved = await database.approve_prompt(prompt["id"])
    if not approved:
        await callback.answer("Не удалось опубликовать тренд", show_alert=True)
        return

    await state.clear()
    await callback.answer("Тренд опубликован")
    if callback.message:
        await callback.message.answer(
            "✅ <b>Тренд опубликован</b>\n\n"
            "Он уже доступен пользователям в текстовом боте и Mini App.",
            parse_mode="HTML",
        )
        await _render_trend_catalog(callback.message, callback.from_user.id)


@router.callback_query(F.data == "trend_add_cancel")
async def cancel_trend_upload(
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
            "Создание тренда отменено.",
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


def install_text_trend_upload(trends_module: Any) -> None:
    global _INSTALLED, _TRENDS_MODULE
    if _INSTALLED:
        return

    _TRENDS_MODULE = trends_module
    original_keyboard = trends_module._trend_keyboard
    original_render = trends_module._render_trends

    def trend_keyboard_with_admin_upload(
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
        return _add_admin_upload_button(markup) if is_admin else markup

    async def render_trends_with_admin_upload(
        message: types.Message,
        *,
        index: int = 0,
        admin_telegram_id: int | None = None,
    ) -> None:
        trends = await trends_module._get_trends()
        if not trends and config.is_admin(admin_telegram_id):
            await message.answer(
                "🔥 <b>Тренды</b>\n\n"
                "Пока витрина пустая. Нажмите «Загрузить тренд» и пройдите "
                "пошаговый мастер прямо в текстовом боте.",
                reply_markup=_empty_admin_keyboard(),
                parse_mode="HTML",
            )
            return
        await original_render(
            message,
            index=index,
            admin_telegram_id=admin_telegram_id,
        )

    trends_module._trend_keyboard = trend_keyboard_with_admin_upload
    trends_module._render_trends = render_trends_with_admin_upload
    _INSTALLED = True
