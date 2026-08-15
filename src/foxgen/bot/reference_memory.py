from __future__ import annotations

from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Filter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from foxgen.bot.api_client import FoxGenApiClient, FoxGenApiError, SavedReferencePage
from foxgen.bot.callbacks import safe_edit_callback_message
from foxgen.bot.generation_capabilities import VideoGenerationType, VideoModelCapability
from foxgen.bot.generation_draft import (
    MAX_VIDEO_REFERENCE_TOTAL,
    ResolvedInput,
    StoredInput,
    image_capability,
    required_text,
    saved_reference_ids,
    stored_media,
    submission_payload,
    temporary_storage_keys,
    validate_video_media,
    video_capability,
    video_type,
)
from foxgen.bot.generation_keyboards import video_media_keyboard
from foxgen.bot.generation_screens import (
    image_reference_keyboard_for_data,
    image_references_text,
    render_image_references,
    render_image_settings,
    render_video_media,
    render_video_settings,
    video_media_max_count,
    video_media_text,
)
from foxgen.bot.keyboards import after_submit_keyboard, confirmation_keyboard
from foxgen.bot.states import GenerationStates
from foxgen.bot.uploads import TelegramInputMediaStorage, message_media_kind
from foxgen.core.errors import ErrorCode, SubmissionError


router = Router(name="foxgen-reference-memory")
_MEMORY_FIELDS = (
    "memory_origin",
    "memory_selected",
    "memory_index",
    "memory_current_id",
    "memory_control_chat_id",
    "memory_control_message_id",
    "memory_delete_confirm",
)


class HasSavedReferences(Filter):
    async def __call__(self, state: FSMContext) -> bool:
        data = await state.get_data()
        return bool(saved_reference_ids(stored_media(data)))


HAS_SAVED_REFERENCES = HasSavedReferences()


@router.callback_query(
    GenerationStates.image_uploading_references,
    F.data == "gw:i:refs:memory",
)
async def open_image_memory(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    api_client: FoxGenApiClient,
) -> None:
    data = await state.get_data()
    capability = image_capability(data)
    if not capability.supports_references:
        await callback.answer("Эта модель не принимает референсы.", show_alert=True)
        return
    await _open_memory(callback, state, bot, api_client, origin="image")


@router.callback_query(
    GenerationStates.video_uploading_media,
    F.data == "gw:v:media:memory",
)
async def open_video_memory(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    api_client: FoxGenApiClient,
) -> None:
    data = await state.get_data()
    if video_type(data) == VideoGenerationType.TEXT:
        await callback.answer("Для текстового видео референсы не нужны.", show_alert=True)
        return
    await _open_memory(callback, state, bot, api_client, origin="video")


# Saved references are durable objects, so cleanup actions must delete only temporary inputs.
# These handlers run before generation_wizard and intercept drafts containing saved references.
@router.callback_query(
    GenerationStates.image_uploading_references,
    HAS_SAVED_REFERENCES,
    F.data == "gw:i:refs:skip",
)
async def skip_image_references_with_memory(
    callback: CallbackQuery,
    state: FSMContext,
    input_media: TelegramInputMediaStorage,
) -> None:
    data = await state.get_data()
    await input_media.delete_many(temporary_storage_keys(stored_media(data)))
    capability = image_capability(data)
    await state.update_data(
        media=[],
        model_slug=capability.submission_slug(has_references=False),
        can_submit=False,
    )
    await render_image_settings(callback, state)


@router.callback_query(
    GenerationStates.image_uploading_references,
    HAS_SAVED_REFERENCES,
    F.data == "gw:i:refs:clear",
)
async def clear_image_references_with_memory(
    callback: CallbackQuery,
    state: FSMContext,
    input_media: TelegramInputMediaStorage,
) -> None:
    data = await state.get_data()
    await input_media.delete_many(temporary_storage_keys(stored_media(data)))
    await state.update_data(media=[], can_submit=False)
    await render_image_references(callback, state)


@router.callback_query(
    GenerationStates.video_uploading_media,
    HAS_SAVED_REFERENCES,
    F.data == "gw:v:media:clear",
)
async def clear_video_media_with_memory(
    callback: CallbackQuery,
    state: FSMContext,
    input_media: TelegramInputMediaStorage,
) -> None:
    data = await state.get_data()
    await input_media.delete_many(temporary_storage_keys(stored_media(data)))
    await state.update_data(media=[], can_submit=False)
    await render_video_media(callback, state)


