from __future__ import annotations

from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Filter, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from foxgen.bot.api_client import FoxGenApiClient, FoxGenApiError
from foxgen.bot.callbacks import safe_edit_callback_message
from foxgen.bot.generation_capabilities import VideoGenerationType, image_model, video_model
from foxgen.bot.generation_draft import (
    WIZARD_VERSION,
    ResolvedInput,
    StoredInput,
    default_image_flow_data,
    default_video_flow_data,
    image_capability,
    normalize_prompt,
    required_text,
    stored_media,
    submission_payload,
    validate_video_media,
    video_capability,
    video_media_complete,
    video_media_requirement,
    video_media_status,
    video_type,
)
from foxgen.bot.generation_keyboards import (
    image_reference_keyboard,
    prompt_keyboard,
    video_media_keyboard,
)
from foxgen.bot.generation_screens import (
    render_confirmation_callback,
    render_confirmation_message,
    render_image_model,
    render_image_prompt,
    render_image_references,
    render_image_settings,
    render_video_media,
    render_video_model,
    render_video_prompt,
    render_video_settings,
    render_video_type,
)
from foxgen.bot.keyboards import after_submit_keyboard, confirmation_keyboard, main_menu
from foxgen.bot.states import GenerationStates
from foxgen.bot.uploads import TelegramInputMediaStorage, message_media_kind, stored_input_keys
from foxgen.core.errors import ErrorCode, SubmissionError


router = Router(name="foxgen-generation-wizard")


class WizardDraftFilter(Filter):
    async def __call__(self, state: FSMContext) -> bool:
        data = await state.get_data()
        return data.get("entrypoint") == "wizard" and data.get("wizard_version") == WIZARD_VERSION


WIZARD_DRAFT = WizardDraftFilter()


@router.callback_query(F.data == "create:image")
async def start_image_wizard(
    callback: CallbackQuery,
    state: FSMContext,
    input_media: TelegramInputMediaStorage,
) -> None:
    await _reset_with_input_cleanup(state, input_media)
    await state.update_data(**default_image_flow_data(callback.from_user.id))
    await render_image_model(callback, state)


@router.callback_query(F.data == "create:video")
async def start_video_wizard(
    callback: CallbackQuery,
    state: FSMContext,
    input_media: TelegramInputMediaStorage,
) -> None:
    await _reset_with_input_cleanup(state, input_media)
    await state.update_data(**default_video_flow_data(callback.from_user.id))
    await render_video_model(callback, state)


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
    media = stored_media(data)
    if len(media) > capability.max_references:
        await callback.answer(
            f"У этой модели лимит {capability.max_references} референсов. Сначала удалите лишние.",
            show_alert=True,
        )
        return
    await state.update_data(
        image_model_key=capability.key,
        model_slug=capability.submission_slug(has_references=bool(media)),
        model_title=capability.title,
        aspect_ratio=capability.default_aspect_ratio,
        resolution=capability.default_resolution or "1K",
        quality=capability.default_quality or "basic",
        output_format=capability.default_output_format,
        can_submit=False,
    )
    await render_image_references(callback, state)


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
    capability = image_capability(data)
    media = stored_media(data)
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
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "На этом экране нужен файл изображения.",
            )
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
    capability = image_capability(data)
    media = stored_media(data)
    await state.update_data(
        model_slug=capability.submission_slug(has_references=bool(media)),
        can_submit=False,
    )
    await render_image_settings(callback, state)


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
    await input_media.delete_many(tuple(item["storage_key"] for item in stored_media(data)))
    await state.update_data(media=[], can_submit=False)
    await render_image_references(callback, state)


