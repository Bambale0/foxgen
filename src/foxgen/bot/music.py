from __future__ import annotations

from html import escape
from uuid import uuid4

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from foxgen.bot.api_client import FoxGenApiClient, FoxGenApiError
from foxgen.bot.callbacks import safe_edit_callback_message
from foxgen.bot.keyboards import after_submit_keyboard, main_menu
from foxgen.bot.states import MusicStates


router = Router(name="music-suno")

SUNO_MODEL_SLUG = "suno-v5"
SUNO_MODEL_TITLE = "Suno V5"


def _nav(*, back: bool = True) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if back:
        rows.append([InlineKeyboardButton(text="← Назад", callback_data="music:back")])
    rows.append(
        [
            InlineKeyboardButton(text="Отмена", callback_data="nav:cancel"),
            InlineKeyboardButton(text="Меню", callback_data="nav:menu"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚡ Быстро", callback_data="music:mode:simple")],
            [InlineKeyboardButton(text="🎛 Кастомно", callback_data="music:mode:custom")],
            [InlineKeyboardButton(text="← Меню", callback_data="music:back")],
            [InlineKeyboardButton(text="Отмена", callback_data="nav:cancel")],
        ]
    )


def _vocal_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎤 С вокалом", callback_data="music:vocal:no"),
                InlineKeyboardButton(text="🎹 Инструментал", callback_data="music:vocal:yes"),
            ],
            [InlineKeyboardButton(text="← Назад", callback_data="music:back")],
            [InlineKeyboardButton(text="Отмена", callback_data="nav:cancel")],
        ]
    )


