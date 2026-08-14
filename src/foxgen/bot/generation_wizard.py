from __future__ import annotations

from html import escape
from typing import Any, TypedDict
from uuid import uuid4

from aiogram import Bot, F, Router
from aiogram.filters import Filter, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from foxgen.bot.api_client import FoxGenApiClient, FoxGenApiError
from foxgen.bot.callbacks import safe_edit_callback_message
from foxgen.bot.generation_capabilities import (
    IMAGE_MODELS,
    VIDEO_MODELS,
    ImageModelCapability,
    VideoGenerationType,
    VideoModelCapability,
    image_model,
    video_model,
)
from foxgen.bot.generation_keyboards import (
    image_model_keyboard,
    image_reference_keyboard,
    image_settings_keyboard,
    prompt_keyboard,
    video_media_keyboard,
    video_model_keyboard,
    video_settings_keyboard,
    video_type_keyboard,
)
from foxgen.bot.keyboards import after_submit_keyboard, confirmation_keyboard, main_menu
from foxgen.bot.states import GenerationStates
from foxgen.bot.uploads import TelegramInputMediaStorage, message_media_kind, stored_input_keys
from foxgen.core.errors import ErrorCode, SubmissionError


router = Router(name="foxgen-generation-wizard")
WIZARD_VERSION = "screen-v2"
MAX_VIDEO_REFERENCE_TOTAL = 6


class StoredInput(TypedDict):
    kind: str
    storage_key: str


class ResolvedInput(TypedDict):
    kind: str
    url: str


class WizardDraftFilter(Filter):
    async def __call__(self, state: FSMContext) -> bool:
        data = await state.get_data()
        return data.get("entrypoint") == "wizard" and data.get("wizard_version") == WIZARD_VERSION


WIZARD_DRAFT = WizardDraftFilter()


def default_image_flow_data(user_id: int) -> dict[str, object]:
    """Stable image draft shape, analogous to tanyapi's default image FSM data."""

    return {
        "entrypoint": "wizard",
        "wizard_version": WIZARD_VERSION,
        "generation_type": "image",
        "image_flow_step": "select_model",
        "image_model_key": "seedream-5-pro",
        "model_slug": "seedream-5-pro",
        "model_title": IMAGE_MODELS["seedream-5-pro"].title,
        "aspect_ratio": "1:1",
        "quality": "basic",
        "resolution": "1K",
        "output_format": "png",
        "media": [],
        "prompt": "",
        "can_submit": False,
        "idempotency_key": f"generation:{user_id}:{uuid4().hex}",
    }


def default_video_flow_data(user_id: int) -> dict[str, object]:
    """Stable video draft shape, analogous to tanyapi's default video FSM data."""

    return {
        "entrypoint": "wizard",
        "wizard_version": WIZARD_VERSION,
        "generation_type": "video",
        "video_flow_step": "select_model",
        "video_model_key": "seedance-2",
        "video_type": VideoGenerationType.TEXT.value,
        "model_slug": "seedance-2",
        "model_title": VIDEO_MODELS["seedance-2"].title,
        "aspect_ratio": "16:9",
        "duration": 5,
        "resolution": "720p",
        "generate_audio": False,
        "return_last_frame": False,
        "web_search": False,
        "media": [],
        "prompt": "",
        "can_submit": False,
        "idempotency_key": f"generation:{user_id}:{uuid4().hex}",
    }


@router.callback_query(F.data == "create:image")
async def start_image_wizard(
    callback: CallbackQuery,
    state: FSMContext,
    input_media: TelegramInputMediaStorage,
) -> None:
    await _reset_with_input_cleanup(state, input_media)
    await state.update_data(**default_image_flow_data(callback.from_user.id))
    await _show_image_model(callback, state)


@router.callback_query(F.data == "create:video")
async def start_video_wizard(
    callback: CallbackQuery,
    state: FSMContext,
    input_media: TelegramInputMediaStorage,
) -> None:
    await _reset_with_input_cleanup(state, input_media)
    await state.update_data(**default_video_flow_data(callback.from_user.id))
    await _show_video_model(callback, state)


@router.callback_query(
    GenerationStates.image_selecting_model,
    WIZARD_DRAFT,
    F.data.startswith("gw:i:model:"),
)
async def choose_image_model(callback: CallbackQuery, state: FSMContext) -> None:
    key = (callback.data or "").removeprefix("gw:i:model:")
    try:
        capability = image_model(key)
    except ValueError:
        await callback.answer("Эта модель недоступна.", show_alert=True)
        return
    data = await state.get_data()
    media = _stored_media(data)
    if len(media) > capability.max_references:
        await callback.answer(
            f"У новой модели лимит {capability.max_references} референсов. Сначала удалите лишние.",
            show_alert=True,
        )
        return
    await state.update_data(
        image_model_key=capability.key,
        model_slug=capability.text_slug,
        model_title=capability.title,
        aspect_ratio=capability.default_aspect_ratio,
        resolution=capability.default_resolution or "1K",
        quality=capability.default_quality or "basic",
        output_format=capability.default_output_format,
        image_flow_step="references",
        can_submit=False,
    )
    await _show_image_references(callback, state)


