from __future__ import annotations

from html import escape
from uuid import uuid4

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from foxgen.bot.api_client import FoxGenApiClient, FoxGenApiError
from foxgen.bot.callbacks import safe_edit_callback_message
from foxgen.bot.keyboards import after_submit_keyboard, main_menu
from foxgen.bot.states import VoiceStates


router = Router(name="voice-tts")

TTS_MODEL_SLUG = "elevenlabs-turbo-2-5"
TTS_MODEL_TITLE = "ElevenLabs Turbo 2.5"
DEFAULT_VOICE = "Rachel"
DEFAULT_STABILITY = 0.5
DEFAULT_SIMILARITY_BOOST = 0.75
DEFAULT_STYLE = 0.0
DEFAULT_SPEED = 1.0
SPEED_OPTIONS = (0.8, 1.0, 1.2)


def _navigation_keyboard(*, back: bool = True) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if back:
        rows.append([InlineKeyboardButton(text="← Назад", callback_data="voice:back")])
    rows.append(
        [
            InlineKeyboardButton(text="Отмена", callback_data="nav:cancel"),
            InlineKeyboardButton(text="Меню", callback_data="nav:menu"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _voice_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Rachel · по умолчанию", callback_data="voice:default")],
            [InlineKeyboardButton(text="← Назад", callback_data="voice:back")],
            [
                InlineKeyboardButton(text="Отмена", callback_data="nav:cancel"),
                InlineKeyboardButton(text="Меню", callback_data="nav:menu"),
            ],
        ]
    )


def _speed_keyboard(selected: float) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{'✓ ' if selected == value else ''}{value:.1f}x",
                    callback_data=f"voice:speed:{value:.1f}",
                )
                for value in SPEED_OPTIONS
            ],
            [InlineKeyboardButton(text="← Назад", callback_data="voice:back")],
            [
                InlineKeyboardButton(text="Отмена", callback_data="nav:cancel"),
                InlineKeyboardButton(text="Меню", callback_data="nav:menu"),
            ],
        ]
    )


