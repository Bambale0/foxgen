from __future__ import annotations

from html import escape
from uuid import uuid4

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from foxgen.bot.api_client import FoxGenApiClient, FoxGenApiError
from foxgen.bot.callbacks import safe_edit_callback_message
from foxgen.bot.keyboards import after_submit_keyboard
from foxgen.bot.states import MusicExtendStates, MusicUploadExtendStates
from foxgen.bot.suno_upload_extend_transport import (
    SunoUploadExtendTransportError,
    submit_suno_upload_extend,
)
from foxgen.bot.uploads import TelegramInputMediaStorage, message_media_kind
from foxgen.core.errors import SubmissionError

router = Router(name="music-suno-upload-extend")
MODEL_SLUG = "suno-v5-upload-extend"


def _button(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def _mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Быстро продолжить", "music:upload-extend:mode:simple")],
            [_button("Кастомное продолжение", "music:upload-extend:mode:custom")],
            [_button("Отмена", "nav:cancel"), _button("Меню", "nav:menu")],
        ]
    )


def _vocal_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("С вокалом", "music:upload-extend:vocal:yes")],
            [_button("Инструментал", "music:upload-extend:vocal:no")],
            [_button("← Назад", "music:upload-extend:back:mode")],
            [_button("Отмена", "nav:cancel"), _button("Меню", "nav:menu")],
        ]
    )


def _nav(back: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("← Назад", back)],
            [_button("Отмена", "nav:cancel"), _button("Меню", "nav:menu")],
        ]
    )


def _confirm_keyboard(can_submit: bool) -> InlineKeyboardMarkup:
    primary = (
        [_button("Запустить Upload & Extend", "music:upload-extend:confirm")]
        if can_submit
        else [_button("Обновить цену и баланс", "music:upload-extend:refresh")]
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            primary,
            [_button("← Назад", "music:upload-extend:back:confirm")],
            [_button("Отмена", "nav:cancel"), _button("Меню", "nav:menu")],
        ]
    )


