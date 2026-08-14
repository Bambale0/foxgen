from html import escape
from typing import Any, TypedDict
from uuid import uuid4

from aiogram import Bot, F, Router
from aiogram.filters import Filter, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, PhotoSize

from foxgen.bot.api_client import FoxGenApiClient
from foxgen.bot.callbacks import safe_edit_callback_message
from foxgen.bot.catalog import GenerationMode, model_choice, product_for_mode
from foxgen.bot.flows import _show_confirmation_message
from foxgen.bot.keyboards import (
    aspect_ratio_keyboard,
    main_menu,
    model_keyboard,
    navigation_keyboard,
    quick_start_keyboard,
    reference_product_keyboard,
)
from foxgen.bot.states import GenerationStates
from foxgen.bot.uploads import (
    TelegramInputMediaStorage,
    message_media_kind,
    stored_input_keys,
)
from foxgen.core.errors import SubmissionError

router = Router(name="quick-start")


class StoredInput(TypedDict):
    kind: str
    storage_key: str


class ReferenceDraftFilter(Filter):
    async def __call__(self, callback: CallbackQuery, state: FSMContext) -> bool:
        del callback
        data = await state.get_data()
        return data.get("entrypoint") == "reference"


REFERENCE_DRAFT = ReferenceDraftFilter()


@router.callback_query(F.data == "quick:start")
async def start_quick_launch(
    callback: CallbackQuery,
    state: FSMContext,
    input_media: TelegramInputMediaStorage,
) -> None:
    await _clear_reference_inputs(state, input_media)
    await state.set_state(GenerationStates.quick_start_waiting_media)
    await _edit_callback(
        callback,
        (
            "<b>Быстрый запуск</b>\n\n"
            "Отправьте фото или видео. Я сохраню референс и предложу совместимые варианты."
        ),
        quick_start_keyboard(),
    )


@router.message(
    GenerationStates.quick_start_waiting_media,
    F.photo | F.video | F.animation | F.document,
)
@router.message(
    StateFilter(None),
    F.photo | F.video | F.animation | F.document,
)
async def receive_reference_entry(
    message: Message,
    state: FSMContext,
    bot: Bot,
    input_media: TelegramInputMediaStorage,
) -> None:
    uploaded: StoredInput | None = None
    preview: StoredInput | None = None
    try:
        kind = message_media_kind(message)
        if kind not in {"image", "video"}:
            await message.answer("Для быстрого запуска отправьте фото или видео.")
            return
        user_id = message.from_user.id if message.from_user is not None else 0
        original_upload = await input_media.upload(
            bot=bot,
            message=message,
            user_id=user_id,
        )
        uploaded = {
            "kind": original_upload.kind,
            "storage_key": original_upload.storage_key,
        }
        thumbnail = _video_thumbnail(message) if kind == "video" else None
        if thumbnail is not None:
            preview_upload = await input_media.upload_photo_size(
                bot=bot,
                photo=thumbnail,
                user_id=user_id,
            )
            preview = {
                "kind": preview_upload.kind,
                "storage_key": preview_upload.storage_key,
            }
    except SubmissionError as exc:
        if uploaded is not None:
            await input_media.delete_many((uploaded["storage_key"],))
        await message.answer(exc.public_message)
        return

    if uploaded is None:
        await message.answer("Не удалось сохранить референс. Повторите попытку.")
        return
    await state.clear()
    await state.update_data(
        entrypoint="reference",
        reference_kind=kind,
        reference_original=uploaded,
        reference_preview=preview,
        reference_caption=(message.caption or "").strip(),
        media=[uploaded],
        idempotency_key=f"generation:{user_id}:{uuid4().hex}",
        can_submit=False,
    )
    await state.set_state(GenerationStates.reference_choosing_product)
    await message.answer(
        _reference_choice_text(kind, preview is not None),
        reply_markup=reference_product_keyboard(kind),
    )


@router.message(GenerationStates.quick_start_waiting_media)
async def invalid_quick_start_media(message: Message) -> None:
    await message.answer(
        "Отправьте одно фото или видео.",
        reply_markup=quick_start_keyboard(),
    )


