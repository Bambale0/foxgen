from html import escape
from typing import Any, TypedDict
from uuid import uuid4

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from foxgen.bot.api_client import FoxGenApiClient, FoxGenApiError
from foxgen.bot.catalog import (
    MODE_CALLBACKS,
    MODE_TITLES,
    GenerationMode,
    Product,
    mode_requires_media,
    mode_supports_multiple_media,
    model_choice,
    model_uses_seedream_quality,
    product_for_mode,
)
from foxgen.bot.keyboards import (
    after_submit_keyboard,
    aspect_ratio_keyboard,
    confirmation_keyboard,
    image_quality_keyboard,
    main_menu,
    mode_keyboard,
    model_keyboard,
    navigation_keyboard,
    video_audio_keyboard,
    video_duration_keyboard,
)
from foxgen.bot.states import GenerationStates
from foxgen.bot.uploads import TelegramInputMediaStorage, message_media_kind
from foxgen.core.errors import ErrorCode, SubmissionError


router = Router(name="generation-flows")


class StoredInput(TypedDict):
    kind: str
    storage_key: str


class ResolvedInput(TypedDict):
    kind: str
    url: str


@router.callback_query(F.data.in_({"create:image", "create:video"}))
async def choose_product_mode(callback: CallbackQuery, state: FSMContext) -> None:
    product = Product.IMAGE if callback.data == "create:image" else Product.VIDEO
    await state.clear()
    await state.update_data(
        product=product.value,
        idempotency_key=f"generation:{callback.from_user.id}:{uuid4().hex}",
        media=[],
        can_submit=False,
    )
    await state.set_state(GenerationStates.choosing_mode)
    await _edit_callback(
        callback,
        "<b>Выберите сценарий</b>\n\nЯ покажу только совместимые модели и параметры.",
        mode_keyboard(product),
    )


@router.callback_query(GenerationStates.choosing_mode, F.data.in_(set(MODE_CALLBACKS)))
async def choose_mode(callback: CallbackQuery, state: FSMContext) -> None:
    data_value = callback.data or ""
    mode = MODE_CALLBACKS[data_value]
    await state.update_data(
        mode=mode.value,
        product=product_for_mode(mode).value,
        media=[],
        can_submit=False,
    )
    await state.set_state(GenerationStates.choosing_model)
    await _edit_callback(
        callback,
        f"<b>{escape(MODE_TITLES[mode])}</b>\n\nВыберите модель:",
        model_keyboard(mode),
    )


@router.callback_query(GenerationStates.choosing_model, F.data.startswith("model:"))
async def choose_model(callback: CallbackQuery, state: FSMContext) -> None:
    slug = (callback.data or "").partition(":")[2]
    data = await state.get_data()
    mode = _mode(data)
    try:
        choice = model_choice(mode, slug)
    except KeyError:
        await callback.answer("Эта модель недоступна в выбранном сценарии.", show_alert=True)
        return
    await state.update_data(
        model_slug=choice.slug,
        model_title=choice.title,
        can_submit=False,
    )
    await state.set_state(GenerationStates.waiting_prompt)
    await _edit_callback(
        callback,
        (
            f"<b>{escape(choice.title)}</b>\n\n"
            "Опишите желаемый результат обычными словами. "
            "Укажите сюжет, стиль, движение, свет и важные ограничения."
        ),
        navigation_keyboard(),
    )