@router.callback_query(
    MusicExtendStates.choosing_action,
    F.data == "music:upload-extend:start",
)
async def begin_upload_extend(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.update_data(
        idempotency_key=f"suno-upload-extend:{callback.from_user.id}:{uuid4().hex}",
        media=[],
        can_submit=False,
    )
    await state.set_state(MusicUploadExtendStates.waiting_audio)
    await safe_edit_callback_message(
        callback,
        (
            "<b>Suno Upload & Extend</b>\n\n"
            "Отправьте один аудиофайл, voice-message или аудио-документ. "
            "FoxGen сохранит его приватно; внешний URL вводить не нужно."
        ),
        _nav("music:upload-extend:back:hub"),
    )


@router.message(
    MusicUploadExtendStates.waiting_audio,
    F.audio | F.voice | F.document,
)
async def receive_upload_extend_audio(
    message: Message,
    state: FSMContext,
    bot: Bot,
    input_media: TelegramInputMediaStorage,
) -> None:
    try:
        if message_media_kind(message) != "audio":
            await message.answer("Для Suno Upload & Extend нужен именно аудиофайл.")
            return
        user_id = message.from_user.id if message.from_user is not None else 0
        uploaded = await input_media.upload(
            bot=bot,
            message=message,
            user_id=user_id,
        )
    except SubmissionError as exc:
        await message.answer(exc.public_message)
        return

    await state.update_data(
        media=[{"kind": "audio", "storage_key": uploaded.storage_key}],
        input_storage_key=uploaded.storage_key,
        default_param_flag=False,
        instrumental=False,
        prompt="",
        style="",
        title="",
        continue_at=None,
        negative_tags="",
        can_submit=False,
    )
    await state.set_state(MusicUploadExtendStates.choosing_mode)
    await message.answer(
        "<b>Аудио сохранено</b>\n\nКак продолжить трек?",
        reply_markup=_mode_keyboard(),
    )


@router.message(MusicUploadExtendStates.waiting_audio)
async def invalid_upload_extend_audio(message: Message) -> None:
    await message.answer("Отправьте один аудиофайл или voice-message.")


@router.callback_query(
    MusicUploadExtendStates.choosing_mode,
    F.data.in_(
        {
            "music:upload-extend:mode:simple",
            "music:upload-extend:mode:custom",
        }
    ),
)
async def choose_upload_extend_mode(callback: CallbackQuery, state: FSMContext) -> None:
    custom = (callback.data or "").endswith(":custom")
    await state.update_data(
        default_param_flag=custom,
        instrumental=False,
        prompt="",
        style="",
        title="",
        continue_at=None,
        negative_tags="",
        can_submit=False,
    )
    if not custom:
        await state.set_state(MusicUploadExtendStates.waiting_prompt)
        await safe_edit_callback_message(
            callback,
            (
                "<b>Как продолжить трек?</b>\n\n"
                "Опишите продолжение. Быстрый режим использует только загруженное аудио "
                "и prompt, остальные параметры наследует Suno."
            ),
            _nav("music:upload-extend:back:mode"),
        )
        return

    await state.set_state(MusicUploadExtendStates.choosing_vocal_mode)
    await safe_edit_callback_message(
        callback,
        "<b>Тип продолжения</b>\n\nВыберите вокальное или инструментальное продолжение.",
        _vocal_keyboard(),
    )


@router.callback_query(
    MusicUploadExtendStates.choosing_vocal_mode,
    F.data.in_({"music:upload-extend:vocal:yes", "music:upload-extend:vocal:no"}),
)
async def choose_upload_extend_vocal(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not bool(data.get("default_param_flag")):
        await callback.answer(
            "Тип результата настраивается только в кастомном режиме.",
            show_alert=True,
        )
        return
    instrumental = (callback.data or "").endswith(":no")
    await state.update_data(instrumental=instrumental, can_submit=False)
    if instrumental:
        await state.set_state(MusicUploadExtendStates.waiting_style)
        await safe_edit_callback_message(
            callback,
            "<b>Стиль продолжения</b>\n\nНапример: cinematic orchestral, synthwave, acoustic folk.",
            _nav("music:upload-extend:back:vocal"),
        )
        return
    await state.set_state(MusicUploadExtendStates.waiting_prompt)
    await safe_edit_callback_message(
        callback,
        "<b>Prompt</b>\n\nОпишите вокальное продолжение. Лимит — 5000 символов.",
        _nav("music:upload-extend:back:vocal"),
    )


@router.message(MusicUploadExtendStates.waiting_prompt, F.text)
async def receive_upload_extend_prompt(
    message: Message,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    prompt = (message.text or "").strip()
    if not prompt:
        await message.answer("Prompt не может быть пустым.")
        return
    if len(prompt) > 5000:
        await message.answer("Prompt Suno Upload & Extend ограничен 5000 символами.")
        return
    data = await state.get_data()
    custom = bool(data.get("default_param_flag"))
    await state.update_data(prompt=prompt, can_submit=False)
    if custom:
        await state.set_state(MusicUploadExtendStates.waiting_style)
        await message.answer(
            "<b>Стиль продолжения</b>\n\nДо 1000 символов.",
            reply_markup=_nav("music:upload-extend:back:prompt"),
        )
        return
    await state.set_state(MusicUploadExtendStates.confirming)
    await _show_confirmation_message(message, state, api_client)


@router.message(MusicUploadExtendStates.waiting_style, F.text)
async def receive_upload_extend_style(message: Message, state: FSMContext) -> None:
    style = (message.text or "").strip()
    if not style:
        await message.answer("Стиль не может быть пустым.")
        return
    if len(style) > 1000:
        await message.answer("Стиль Suno Upload & Extend ограничен 1000 символами.")
        return
    await state.update_data(style=style, can_submit=False)
    await state.set_state(MusicUploadExtendStates.waiting_title)
    await message.answer(
        "<b>Название результата</b>\n\nДо 100 символов.",
        reply_markup=_nav("music:upload-extend:back:style"),
    )


@router.message(MusicUploadExtendStates.waiting_title, F.text)
async def receive_upload_extend_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not title:
        await message.answer("Название не может быть пустым.")
        return
    if len(title) > 100:
        await message.answer("Название Suno Upload & Extend ограничено 100 символами.")
        return
    await state.update_data(title=title, can_submit=False)
    await state.set_state(MusicUploadExtendStates.waiting_continue_at)
    await message.answer(
        (
            "<b>Точка продолжения</b>\n\n"
            "Введите время в секундах, например <code>45</code> или <code>72.5</code>. "
            "Значение должно быть больше 0 и находиться внутри исходного аудио."
        ),
        reply_markup=_nav("music:upload-extend:back:title"),
    )


@router.message(MusicUploadExtendStates.waiting_continue_at, F.text)
async def receive_upload_extend_continue_at(
    message: Message,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    raw = (message.text or "").strip().replace(",", ".")
    try:
        continue_at = float(raw)
    except ValueError:
        await message.answer("Введите число секунд, например 45 или 72.5.")
        return
    if continue_at <= 0:
        await message.answer("Точка продолжения должна быть больше 0 секунд.")
        return
    await state.update_data(continue_at=continue_at, can_submit=False)
    await state.set_state(MusicUploadExtendStates.confirming)
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
    quote = prices.get(MODEL_SLUG)
    if quote is None:
        await state.update_data(can_submit=False)
        return (
            "⚠️ Для Suno V5 Upload & Extend ещё не опубликована активная цена. "
            "Запуск заблокирован до явной публикации тарифа.",
            False,
        )
    enough = balance.available_units >= quote.amount_units
    await state.update_data(can_submit=enough)
    custom = bool(data.get("default_param_flag"))
    instrumental = bool(data.get("instrumental")) if custom else False
    lines = [
        "<b>Проверьте Upload & Extend</b>",
        "",
        f"Режим: {'кастомный' if custom else 'быстрый'}",
    ]
    if custom:
        lines.append(f"Результат: {'инструментал' if instrumental else 'с вокалом'}")
    if data.get("prompt"):
        lines.append(f"Prompt: {escape(str(data.get('prompt')))}")
    if custom:
        lines.extend(
            [
                f"Стиль: {escape(str(data.get('style') or ''))}",
                f"Название: {escape(str(data.get('title') or ''))}",
                f"Продолжить с: {float(data.get('continue_at') or 0):g} сек",
            ]
        )
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
            "Исходный файл остаётся приватным; provider URL создаётся сервером при отправке задачи.",
        ]
    )
    return "\n".join(lines), enough


async def _show_confirmation_message(
    message: Message,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    user_id = message.from_user.id if message.from_user is not None else 0
    text, can_submit = await _quote(state, api_client, user_id)
    await message.answer(text, reply_markup=_confirm_keyboard(can_submit))


async def _show_confirmation_callback(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    text, can_submit = await _quote(state, api_client, callback.from_user.id)
    await safe_edit_callback_message(callback, text, _confirm_keyboard(can_submit))


@router.callback_query(
    MusicUploadExtendStates.confirming,
    F.data == "music:upload-extend:refresh",
)
async def refresh_upload_extend(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    await _show_confirmation_callback(callback, state, api_client)


@router.callback_query(
    MusicUploadExtendStates.confirming,
    F.data == "music:upload-extend:confirm",
)
async def confirm_upload_extend(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not bool(data.get("can_submit")):
        await callback.answer("Сначала дождитесь цены и достаточного баланса.", show_alert=True)
        return
    storage_key = data.get("input_storage_key")
    if not isinstance(storage_key, str):
        await callback.answer("Исходный аудиофайл потерян. Загрузите его заново.", show_alert=True)
        return
    custom = bool(data.get("default_param_flag"))
    payload: dict[str, object] = {
        "input_storage_key": storage_key,
        "default_param_flag": custom,
        "instrumental": bool(data.get("instrumental")) if custom else False,
        "prompt": str(data.get("prompt") or ""),
        "style": str(data.get("style") or "") if custom else "",
        "title": str(data.get("title") or "") if custom else "",
        "negative_tags": str(data.get("negative_tags") or "") if custom else "",
    }
    if custom:
        payload["continue_at"] = float(data.get("continue_at") or 0)

    await state.set_state(MusicUploadExtendStates.submitting)
    await safe_edit_callback_message(
        callback,
        "Ставлю Suno Upload & Extend в очередь…",
        answer_callback=False,
    )
    try:
        result = await submit_suno_upload_extend(
            user_id=callback.from_user.id,
            username=callback.from_user.username,
            input_data=payload,
            idempotency_key=str(data.get("idempotency_key") or ""),
        )
    except SunoUploadExtendTransportError as exc:
        await state.set_state(MusicUploadExtendStates.confirming)
        await state.update_data(can_submit=False)
        if callback.message:
            await callback.message.answer(
                f"⚠️ {escape(str(exc))}",
                reply_markup=_confirm_keyboard(False),
            )
        return

    # Do not remove an admitted input here. The worker still needs the durable
    # input_storage_key; retention owns cleanup after the provider side effect.
    await state.clear()
    if callback.message:
        await callback.message.answer(
            (
                "✅ <b>Suno Upload & Extend поставлен в очередь</b>\n\n"
                f"ID: <code>{escape(result.generation_id)}</code>\n"
                "Все варианты будут сохранены и доставлены через общий media pipeline."
            ),
            reply_markup=after_submit_keyboard(result.generation_id),
        )


@router.callback_query(
    MusicUploadExtendStates.submitting,
    F.data == "music:upload-extend:confirm",
)
async def duplicate_upload_extend_submit(callback: CallbackQuery) -> None:
    await callback.answer("Suno Upload & Extend уже ставится в очередь.")


@router.callback_query(F.data.startswith("music:upload-extend:back:"))
async def back_upload_extend(callback: CallbackQuery, state: FSMContext) -> None:
    action = (callback.data or "").rsplit(":", 1)[-1]
    data = await state.get_data()
    custom = bool(data.get("default_param_flag"))
    instrumental = bool(data.get("instrumental"))

    if action == "mode":
        await state.set_state(MusicUploadExtendStates.choosing_mode)
        await safe_edit_callback_message(callback, "Выберите режим Upload & Extend:", _mode_keyboard())
        return
    if action == "vocal":
        await state.set_state(MusicUploadExtendStates.choosing_vocal_mode)
        await safe_edit_callback_message(callback, "Выберите тип продолжения:", _vocal_keyboard())
        return
    if action == "prompt":
        await state.set_state(MusicUploadExtendStates.waiting_prompt)
        await safe_edit_callback_message(
            callback,
            "Отправьте prompt для продолжения:",
            _nav("music:upload-extend:back:vocal"),
        )
        return
    if action == "style":
        await state.set_state(MusicUploadExtendStates.waiting_style)
        await safe_edit_callback_message(
            callback,
            "Отправьте стиль продолжения:",
            _nav("music:upload-extend:back:prompt" if not instrumental else "music:upload-extend:back:vocal"),
        )
        return
    if action == "title":
        await state.set_state(MusicUploadExtendStates.waiting_title)
        await safe_edit_callback_message(
            callback,
            "Отправьте название результата:",
            _nav("music:upload-extend:back:style"),
        )
        return
    if action == "confirm":
        await state.update_data(can_submit=False)
        if custom:
            await state.set_state(MusicUploadExtendStates.waiting_continue_at)
            await safe_edit_callback_message(
                callback,
                "Введите точку продолжения в секундах:",
                _nav("music:upload-extend:back:title"),
            )
        else:
            await state.set_state(MusicUploadExtendStates.waiting_prompt)
            await safe_edit_callback_message(
                callback,
                "Отправьте prompt для быстрого продолжения:",
                _nav("music:upload-extend:back:mode"),
            )
        return
    if action == "hub":
        await state.clear()
        await state.set_state(MusicExtendStates.choosing_action)
        await safe_edit_callback_message(
            callback,
            "Откройте раздел «Создать музыку» заново.",
            InlineKeyboardMarkup(inline_keyboard=[[_button("Меню", "nav:menu")]]),
        )
        return
    await callback.answer("Эта кнопка устарела.", show_alert=True)


@router.message(MusicUploadExtendStates.choosing_mode)
@router.message(MusicUploadExtendStates.choosing_vocal_mode)
@router.message(MusicUploadExtendStates.confirming)
async def invalid_upload_extend_message(message: Message) -> None:
    await message.answer("Используйте кнопки текущего шага или /menu.")