@router.callback_query(
    GenerationStates.image_configuring,
    WIZARD_DRAFT,
    F.data.startswith("gw:i:"),
)
async def update_image_setting(callback: CallbackQuery, state: FSMContext) -> None:
    action = callback.data or ""
    data = await state.get_data()
    capability = image_capability(data)

    if action == "gw:i:settings:done":
        await render_image_prompt(callback, state)
        return
    if action.startswith("gw:i:ratio:"):
        value = action.removeprefix("gw:i:ratio:").replace("x", ":")
        if value not in capability.aspect_ratios:
            await callback.answer("Этот формат недоступен.", show_alert=True)
            return
        await state.update_data(aspect_ratio=value, can_submit=False)
    elif action.startswith("gw:i:resolution:"):
        value = action.removeprefix("gw:i:resolution:")
        if value not in capability.resolutions:
            await callback.answer("Это разрешение недоступно.", show_alert=True)
            return
        await state.update_data(resolution=value, can_submit=False)
    elif action.startswith("gw:i:quality:"):
        value = action.removeprefix("gw:i:quality:")
        if value not in capability.qualities:
            await callback.answer("Это качество недоступно.", show_alert=True)
            return
        await state.update_data(quality=value, can_submit=False)
    elif action.startswith("gw:i:format:"):
        value = action.removeprefix("gw:i:format:")
        if value not in capability.output_formats:
            await callback.answer("Этот формат файла недоступен.", show_alert=True)
            return
        await state.update_data(output_format=value, can_submit=False)
    else:
        await callback.answer("Неизвестная настройка.", show_alert=True)
        return
    await render_image_settings(callback, state)


@router.message(GenerationStates.image_waiting_prompt, WIZARD_DRAFT, F.text)
async def receive_image_prompt(
    message: Message,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    prompt = normalize_prompt(message.text)
    if prompt is None:
        await message.answer("Промпт должен содержать от 3 до 3500 символов.")
        return
    data = await state.get_data()
    capability = image_capability(data)
    await state.update_data(
        prompt=prompt,
        model_slug=capability.submission_slug(has_references=bool(stored_media(data))),
        image_flow_step="confirm",
        can_submit=False,
    )
    await state.set_state(GenerationStates.confirming)
    await render_confirmation_message(message, state, api_client)


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

    data = await state.get_data()
    preferred_type = _compatible_video_type(capability, data)
    await state.update_data(
        video_model_key=capability.key,
        model_slug=capability.slug,
        model_title=capability.title,
        video_type=preferred_type.value,
        aspect_ratio=capability.default_aspect_ratio,
        duration=capability.default_duration,
        resolution=capability.default_resolution,
        generate_audio=False,
        return_last_frame=False,
        web_search=False,
        can_submit=False,
    )
    await render_video_type(callback, state)


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
        selected_type = VideoGenerationType(raw)
    except ValueError:
        await callback.answer("Неизвестный сценарий видео.", show_alert=True)
        return

    data = await state.get_data()
    capability = video_capability(data)
    if not capability.supports_type(selected_type):
        await callback.answer("Эта модель не поддерживает выбранный сценарий.", show_alert=True)
        return

    media = stored_media(data)
    if media and not _media_compatible_with_video_type(capability, selected_type, media):
        await input_media.delete_many(tuple(item["storage_key"] for item in media))
        media = []
    await state.update_data(
        video_type=selected_type.value,
        media=media,
        can_submit=False,
    )
    if selected_type == VideoGenerationType.TEXT:
        await render_video_settings(callback, state)
        return
    await render_video_media(callback, state)


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
    capability = video_capability(data)
    selected_type = video_type(data)
    media = stored_media(data)
    try:
        kind = message_media_kind(message)
        validate_video_media(capability, selected_type, media, kind)
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
        video_media_status(selected_type, media),
        reply_markup=video_media_keyboard(
            generation_type=selected_type,
            count=len(media),
            can_continue=video_media_complete(selected_type, media),
        ),
    )