@router.message(
    GenerationStates.image_uploading_references,
    WIZARD_DRAFT,
    F.photo | F.document,
)
async def upload_image_reference(
    message: Message,
    state: FSMContext,
    bot: Bot,
    input_media: TelegramInputMediaStorage,
) -> None:
    data = await state.get_data()
    capability = _image_capability(data)
    media = _stored_media(data)
    if not capability.supports_references:
        await message.answer("Выбранная модель не принимает референсы.")
        return
    if len(media) >= capability.max_references:
        await message.answer(
            f"Лимит этой модели — {capability.max_references} референсов.",
            reply_markup=image_reference_keyboard(
                count=len(media),
                max_count=capability.max_references,
            ),
        )
        return
    try:
        kind = message_media_kind(message)
        if kind != "image":
            raise SubmissionError(ErrorCode.VALIDATION, "На этом экране нужен файл изображения.")
        uploaded = await input_media.upload(
            bot=bot,
            message=message,
            user_id=message.from_user.id if message.from_user else 0,
        )
    except SubmissionError as exc:
        await message.answer(exc.public_message)
        return
    media.append({"kind": uploaded.kind, "storage_key": uploaded.storage_key})
    await state.update_data(media=media, can_submit=False)
    await message.answer(
        f"Референс добавлен. Сейчас {len(media)} из {capability.max_references}.",
        reply_markup=image_reference_keyboard(
            count=len(media),
            max_count=capability.max_references,
        ),
    )