def _confirmation_keyboard(*, can_submit: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if can_submit:
        rows.append([InlineKeyboardButton(text="Создать озвучку", callback_data="voice:confirm")])
    else:
        rows.append([InlineKeyboardButton(text="Обновить цену и баланс", callback_data="voice:refresh")])
    rows.extend(
        [
            [
                InlineKeyboardButton(text="Изменить текст", callback_data="voice:edit:text"),
                InlineKeyboardButton(text="Изменить голос", callback_data="voice:edit:voice"),
            ],
            [InlineKeyboardButton(text="← Скорость", callback_data="voice:back")],
            [
                InlineKeyboardButton(text="Отмена", callback_data="nav:cancel"),
                InlineKeyboardButton(text="Меню", callback_data="nav:menu"),
            ],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _begin(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.update_data(
        model_slug=TTS_MODEL_SLUG,
        model_title=TTS_MODEL_TITLE,
        idempotency_key=f"tts:{callback.from_user.id}:{uuid4().hex}",
        voice=DEFAULT_VOICE,
        stability=DEFAULT_STABILITY,
        similarity_boost=DEFAULT_SIMILARITY_BOOST,
        style=DEFAULT_STYLE,
        speed=DEFAULT_SPEED,
        timestamps=False,
        previous_text="",
        next_text="",
        language_code="",
        can_submit=False,
    )
    await state.set_state(VoiceStates.waiting_text)
    await safe_edit_callback_message(
        callback,
        (
            "<b>Озвучка · ElevenLabs Turbo 2.5</b>\n\n"
            "Отправьте текст для озвучки одним сообщением. "
            "После этого выберем голос и скорость."
        ),
        _navigation_keyboard(back=False),
    )


@router.callback_query(F.data == "create:voice")
async def begin_voice(callback: CallbackQuery, state: FSMContext) -> None:
    await _begin(callback, state)


@router.message(VoiceStates.waiting_text, F.text)
async def receive_text(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if len(text) < 1:
        await message.answer("Отправьте текст, который нужно озвучить.")
        return
    if len(text) > 3900:
        await message.answer(
            "Одно Telegram-сообщение для этого сценария ограничено 3900 символами. "
            "Сократите текст или разделите озвучку на несколько запусков."
        )
        return
    await state.update_data(text=text, can_submit=False)
    await state.set_state(VoiceStates.waiting_voice)
    await message.answer(
        (
            "<b>Голос</b>\n\n"
            "Нажмите Rachel для быстрого старта или отправьте имя/ID другого "
            "доступного ElevenLabs-голоса."
        ),
        reply_markup=_voice_keyboard(),
    )


async def _accept_voice(value: str, message: Message, state: FSMContext) -> None:
    voice = value.strip()
    if not voice or len(voice) > 128:
        await message.answer("Имя/ID голоса должно содержать от 1 до 128 символов.")
        return
    await state.update_data(voice=voice, can_submit=False)
    await state.set_state(VoiceStates.choosing_speed)
    await message.answer(
        "<b>Скорость речи</b>\n\nВыберите один из безопасных пресетов:",
        reply_markup=_speed_keyboard(DEFAULT_SPEED),
    )


@router.message(VoiceStates.waiting_voice, F.text)
async def receive_voice(message: Message, state: FSMContext) -> None:
    await _accept_voice(message.text or "", message, state)


@router.callback_query(VoiceStates.waiting_voice, F.data == "voice:default")
async def choose_default_voice(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(voice=DEFAULT_VOICE, can_submit=False)
    await state.set_state(VoiceStates.choosing_speed)
    await safe_edit_callback_message(
        callback,
        "<b>Скорость речи</b>\n\nВыберите один из безопасных пресетов:",
        _speed_keyboard(DEFAULT_SPEED),
    )


@router.callback_query(VoiceStates.choosing_speed, F.data.startswith("voice:speed:"))
async def choose_speed(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    raw = (callback.data or "").rsplit(":", 1)[-1]
    try:
        speed = float(raw)
    except ValueError:
        await callback.answer("Некорректная скорость.", show_alert=True)
        return
    if speed not in SPEED_OPTIONS:
        await callback.answer("Этот пресет скорости недоступен.", show_alert=True)
        return
    await state.update_data(speed=speed, can_submit=False)
    await state.set_state(VoiceStates.confirming)
    await _show_confirmation_callback(callback, state, api_client)


async def _confirmation(
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

    quote = prices.get(TTS_MODEL_SLUG)
    if quote is None:
        await state.update_data(can_submit=False)
        return (
            "⚠️ Для ElevenLabs Turbo 2.5 ещё не опубликована активная цена. "
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
    text = str(data.get("text", ""))
    preview = text if len(text) <= 280 else f"{text[:277]}…"
    voice = str(data.get("voice", DEFAULT_VOICE))
    speed = float(data.get("speed", DEFAULT_SPEED))
    balance_line = (
        f"Доступно: {balance.available_units} {escape(balance.currency)}"
        if enough
        else f"⚠️ Доступно только {balance.available_units} {escape(balance.currency)}"
    )
    return (
        "<b>Проверьте озвучку</b>\n\n"
        f"Модель: <b>{escape(TTS_MODEL_TITLE)}</b>\n"
        f"Голос: <b>{escape(voice)}</b>\n"
        f"Скорость: {speed:.1f}x\n"
        f"Текст: {escape(preview)}\n\n"
        f"Стоимость: <b>{quote.amount_units} {escape(quote.currency)}</b>\n"
        f"{balance_line}\n\n"
        "Средства резервируются атомарно при постановке задачи в очередь.",
        enough,
    )


async def _show_confirmation_callback(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    text, can_submit = await _confirmation(state, api_client, callback.from_user.id)
    await safe_edit_callback_message(
        callback,
        text,
        _confirmation_keyboard(can_submit=can_submit),
    )


@router.callback_query(VoiceStates.confirming, F.data == "voice:refresh")
async def refresh_confirmation(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    await _show_confirmation_callback(callback, state, api_client)


@router.callback_query(VoiceStates.confirming, F.data == "voice:edit:text")
async def edit_text(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(can_submit=False)
    await state.set_state(VoiceStates.waiting_text)
    await safe_edit_callback_message(
        callback,
        "Отправьте новый текст для озвучки:",
        _navigation_keyboard(),
    )


@router.callback_query(VoiceStates.confirming, F.data == "voice:edit:voice")
async def edit_voice(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(can_submit=False)
    await state.set_state(VoiceStates.waiting_voice)
    await safe_edit_callback_message(
        callback,
        "Отправьте новое имя/ID голоса или выберите Rachel:",
        _voice_keyboard(),
    )


@router.callback_query(VoiceStates.confirming, F.data == "voice:confirm")
async def confirm_voice(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    data = await state.get_data()
    if not bool(data.get("can_submit")):
        await callback.answer("Сначала дождитесь доступной цены и достаточного баланса.", show_alert=True)
        return

    await state.set_state(VoiceStates.submitting)
    await safe_edit_callback_message(
        callback,
        "Ставлю озвучку в очередь…",
        answer_callback=False,
    )
    try:
        result = await api_client.submit(
            user_id=callback.from_user.id,
            username=callback.from_user.username,
            model_slug=TTS_MODEL_SLUG,
            input_data={
                "text": str(data.get("text", "")),
                "voice": str(data.get("voice", DEFAULT_VOICE)),
                "stability": DEFAULT_STABILITY,
                "similarity_boost": DEFAULT_SIMILARITY_BOOST,
                "style": DEFAULT_STYLE,
                "speed": float(data.get("speed", DEFAULT_SPEED)),
                "timestamps": False,
                "previous_text": "",
                "next_text": "",
                "language_code": "",
            },
            idempotency_key=str(data.get("idempotency_key", "")),
        )
    except FoxGenApiError as exc:
        await state.set_state(VoiceStates.confirming)
        await state.update_data(can_submit=False)
        if callback.message:
            await callback.message.answer(
                f"⚠️ {escape(exc.message)}\n\nПроверьте цену/баланс и повторите.",
                reply_markup=_confirmation_keyboard(can_submit=False),
            )
        return

    await state.clear()
    if callback.message:
        replay = "\nПовторный клик безопасно переиспользовал существующую задачу." if result.replayed else ""
        await callback.message.answer(
            (
                "✅ <b>Озвучка поставлена в очередь</b>\n\n"
                f"ID: <code>{escape(result.generation_id)}</code>\n"
                "Готовый аудиофайл придёт через обычный FoxGen delivery pipeline."
                f"{replay}"
            ),
            reply_markup=after_submit_keyboard(),
        )


@router.callback_query(VoiceStates.submitting, F.data == "voice:confirm")
async def duplicate_submit(callback: CallbackQuery) -> None:
    await callback.answer("Озвучка уже ставится в очередь.")


@router.callback_query(
    VoiceStates.waiting_text,
    F.data == "voice:back",
)
async def back_from_text(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await safe_edit_callback_message(callback, "Главное меню", main_menu())


@router.callback_query(
    VoiceStates.waiting_voice,
    F.data == "voice:back",
)
async def back_from_voice(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(VoiceStates.waiting_text)
    await safe_edit_callback_message(
        callback,
        "Отправьте текст для озвучки:",
        _navigation_keyboard(back=False),
    )


@router.callback_query(
    VoiceStates.choosing_speed,
    F.data == "voice:back",
)
async def back_from_speed(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(VoiceStates.waiting_voice)
    await safe_edit_callback_message(
        callback,
        "Отправьте имя/ID голоса или выберите Rachel:",
        _voice_keyboard(),
    )


@router.callback_query(
    VoiceStates.confirming,
    F.data == "voice:back",
)
async def back_from_confirmation(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    selected = float(data.get("speed", DEFAULT_SPEED))
    await state.update_data(can_submit=False)
    await state.set_state(VoiceStates.choosing_speed)
    await safe_edit_callback_message(
        callback,
        "Выберите скорость речи:",
        _speed_keyboard(selected),
    )


@router.message(VoiceStates.choosing_speed)
async def invalid_speed_message(message: Message) -> None:
    await message.answer("Выберите скорость кнопкой ниже: 0.8x, 1.0x или 1.2x.")


@router.message(VoiceStates.confirming)
async def invalid_confirmation_message(message: Message) -> None:
    await message.answer("Используйте кнопки подтверждения, изменения текста/голоса или отмены.")