@router.callback_query(
    GenerationStates.video_selecting_type,
    HAS_SAVED_REFERENCES,
    F.data.startswith("gw:v:type:"),
)
async def choose_video_type_with_memory(
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
        await input_media.delete_many(temporary_storage_keys(media))
        media = []
    await state.update_data(video_type=selected_type.value, media=media, can_submit=False)
    if selected_type == VideoGenerationType.TEXT:
        await render_video_settings(callback, state)
        return
    await render_video_media(callback, state)


# Final admission always re-resolves saved IDs through the owner-scoped internal API.
@router.callback_query(
    GenerationStates.confirming,
    HAS_SAVED_REFERENCES,
    F.data == "draft:confirm",
)
async def confirm_generation_with_saved_references(
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
        resolved_media = await _resolve_draft_media(
            data,
            input_media,
            api_client,
            callback.from_user.id,
        )
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
        "\nПовторный запрос распознан — новая задача не создавалась." if queued.replayed else ""
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
    GenerationStates.reference_memory_browsing,
    F.data == "rm:status",
)
async def memory_status(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    selected = _selected(data)
    await callback.answer(f"Выбрано: {len(selected)}/{_saved_image_capacity(data)}")


@router.callback_query(
    GenerationStates.reference_memory_browsing,
    F.data == "rm:prev",
)
async def memory_previous(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    api_client: FoxGenApiClient,
) -> None:
    data = await state.get_data()
    index = max(0, _memory_index(data) - 1)
    await state.update_data(memory_index=index, memory_delete_confirm=None)
    await callback.answer()
    await _replace_browser(bot, callback.from_user.id, state, api_client)


@router.callback_query(
    GenerationStates.reference_memory_browsing,
    F.data == "rm:next",
)
async def memory_next(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    api_client: FoxGenApiClient,
) -> None:
    data = await state.get_data()
    await state.update_data(memory_index=_memory_index(data) + 1, memory_delete_confirm=None)
    await callback.answer()
    await _replace_browser(bot, callback.from_user.id, state, api_client)


@router.callback_query(
    GenerationStates.reference_memory_browsing,
    F.data == "rm:toggle",
)
async def toggle_memory_reference(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    api_client: FoxGenApiClient,
) -> None:
    data = await state.get_data()
    current_id = data.get("memory_current_id")
    if not isinstance(current_id, str):
        await callback.answer("Референс уже недоступен.", show_alert=True)
        return
    selected = _selected(data)
    if current_id in selected:
        selected.remove(current_id)
    else:
        capacity = _saved_image_capacity(data)
        if len(selected) >= capacity:
            await callback.answer(
                f"Для текущей модели можно выбрать из памяти не больше {capacity} изображений.",
                show_alert=True,
            )
            return
        selected.append(current_id)
    await state.update_data(memory_selected=selected, memory_delete_confirm=None)
    await callback.answer("Выбор обновлён")
    await _replace_browser(bot, callback.from_user.id, state, api_client)


@router.callback_query(
    GenerationStates.reference_memory_browsing,
    F.data == "rm:add",
)
async def begin_add_reference(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
) -> None:
    await state.set_state(GenerationStates.reference_memory_adding)
    await callback.answer()
    await _replace_memory_message(
        bot,
        state,
        callback.from_user.id,
        "📚 <b>Сохранить референс</b>\n\nОтправьте одно фото или файл-изображение.",
        _add_keyboard(),
    )


@router.callback_query(
    GenerationStates.reference_memory_adding,
    F.data == "rm:add:back",
)
async def cancel_add_reference(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    api_client: FoxGenApiClient,
) -> None:
    await state.set_state(GenerationStates.reference_memory_browsing)
    await callback.answer()
    await _replace_browser(bot, callback.from_user.id, state, api_client)


@router.message(
    GenerationStates.reference_memory_adding,
    F.photo | F.document,
)
async def save_new_reference(
    message: Message,
    state: FSMContext,
    bot: Bot,
    input_media: TelegramInputMediaStorage,
    api_client: FoxGenApiClient,
) -> None:
    user_id = message.from_user.id if message.from_user else 0
    try:
        if message_media_kind(message) != "image":
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "В память референсов можно сохранить только изображение.",
            )
        uploaded = await input_media.upload(
            bot=bot,
            message=message,
            user_id=user_id,
        )
        try:
            result = await api_client.save_reference(
                user_id=user_id,
                username=message.from_user.username if message.from_user else None,
                storage_key=uploaded.storage_key,
            )
        finally:
            await input_media.delete_many((uploaded.storage_key,))
    except (SubmissionError, FoxGenApiError) as exc:
        text = exc.public_message if isinstance(exc, SubmissionError) else exc.message
        await message.answer(f"⚠️ {escape(text)}")
        return

    data = await state.get_data()
    selected = _selected(data)
    if result.item.id not in selected and len(selected) < _saved_image_capacity(data):
        selected.append(result.item.id)
    await state.update_data(
        memory_selected=selected,
        memory_index=0,
        memory_delete_confirm=None,
    )
    await state.set_state(GenerationStates.reference_memory_browsing)
    await _replace_browser(bot, user_id, state, api_client)
    await message.answer(
        "✅ Уже было в памяти — выбрал существующий референс."
        if result.duplicate
        else "✅ Фото сохранено в память и выбрано."
    )


@router.message(GenerationStates.reference_memory_adding)
async def invalid_memory_add(message: Message) -> None:
    await message.answer("Отправьте одно фото/изображение или нажмите «Назад».")


@router.callback_query(
    GenerationStates.reference_memory_browsing,
    F.data == "rm:save-current",
)
async def save_current_temporary_references(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    data = await state.get_data()
    temporary = [
        item
        for item in stored_media(data)
        if item["kind"] == "image" and isinstance(item.get("storage_key"), str)
    ]
    if not temporary:
        await callback.answer("В текущем черновике нет новых фото для сохранения.", show_alert=True)
        return

    saved = 0
    duplicates = 0
    for item in temporary:
        storage_key = item.get("storage_key")
        if not isinstance(storage_key, str):
            continue
        try:
            result = await api_client.save_reference(
                user_id=callback.from_user.id,
                username=callback.from_user.username,
                storage_key=storage_key,
            )
        except FoxGenApiError as exc:
            await callback.answer(
                f"Сохранено {saved}. {exc.message}",
                show_alert=True,
            )
            return
        if result.duplicate:
            duplicates += 1
        else:
            saved += 1
    await callback.answer(
        f"Сохранено новых: {saved}; уже были в памяти: {duplicates}.",
        show_alert=True,
    )


@router.callback_query(
    GenerationStates.reference_memory_browsing,
    F.data == "rm:delete",
)
async def request_delete_reference(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    api_client: FoxGenApiClient,
) -> None:
    data = await state.get_data()
    current_id = data.get("memory_current_id")
    if not isinstance(current_id, str):
        await callback.answer("Референс уже недоступен.", show_alert=True)
        return
    await state.update_data(memory_delete_confirm=current_id)
    await callback.answer("Подтвердите удаление")
    await _replace_browser(bot, callback.from_user.id, state, api_client)


@router.callback_query(
    GenerationStates.reference_memory_browsing,
    F.data == "rm:delete:cancel",
)
async def cancel_delete_reference(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    api_client: FoxGenApiClient,
) -> None:
    await state.update_data(memory_delete_confirm=None)
    await callback.answer()
    await _replace_browser(bot, callback.from_user.id, state, api_client)


@router.callback_query(
    GenerationStates.reference_memory_browsing,
    F.data == "rm:delete:confirm",
)
async def confirm_delete_reference(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    api_client: FoxGenApiClient,
) -> None:
    data = await state.get_data()
    reference_id = data.get("memory_delete_confirm")
    if not isinstance(reference_id, str):
        await callback.answer("Удаление уже отменено.", show_alert=True)
        return
    try:
        await api_client.delete_reference(
            user_id=callback.from_user.id,
            reference_id=reference_id,
        )
    except FoxGenApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    selected = [item for item in _selected(data) if item != reference_id]
    await state.update_data(
        memory_selected=selected,
        memory_delete_confirm=None,
    )
    await callback.answer("Удаление поставлено в очередь")
    await _replace_browser(bot, callback.from_user.id, state, api_client)


@router.callback_query(
    GenerationStates.reference_memory_browsing,
    F.data == "rm:apply",
)
async def apply_memory_selection(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    api_client: FoxGenApiClient,
) -> None:
    data = await state.get_data()
    selected = _selected(data)
    try:
        if selected:
            resolved = await api_client.resolve_references(
                user_id=callback.from_user.id,
                reference_ids=tuple(selected),
            )
            if tuple(item.id for item in resolved) != tuple(selected):
                raise SubmissionError(
                    ErrorCode.VALIDATION,
                    "Не удалось подтвердить порядок выбранных референсов.",
                )
        media = _apply_selected(data, selected)
    except (SubmissionError, FoxGenApiError) as exc:
        text = exc.public_message if isinstance(exc, SubmissionError) else exc.message
        await callback.answer(text, show_alert=True)
        return

    await state.update_data(media=media, can_submit=False)
    await callback.answer("Референсы добавлены")
    await _return_to_origin(bot, callback.from_user.id, state)


@router.callback_query(
    GenerationStates.reference_memory_browsing,
    F.data == "rm:back",
)
async def leave_memory_without_changes(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
) -> None:
    await callback.answer()
    await _return_to_origin(bot, callback.from_user.id, state)


@router.message(GenerationStates.reference_memory_browsing)
async def invalid_memory_browser(message: Message) -> None:
    await message.answer("В памяти референсов используйте кнопки под превью.")


async def _open_memory(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    api_client: FoxGenApiClient,
    *,
    origin: str,
) -> None:
    data = await state.get_data()
    await state.update_data(
        memory_origin=origin,
        memory_selected=list(saved_reference_ids(stored_media(data))),
        memory_index=0,
        memory_current_id=None,
        memory_delete_confirm=None,
    )
    await state.set_state(GenerationStates.reference_memory_browsing)
    await callback.answer()
    if isinstance(callback.message, Message):
        await _delete_message(bot, callback.message.chat.id, callback.message.message_id)
    await _replace_browser(bot, callback.from_user.id, state, api_client)


async def _replace_browser(
    bot: Bot,
    user_id: int,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    data = await state.get_data()
    index = _memory_index(data)
    try:
        page = await api_client.list_references(user_id=user_id, offset=index, limit=1)
        if page.total and index >= page.total:
            index = page.total - 1
            await state.update_data(memory_index=index)
            page = await api_client.list_references(user_id=user_id, offset=index, limit=1)
    except FoxGenApiError as exc:
        await _replace_memory_message(
            bot,
            state,
            user_id,
            f"⚠️ {escape(exc.message)}",
            _empty_keyboard(has_temporary=_has_temporary_images(data)),
        )
        return

    await _delete_memory_control(bot, state)
    data = await state.get_data()
    if not page.items:
        await state.update_data(memory_current_id=None, memory_index=0)
        message = await bot.send_message(
            chat_id=user_id,
            text=_empty_text(page),
            reply_markup=_empty_keyboard(has_temporary=_has_temporary_images(data)),
        )
    else:
        item = page.items[0]
        await state.update_data(memory_current_id=item.id)
        selected = _selected(data)
        message = await bot.send_photo(
            chat_id=user_id,
            photo=item.preview_url,
            caption=_memory_caption(page, index, item.id in selected, data),
            reply_markup=_browser_keyboard(
                index=index,
                total=page.total,
                selected_count=len(selected),
                capacity=_saved_image_capacity(data),
                current_selected=item.id in selected,
                confirm_delete=data.get("memory_delete_confirm") == item.id,
                has_temporary=_has_temporary_images(data),
            ),
        )
    await state.update_data(
        memory_control_chat_id=message.chat.id,
        memory_control_message_id=message.message_id,
    )


async def _replace_memory_message(
    bot: Bot,
    state: FSMContext,
    chat_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup,
) -> None:
    await _delete_memory_control(bot, state)
    message = await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
    await state.update_data(
        memory_control_chat_id=message.chat.id,
        memory_control_message_id=message.message_id,
    )


async def _delete_memory_control(bot: Bot, state: FSMContext) -> None:
    data = await state.get_data()
    chat_id = data.get("memory_control_chat_id")
    message_id = data.get("memory_control_message_id")
    if isinstance(chat_id, int) and isinstance(message_id, int):
        await _delete_message(bot, chat_id, message_id)


async def _delete_message(bot: Bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except TelegramBadRequest:
        pass


async def _return_to_origin(bot: Bot, chat_id: int, state: FSMContext) -> None:
    await _delete_memory_control(bot, state)
    current = await state.get_data()
    origin = current.get("memory_origin")
    data = dict(current)
    for key in _MEMORY_FIELDS:
        data.pop(key, None)
    await state.set_data(data)

    if origin == "image":
        await state.set_state(GenerationStates.image_uploading_references)
        text = image_references_text(data)
        keyboard = image_reference_keyboard_for_data(data)
    elif origin == "video":
        await state.set_state(GenerationStates.video_uploading_media)
        generation_type = video_type(data)
        media = stored_media(data)
        text = video_media_text(data)
        keyboard = video_media_keyboard(
            generation_type=generation_type,
            count=len(media),
            max_count=video_media_max_count(data),
            can_continue=True,
        )
    else:
        await state.clear()
        await bot.send_message(chat_id, "Черновик памяти устарел. Откройте /menu.")
        return

    control = await bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
    await state.update_data(
        wizard_control_chat_id=control.chat.id,
        wizard_control_message_id=control.message_id,
    )


async def _resolve_draft_media(
    data: dict[str, object],
    input_media: TelegramInputMediaStorage,
    api_client: FoxGenApiClient,
    user_id: int,
) -> list[ResolvedInput]:
    media = stored_media(data)
    reference_ids = saved_reference_ids(media)
    resolved_by_id: dict[str, str] = {}
    if reference_ids:
        resolved = await api_client.resolve_references(
            user_id=user_id,
            reference_ids=reference_ids,
        )
        resolved_by_id = {item.id: item.preview_url for item in resolved}
        if set(resolved_by_id) != set(reference_ids):
            raise SubmissionError(
                ErrorCode.AUTHORIZATION,
                "Один или несколько сохранённых референсов больше недоступны.",
            )

    result: list[ResolvedInput] = []
    for item in media:
        reference_id = item.get("reference_id")
        if isinstance(reference_id, str):
            url = resolved_by_id.get(reference_id)
            if url is None:
                raise SubmissionError(
                    ErrorCode.AUTHORIZATION,
                    "Сохранённый референс больше недоступен.",
                )
        else:
            storage_key = item.get("storage_key")
            if not isinstance(storage_key, str):
                raise SubmissionError(ErrorCode.VALIDATION, "Референс повреждён.")
            url = await input_media.presign(storage_key)
        result.append({"kind": item["kind"], "url": url})
    return result


def _apply_selected(data: dict[str, object], selected: list[str]) -> list[StoredInput]:
    media = stored_media(data)
    temporary = [item for item in media if isinstance(item.get("storage_key"), str)]
    candidate: list[StoredInput] = list(temporary)
    if data.get("generation_type") == "image":
        capability = image_capability(data)
        if len(candidate) + len(selected) > capability.max_references:
            raise SubmissionError(
                ErrorCode.VALIDATION,
                f"У модели лимит {capability.max_references} референсов.",
            )
        candidate.extend({"kind": "image", "reference_id": item} for item in selected)
        return candidate

    capability = video_capability(data)
    generation_type = video_type(data)
    for reference_id in selected:
        validate_video_media(capability, generation_type, candidate, "image")
        candidate.append({"kind": "image", "reference_id": reference_id})
    return candidate


def _saved_image_capacity(data: dict[str, object]) -> int:
    media = stored_media(data)
    temporary = [item for item in media if isinstance(item.get("storage_key"), str)]
    if data.get("generation_type") == "image":
        return max(0, image_capability(data).max_references - len(temporary))

    generation_type = video_type(data)
    if generation_type == VideoGenerationType.TEXT:
        return 0
    if generation_type == VideoGenerationType.FIRST_FRAME:
        return max(0, 1 - len(temporary))
    if generation_type == VideoGenerationType.FIRST_LAST:
        return max(0, 2 - len(temporary))
    capability = video_capability(data)
    temporary_images = sum(1 for item in temporary if item["kind"] == "image")
    total_capacity = max(0, MAX_VIDEO_REFERENCE_TOTAL - len(temporary))
    image_capacity = max(0, capability.max_reference_images - temporary_images)
    return min(total_capacity, image_capacity)


def _selected(data: dict[str, object]) -> list[str]:
    raw = data.get("memory_selected")
    if not isinstance(raw, list):
        return []
    return list(dict.fromkeys(item for item in raw if isinstance(item, str) and item))


def _memory_index(data: dict[str, object]) -> int:
    value = data.get("memory_index")
    return max(0, value) if isinstance(value, int) else 0


def _has_temporary_images(data: dict[str, object]) -> bool:
    return any(
        item["kind"] == "image" and isinstance(item.get("storage_key"), str)
        for item in stored_media(data)
    )


def _memory_caption(
    page: SavedReferencePage,
    index: int,
    selected: bool,
    data: dict[str, object],
) -> str:
    used_mb = page.used_bytes / (1024 * 1024)
    max_mb = page.max_bytes / (1024 * 1024)
    order_hint = "\nПорядок выбора = порядок кадров." if _is_first_last(data) else ""
    return (
        "📚 <b>Память референсов</b>\n\n"
        f"Фото <b>{index + 1}/{page.total}</b> · {'✅ выбрано' if selected else 'не выбрано'}\n"
        f"Память: {page.total}/{page.max_items} · {used_mb:.1f}/{max_mb:.0f} МБ"
        f"{order_hint}"
    )


def _empty_text(page: SavedReferencePage) -> str:
    max_mb = page.max_bytes / (1024 * 1024)
    return (
        "📚 <b>Память референсов</b>\n\n"
        "Здесь пока нет сохранённых фото.\n"
        f"Лимит: {page.max_items} изображений · до {max_mb:.0f} МБ."
    )


def _browser_keyboard(
    *,
    index: int,
    total: int,
    selected_count: int,
    capacity: int,
    current_selected: bool,
    confirm_delete: bool,
    has_temporary: bool,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=f"Выбрано: {selected_count}/{capacity}",
                callback_data="rm:status",
            )
        ],
        [
            InlineKeyboardButton(
                text="☑️ Убрать" if current_selected else "➕ Выбрать",
                callback_data="rm:toggle",
            )
        ],
    ]
    navigation: list[InlineKeyboardButton] = []
    if index > 0:
        navigation.append(InlineKeyboardButton(text="⬅️", callback_data="rm:prev"))
    if index + 1 < total:
        navigation.append(InlineKeyboardButton(text="➡️", callback_data="rm:next"))
    if navigation:
        rows.append(navigation)
    rows.append([InlineKeyboardButton(text="➕ Добавить фото", callback_data="rm:add")])
    if has_temporary:
        rows.append(
            [
                InlineKeyboardButton(
                    text="💾 Сохранить загруженные",
                    callback_data="rm:save-current",
                )
            ]
        )
    if confirm_delete:
        rows.append(
            [
                InlineKeyboardButton(text="🗑 Да, удалить", callback_data="rm:delete:confirm"),
                InlineKeyboardButton(text="Отмена", callback_data="rm:delete:cancel"),
            ]
        )
    else:
        rows.append([InlineKeyboardButton(text="🗑 Удалить", callback_data="rm:delete")])
    rows.append([InlineKeyboardButton(text="✅ Использовать выбранные", callback_data="rm:apply")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="rm:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _empty_keyboard(*, has_temporary: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="➕ Добавить фото", callback_data="rm:add")]]
    if has_temporary:
        rows.append(
            [
                InlineKeyboardButton(
                    text="💾 Сохранить загруженные",
                    callback_data="rm:save-current",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="rm:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _add_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="rm:add:back")],
        ]
    )


def _is_first_last(data: dict[str, object]) -> bool:
    try:
        return video_type(data) == VideoGenerationType.FIRST_LAST
    except SubmissionError:
        return False


def _media_compatible_with_video_type(
    capability: VideoModelCapability,
    selected_type: VideoGenerationType,
    media: list[StoredInput],
) -> bool:
    if selected_type == VideoGenerationType.TEXT:
        return not media
    try:
        for index, item in enumerate(media):
            validate_video_media(
                capability,
                selected_type,
                media[:index],
                item["kind"],
            )
    except SubmissionError:
        return False
    return True