def _confirmation_keyboard(*, can_submit: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if can_submit:
        rows.append([InlineKeyboardButton(text="Создать музыку", callback_data="music:confirm")])
    else:
        rows.append([InlineKeyboardButton(text="Обновить цену и баланс", callback_data="music:refresh")])
    rows.extend(
        [
            [InlineKeyboardButton(text="← Назад", callback_data="music:back")],
            [
                InlineKeyboardButton(text="Отмена", callback_data="nav:cancel"),
                InlineKeyboardButton(text="Меню", callback_data="nav:menu"),
            ],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_mode(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(MusicStates.choosing_mode)
    await safe_edit_callback_message(
        callback,
        (
            "<b>Музыка · Suno V5</b>\n\n"
            "Быстро — один prompt.\n"
            "Кастомно — отдельно стиль и название."
        ),
        _mode_keyboard(),
    )


@router.callback_query(F.data.in_({"create:music", "planned:music"}))
async def begin_music(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.update_data(
        model_slug=SUNO_MODEL_SLUG,
        model_title=SUNO_MODEL_TITLE,
        idempotency_key=f"music:{callback.from_user.id}:{uuid4().hex}",
        custom_mode=False,
        instrumental=False,
        prompt="",
        style="",
        title="",
        negative_tags="",
        can_submit=False,
    )
    await _show_mode(callback, state)


@router.callback_query(MusicStates.choosing_mode, F.data.startswith("music:mode:"))
async def choose_mode(callback: CallbackQuery, state: FSMContext) -> None:
    custom = (callback.data or "").endswith(":custom")
    await state.update_data(
        custom_mode=custom,
        prompt="",
        style="",
        title="",
        can_submit=False,
    )
    await state.set_state(MusicStates.choosing_vocal_mode)
    await safe_edit_callback_message(
        callback,
        "<b>Тип трека</b>\n\nНужен вокал или чистый инструментал?",
        _vocal_keyboard(),
    )


@router.callback_query(MusicStates.choosing_vocal_mode, F.data.startswith("music:vocal:"))
async def choose_vocal_mode(callback: CallbackQuery, state: FSMContext) -> None:
    instrumental = (callback.data or "").endswith(":yes")
    await state.update_data(instrumental=instrumental, can_submit=False)
    data = await state.get_data()
    if bool(data.get("custom_mode")) and instrumental:
        await state.set_state(MusicStates.waiting_style)
        await safe_edit_callback_message(
            callback,
            (
                "<b>Стиль музыки</b>\n\n"
                "Например: cinematic synthwave, dark electronic, 120 BPM."
            ),
            _nav(),
        )
        return
    await state.set_state(MusicStates.waiting_prompt)
    prompt_hint = (
        "Опишите песню/лирику и настроение. В custom mode это поле может быть до 5000 символов."
        if bool(data.get("custom_mode"))
        else "Опишите желаемую музыку одним prompt до 500 символов."
    )
    await safe_edit_callback_message(
        callback,
        f"<b>Prompt</b>\n\n{prompt_hint}",
        _nav(),
    )


@router.message(MusicStates.waiting_prompt, F.text)
async def receive_prompt(message: Message, state: FSMContext) -> None:
    prompt = (message.text or "").strip()
    data = await state.get_data()
    limit = 5000 if bool(data.get("custom_mode")) else 500
    if not prompt:
        await message.answer("Prompt не может быть пустым.")
        return
    if len(prompt) > limit:
        await message.answer(f"Для выбранного режима prompt ограничен {limit} символами.")
        return
    await state.update_data(prompt=prompt, can_submit=False)
    if bool(data.get("custom_mode")):
        await state.set_state(MusicStates.waiting_style)
        await message.answer(
            "<b>Стиль музыки</b>\n\nНапример: indie pop, warm female vocal, analog synths.",
            reply_markup=_nav(),
        )
        return
    await state.set_state(MusicStates.confirming)
    await _show_confirmation_message(message, state)


@router.message(MusicStates.waiting_style, F.text)
async def receive_style(message: Message, state: FSMContext) -> None:
    style = (message.text or "").strip()
    if not style:
        await message.answer("Стиль не может быть пустым в кастомном режиме.")
        return
    if len(style) > 1000:
        await message.answer("Стиль ограничен 1000 символами для Suno V5.")
        return
    await state.update_data(style=style, can_submit=False)
    await state.set_state(MusicStates.waiting_title)
    await message.answer(
        "<b>Название трека</b>\n\nДо 80 символов.",
        reply_markup=_nav(),
    )


@router.message(MusicStates.waiting_title, F.text)
async def receive_title(
    message: Message,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    title = (message.text or "").strip()
    if not title:
        await message.answer("Название не может быть пустым в кастомном режиме.")
        return
    if len(title) > 80:
        await message.answer("Название ограничено 80 символами.")
        return
    await state.update_data(title=title, can_submit=False)
    await state.set_state(MusicStates.confirming)
    await _show_confirmation_message(message, state, api_client)


async def _quote(
    state: FSMContext,
    api_client: FoxGenApiClient,
    user_id: int,
) -> tuple[str, bool]:
    data = await state.get_data()
    try:
        prices = await api_client.prices()
        balance = await api_client.balance(user_id)
    except FoxGenApiError as exc:
        await state.update_data(can_submit=False)
        return f"⚠️ {escape(exc.message)}\n\nПовторите проверку позже.", False

    quote = prices.get(SUNO_MODEL_SLUG)
    if quote is None:
        await state.update_data(can_submit=False)
        return (
            "⚠️ Для Suno V5 ещё не опубликована активная цена. "
            "Запуск заблокирован до явной публикации тарифа.",
            False,
        )
    enough = balance.available_units >= quote.amount_units
    await state.update_data(
        price_units=quote.amount_units,
        price_version=quote.version,
        currency=quote.currency,
        can_submit=enough,
    )
    prompt = str(data.get("prompt", "")).strip()
    style = str(data.get("style", "")).strip()
    title = str(data.get("title", "")).strip()
    preview = prompt if len(prompt) <= 260 else f"{prompt[:257]}…"
    lines = [
        "<b>Проверьте музыку</b>",
        "",
        f"Модель: <b>{SUNO_MODEL_TITLE}</b>",
        f"Режим: {'кастомный' if bool(data.get('custom_mode')) else 'быстрый'}",
        f"Тип: {'инструментал' if bool(data.get('instrumental')) else 'с вокалом'}",
    ]
    if preview:
        lines.append(f"Prompt: {escape(preview)}")
    if style:
        lines.append(f"Стиль: {escape(style)}")
    if title:
        lines.append(f"Название: {escape(title)}")
    lines.extend(
        [
            "",
            f"Стоимость: <b>{quote.amount_units} {escape(quote.currency)}</b>",
            (
                f"Доступно: {balance.available_units} {escape(balance.currency)}"
                if enough
                else f"⚠️ Доступно только {balance.available_units} {escape(balance.currency)}"
            ),
            "",
            "Suno обычно возвращает несколько вариантов; FoxGen сохранит каждый аудиотрек.",
        ]
    )
    return "\n".join(lines), enough


async def _show_confirmation_message(
    message: Message,
    state: FSMContext,
    api_client: FoxGenApiClient | None = None,
) -> None:
    if api_client is None:
        await message.answer("Проверяю цену… Откройте /menu и повторите шаг.")
        return
    text, can_submit = await _quote(state, api_client, message.from_user.id)
    await message.answer(text, reply_markup=_confirmation_keyboard(can_submit=can_submit))


async def _show_confirmation_callback(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    text, can_submit = await _quote(state, api_client, callback.from_user.id)
    await safe_edit_callback_message(
        callback,
        text,
        _confirmation_keyboard(can_submit=can_submit),
    )


@router.callback_query(MusicStates.confirming, F.data == "music:refresh")
async def refresh_music(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    await _show_confirmation_callback(callback, state, api_client)


@router.callback_query(MusicStates.confirming, F.data == "music:confirm")
async def confirm_music(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    data = await state.get_data()
    if not bool(data.get("can_submit")):
        await callback.answer(
            "Сначала дождитесь доступной цены и достаточного баланса.",
            show_alert=True,
        )
        return

    await state.set_state(MusicStates.submitting)
    await safe_edit_callback_message(
        callback,
        "Ставлю музыку в очередь…",
        answer_callback=False,
    )
    input_data: dict[str, object] = {
        "custom_mode": bool(data.get("custom_mode")),
        "instrumental": bool(data.get("instrumental")),
        "prompt": str(data.get("prompt", "")),
        "style": str(data.get("style", "")),
        "title": str(data.get("title", "")),
        "negative_tags": str(data.get("negative_tags", "")),
    }
    try:
        result = await api_client.submit(
            user_id=callback.from_user.id,
            username=callback.from_user.username,
            model_slug=SUNO_MODEL_SLUG,
            input_data=input_data,
            idempotency_key=str(data.get("idempotency_key", "")),
        )
    except FoxGenApiError as exc:
        await state.set_state(MusicStates.confirming)
        await state.update_data(can_submit=False)
        if callback.message:
            await callback.message.answer(
                f"⚠️ {escape(exc.message)}\n\nПроверьте цену/баланс и повторите.",
                reply_markup=_confirmation_keyboard(can_submit=False),
            )
        return

    await state.clear()
    if callback.message:
        replay = (
            "\nПовторный клик безопасно переиспользовал существующую задачу."
            if result.replayed
            else ""
        )
        await callback.message.answer(
            (
                "✅ <b>Музыка поставлена в очередь</b>\n\n"
                f"ID: <code>{escape(result.generation_id)}</code>\n"
                "Все готовые варианты будут сохранены и доставлены через общий media pipeline."
                f"{replay}"
            ),
            reply_markup=after_submit_keyboard(result.generation_id),
        )


@router.callback_query(MusicStates.submitting, F.data == "music:confirm")
async def duplicate_music_submit(callback: CallbackQuery) -> None:
    await callback.answer("Музыка уже ставится в очередь.")


@router.callback_query(MusicStates.choosing_mode, F.data == "music:back")
async def back_from_mode(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await safe_edit_callback_message(callback, "Главное меню", main_menu())


@router.callback_query(MusicStates.choosing_vocal_mode, F.data == "music:back")
async def back_from_vocal(callback: CallbackQuery, state: FSMContext) -> None:
    await _show_mode(callback, state)


@router.callback_query(MusicStates.waiting_prompt, F.data == "music:back")
async def back_from_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(MusicStates.choosing_vocal_mode)
    await safe_edit_callback_message(
        callback,
        "<b>Тип трека</b>\n\nНужен вокал или чистый инструментал?",
        _vocal_keyboard(),
    )


@router.callback_query(MusicStates.waiting_style, F.data == "music:back")
async def back_from_style(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if bool(data.get("instrumental")):
        await state.set_state(MusicStates.choosing_vocal_mode)
        await safe_edit_callback_message(
            callback,
            "<b>Тип трека</b>\n\nНужен вокал или чистый инструментал?",
            _vocal_keyboard(),
        )
        return
    await state.set_state(MusicStates.waiting_prompt)
    await safe_edit_callback_message(callback, "Отправьте prompt песни:", _nav())


@router.callback_query(MusicStates.waiting_title, F.data == "music:back")
async def back_from_title(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(MusicStates.waiting_style)
    await safe_edit_callback_message(callback, "Отправьте стиль музыки:", _nav())


@router.callback_query(MusicStates.confirming, F.data == "music:back")
async def back_from_confirmation(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(can_submit=False)
    if bool(data.get("custom_mode")):
        await state.set_state(MusicStates.waiting_title)
        await safe_edit_callback_message(callback, "Отправьте название трека:", _nav())
        return
    await state.set_state(MusicStates.waiting_prompt)
    await safe_edit_callback_message(callback, "Отправьте prompt музыки:", _nav())


@router.message(MusicStates.choosing_mode)
@router.message(MusicStates.choosing_vocal_mode)
@router.message(MusicStates.confirming)
async def invalid_music_message(message: Message) -> None:
    await message.answer("Используйте кнопки текущего шага или /menu.")
