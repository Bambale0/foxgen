from html import escape
from uuid import uuid4

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from foxgen.bot.api_client import FoxGenApiClient, FoxGenApiError
from foxgen.bot.catalog import (
    MODE_CALLBACKS,
    MODE_TITLES,
    GenerationMode,
    Product,
    mode_requires_media,
    mode_supports_multiple_media,
    model_choice,
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
from foxgen.bot.uploads import TelegramInputMediaStorage
from foxgen.core.errors import SubmissionError


router = Router(name="generation-flows")


@router.callback_query(F.data.in_({"create:image", "create:video"}))
async def choose_product_mode(callback: CallbackQuery, state: FSMContext) -> None:
    product = Product.IMAGE if callback.data == "create:image" else Product.VIDEO
    await state.clear()
    await state.update_data(
        product=product.value,
        idempotency_key=f"generation:{callback.from_user.id}:{uuid4().hex}",
        media=[],
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
    await state.update_data(mode=mode.value, product=product_for_mode(mode).value, media=[])
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
    mode = GenerationMode(str(data["mode"]))
    try:
        choice = model_choice(mode, slug)
    except KeyError:
        await callback.answer("Эта модель недоступна в выбранном сценарии.", show_alert=True)
        return
    await state.update_data(model_slug=choice.slug, model_title=choice.title)
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
    await state.update_data(prompt=prompt, editing_prompt=False)
    if editing and data.get("aspect_ratio"):
        await state.set_state(GenerationStates.confirming)
        await _show_confirmation_message(message, state, api_client)
        return

    mode = GenerationMode(str(data["mode"]))
    if mode_requires_media(mode):
        await state.set_state(GenerationStates.waiting_media)
        text = _media_prompt(mode)
        await message.answer(
            text,
            reply_markup=navigation_keyboard(
                media_done=mode_supports_multiple_media(mode)
            ),
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
    mode = GenerationMode(str(data["mode"]))
    media = list(data.get("media", []))
    if len(media) >= 6:
        await message.answer("Можно добавить не больше шести референсов.")
        return
    try:
        uploaded = await input_media.upload(
            bot=bot,
            message=message,
            user_id=message.from_user.id if message.from_user else 0,
        )
    except SubmissionError as exc:
        await message.answer(exc.public_message)
        return
    media.append({"kind": uploaded.kind, "url": uploaded.url})
    await state.update_data(media=media)

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
    if not data.get("media"):
        await callback.answer("Сначала добавьте хотя бы один референс.", show_alert=True)
        return
    mode = GenerationMode(str(data["mode"]))
    await state.set_state(GenerationStates.choosing_aspect_ratio)
    await _edit_callback(
        callback,
        "Референсы сохранены. Выберите формат результата:",
        aspect_ratio_keyboard(product_for_mode(mode)),
    )


@router.callback_query(GenerationStates.choosing_aspect_ratio, F.data.startswith("aspect:"))
async def choose_aspect_ratio(callback: CallbackQuery, state: FSMContext) -> None:
    ratio = (callback.data or "").partition(":")[2].replace("x", ":")
    data = await state.get_data()
    mode = GenerationMode(str(data["mode"]))
    await state.update_data(aspect_ratio=ratio)
    if product_for_mode(mode) == Product.IMAGE:
        await state.set_state(GenerationStates.choosing_quality)
        await _edit_callback(
            callback,
            "Выберите качество изображения:",
            image_quality_keyboard(),
        )
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
    await state.update_data(quality=quality)
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
    await state.update_data(duration=duration, resolution="720p")
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
    generate_audio = (callback.data or "") == "audio:yes"
    await state.update_data(generate_audio=generate_audio)
    await state.set_state(GenerationStates.confirming)
    await _show_confirmation_callback(callback, state, api_client)


@router.callback_query(GenerationStates.confirming, F.data == "draft:edit")
async def edit_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(editing_prompt=True)
    await state.set_state(GenerationStates.waiting_prompt)
    await _edit_callback(
        callback,
        "Отправьте новое описание. Остальные параметры сохранятся.",
        navigation_keyboard(),
    )


@router.callback_query(GenerationStates.confirming, F.data == "draft:confirm")
async def confirm_generation(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    data = await state.get_data()
    await state.set_state(GenerationStates.submitting)
    if callback.message:
        await callback.message.edit_text("⏳ Проверяю баланс и ставлю генерацию в очередь…")
    await callback.answer()

    try:
        payload = _provider_payload(data)
        queued = await api_client.submit(
            user_id=callback.from_user.id,
            username=callback.from_user.username,
            model_slug=str(data["model_slug"]),
            input_data=payload,
            idempotency_key=str(data["idempotency_key"]),
        )
    except FoxGenApiError as exc:
        await state.set_state(GenerationStates.confirming)
        if callback.message:
            await callback.message.edit_text(
                f"⚠️ {escape(exc.message)}\n\nПараметры сохранены.",
                reply_markup=confirmation_keyboard(),
            )
        return

    await state.clear()
    replay_text = "\nПовторный запрос распознан — новая задача не создавалась." if queued.replayed else ""
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
        product = Product(str(data["product"]))
        await state.set_state(GenerationStates.choosing_mode)
        await _edit_callback(callback, "Выберите сценарий:", mode_keyboard(product))
        return
    if current == GenerationStates.waiting_prompt.state:
        mode = GenerationMode(str(data["mode"]))
        await state.set_state(GenerationStates.choosing_model)
        await _edit_callback(callback, "Выберите модель:", model_keyboard(mode))
        return
    if current == GenerationStates.waiting_media.state:
        await state.update_data(media=[])
        await state.set_state(GenerationStates.waiting_prompt)
        await _edit_callback(
            callback,
            "Отправьте описание результата:",
            navigation_keyboard(),
        )
        return
    if current == GenerationStates.choosing_aspect_ratio.state:
        mode = GenerationMode(str(data["mode"]))
        target = GenerationStates.waiting_media if mode_requires_media(mode) else GenerationStates.waiting_prompt
        await state.set_state(target)
        text = _media_prompt(mode) if mode_requires_media(mode) else "Отправьте описание результата:"
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
        mode = GenerationMode(str(data["mode"]))
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
        mode = GenerationMode(str(data["mode"]))
        if product_for_mode(mode) == Product.IMAGE:
            await state.set_state(GenerationStates.choosing_quality)
            await _edit_callback(callback, "Выберите качество:", image_quality_keyboard())
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
    text = await _confirmation_text(state, api_client, callback.from_user.id)
    await _edit_callback(callback, text, confirmation_keyboard())


async def _show_confirmation_message(
    message: Message,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    user_id = message.from_user.id if message.from_user else 0
    text = await _confirmation_text(state, api_client, user_id)
    await message.answer(text, reply_markup=confirmation_keyboard())


async def _confirmation_text(
    state: FSMContext,
    api_client: FoxGenApiClient,
    user_id: int,
) -> str:
    data = await state.get_data()
    model_slug = str(data["model_slug"])
    try:
        prices = await api_client.prices()
        quote = prices.get(model_slug)
        balance = await api_client.balance(user_id)
    except FoxGenApiError as exc:
        return f"⚠️ {escape(exc.message)}\n\nПроверьте параметры и повторите попытку позже."
    if quote is None:
        return (
            "⚠️ Для этой модели пока не опубликована цена. "
            "Запуск заблокирован, чтобы не произошло неожиданного списания."
        )
    await state.update_data(price_units=quote.amount_units, currency=quote.currency)
    enough = balance.available_units >= quote.amount_units
    media_count = len(data.get("media", []))
    balance_line = (
        f"Доступно: {balance.available_units} {escape(balance.currency)}"
        if enough
        else f"⚠️ Доступно только {balance.available_units} {escape(balance.currency)}"
    )
    return (
        "<b>Проверьте генерацию</b>\n\n"
        f"Сценарий: {escape(MODE_TITLES[GenerationMode(str(data['mode']))])}\n"
        f"Модель: <b>{escape(str(data['model_title']))}</b>\n"
        f"Формат: {escape(str(data['aspect_ratio']))}\n"
        f"Медиа: {media_count}\n"
        f"Описание: {escape(str(data['prompt']))}\n\n"
        f"Стоимость: <b>{quote.amount_units} {escape(quote.currency)}</b>\n"
        f"{balance_line}\n\n"
        "Средства резервируются атомарно при постановке в очередь."
    )


def _provider_payload(data: dict[str, object]) -> dict[str, object]:
    mode = GenerationMode(str(data["mode"]))
    slug = str(data["model_slug"])
    prompt = str(data["prompt"])
    ratio = str(data["aspect_ratio"])
    media = list(data.get("media", []))

    if product_for_mode(mode) == Product.IMAGE:
        if slug.startswith("seedream-4-5"):
            payload: dict[str, object] = {
                "prompt": prompt,
                "aspect_ratio": ratio,
                "quality": str(data.get("quality", "basic")),
                "nsfw_checker": False,
            }
            if mode == GenerationMode.IMAGE_EDIT:
                payload["image_urls"] = [str(item["url"]) for item in media]
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
                payload["image_urls"] = [str(item["url"]) for item in media]
            return payload
        return {
            "prompt": prompt,
            "image_input": [str(item["url"]) for item in media],
            "aspect_ratio": ratio,
            "resolution": "1K",
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
        payload["first_frame_url"] = str(media[0]["url"])
    elif mode == GenerationMode.VIDEO_REFERENCE:
        payload["reference_image_urls"] = [
            str(item["url"]) for item in media if item["kind"] == "image"
        ]
        payload["reference_video_urls"] = [
            str(item["url"]) for item in media if item["kind"] == "video"
        ]
        payload["reference_audio_urls"] = [
            str(item["url"]) for item in media if item["kind"] == "audio"
        ]
    return payload


def _media_prompt(mode: GenerationMode) -> str:
    if mode == GenerationMode.IMAGE_EDIT:
        return "Отправьте изображение, которое нужно изменить."
    if mode == GenerationMode.VIDEO_IMAGE:
        return "Отправьте первый кадр — изображение, которое нужно оживить."
    return (
        "Отправляйте референсы по одному: изображения, видео или аудио. "
        "Когда закончите, нажмите «Референсы добавлены»."
    )


async def _edit_callback(callback: CallbackQuery, text: str, reply_markup: object) -> None:
    if callback.message:
        await callback.message.edit_text(text, reply_markup=reply_markup)
    await callback.answer()