@router.callback_query(
    GenerationStates.video_uploading_media,
    WIZARD_DRAFT,
    F.data == "gw:v:media:done",
)
async def finish_video_media(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    selected_type = video_type(data)
    media = stored_media(data)
    if not video_media_complete(selected_type, media):
        await callback.answer(video_media_requirement(selected_type), show_alert=True)
        return
    await render_video_settings(callback, state)


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
    await input_media.delete_many(tuple(item["storage_key"] for item in stored_media(data)))
    await state.update_data(media=[], can_submit=False)
    await render_video_media(callback, state)


@router.callback_query(
    GenerationStates.video_configuring,
    WIZARD_DRAFT,
    F.data.startswith("gw:v:"),
)
async def update_video_setting(callback: CallbackQuery, state: FSMContext) -> None:
    action = callback.data or ""
    data = await state.get_data()
    capability = video_capability(data)

    if action == "gw:v:settings:done":
        await render_video_prompt(callback, state)
        return
    if action.startswith("gw:v:ratio:"):
        value = action.removeprefix("gw:v:ratio:").replace("x", ":")
        if value not in capability.aspect_ratios:
            await callback.answer("Этот формат недоступен.", show_alert=True)
            return
        await state.update_data(aspect_ratio=value, can_submit=False)
    elif action.startswith("gw:v:duration:"):
        raw = action.removeprefix("gw:v:duration:")
        try:
            value = int(raw)
        except ValueError:
            await callback.answer("Некорректная длительность.", show_alert=True)
            return
        if value not in capability.durations:
            await callback.answer("Эта длительность недоступна.", show_alert=True)
            return
        await state.update_data(duration=value, can_submit=False)
    elif action.startswith("gw:v:resolution:"):
        value = action.removeprefix("gw:v:resolution:")
        if value not in capability.resolutions:
            await callback.answer("Это разрешение недоступно.", show_alert=True)
            return
        await state.update_data(resolution=value, can_submit=False)
    elif action == "gw:v:toggle:audio":
        if not capability.supports_generated_audio:
            await callback.answer("Генерация звука недоступна.", show_alert=True)
            return
        await state.update_data(
            generate_audio=not bool(data.get("generate_audio")),
            can_submit=False,
        )
    elif action == "gw:v:toggle:last":
        if not capability.supports_return_last_frame:
            await callback.answer("Возврат последнего кадра недоступен.", show_alert=True)
            return
        await state.update_data(
            return_last_frame=not bool(data.get("return_last_frame")),
            can_submit=False,
        )
    elif action == "gw:v:toggle:web":
        if not capability.supports_web_search:
            await callback.answer("Web search недоступен.", show_alert=True)
            return
        await state.update_data(
            web_search=not bool(data.get("web_search")),
            can_submit=False,
        )
    else:
        await callback.answer("Неизвестная настройка.", show_alert=True)
        return
    await render_video_settings(callback, state)


@router.message(GenerationStates.video_waiting_prompt, WIZARD_DRAFT, F.text)
async def receive_video_prompt(
    message: Message,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    prompt = normalize_prompt(message.text)
    if prompt is None:
        await message.answer("Промпт должен содержать от 3 до 3500 символов.")
        return
    await state.update_data(
        prompt=prompt,
        video_flow_step="confirm",
        can_submit=False,
    )
    await state.set_state(GenerationStates.confirming)
    await render_confirmation_message(message, state, api_client)


@router.callback_query(
    GenerationStates.confirming,
    WIZARD_DRAFT,
    F.data == "draft:refresh",
)
async def refresh_wizard_confirmation(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    await render_confirmation_callback(callback, state, api_client)


@router.callback_query(
    GenerationStates.confirming,
    WIZARD_DRAFT,
    F.data == "draft:edit",
)
async def edit_wizard_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("generation_type") == "image":
        await render_image_prompt(callback, state)
        return
    await render_video_prompt(callback, state)


@router.callback_query(
    GenerationStates.confirming,
    WIZARD_DRAFT,
    F.data == "draft:confirm",
)
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
        model_slug, payload = submission_payload(data, resolved_media)
        queued = await api_client.submit(
            user_id=callback.from_user.id,
            username=callback.from_user.username,
            model_slug=model_slug,
            input_data=payload,
            idempotency_key=required_text(data, "idempotency_key"),
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
    replay = (
        "\nПовторный запрос распознан — новая задача не создавалась."
        if queued.replayed
        else ""
    )
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


@router.callback_query(
    GenerationStates.submitting,
    WIZARD_DRAFT,
    F.data == "draft:confirm",
)
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
        await render_image_model(callback, state)
        return
    if current == GenerationStates.image_configuring.state:
        await render_image_references(callback, state)
        return
    if current == GenerationStates.image_waiting_prompt.state:
        await render_image_settings(callback, state)
        return
    if current == GenerationStates.video_selecting_model.state:
        await state.clear()
        await safe_edit_callback_message(callback, "Что создаём?", main_menu())
        return
    if current == GenerationStates.video_selecting_type.state:
        await render_video_model(callback, state)
        return
    if current == GenerationStates.video_uploading_media.state:
        await render_video_type(callback, state)
        return
    if current == GenerationStates.video_configuring.state:
        if video_type(data) == VideoGenerationType.TEXT:
            await render_video_type(callback, state)
        else:
            await render_video_media(callback, state)
        return
    if current == GenerationStates.video_waiting_prompt.state:
        await render_video_settings(callback, state)
        return
    await callback.answer("На этом шаге вернуться назад нельзя.", show_alert=True)


@router.callback_query(
    GenerationStates.confirming,
    WIZARD_DRAFT,
    F.data == "nav:back",
)
async def back_from_wizard_confirmation(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("generation_type") == "image":
        await render_image_prompt(callback, state)
        return
    await render_video_prompt(callback, state)


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
    await message.answer(
        "На этом экране выберите вариант кнопкой. /start полностью сбросит черновик."
    )


@router.message(GenerationStates.image_uploading_references, WIZARD_DRAFT)
async def invalid_image_reference(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    capability = image_capability(data)
    await message.answer(
        "Отправьте изображение или используйте кнопки ниже.",
        reply_markup=image_reference_keyboard(
            count=len(stored_media(data)),
            max_count=capability.max_references,
        ),
    )


@router.message(GenerationStates.video_uploading_media, WIZARD_DRAFT)
async def invalid_video_media(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    selected_type = video_type(data)
    media = stored_media(data)
    await message.answer(
        video_media_requirement(selected_type),
        reply_markup=video_media_keyboard(
            generation_type=selected_type,
            count=len(media),
            can_continue=video_media_complete(selected_type, media),
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


async def _resolve_media(
    data: dict[str, object],
    input_media: TelegramInputMediaStorage,
) -> list[ResolvedInput]:
    return [
        {
            "kind": item["kind"],
            "url": await input_media.presign(item["storage_key"]),
        }
        for item in stored_media(data)
    ]


def _compatible_video_type(capability: object, data: dict[str, object]) -> VideoGenerationType:
    candidate: VideoGenerationType
    try:
        candidate = video_type(data)
    except SubmissionError:
        candidate = VideoGenerationType.TEXT
    if hasattr(capability, "supports_type") and capability.supports_type(candidate):
        return candidate
    return capability.generation_types[0]


def _media_compatible_with_video_type(
    capability: object,
    selected_type: VideoGenerationType,
    media: list[StoredInput],
) -> bool:
    if selected_type == VideoGenerationType.TEXT:
        return not media
    if selected_type == VideoGenerationType.FIRST_FRAME:
        return len(media) <= 1 and all(item["kind"] == "image" for item in media)
    if selected_type == VideoGenerationType.FIRST_LAST:
        return len(media) <= 2 and all(item["kind"] == "image" for item in media)
    try:
        for index, item in enumerate(media):
            validate_video_media(capability, selected_type, media[:index], item["kind"])
    except SubmissionError:
        return False
    return True


async def _reset_with_input_cleanup(
    state: FSMContext,
    input_media: TelegramInputMediaStorage,
) -> None:
    data = await state.get_data()
    await input_media.delete_many(stored_input_keys(data))
    await state.clear()