@router.callback_query(
    GenerationStates.image_uploading_references,
    WIZARD_DRAFT,
    F.data.in_({"gw:i:refs:skip", "gw:i:refs:done"}),
)
async def finish_image_references(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    capability = _image_capability(data)
    media = _stored_media(data)
    if capability.reference_mode.value == "required" and not media:
        await callback.answer("Для этой модели нужен хотя бы один референс.", show_alert=True)
        return
    await state.update_data(
        model_slug=capability.submission_slug(has_references=bool(media)),
        image_flow_step="settings",
        can_submit=False,
    )
    await _show_image_settings(callback, state)


@router.callback_query(
    GenerationStates.image_uploading_references,
    WIZARD_DRAFT,
    F.data == "gw:i:refs:clear",
)
async def clear_image_references(
    callback: CallbackQuery,
    state: FSMContext,
    input_media: TelegramInputMediaStorage,
) -> None:
    data = await state.get_data()
    await input_media.delete_many(tuple(item["storage_key"] for item in _stored_media(data)))
    await state.update_data(media=[], can_submit=False)
    await _show_image_references(callback, state)


@router.callback_query(
    GenerationStates.image_configuring,
    WIZARD_DRAFT,
    F.data.startswith("gw:i:ratio:"),
)
async def set_image_ratio(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    capability = _image_capability(data)
    value = (callback.data or "").removeprefix("gw:i:ratio:").replace("x", ":")
    if value not in capability.aspect_ratios:
        await callback.answer("Этот формат недоступен.", show_alert=True)
        return
    await state.update_data(aspect_ratio=value, can_submit=False)
    await _show_image_settings(callback, state)


@router.callback_query(
    GenerationStates.image_configuring,
    WIZARD_DRAFT,
    F.data.startswith("gw:i:resolution:"),
)
async def set_image_resolution(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    capability = _image_capability(data)
    value = (callback.data or "").removeprefix("gw:i:resolution:")
    if value not in capability.resolutions:
        await callback.answer("Это разрешение недоступно.", show_alert=True)
        return
    await state.update_data(resolution=value, can_submit=False)
    await _show_image_settings(callback, state)


@router.callback_query(
    GenerationStates.image_configuring,
    WIZARD_DRAFT,
    F.data.startswith("gw:i:quality:"),
)
async def set_image_quality(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    capability = _image_capability(data)
    value = (callback.data or "").removeprefix("gw:i:quality:")
    if value not in capability.qualities:
        await callback.answer("Это качество недоступно.", show_alert=True)
        return
    await state.update_data(quality=value, can_submit=False)
    await _show_image_settings(callback, state)


@router.callback_query(
    GenerationStates.image_configuring,
    WIZARD_DRAFT,
    F.data.startswith("gw:i:format:"),
)
async def set_image_format(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    capability = _image_capability(data)
    value = (callback.data or "").removeprefix("gw:i:format:")
    if value not in capability.output_formats:
        await callback.answer("Этот формат файла недоступен.", show_alert=True)
        return
    await state.update_data(output_format=value, can_submit=False)
    await _show_image_settings(callback, state)


@router.callback_query(
    GenerationStates.image_configuring,
    WIZARD_DRAFT,
    F.data == "gw:i:settings:done",
)
async def finish_image_settings(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(image_flow_step="prompt", can_submit=False)
    await _show_image_prompt(callback, state)


@router.message(GenerationStates.image_waiting_prompt, WIZARD_DRAFT, F.text)
async def receive_image_prompt(
    message: Message,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    prompt = _normalize_prompt(message.text)
    if prompt is None:
        await message.answer("Промпт должен содержать от 3 до 3500 символов.")
        return
    data = await state.get_data()
    capability = _image_capability(data)
    media = _stored_media(data)
    await state.update_data(
        prompt=prompt,
        model_slug=capability.submission_slug(has_references=bool(media)),
        image_flow_step="confirm",
        can_submit=False,
    )
    await state.set_state(GenerationStates.confirming)
    await _show_confirmation_message(message, state, api_client)


@router.callback_query(
    GenerationStates.video_selecting_model,
    WIZARD_DRAFT,
    F.data.startswith("gw:v:model:"),
)
async def choose_video_model(callback: CallbackQuery, state: FSMContext) -> None:
    key = (callback.data or "").removeprefix("gw:v:model:")
    try:
        capability = video_model(key)
    except ValueError:
        await callback.answer("Эта модель недоступна.", show_alert=True)
        return
    await state.update_data(
        video_model_key=capability.key,
        model_slug=capability.slug,
        model_title=capability.title,
        video_type=capability.generation_types[0].value,
        aspect_ratio=capability.default_aspect_ratio,
        duration=capability.default_duration,
        resolution=capability.default_resolution,
        generate_audio=False,
        return_last_frame=False,
        web_search=False,
        video_flow_step="select_type",
        can_submit=False,
    )
    await _show_video_type(callback, state)


@router.callback_query(
    GenerationStates.video_selecting_type,
    WIZARD_DRAFT,
    F.data.startswith("gw:v:type:"),
)
async def choose_video_type(
    callback: CallbackQuery,
    state: FSMContext,
    input_media: TelegramInputMediaStorage,
) -> None:
    raw = (callback.data or "").removeprefix("gw:v:type:")
    try:
        generation_type = VideoGenerationType(raw)
    except ValueError:
        await callback.answer("Неизвестный сценарий видео.", show_alert=True)
        return
    data = await state.get_data()
    capability = _video_capability(data)
    if not capability.supports_type(generation_type):
        await callback.answer("Эта модель не поддерживает выбранный сценарий.", show_alert=True)
        return
    media = _stored_media(data)
    if media:
        await input_media.delete_many(tuple(item["storage_key"] for item in media))
    await state.update_data(
        video_type=generation_type.value,
        media=[],
        can_submit=False,
    )
    if generation_type == VideoGenerationType.TEXT:
        await state.update_data(video_flow_step="settings")
        await _show_video_settings(callback, state)
        return
    await state.update_data(video_flow_step="media")
    await _show_video_media(callback, state)


@router.message(
    GenerationStates.video_uploading_media,
    WIZARD_DRAFT,
    F.photo | F.video | F.animation | F.audio | F.voice | F.document,
)
async def upload_video_media(
    message: Message,
    state: FSMContext,
    bot: Bot,
    input_media: TelegramInputMediaStorage,
) -> None:
    data = await state.get_data()
    capability = _video_capability(data)
    generation_type = _video_type(data)
    media = _stored_media(data)
    try:
        kind = message_media_kind(message)
        _validate_video_media(capability, generation_type, media, kind)
        uploaded = await input_media.upload(
            bot=bot,
            message=message,
            user_id=message.from_user.id if message.from_user else 0,
        )
    except SubmissionError as exc:
        await message.answer(exc.public_message)
        return
    media.append({"kind": uploaded.kind, "storage_key": uploaded.storage_key})
    await state.update_data(media=media, can_submit=False)
    can_continue = _video_media_complete(generation_type, media)
    await message.answer(
        _video_media_status(generation_type, media),
        reply_markup=video_media_keyboard(
            generation_type=generation_type,
            count=len(media),
            can_continue=can_continue,
        ),
    )


@router.callback_query(
    GenerationStates.video_uploading_media,
    WIZARD_DRAFT,
    F.data == "gw:v:media:done",
)
async def finish_video_media(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    generation_type = _video_type(data)
    media = _stored_media(data)
    if not _video_media_complete(generation_type, media):
        await callback.answer(_video_media_requirement(generation_type), show_alert=True)
        return
    await state.update_data(video_flow_step="settings", can_submit=False)
    await _show_video_settings(callback, state)


@router.callback_query(
    GenerationStates.video_uploading_media,
    WIZARD_DRAFT,
    F.data == "gw:v:media:clear",
)
async def clear_video_media(
    callback: CallbackQuery,
    state: FSMContext,
    input_media: TelegramInputMediaStorage,
) -> None:
    data = await state.get_data()
    await input_media.delete_many(tuple(item["storage_key"] for item in _stored_media(data)))
    await state.update_data(media=[], can_submit=False)
    await _show_video_media(callback, state)


@router.callback_query(
    GenerationStates.video_configuring,
    WIZARD_DRAFT,
    F.data.startswith("gw:v:ratio:"),
)
async def set_video_ratio(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    capability = _video_capability(data)
    value = (callback.data or "").removeprefix("gw:v:ratio:").replace("x", ":")
    if value not in capability.aspect_ratios:
        await callback.answer("Этот формат недоступен.", show_alert=True)
        return
    await state.update_data(aspect_ratio=value, can_submit=False)
    await _show_video_settings(callback, state)


@router.callback_query(
    GenerationStates.video_configuring,
    WIZARD_DRAFT,
    F.data.startswith("gw:v:duration:"),
)
async def set_video_duration(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    capability = _video_capability(data)
    raw = (callback.data or "").removeprefix("gw:v:duration:")
    try:
        value = int(raw)
    except ValueError:
        await callback.answer("Некорректная длительность.", show_alert=True)
        return
    if value not in capability.durations:
        await callback.answer("Эта длительность недоступна.", show_alert=True)
        return
    await state.update_data(duration=value, can_submit=False)
    await _show_video_settings(callback, state)


@router.callback_query(
    GenerationStates.video_configuring,
    WIZARD_DRAFT,
    F.data.startswith("gw:v:resolution:"),
)
async def set_video_resolution(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    capability = _video_capability(data)
    value = (callback.data or "").removeprefix("gw:v:resolution:")
    if value not in capability.resolutions:
        await callback.answer("Это разрешение недоступно.", show_alert=True)
        return
    await state.update_data(resolution=value, can_submit=False)
    await _show_video_settings(callback, state)


@router.callback_query(
    GenerationStates.video_configuring,
    WIZARD_DRAFT,
    F.data.in_({"gw:v:toggle:audio", "gw:v:toggle:last", "gw:v:toggle:web"}),
)
async def toggle_video_setting(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    capability = _video_capability(data)
    action = callback.data or ""
    if action == "gw:v:toggle:audio":
        if not capability.supports_generated_audio:
            await callback.answer("Генерация звука недоступна.", show_alert=True)
            return
        await state.update_data(generate_audio=not bool(data.get("generate_audio")), can_submit=False)
    elif action == "gw:v:toggle:last":
        if not capability.supports_return_last_frame:
            await callback.answer("Возврат последнего кадра недоступен.", show_alert=True)
            return
        await state.update_data(
            return_last_frame=not bool(data.get("return_last_frame")),
            can_submit=False,
        )
    else:
        if not capability.supports_web_search:
            await callback.answer("Web search недоступен.", show_alert=True)
            return
        await state.update_data(web_search=not bool(data.get("web_search")), can_submit=False)
    await _show_video_settings(callback, state)


@router.callback_query(
    GenerationStates.video_configuring,
    WIZARD_DRAFT,
    F.data == "gw:v:settings:done",
)
async def finish_video_settings(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(video_flow_step="prompt", can_submit=False)
    await _show_video_prompt(callback, state)


@router.message(GenerationStates.video_waiting_prompt, WIZARD_DRAFT, F.text)
async def receive_video_prompt(
    message: Message,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    prompt = _normalize_prompt(message.text)
    if prompt is None:
        await message.answer("Промпт должен содержать от 3 до 3500 символов.")
        return
    await state.update_data(prompt=prompt, video_flow_step="confirm", can_submit=False)
    await state.set_state(GenerationStates.confirming)
    await _show_confirmation_message(message, state, api_client)


@router.callback_query(GenerationStates.confirming, WIZARD_DRAFT, F.data == "draft:refresh")
async def refresh_wizard_confirmation(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    await _show_confirmation_callback(callback, state, api_client)


@router.callback_query(GenerationStates.confirming, WIZARD_DRAFT, F.data == "draft:edit")
async def edit_wizard_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("generation_type") == "image":
        await state.update_data(image_flow_step="prompt", can_submit=False)
        await _show_image_prompt(callback, state)
        return
    await state.update_data(video_flow_step="prompt", can_submit=False)
    await _show_video_prompt(callback, state)


@router.callback_query(GenerationStates.confirming, WIZARD_DRAFT, F.data == "draft:confirm")
async def confirm_wizard_generation(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
    input_media: TelegramInputMediaStorage,
) -> None:
    data = await state.get_data()
    if not bool(data.get("can_submit")):
        await callback.answer("Сначала обновите цену и баланс.", show_alert=True)
        return
    await state.set_state(GenerationStates.submitting)
    await safe_edit_callback_message(callback, "⏳ Ставлю генерацию в очередь…")
    try:
        resolved_media = await _resolve_media(data, input_media)
        model_slug, payload = _submission_payload(data, resolved_media)
        queued = await api_client.submit(
            user_id=callback.from_user.id,
            username=callback.from_user.username,
            model_slug=model_slug,
            input_data=payload,
            idempotency_key=_required_text(data, "idempotency_key"),
        )
    except (SubmissionError, FoxGenApiError) as exc:
        await state.set_state(GenerationStates.confirming)
        await state.update_data(can_submit=False)
        message = exc.public_message if isinstance(exc, SubmissionError) else exc.message
        await safe_edit_callback_message(
            callback,
            f"⚠️ {escape(message)}\n\nПараметры сохранены.",
            confirmation_keyboard(can_submit=False),
        )
        return
    await state.clear()
    replay = "\nПовторный запрос распознан — новая задача не создавалась." if queued.replayed else ""
    await safe_edit_callback_message(
        callback,
        (
            "✅ <b>Генерация поставлена в очередь</b>\n\n"
            f"ID: <code>{escape(queued.generation_id)}</code>\n"
            "Результат придёт сюда автоматически после сохранения."
            f"{replay}"
        ),
        after_submit_keyboard(),
    )


@router.callback_query(GenerationStates.submitting, WIZARD_DRAFT, F.data == "draft:confirm")
async def duplicate_wizard_confirmation(callback: CallbackQuery) -> None:
    await callback.answer("Генерация уже запускается.", show_alert=True)


@router.callback_query(WIZARD_DRAFT, F.data == "gw:back")
async def wizard_back(callback: CallbackQuery, state: FSMContext) -> None:
    current = await state.get_state()
    data = await state.get_data()
    if current == GenerationStates.image_selecting_model.state:
        await state.clear()
        await safe_edit_callback_message(callback, "Что создаём?", main_menu())
        return
    if current == GenerationStates.image_uploading_references.state:
        await _show_image_model(callback, state)
        return
    if current == GenerationStates.image_configuring.state:
        await _show_image_references(callback, state)
        return
    if current == GenerationStates.image_waiting_prompt.state:
        await _show_image_settings(callback, state)
        return
    if current == GenerationStates.video_selecting_model.state:
        await state.clear()
        await safe_edit_callback_message(callback, "Что создаём?", main_menu())
        return
    if current == GenerationStates.video_selecting_type.state:
        await _show_video_model(callback, state)
        return
    if current == GenerationStates.video_uploading_media.state:
        await _show_video_type(callback, state)
        return
    if current == GenerationStates.video_configuring.state:
        if _video_type(data) == VideoGenerationType.TEXT:
            await _show_video_type(callback, state)
        else:
            await _show_video_media(callback, state)
        return
    if current == GenerationStates.video_waiting_prompt.state:
        await _show_video_settings(callback, state)
        return
    await callback.answer("На этом шаге вернуться назад нельзя.", show_alert=True)


@router.callback_query(GenerationStates.confirming, WIZARD_DRAFT, F.data == "nav:back")
async def back_from_wizard_confirmation(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("generation_type") == "image":
        await _show_image_prompt(callback, state)
        return
    await _show_video_prompt(callback, state)


WIZARD_BUTTON_STATES = (
    GenerationStates.image_selecting_model,
    GenerationStates.image_configuring,
    GenerationStates.video_selecting_model,
    GenerationStates.video_selecting_type,
    GenerationStates.video_configuring,
    GenerationStates.confirming,
)


@router.message(StateFilter(*WIZARD_BUTTON_STATES), WIZARD_DRAFT)
async def wizard_button_screen_invalid_message(message: Message) -> None:
    await message.answer("На этом экране выберите вариант кнопкой. /start полностью сбросит черновик.")


@router.message(GenerationStates.image_uploading_references, WIZARD_DRAFT)
async def invalid_image_reference(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    capability = _image_capability(data)
    await message.answer(
        "Отправьте изображение или используйте кнопки ниже.",
        reply_markup=image_reference_keyboard(
            count=len(_stored_media(data)),
            max_count=capability.max_references,
        ),
    )


@router.message(GenerationStates.video_uploading_media, WIZARD_DRAFT)
async def invalid_video_media(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    generation_type = _video_type(data)
    media = _stored_media(data)
    await message.answer(
        _video_media_requirement(generation_type),
        reply_markup=video_media_keyboard(
            generation_type=generation_type,
            count=len(media),
            can_continue=_video_media_complete(generation_type, media),
        ),
    )


@router.message(
    StateFilter(GenerationStates.image_waiting_prompt, GenerationStates.video_waiting_prompt),
    WIZARD_DRAFT,
)
async def invalid_wizard_prompt(message: Message) -> None:
    await message.answer(
        "На этом шаге нужен текстовый промпт. /start полностью сбросит черновик.",
        reply_markup=prompt_keyboard(),
    )


async def _show_image_model(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(image_flow_step="select_model", can_submit=False)
    await state.set_state(GenerationStates.image_selecting_model)
    await safe_edit_callback_message(
        callback,
        "<b>Создать фото · 1/4</b>\n\nВыберите модель. Дальше можно добавить референсы.",
        image_model_keyboard(str(data.get("image_model_key") or "")),
    )


async def _show_image_references(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    capability = _image_capability(data)
    media = _stored_media(data)
    await state.update_data(image_flow_step="references", can_submit=False)
    await state.set_state(GenerationStates.image_uploading_references)
    await safe_edit_callback_message(
        callback,
        (
            "<b>Создать фото · 2/4</b>\n\n"
            f"{escape(capability.title)} принимает до {capability.max_references} референсов. "
            "Отправляйте изображения по одному или пропустите шаг."
        ),
        image_reference_keyboard(count=len(media), max_count=capability.max_references),
    )


async def _show_image_settings(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    capability = _image_capability(data)
    await state.update_data(image_flow_step="settings", can_submit=False)
    await state.set_state(GenerationStates.image_configuring)
    await safe_edit_callback_message(
        callback,
        _image_settings_text(capability, data),
        image_settings_keyboard(capability, data),
    )


async def _show_image_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(image_flow_step="prompt", can_submit=False)
    await state.set_state(GenerationStates.image_waiting_prompt)
    await safe_edit_callback_message(
        callback,
        (
            "<b>Создать фото · 4/4</b>\n\n"
            "Опишите результат обычными словами: сюжет, стиль, свет, композицию и важные ограничения."
        ),
        prompt_keyboard(),
    )


async def _show_video_model(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(video_flow_step="select_model", can_submit=False)
    await state.set_state(GenerationStates.video_selecting_model)
    await safe_edit_callback_message(
        callback,
        "<b>Создать видео · 1/5</b>\n\nВыберите модель:",
        video_model_keyboard(str(data.get("video_model_key") or "")),
    )


async def _show_video_type(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    capability = _video_capability(data)
    try:
        current = _video_type(data)
    except SubmissionError:
        current = None
    await state.update_data(video_flow_step="select_type", can_submit=False)
    await state.set_state(GenerationStates.video_selecting_type)
    await safe_edit_callback_message(
        callback,
        "<b>Создать видео · 2/5</b>\n\nЧто используем как вход?",
        video_type_keyboard(capability, current),
    )


async def _show_video_media(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    generation_type = _video_type(data)
    media = _stored_media(data)
    await state.update_data(video_flow_step="media", can_submit=False)
    await state.set_state(GenerationStates.video_uploading_media)
    await safe_edit_callback_message(
        callback,
        f"<b>Создать видео · 3/5</b>\n\n{escape(_video_media_requirement(generation_type))}",
        video_media_keyboard(
            generation_type=generation_type,
            count=len(media),
            can_continue=_video_media_complete(generation_type, media),
        ),
    )


async def _show_video_settings(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    capability = _video_capability(data)
    await state.update_data(video_flow_step="settings", can_submit=False)
    await state.set_state(GenerationStates.video_configuring)
    await safe_edit_callback_message(
        callback,
        _video_settings_text(capability, data),
        video_settings_keyboard(capability, data),
    )


async def _show_video_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(video_flow_step="prompt", can_submit=False)
    await state.set_state(GenerationStates.video_waiting_prompt)
    await safe_edit_callback_message(
        callback,
        (
            "<b>Создать видео · 5/5</b>\n\n"
            "Опишите сцену, движение камеры/объектов, темп, свет, звук и ограничения."
        ),
        prompt_keyboard(),
    )


async def _show_confirmation_callback(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    text, can_submit = await _confirmation_text(state, api_client, callback.from_user.id)
    await safe_edit_callback_message(
        callback,
        text,
        confirmation_keyboard(can_submit=can_submit),
    )


async def _show_confirmation_message(
    message: Message,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    user_id = message.from_user.id if message.from_user else 0
    text, can_submit = await _confirmation_text(state, api_client, user_id)
    await message.answer(text, reply_markup=confirmation_keyboard(can_submit=can_submit))


async def _confirmation_text(
    state: FSMContext,
    api_client: FoxGenApiClient,
    user_id: int,
) -> tuple[str, bool]:
    data = await state.get_data()
    model_slug, _ = _submission_payload(data, [])
    try:
        prices = await api_client.prices()
        quote = prices.get(model_slug)
        balance = await api_client.balance(user_id)
    except FoxGenApiError as exc:
        await state.update_data(can_submit=False)
        return f"⚠️ {escape(exc.message)}\n\nПараметры сохранены.", False
    if quote is None:
        await state.update_data(can_submit=False)
        return "⚠️ Для выбранной модели пока не опубликована цена. Запуск заблокирован.", False
    enough = balance.available_units >= quote.amount_units
    await state.update_data(
        model_slug=model_slug,
        price_units=quote.amount_units,
        currency=quote.currency,
        price_version=quote.version,
        can_submit=enough,
    )
    balance_line = (
        f"Доступно: {balance.available_units} {escape(balance.currency)}"
        if enough
        else f"⚠️ Доступно только {balance.available_units} {escape(balance.currency)}"
    )
    return (
        "<b>Проверьте генерацию</b>\n\n"
        f"{_wizard_summary(data)}\n\n"
        f"Промпт: {escape(_required_text(data, 'prompt'))}\n\n"
        f"Стоимость: <b>{quote.amount_units} {escape(quote.currency)}</b>\n"
        f"{balance_line}\n\n"
        "Средства резервируются атомарно при постановке в очередь.",
        enough,
    )


def _submission_payload(
    data: dict[str, Any],
    media: list[ResolvedInput],
) -> tuple[str, dict[str, object]]:
    generation_type = _required_text(data, "generation_type")
    prompt = _required_text(data, "prompt") if data.get("prompt") else "preview"
    if generation_type == "image":
        capability = _image_capability(data)
        has_references = bool(_stored_media(data))
        slug = capability.submission_slug(has_references=has_references)
        if slug.startswith("seedream-5-pro"):
            payload: dict[str, object] = {
                "prompt": prompt,
                "aspect_ratio": _required_text(data, "aspect_ratio"),
                "quality": str(data.get("quality") or capability.default_quality or "basic"),
                "output_format": str(data.get("output_format") or capability.default_output_format),
                "nsfw_checker": False,
            }
            if has_references:
                payload["image_urls"] = [item["url"] for item in media if item["kind"] == "image"]
            return slug, payload
        return slug, {
            "prompt": prompt,
            "image_input": [item["url"] for item in media if item["kind"] == "image"],
            "aspect_ratio": _required_text(data, "aspect_ratio"),
            "resolution": str(data.get("resolution") or capability.default_resolution or "1K"),
            "output_format": str(data.get("output_format") or capability.default_output_format),
        }

    capability = _video_capability(data)
    video_type = _video_type(data)
    payload = {
        "prompt": prompt,
        "return_last_frame": bool(data.get("return_last_frame")),
        "generate_audio": bool(data.get("generate_audio")),
        "resolution": str(data.get("resolution") or capability.default_resolution),
        "aspect_ratio": _required_text(data, "aspect_ratio"),
        "duration": int(data.get("duration") or capability.default_duration),
        "web_search": bool(data.get("web_search")),
    }
    if video_type == VideoGenerationType.FIRST_FRAME:
        images = [item["url"] for item in media if item["kind"] == "image"]
        if len(images) != 1:
            raise SubmissionError(ErrorCode.VALIDATION, "Нужен ровно один первый кадр.")
        payload["first_frame_url"] = images[0]
    elif video_type == VideoGenerationType.FIRST_LAST:
        images = [item["url"] for item in media if item["kind"] == "image"]
        if len(images) != 2:
            raise SubmissionError(ErrorCode.VALIDATION, "Нужны первый и последний кадр.")
        payload["first_frame_url"] = images[0]
        payload["last_frame_url"] = images[1]
    elif video_type == VideoGenerationType.REFERENCES:
        payload["reference_image_urls"] = [item["url"] for item in media if item["kind"] == "image"]
        payload["reference_video_urls"] = [item["url"] for item in media if item["kind"] == "video"]
        payload["reference_audio_urls"] = [item["url"] for item in media if item["kind"] == "audio"]
    return capability.slug, payload


async def _resolve_media(
    data: dict[str, Any],
    input_media: TelegramInputMediaStorage,
) -> list[ResolvedInput]:
    return [
        {
            "kind": item["kind"],
            "url": await input_media.presign(item["storage_key"]),
        }
        for item in _stored_media(data)
    ]


def _image_settings_text(
    capability: ImageModelCapability,
    data: dict[str, object],
) -> str:
    media_count = len(_stored_media(data))
    lines = [
        "<b>Создать фото · 3/4</b>",
        "",
        f"Модель: <b>{escape(capability.title)}</b>",
        f"Референсы: {media_count}",
        f"Формат: {escape(str(data.get('aspect_ratio') or capability.default_aspect_ratio))}",
    ]
    if capability.resolutions:
        lines.append(f"Разрешение: {escape(str(data.get('resolution') or capability.default_resolution))}")
    if capability.qualities:
        lines.append(f"Качество: {escape(str(data.get('quality') or capability.default_quality))}")
    lines.append(f"Файл: {escape(str(data.get('output_format') or capability.default_output_format)).upper()}")
    lines.extend(("", "Настройки меняются на этом же экране — без лишних переходов."))
    return "\n".join(lines)


def _video_settings_text(
    capability: VideoModelCapability,
    data: dict[str, object],
) -> str:
    return (
        "<b>Создать видео · 4/5</b>\n\n"
        f"Модель: <b>{escape(capability.title)}</b>\n"
        f"Тип: {escape(_video_type(data).value)}\n"
        f"Формат: {escape(str(data.get('aspect_ratio') or capability.default_aspect_ratio))}\n"
        f"Длительность: {int(data.get('duration') or capability.default_duration)} сек.\n"
        f"Разрешение: {escape(str(data.get('resolution') or capability.default_resolution))}\n"
        f"Звук: {'да' if bool(data.get('generate_audio')) else 'нет'}\n"
        f"Вернуть последний кадр: {'да' if bool(data.get('return_last_frame')) else 'нет'}\n"
        f"Web search: {'да' if bool(data.get('web_search')) else 'нет'}\n\n"
        "Настройки меняются на этом же экране."
    )


def _wizard_summary(data: dict[str, object]) -> str:
    if data.get("generation_type") == "image":
        capability = _image_capability(data)
        details = [
            f"Модель: <b>{escape(capability.title)}</b>",
            f"Референсы: {len(_stored_media(data))}",
            f"Формат: {escape(_required_text(data, 'aspect_ratio'))}",
        ]
        if capability.resolutions:
            details.append(f"Разрешение: {escape(str(data.get('resolution') or '1K'))}")
        if capability.qualities:
            details.append(f"Качество: {escape(str(data.get('quality') or 'basic'))}")
        details.append(f"Файл: {escape(str(data.get('output_format') or 'png')).upper()}")
        return "\n".join(details)
    capability = _video_capability(data)
    return (
        f"Модель: <b>{escape(capability.title)}</b>\n"
        f"Тип: {escape(_video_type(data).value)}\n"
        f"Медиа: {len(_stored_media(data))}\n"
        f"Формат: {escape(_required_text(data, 'aspect_ratio'))}\n"
        f"Длительность: {int(data.get('duration') or capability.default_duration)} сек.\n"
        f"Звук: {'да' if bool(data.get('generate_audio')) else 'нет'}"
    )


def _validate_video_media(
    capability: VideoModelCapability,
    generation_type: VideoGenerationType,
    media: list[StoredInput],
    kind: str,
) -> None:
    if generation_type in {VideoGenerationType.FIRST_FRAME, VideoGenerationType.FIRST_LAST}:
        if kind != "image":
            raise SubmissionError(ErrorCode.VALIDATION, "Для кадров отправьте изображение.")
        limit = 1 if generation_type == VideoGenerationType.FIRST_FRAME else 2
        if len(media) >= limit:
            raise SubmissionError(ErrorCode.VALIDATION, f"Для этого сценария нужно не больше {limit} изображений.")
        return
    if generation_type != VideoGenerationType.REFERENCES:
        raise SubmissionError(ErrorCode.VALIDATION, "Для текстового сценария медиа не требуется.")
    if len(media) >= MAX_VIDEO_REFERENCE_TOTAL:
        raise SubmissionError(ErrorCode.VALIDATION, "Можно добавить не больше шести референсов суммарно.")
    counts = _media_counts(media)
    limits = {
        "image": capability.max_reference_images,
        "video": capability.max_reference_videos,
        "audio": capability.max_reference_audio,
    }
    if kind not in limits or limits[kind] <= 0:
        raise SubmissionError(ErrorCode.VALIDATION, "Этот тип референса модель не поддерживает.")
    if counts.get(kind, 0) >= limits[kind]:
        raise SubmissionError(ErrorCode.VALIDATION, f"Лимит референсов типа {kind}: {limits[kind]}.")


def _video_media_complete(
    generation_type: VideoGenerationType,
    media: list[StoredInput],
) -> bool:
    if generation_type == VideoGenerationType.FIRST_FRAME:
        return len(media) == 1 and all(item["kind"] == "image" for item in media)
    if generation_type == VideoGenerationType.FIRST_LAST:
        return len(media) == 2 and all(item["kind"] == "image" for item in media)
    if generation_type == VideoGenerationType.REFERENCES:
        return bool(media)
    return True


def _video_media_requirement(generation_type: VideoGenerationType) -> str:
    if generation_type == VideoGenerationType.FIRST_FRAME:
        return "Отправьте одно изображение — первый кадр видео."
    if generation_type == VideoGenerationType.FIRST_LAST:
        return "Отправьте два изображения по порядку: сначала первый кадр, затем последний."
    if generation_type == VideoGenerationType.REFERENCES:
        return "Отправляйте изображения, видео или аудио по одному. Суммарно — до шести файлов."
    return "Для текстового сценария медиа не требуется."


def _video_media_status(
    generation_type: VideoGenerationType,
    media: list[StoredInput],
) -> str:
    if generation_type == VideoGenerationType.FIRST_FRAME:
        return "Первый кадр сохранён. Можно продолжать."
    if generation_type == VideoGenerationType.FIRST_LAST:
        return f"Сохранено кадров: {len(media)}/2."
    counts = _media_counts(media)
    return (
        f"Референсы: {len(media)}/{MAX_VIDEO_REFERENCE_TOTAL} · "
        f"фото {counts.get('image', 0)}, видео {counts.get('video', 0)}, аудио {counts.get('audio', 0)}."
    )


def _media_counts(media: list[StoredInput]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in media:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    return counts


def _stored_media(data: dict[str, Any] | dict[str, object]) -> list[StoredInput]:
    raw = data.get("media")
    if not isinstance(raw, list):
        return []
    result: list[StoredInput] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        storage_key = item.get("storage_key")
        if isinstance(kind, str) and isinstance(storage_key, str):
            result.append({"kind": kind, "storage_key": storage_key})
    return result


def _image_capability(data: dict[str, Any] | dict[str, object]) -> ImageModelCapability:
    key = str(data.get("image_model_key") or "")
    try:
        return image_model(key)
    except ValueError as exc:
        raise SubmissionError(
            ErrorCode.VALIDATION,
            "Черновик фото устарел. Откройте /start и начните заново.",
        ) from exc


def _video_capability(data: dict[str, Any] | dict[str, object]) -> VideoModelCapability:
    key = str(data.get("video_model_key") or "")
    try:
        return video_model(key)
    except ValueError as exc:
        raise SubmissionError(
            ErrorCode.VALIDATION,
            "Черновик видео устарел. Откройте /start и начните заново.",
        ) from exc


def _video_type(data: dict[str, Any] | dict[str, object]) -> VideoGenerationType:
    try:
        return VideoGenerationType(str(data.get("video_type") or ""))
    except ValueError as exc:
        raise SubmissionError(
            ErrorCode.VALIDATION,
            "Тип видео потерян. Откройте /start и начните заново.",
        ) from exc


def _normalize_prompt(value: str | None) -> str | None:
    prompt = (value or "").strip()
    if not 3 <= len(prompt) <= 3500:
        return None
    return prompt


def _required_text(data: dict[str, Any] | dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise SubmissionError(
            ErrorCode.VALIDATION,
            "Черновик генерации повреждён. Откройте /start и начните заново.",
            details={"missing_field": key},
        )
    return value


async def _reset_with_input_cleanup(
    state: FSMContext,
    input_media: TelegramInputMediaStorage,
) -> None:
    data = await state.get_data()
    await input_media.delete_many(stored_input_keys(data))
    await state.clear()
