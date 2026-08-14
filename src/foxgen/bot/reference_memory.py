from __future__ import annotations

from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from foxgen.bot.api_client import FoxGenApiClient, FoxGenApiError, SavedReferencePage
from foxgen.bot.generation_draft import (
    MAX_VIDEO_REFERENCE_TOTAL,
    StoredInput,
    image_capability,
    saved_reference_ids,
    stored_media,
    temporary_storage_keys,
    validate_video_media,
    video_capability,
    video_type,
)
from foxgen.bot.generation_keyboards import video_media_keyboard
from foxgen.bot.generation_screens import (
    image_reference_keyboard_for_data,
    image_references_text,
    video_media_max_count,
    video_media_text,
)
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
    if _saved_image_capacity(data) <= 0 and not saved_reference_ids(stored_media(data)):
        await callback.answer(
            "Для текущего сценария уже достигнут лимит изображений.",
            show_alert=True,
        )
        return
    await _open_memory(callback, state, bot, api_client, origin="video")


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
    await callback.answer("Удалено")
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
    data = await _without_memory_fields(state)
    origin = data.get("memory_origin")
    # origin was removed from the cleaned copy; recover it from the pre-clean snapshot.
    current = await state.get_data()
    origin = current.get("memory_origin") if origin is None else origin
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
    await state.set_data(data)
    control = await bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
    await state.update_data(
        wizard_control_chat_id=control.chat.id,
        wizard_control_message_id=control.message_id,
    )


async def _without_memory_fields(state: FSMContext) -> dict[str, object]:
    data = await state.get_data()
    result = dict(data)
    for key in _MEMORY_FIELDS:
        result.pop(key, None)
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
    if generation_type.value == "text":
        return 0
    if generation_type.value == "first_frame":
        return max(0, 1 - len(temporary))
    if generation_type.value == "first_last":
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
    media = stored_media(data)
    keys = set(temporary_storage_keys(media))
    return any(item["kind"] == "image" and item.get("storage_key") in keys for item in media)


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
        return video_type(data).value == "first_last"
    except SubmissionError:
        return False