@router.callback_query(
    GenerationStates.reference_choosing_product,
    F.data.in_({"reference:product:image", "reference:product:video"}),
)
async def choose_reference_product(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    reference_kind = _required_str(data, "reference_kind")
    original = _stored_input(data.get("reference_original"))
    preview = _stored_input(data.get("reference_preview"))
    if original is None:
        await _reset_broken_reference(callback, state)
        return

    if callback.data == "reference:product:image":
        mode = GenerationMode.IMAGE_EDIT
        selected = original if reference_kind == "image" else preview
        if selected is None:
            await callback.answer(
                "Telegram не передал обложку этого видео. Отправьте нужный кадр как фото.",
                show_alert=True,
            )
            return
    else:
        mode = (
            GenerationMode.VIDEO_IMAGE
            if reference_kind == "image"
            else GenerationMode.VIDEO_REFERENCE
        )
        selected = original

    await state.update_data(
        mode=mode.value,
        product=product_for_mode(mode).value,
        media=[selected],
        can_submit=False,
    )
    await state.set_state(GenerationStates.reference_choosing_model)
    await _edit_callback(
        callback,
        "<b>Референс сохранён</b>\n\nВыберите модель:",
        model_keyboard(mode),
    )


@router.message(GenerationStates.reference_choosing_product)
async def invalid_reference_product(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    reference_kind = str(data.get("reference_kind") or "image")
    await message.answer(
        "Выберите кнопкой, что создать по референсу.",
        reply_markup=reference_product_keyboard(reference_kind),
    )


@router.callback_query(
    GenerationStates.reference_choosing_model,
    F.data.startswith("model:"),
)
async def choose_reference_model(callback: CallbackQuery, state: FSMContext) -> None:
    slug = (callback.data or "").partition(":")[2]
    data = await state.get_data()
    try:
        mode = GenerationMode(_required_str(data, "mode"))
        choice = model_choice(mode, slug)
    except (KeyError, ValueError):
        await callback.answer("Эта модель недоступна для референса.", show_alert=True)
        return

    await state.update_data(
        model_slug=choice.slug,
        model_title=choice.title,
        can_submit=False,
    )
    caption = str(data.get("reference_caption") or "").strip()
    if 3 <= len(caption) <= 3500:
        await state.update_data(prompt=caption)
        await state.set_state(GenerationStates.choosing_aspect_ratio)
        await _edit_callback(
            callback,
            (
                f"<b>{escape(choice.title)}</b>\n\n"
                "Описание взято из подписи к референсу. Выберите формат результата:"
            ),
            aspect_ratio_keyboard(product_for_mode(mode)),
        )
        return

    await state.set_state(GenerationStates.reference_waiting_prompt)
    await _edit_callback(
        callback,
        (
            f"<b>{escape(choice.title)}</b>\n\n"
            "Опишите, что нужно получить по референсу. Укажите изменения, стиль, "
            "движение и важные ограничения."
        ),
        navigation_keyboard(),
    )


@router.message(GenerationStates.reference_choosing_model)
async def invalid_reference_model(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    try:
        mode = GenerationMode(_required_str(data, "mode"))
    except ValueError:
        await state.clear()
        await message.answer(
            "Черновик устарел. Начните быстрый запуск заново.",
            reply_markup=main_menu(),
        )
        return
    await message.answer("Выберите модель кнопкой.", reply_markup=model_keyboard(mode))


@router.message(GenerationStates.reference_waiting_prompt, F.text)
async def receive_reference_prompt(
    message: Message,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    prompt = (message.text or "").strip()
    if len(prompt) < 3:
        await message.answer("Описание слишком короткое. Добавьте хотя бы несколько слов.")
        return
    if len(prompt) > 3500:
        await message.answer("Описание длиннее 3500 символов. Сократите его и отправьте снова.")
        return

    data = await state.get_data()
    try:
        mode = GenerationMode(_required_str(data, "mode"))
    except ValueError:
        await state.clear()
        await message.answer(
            "Черновик устарел. Начните быстрый запуск заново.",
            reply_markup=main_menu(),
        )
        return
    editing = bool(data.get("editing_prompt"))
    await state.update_data(prompt=prompt, editing_prompt=False, can_submit=False)
    if editing and isinstance(data.get("aspect_ratio"), str):
        await state.set_state(GenerationStates.confirming)
        await _show_confirmation_message(message, state, api_client)
        return
    await state.set_state(GenerationStates.choosing_aspect_ratio)
    await message.answer(
        "Референс и описание сохранены. Выберите формат результата:",
        reply_markup=aspect_ratio_keyboard(product_for_mode(mode)),
    )


@router.message(GenerationStates.reference_waiting_prompt)
async def invalid_reference_prompt(message: Message) -> None:
    await message.answer(
        "Отправьте текстовое описание результата.",
        reply_markup=navigation_keyboard(),
    )


@router.callback_query(GenerationStates.reference_choosing_product, F.data == "nav:back")
async def choose_another_reference(
    callback: CallbackQuery,
    state: FSMContext,
    input_media: TelegramInputMediaStorage,
) -> None:
    await _clear_reference_inputs(state, input_media)
    await state.set_state(GenerationStates.quick_start_waiting_media)
    await _edit_callback(
        callback,
        "Отправьте другое фото или видео.",
        quick_start_keyboard(),
    )


@router.callback_query(GenerationStates.reference_choosing_model, F.data == "nav:back")
async def back_to_reference_product(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    reference_kind = str(data.get("reference_kind") or "image")
    await state.set_state(GenerationStates.reference_choosing_product)
    await _edit_callback(
        callback,
        _reference_choice_text(
            reference_kind,
            _stored_input(data.get("reference_preview")) is not None,
        ),
        reference_product_keyboard(reference_kind),
    )


@router.callback_query(GenerationStates.reference_waiting_prompt, F.data == "nav:back")
async def back_to_reference_model(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    try:
        mode = GenerationMode(_required_str(data, "mode"))
    except ValueError:
        await _reset_broken_reference(callback, state)
        return
    await state.set_state(GenerationStates.reference_choosing_model)
    await _edit_callback(callback, "Выберите модель:", model_keyboard(mode))


@router.callback_query(
    GenerationStates.choosing_aspect_ratio,
    REFERENCE_DRAFT,
    F.data == "nav:back",
)
async def back_from_reference_aspect(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(
        editing_prompt=isinstance(data.get("aspect_ratio"), str),
        can_submit=False,
    )
    await state.set_state(GenerationStates.reference_waiting_prompt)
    await _edit_callback(
        callback,
        "Отправьте описание результата по сохранённому референсу.",
        navigation_keyboard(),
    )


@router.callback_query(
    GenerationStates.confirming,
    REFERENCE_DRAFT,
    F.data == "draft:edit",
)
async def edit_reference_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(editing_prompt=True, can_submit=False)
    await state.set_state(GenerationStates.reference_waiting_prompt)
    await _edit_callback(
        callback,
        "Отправьте новое описание. Референс и настройки сохранятся.",
        navigation_keyboard(),
    )


async def _clear_reference_inputs(
    state: FSMContext,
    input_media: TelegramInputMediaStorage,
) -> None:
    data = await state.get_data()
    await input_media.delete_many(stored_input_keys(data))
    await state.clear()


def _reference_choice_text(reference_kind: str, has_preview: bool) -> str:
    if reference_kind == "image":
        return "<b>Что создать по этому фото?</b>"
    if has_preview:
        return (
            "<b>Что создать по этому видео?</b>\n\n"
            "Для фото будет использована обложка видео; для видео — исходный ролик."
        )
    return (
        "<b>Что создать по этому видео?</b>\n\n"
        "Видео можно использовать как референс. Для создания фото отправьте нужный кадр отдельно."
    )


def _video_thumbnail(message: Message) -> PhotoSize | None:
    if message.video is not None:
        return message.video.thumbnail
    if message.animation is not None:
        return message.animation.thumbnail
    if message.document is not None:
        return message.document.thumbnail
    return None


def _stored_input(value: object) -> StoredInput | None:
    if not isinstance(value, dict):
        return None
    kind = value.get("kind")
    storage_key = value.get("storage_key")
    if not isinstance(kind, str) or not isinstance(storage_key, str):
        return None
    return {"kind": kind, "storage_key": storage_key}


def _required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(key)
    return value


async def _reset_broken_reference(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Референс устарел. Начните заново.", show_alert=True)
    if callback.message:
        await safe_edit_callback_message(
            callback,
            "Главное меню",
            main_menu(),
            answer_callback=False,
        )


async def _edit_callback(
    callback: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup,
) -> None:
    await safe_edit_callback_message(callback, text, reply_markup)