@router.message(GenerationStates.waiting_prompt, F.text)
async def receive_prompt(
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
    editing = bool(data.get("editing_prompt"))
    await state.update_data(prompt=prompt, editing_prompt=False, can_submit=False)
    if editing and isinstance(data.get("aspect_ratio"), str):
        await state.set_state(GenerationStates.confirming)
        await _show_confirmation_message(message, state, api_client)
        return

    mode = _mode(data)
    if mode_requires_media(mode):
        await state.set_state(GenerationStates.waiting_media)
        await message.answer(
            _media_prompt(mode),
            reply_markup=navigation_keyboard(media_done=mode_supports_multiple_media(mode)),
        )
        return
    await state.set_state(GenerationStates.choosing_aspect_ratio)
    await message.answer(
        "Выберите формат результата:",
        reply_markup=aspect_ratio_keyboard(product_for_mode(mode)),
    )


@router.message(
    GenerationStates.waiting_media,
    F.photo | F.video | F.animation | F.audio | F.voice | F.document,
)
async def receive_media(
    message: Message,
    state: FSMContext,
    bot: Bot,
    input_media: TelegramInputMediaStorage,
) -> None:
    data = await state.get_data()
    mode = _mode(data)
    media = _stored_media(data)
    if len(media) >= 6:
        await message.answer("Можно добавить не больше шести референсов.")
        return

    try:
        kind = message_media_kind(message)
        _validate_media_kind(mode, kind)
        user_id = message.from_user.id if message.from_user is not None else 0
        uploaded = await input_media.upload(
            bot=bot,
            message=message,
            user_id=user_id,
        )
    except SubmissionError as exc:
        await message.answer(exc.public_message)
        return

    media.append({"kind": uploaded.kind, "storage_key": uploaded.storage_key})
    await state.update_data(media=media, can_submit=False)

    if mode_supports_multiple_media(mode):
        await message.answer(
            f"Референс добавлен. Сейчас: {len(media)}. Добавьте ещё или нажмите «Готово».",
            reply_markup=navigation_keyboard(media_done=True),
        )
        return

    await state.set_state(GenerationStates.choosing_aspect_ratio)
    await message.answer(
        "Файл сохранён. Выберите формат результата:",
        reply_markup=aspect_ratio_keyboard(product_for_mode(mode)),
    )


@router.callback_query(GenerationStates.waiting_media, F.data == "media:done")
async def finish_reference_media(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not _stored_media(data):
        await callback.answer("Сначала добавьте хотя бы один референс.", show_alert=True)
        return
    mode = _mode(data)
    await state.set_state(GenerationStates.choosing_aspect_ratio)
    await _edit_callback(
        callback,
        "Референсы сохранены. Выберите формат результата:",
        aspect_ratio_keyboard(product_for_mode(mode)),
    )


@router.callback_query(GenerationStates.choosing_aspect_ratio, F.data.startswith("aspect:"))
async def choose_aspect_ratio(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    ratio = (callback.data or "").partition(":")[2].replace("x", ":")
    data = await state.get_data()
    mode = _mode(data)
    model_slug = _required_str(data, "model_slug")
    await state.update_data(aspect_ratio=ratio, can_submit=False)
    if product_for_mode(mode) == Product.IMAGE:
        if model_uses_seedream_quality(model_slug):
            await state.set_state(GenerationStates.choosing_quality)
            await _edit_callback(
                callback,
                "Выберите качество изображения:",
                image_quality_keyboard(),
            )
            return
        await state.update_data(resolution="1K")
        await state.set_state(GenerationStates.confirming)
        await _show_confirmation_callback(callback, state, api_client)
        return
    await state.set_state(GenerationStates.choosing_duration)
    await _edit_callback(
        callback,
        "Выберите длительность видео:",
        video_duration_keyboard(),
    )


@router.callback_query(GenerationStates.choosing_quality, F.data.startswith("quality:"))
async def choose_image_quality(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    quality = (callback.data or "").partition(":")[2]
    if quality not in {"basic", "high"}:
        await callback.answer("Некорректное качество.", show_alert=True)
        return
    await state.update_data(quality=quality, can_submit=False)
    await state.set_state(GenerationStates.confirming)
    await _show_confirmation_callback(callback, state, api_client)


@router.callback_query(GenerationStates.choosing_duration, F.data.startswith("duration:"))
async def choose_video_duration(callback: CallbackQuery, state: FSMContext) -> None:
    raw_duration = (callback.data or "").partition(":")[2]
    try:
        duration = int(raw_duration)
    except ValueError:
        await callback.answer("Некорректная длительность.", show_alert=True)
        return
    if duration not in {5, 10}:
        await callback.answer("Эта длительность недоступна.", show_alert=True)
        return
    await state.update_data(duration=duration, resolution="720p", can_submit=False)
    await state.set_state(GenerationStates.choosing_audio)
    await _edit_callback(
        callback,
        "Нужно сгенерировать звук вместе с видео?",
        video_audio_keyboard(),
    )


@router.callback_query(GenerationStates.choosing_audio, F.data.startswith("audio:"))
async def choose_video_audio(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    callback_data = callback.data or ""
    if callback_data not in {"audio:yes", "audio:no"}:
        await callback.answer("Некорректный вариант.", show_alert=True)
        return
    await state.update_data(generate_audio=callback_data == "audio:yes", can_submit=False)
    await state.set_state(GenerationStates.confirming)
    await _show_confirmation_callback(callback, state, api_client)


@router.callback_query(GenerationStates.confirming, F.data == "draft:edit")
async def edit_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(editing_prompt=True, can_submit=False)
    await state.set_state(GenerationStates.waiting_prompt)
    await _edit_callback(
        callback,
        "Отправьте новое описание. Остальные параметры сохранятся.",
        navigation_keyboard(),
    )


@router.callback_query(GenerationStates.confirming, F.data == "draft:refresh")
async def refresh_confirmation(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    await _show_confirmation_callback(callback, state, api_client)


@router.callback_query(GenerationStates.confirming, F.data == "draft:confirm")
async def confirm_generation(
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
    if callback.message:
        await callback.message.edit_text("⏳ Проверяю баланс и ставлю генерацию в очередь…")
    await callback.answer()

    try:
        resolved_media = await _resolve_media(data, input_media)
        payload = _provider_payload(data, resolved_media)
        queued = await api_client.submit(
            user_id=callback.from_user.id,
            username=callback.from_user.username,
            model_slug=_required_str(data, "model_slug"),
            input_data=payload,
            idempotency_key=_required_str(data, "idempotency_key"),
        )
    except SubmissionError as exc:
        await state.set_state(GenerationStates.confirming)
        await state.update_data(can_submit=False)
        if callback.message:
            await callback.message.edit_text(
                f"⚠️ {escape(exc.public_message)}\n\nПараметры сохранены.",
                reply_markup=confirmation_keyboard(can_submit=False),
            )
        return
    except FoxGenApiError as exc:
        await state.set_state(GenerationStates.confirming)
        await state.update_data(can_submit=False)
        if callback.message:
            await callback.message.edit_text(
                f"⚠️ {escape(exc.message)}\n\nПараметры сохранены.",
                reply_markup=confirmation_keyboard(can_submit=False),
            )
        return

    await state.clear()
    replay_text = (
        "\nПовторный запрос распознан — новая задача не создавалась."
        if queued.replayed
        else ""
    )
    if callback.message:
        await callback.message.edit_text(
            (
                "✅ <b>Генерация поставлена в очередь</b>\n\n"
                f"ID: <code>{escape(queued.generation_id)}</code>\n"
                "Результат придёт сюда автоматически после сохранения."
                f"{replay_text}"
            ),
            reply_markup=after_submit_keyboard(),
        )


@router.callback_query(GenerationStates.submitting, F.data == "draft:confirm")
async def duplicate_confirmation(callback: CallbackQuery) -> None:
    await callback.answer("Генерация уже запускается.", show_alert=True)


@router.callback_query(F.data == "account:balance")
async def show_balance(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    try:
        balance = await api_client.balance(callback.from_user.id)
    except FoxGenApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return

    current = await state.get_state()
    if current == GenerationStates.confirming.state:
        await _edit_callback(
            callback,
            (
                "<b>Ваш баланс</b>\n\n"
                f"Доступно: <b>{balance.available_units} {escape(balance.currency)}</b>\n"
                f"В резерве: {balance.reserved_units} {escape(balance.currency)}\n\n"
                "Нажмите «Обновить цену и баланс», чтобы вернуться к черновику."
            ),
            confirmation_keyboard(can_submit=False),
        )
        return

    await state.clear()
    await _edit_callback(
        callback,
        (
            "<b>Ваш баланс</b>\n\n"
            f"Доступно: <b>{balance.available_units} {escape(balance.currency)}</b>\n"
            f"В резерве: {balance.reserved_units} {escape(balance.currency)}"
        ),
        main_menu(),
    )


@router.callback_query(F.data == "nav:back")
async def go_back(callback: CallbackQuery, state: FSMContext) -> None:
    current = await state.get_state()
    data = await state.get_data()
    if current == GenerationStates.choosing_mode.state:
        await state.clear()
        await _edit_callback(callback, "Что создаём?", main_menu())
        return
    if current == GenerationStates.choosing_model.state:
        product = Product(_required_str(data, "product"))
        await state.set_state(GenerationStates.choosing_mode)
        await _edit_callback(callback, "Выберите сценарий:", mode_keyboard(product))
        return
    if current == GenerationStates.waiting_prompt.state:
        mode = _mode(data)
        await state.set_state(GenerationStates.choosing_model)
        await _edit_callback(callback, "Выберите модель:", model_keyboard(mode))
        return
    if current == GenerationStates.waiting_media.state:
        await state.update_data(media=[], can_submit=False)
        await state.set_state(GenerationStates.waiting_prompt)
        await _edit_callback(
            callback,
            "Отправьте описание результата:",
            navigation_keyboard(),
        )
        return
    if current == GenerationStates.choosing_aspect_ratio.state:
        mode = _mode(data)
        target = (
            GenerationStates.waiting_media
            if mode_requires_media(mode)
            else GenerationStates.waiting_prompt
        )
        await state.set_state(target)
        text = (
            _media_prompt(mode)
            if mode_requires_media(mode)
            else "Отправьте описание результата:"
        )
        await _edit_callback(
            callback,
            text,
            navigation_keyboard(media_done=mode_supports_multiple_media(mode)),
        )
        return
    if current in {
        GenerationStates.choosing_quality.state,
        GenerationStates.choosing_duration.state,
    }:
        mode = _mode(data)
        await state.set_state(GenerationStates.choosing_aspect_ratio)
        await _edit_callback(
            callback,
            "Выберите формат результата:",
            aspect_ratio_keyboard(product_for_mode(mode)),
        )
        return
    if current == GenerationStates.choosing_audio.state:
        await state.set_state(GenerationStates.choosing_duration)
        await _edit_callback(callback, "Выберите длительность:", video_duration_keyboard())
        return
    if current == GenerationStates.confirming.state:
        mode = _mode(data)
        if product_for_mode(mode) == Product.IMAGE:
            model_slug = _required_str(data, "model_slug")
            if model_uses_seedream_quality(model_slug):
                await state.set_state(GenerationStates.choosing_quality)
                await _edit_callback(callback, "Выберите качество:", image_quality_keyboard())
            else:
                await state.set_state(GenerationStates.choosing_aspect_ratio)
                await _edit_callback(
                    callback,
                    "Выберите формат результата:",
                    aspect_ratio_keyboard(Product.IMAGE),
                )
        else:
            await state.set_state(GenerationStates.choosing_audio)
            await _edit_callback(callback, "Нужно сгенерировать звук?", video_audio_keyboard())
        return
    await callback.answer("Назад перейти уже нельзя. Открыл меню.", show_alert=True)
    await state.clear()
    if callback.message:
        await callback.message.edit_text("Что создаём?", reply_markup=main_menu())


@router.message(GenerationStates.waiting_media)
async def invalid_media(message: Message) -> None:
    await message.answer("Отправьте изображение, видео или аудио — не текстовое сообщение.")


async def _show_confirmation_callback(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    text, can_submit = await _confirmation_text(state, api_client, callback.from_user.id)
    await _edit_callback(
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
    await message.answer(
        text,
        reply_markup=confirmation_keyboard(can_submit=can_submit),
    )


async def _confirmation_text(
    state: FSMContext,
    api_client: FoxGenApiClient,
    user_id: int,
) -> tuple[str, bool]:
    data = await state.get_data()
    model_slug = _required_str(data, "model_slug")
    try:
        prices = await api_client.prices()
        quote = prices.get(model_slug)
        balance = await api_client.balance(user_id)
    except FoxGenApiError as exc:
        await state.update_data(can_submit=False)
        return (
            f"⚠️ {escape(exc.message)}\n\nПроверьте параметры и повторите попытку позже.",
            False,
        )
    if quote is None:
        await state.update_data(can_submit=False)
        return (
            "⚠️ Для этой модели пока не опубликована цена. "
            "Запуск заблокирован, чтобы не произошло неожиданного списания.",
            False,
        )

    enough = balance.available_units >= quote.amount_units
    await state.update_data(
        price_units=quote.amount_units,
        currency=quote.currency,
        price_version=quote.version,
        can_submit=enough,
    )
    media_count = len(_stored_media(data))
    balance_line = (
        f"Доступно: {balance.available_units} {escape(balance.currency)}"
        if enough
        else f"⚠️ Доступно только {balance.available_units} {escape(balance.currency)}"
    )
    options = _options_summary(data)
    return (
        "<b>Проверьте генерацию</b>\n\n"
        f"Сценарий: {escape(MODE_TITLES[_mode(data)])}\n"
        f"Модель: <b>{escape(_required_str(data, 'model_title'))}</b>\n"
        f"Формат: {escape(_required_str(data, 'aspect_ratio'))}\n"
        f"Параметры: {escape(options)}\n"
        f"Медиа: {media_count}\n"
        f"Описание: {escape(_required_str(data, 'prompt'))}\n\n"
        f"Стоимость: <b>{quote.amount_units} {escape(quote.currency)}</b>\n"
        f"{balance_line}\n\n"
        "Средства резервируются атомарно при постановке в очередь.",
        enough,
    )


async def _resolve_media(
    data: dict[str, Any],
    input_media: TelegramInputMediaStorage,
) -> list[ResolvedInput]:
    resolved: list[ResolvedInput] = []
    for item in _stored_media(data):
        resolved.append(
            {
                "kind": item["kind"],
                "url": await input_media.presign(item["storage_key"]),
            }
        )
    return resolved


def _provider_payload(
    data: dict[str, Any],
    media: list[ResolvedInput] | None = None,
) -> dict[str, object]:
    mode = _mode(data)
    slug = _required_str(data, "model_slug")
    prompt = _required_str(data, "prompt")
    ratio = _required_str(data, "aspect_ratio")
    resolved_media = media or []

    if product_for_mode(mode) == Product.IMAGE:
        if slug.startswith("seedream-4-5"):
            payload: dict[str, object] = {
                "prompt": prompt,
                "aspect_ratio": ratio,
                "quality": str(data.get("quality", "basic")),
                "nsfw_checker": False,
            }
            if mode == GenerationMode.IMAGE_EDIT:
                payload["image_urls"] = [item["url"] for item in resolved_media]
            return payload
        if slug.startswith("seedream-5-pro"):
            payload = {
                "prompt": prompt,
                "aspect_ratio": ratio,
                "quality": str(data.get("quality", "basic")),
                "output_format": "png",
                "nsfw_checker": False,
            }
            if mode == GenerationMode.IMAGE_EDIT:
                payload["image_urls"] = [item["url"] for item in resolved_media]
            return payload
        return {
            "prompt": prompt,
            "image_input": [item["url"] for item in resolved_media],
            "aspect_ratio": ratio,
            "resolution": str(data.get("resolution", "1K")),
            "output_format": "png",
        }

    payload = {
        "prompt": prompt,
        "return_last_frame": False,
        "generate_audio": bool(data.get("generate_audio", False)),
        "resolution": str(data.get("resolution", "720p")),
        "aspect_ratio": ratio,
        "duration": int(data.get("duration", 5)),
        "web_search": False,
    }
    if mode == GenerationMode.VIDEO_IMAGE:
        if not resolved_media:
            raise SubmissionError(ErrorCode.VALIDATION, "Не найден первый кадр.")
        payload["first_frame_url"] = resolved_media[0]["url"]
    elif mode == GenerationMode.VIDEO_REFERENCE:
        payload["reference_image_urls"] = [
            item["url"] for item in resolved_media if item["kind"] == "image"
        ]
        payload["reference_video_urls"] = [
            item["url"] for item in resolved_media if item["kind"] == "video"
        ]
        payload["reference_audio_urls"] = [
            item["url"] for item in resolved_media if item["kind"] == "audio"
        ]
    return payload


def _options_summary(data: dict[str, Any]) -> str:
    mode = _mode(data)
    if product_for_mode(mode) == Product.IMAGE:
        if model_uses_seedream_quality(_required_str(data, "model_slug")):
            return f"качество {data.get('quality', 'basic')}"
        return f"разрешение {data.get('resolution', '1K')}"
    audio = "со звуком" if bool(data.get("generate_audio")) else "без звука"
    return f"{data.get('duration', 5)} сек., {data.get('resolution', '720p')}, {audio}"


def _media_prompt(mode: GenerationMode) -> str:
    if mode == GenerationMode.IMAGE_EDIT:
        return "Отправьте изображение, которое нужно изменить."
    if mode == GenerationMode.VIDEO_IMAGE:
        return "Отправьте первый кадр — изображение, которое нужно оживить."
    return (
        "Отправляйте референсы по одному: изображения, видео или аудио. "
        "Можно добавить до шести файлов. Когда закончите, нажмите «Референсы добавлены»."
    )


def _validate_media_kind(mode: GenerationMode, kind: str) -> None:
    if mode in {GenerationMode.IMAGE_EDIT, GenerationMode.VIDEO_IMAGE} and kind != "image":
        raise SubmissionError(
            ErrorCode.VALIDATION,
            "В этом сценарии требуется изображение.",
        )
    if mode == GenerationMode.VIDEO_REFERENCE and kind not in {"image", "video", "audio"}:
        raise SubmissionError(
            ErrorCode.VALIDATION,
            "Поддерживаются только изображения, видео и аудио.",
        )


def _stored_media(data: dict[str, Any]) -> list[StoredInput]:
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


def _mode(data: dict[str, Any]) -> GenerationMode:
    value = _required_str(data, "mode")
    try:
        return GenerationMode(value)
    except ValueError as exc:
        raise SubmissionError(
            ErrorCode.VALIDATION,
            "Черновик генерации устарел. Откройте главное меню и начните заново.",
        ) from exc


def _required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise SubmissionError(
            ErrorCode.VALIDATION,
            "Черновик генерации повреждён. Откройте главное меню и начните заново.",
            details={"missing_field": key},
        )
    return value


async def _edit_callback(
    callback: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup,
) -> None:
    if callback.message:
        try:
            await callback.message.edit_text(text, reply_markup=reply_markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc):
                raise
    await callback.answer()
