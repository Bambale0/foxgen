from __future__ import annotations

from html import escape

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from foxgen.bot.api_client import FoxGenApiClient, FoxGenApiError
from foxgen.bot.callbacks import safe_edit_callback_message
from foxgen.bot.generation_draft import (
    image_capability,
    required_text,
    stored_media,
    submission_model_slug,
    video_capability,
    video_media_complete,
    video_media_requirement,
    video_type,
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
from foxgen.bot.keyboards import confirmation_keyboard
from foxgen.bot.states import GenerationStates


async def render_image_model(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(image_flow_step="select_model", can_submit=False)
    await state.set_state(GenerationStates.image_selecting_model)
    await safe_edit_callback_message(
        callback,
        "<b>Создать фото · 1/4</b>\n\nВыберите модель. Дальше можно добавить референсы.",
        image_model_keyboard(str(data.get("image_model_key") or "")),
    )


async def render_image_references(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    capability = image_capability(data)
    media = stored_media(data)
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


async def render_image_settings(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    capability = image_capability(data)
    await state.update_data(image_flow_step="settings", can_submit=False)
    await state.set_state(GenerationStates.image_configuring)
    await safe_edit_callback_message(
        callback,
        image_settings_text(data),
        image_settings_keyboard(capability, data),
    )


async def render_image_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    caption = str(data.get("reference_caption") or "").strip()
    hint = ""
    if 3 <= len(caption) <= 3500:
        hint = "\n\nПодпись исходного референса сохранена. Можно отправить её снова или написать новый промпт."
    await state.update_data(image_flow_step="prompt", can_submit=False)
    await state.set_state(GenerationStates.image_waiting_prompt)
    await safe_edit_callback_message(
        callback,
        (
            "<b>Создать фото · 4/4</b>\n\n"
            "Опишите результат обычными словами: сюжет, стиль, свет, композицию и важные ограничения."
            f"{hint}"
        ),
        prompt_keyboard(),
    )


async def render_video_model(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(video_flow_step="select_model", can_submit=False)
    await state.set_state(GenerationStates.video_selecting_model)
    await safe_edit_callback_message(
        callback,
        "<b>Создать видео · 1/5</b>\n\nВыберите модель:",
        video_model_keyboard(str(data.get("video_model_key") or "")),
    )


async def render_video_type(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    capability = video_capability(data)
    current = video_type(data)
    await state.update_data(video_flow_step="select_type", can_submit=False)
    await state.set_state(GenerationStates.video_selecting_type)
    await safe_edit_callback_message(
        callback,
        "<b>Создать видео · 2/5</b>\n\nЧто используем как вход?",
        video_type_keyboard(capability, current),
    )


async def render_video_media(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    generation_type = video_type(data)
    media = stored_media(data)
    await state.update_data(video_flow_step="media", can_submit=False)
    await state.set_state(GenerationStates.video_uploading_media)
    await safe_edit_callback_message(
        callback,
        f"<b>Создать видео · 3/5</b>\n\n{escape(video_media_requirement(generation_type))}",
        video_media_keyboard(
            generation_type=generation_type,
            count=len(media),
            can_continue=video_media_complete(generation_type, media),
        ),
    )


async def render_video_settings(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    capability = video_capability(data)
    await state.update_data(video_flow_step="settings", can_submit=False)
    await state.set_state(GenerationStates.video_configuring)
    await safe_edit_callback_message(
        callback,
        video_settings_text(data),
        video_settings_keyboard(capability, data),
    )


async def render_video_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    caption = str(data.get("reference_caption") or "").strip()
    hint = ""
    if 3 <= len(caption) <= 3500:
        hint = (
            "\n\nПодпись исходного референса сохранена. Можно использовать её как основу промпта."
        )
    await state.update_data(video_flow_step="prompt", can_submit=False)
    await state.set_state(GenerationStates.video_waiting_prompt)
    await safe_edit_callback_message(
        callback,
        (
            "<b>Создать видео · 5/5</b>\n\n"
            "Опишите сцену, движение камеры/объектов, темп, свет, звук и ограничения."
            f"{hint}"
        ),
        prompt_keyboard(),
    )


async def render_confirmation_callback(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    text, can_submit = await confirmation_text(state, api_client, callback.from_user.id)
    await safe_edit_callback_message(
        callback,
        text,
        confirmation_keyboard(can_submit=can_submit),
    )


async def render_confirmation_message(
    message: Message,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    user_id = message.from_user.id if message.from_user else 0
    text, can_submit = await confirmation_text(state, api_client, user_id)
    await message.answer(text, reply_markup=confirmation_keyboard(can_submit=can_submit))


async def confirmation_text(
    state: FSMContext,
    api_client: FoxGenApiClient,
    user_id: int,
) -> tuple[str, bool]:
    data = await state.get_data()
    model_slug = submission_model_slug(data)
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
        f"{wizard_summary(data)}\n\n"
        f"Промпт: {escape(required_text(data, 'prompt'))}\n\n"
        f"Стоимость: <b>{quote.amount_units} {escape(quote.currency)}</b>\n"
        f"{balance_line}\n\n"
        "Средства резервируются атомарно при постановке в очередь.",
        enough,
    )


def image_settings_text(data: dict[str, object]) -> str:
    capability = image_capability(data)
    lines = [
        "<b>Создать фото · 3/4</b>",
        "",
        f"Модель: <b>{escape(capability.title)}</b>",
        f"Референсы: {len(stored_media(data))}",
        f"Формат: {escape(str(data.get('aspect_ratio') or capability.default_aspect_ratio))}",
    ]
    if capability.resolutions:
        lines.append(
            f"Разрешение: {escape(str(data.get('resolution') or capability.default_resolution))}"
        )
    if capability.qualities:
        lines.append(f"Качество: {escape(str(data.get('quality') or capability.default_quality))}")
    lines.append(
        f"Файл: {escape(str(data.get('output_format') or capability.default_output_format)).upper()}"
    )
    lines.extend(("", "Настройки меняются на этом же экране — без лишних переходов."))
    return "\n".join(lines)


def video_settings_text(data: dict[str, object]) -> str:
    capability = video_capability(data)
    return (
        "<b>Создать видео · 4/5</b>\n\n"
        f"Модель: <b>{escape(capability.title)}</b>\n"
        f"Тип: {escape(video_type(data).value)}\n"
        f"Формат: {escape(str(data.get('aspect_ratio') or capability.default_aspect_ratio))}\n"
        f"Длительность: {int(data.get('duration') or capability.default_duration)} сек.\n"
        f"Разрешение: {escape(str(data.get('resolution') or capability.default_resolution))}\n"
        f"Звук: {'да' if bool(data.get('generate_audio')) else 'нет'}\n"
        f"Вернуть последний кадр: {'да' if bool(data.get('return_last_frame')) else 'нет'}\n"
        f"Web search: {'да' if bool(data.get('web_search')) else 'нет'}\n\n"
        "Настройки меняются на этом же экране."
    )


def wizard_summary(data: dict[str, object]) -> str:
    if data.get("generation_type") == "image":
        capability = image_capability(data)
        details = [
            f"Модель: <b>{escape(capability.title)}</b>",
            f"Референсы: {len(stored_media(data))}",
            f"Формат: {escape(required_text(data, 'aspect_ratio'))}",
        ]
        if capability.resolutions:
            details.append(f"Разрешение: {escape(str(data.get('resolution') or '1K'))}")
        if capability.qualities:
            details.append(f"Качество: {escape(str(data.get('quality') or 'basic'))}")
        details.append(f"Файл: {escape(str(data.get('output_format') or 'png')).upper()}")
        return "\n".join(details)

    capability = video_capability(data)
    return (
        f"Модель: <b>{escape(capability.title)}</b>\n"
        f"Тип: {escape(video_type(data).value)}\n"
        f"Медиа: {len(stored_media(data))}\n"
        f"Формат: {escape(required_text(data, 'aspect_ratio'))}\n"
        f"Длительность: {int(data.get('duration') or capability.default_duration)} сек.\n"
        f"Звук: {'да' if bool(data.get('generate_audio')) else 'нет'}"
    )
