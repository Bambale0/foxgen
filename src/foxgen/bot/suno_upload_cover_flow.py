from __future__ import annotations

from html import escape
from uuid import uuid4

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from foxgen.bot.api_client import FoxGenApiClient, FoxGenApiError
from foxgen.bot.callbacks import safe_edit_callback_message
from foxgen.bot.keyboards import after_submit_keyboard
from foxgen.bot.states import MusicCoverStates, MusicExtendStates
from foxgen.bot.suno_upload_cover_transport import (
    SunoUploadCoverTransportError,
    submit_suno_upload_cover,
)
from foxgen.bot.uploads import TelegramInputMediaStorage, message_media_kind
from foxgen.core.errors import SubmissionError


router = Router(name="music-suno-upload-cover")
MODEL_SLUG = "suno-v5-upload-cover"


def _button(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def _mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Быстрый Cover", "music:cover:mode:simple")],
            [_button("Кастомный Cover", "music:cover:mode:custom")],
            [_button("Отмена", "nav:cancel"), _button("Меню", "nav:menu")],
        ]
    )


def _vocal_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("С вокалом", "music:cover:vocal:yes")],
            [_button("Инструментал", "music:cover:vocal:no")],
            [_button("← Назад", "music:cover:back:mode")],
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
    first = (
        [_button("Создать Cover", "music:cover:confirm")]
        if can_submit
        else [_button("Обновить цену и баланс", "music:cover:refresh")]
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            first,
            [_button("← Назад", "music:cover:back:confirm")],
            [_button("Отмена", "nav:cancel"), _button("Меню", "nav:menu")],
        ]
    )


@router.callback_query(MusicExtendStates.choosing_action, F.data == "music:cover:start")
async def begin_cover(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.update_data(
        idempotency_key=f"suno-cover:{callback.from_user.id}:{uuid4().hex}",
        media=[],
        can_submit=False,
    )
    await state.set_state(MusicCoverStates.waiting_audio)
    await safe_edit_callback_message(
        callback,
        (
            "<b>Suno Cover из аудио</b>\n\n"
            "Отправьте один аудиофайл, voice-message или аудио-документ. "
            "Файл сохранится приватно в FoxGen; внешний URL вводить не нужно."
        ),
        _nav("music:cover:back:hub"),
    )


@router.message(
    MusicCoverStates.waiting_audio,
    F.audio | F.voice | F.document,
)
async def receive_cover_audio(
    message: Message,
    state: FSMContext,
    bot: Bot,
    input_media: TelegramInputMediaStorage,
) -> None:
    try:
        if message_media_kind(message) != "audio":
            await message.answer("Для Suno Cover нужен именно аудиофайл.")
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

    stored = {"kind": "audio", "storage_key": uploaded.storage_key}
    await state.update_data(
        media=[stored],
        input_storage_key=uploaded.storage_key,
        custom_mode=False,
        instrumental=False,
        prompt="",
        style="",
        title="",
        negative_tags="",
        can_submit=False,
    )
    await state.set_state(MusicCoverStates.choosing_mode)
    await message.answer(
        "<b>Аудио сохранено</b>\n\nВыберите режим Cover:",
        reply_markup=_mode_keyboard(),
    )


@router.message(MusicCoverStates.waiting_audio)
async def invalid_cover_audio(message: Message) -> None:
    await message.answer("Отправьте один аудиофайл или voice-message.")


@router.callback_query(
    MusicCoverStates.choosing_mode,
    F.data.in_({"music:cover:mode:simple", "music:cover:mode:custom"}),
)
async def choose_cover_mode(callback: CallbackQuery, state: FSMContext) -> None:
    custom = (callback.data or "").endswith(":custom")
    await state.update_data(
        custom_mode=custom,
        instrumental=False,
        prompt="",
        style="",
        title="",
        negative_tags="",
        can_submit=False,
    )
    if not custom:
        await state.set_state(MusicCoverStates.waiting_prompt)
        await safe_edit_callback_message(
            callback,
            (
                "<b>Prompt для быстрого Cover</b>\n\n"
                "Опишите желаемую переработку. В быстром режиме используется только prompt "
                "и загруженное аудио; лимит prompt — 500 символов."
            ),
            _nav("music:cover:back:mode"),
        )
        return
    await state.set_state(MusicCoverStates.choosing_vocal_mode)
    await safe_edit_callback_message(
        callback,
        "<b>Тип результата</b>\n\nВыберите вокальный Cover или инструментальную переработку.",
        _vocal_keyboard(),
    )


@router.callback_query(
    MusicCoverStates.choosing_vocal_mode,
    F.data.in_({"music:cover:vocal:yes", "music:cover:vocal:no"}),
)
async def choose_cover_vocal(callback: CallbackQuery, state: FSMContext) -> None:
    instrumental = (callback.data or "").endswith(":no")
    data = await state.get_data()
    custom = bool(data.get("custom_mode"))
    if not custom:
        await callback.answer(
            "Тип результата настраивается только в кастомном режиме.", show_alert=True
        )
        return
    await state.update_data(instrumental=instrumental, can_submit=False)
    if instrumental:
        await state.set_state(MusicCoverStates.waiting_style)
        await safe_edit_callback_message(
            callback,
            "<b>Стиль Cover</b>\n\nНапример: cinematic orchestral, synthwave, acoustic folk.",
            _nav("music:cover:back:vocal"),
        )
        return
    await state.set_state(MusicCoverStates.waiting_prompt)
    await safe_edit_callback_message(
        callback,
        "<b>Prompt для Cover</b>\n\nОпишите новый текст/направление. Лимит — 5000 символов.",
        _nav("music:cover:back:vocal"),
    )


@router.message(MusicCoverStates.waiting_prompt, F.text)
async def receive_cover_prompt(
    message: Message,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    prompt = (message.text or "").strip()
    data = await state.get_data()
    custom = bool(data.get("custom_mode"))
    limit = 5000 if custom else 500
    if not prompt:
        await message.answer("Prompt не может быть пустым.")
        return
    if len(prompt) > limit:
        await message.answer(f"Prompt этого режима ограничен {limit} символами.")
        return
    await state.update_data(prompt=prompt, can_submit=False)
    if custom:
        await state.set_state(MusicCoverStates.waiting_style)
        await message.answer(
            "<b>Стиль Cover</b>\n\nДо 1000 символов.",
            reply_markup=_nav("music:cover:back:prompt"),
        )
        return
    await state.set_state(MusicCoverStates.confirming)
    await _show_confirmation_message(message, state, api_client)


@router.message(MusicCoverStates.waiting_style, F.text)
async def receive_cover_style(message: Message, state: FSMContext) -> None:
    style = (message.text or "").strip()
    if not style:
        await message.answer("Стиль не может быть пустым.")
        return
    if len(style) > 1000:
        await message.answer("Стиль Suno Cover ограничен 1000 символами.")
        return
    await state.update_data(style=style, can_submit=False)
    await state.set_state(MusicCoverStates.waiting_title)
    await message.answer(
        "<b>Название результата</b>\n\nДо 100 символов.",
        reply_markup=_nav("music:cover:back:style"),
    )


@router.message(MusicCoverStates.waiting_title, F.text)
async def receive_cover_title(
    message: Message,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    title = (message.text or "").strip()
    if not title:
        await message.answer("Название не может быть пустым.")
        return
    if len(title) > 100:
        await message.answer("Название Suno Cover ограничено 100 символами.")
        return
    await state.update_data(title=title, can_submit=False)
    await state.set_state(MusicCoverStates.confirming)
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
            "⚠️ Для Suno V5 Cover ещё не опубликована активная цена. "
            "Запуск заблокирован до явной публикации тарифа.",
            False,
        )
    enough = balance.available_units >= quote.amount_units
    await state.update_data(can_submit=enough)
    custom = bool(data.get("custom_mode"))
    instrumental = bool(data.get("instrumental")) if custom else False
    lines = [
        "<b>Проверьте Suno Cover</b>",
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
    text, can_submit = await _quote(state, api_client, message.from_user.id)
    await message.answer(text, reply_markup=_confirm_keyboard(can_submit))


async def _show_confirmation_callback(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    text, can_submit = await _quote(state, api_client, callback.from_user.id)
    await safe_edit_callback_message(callback, text, _confirm_keyboard(can_submit))


@router.callback_query(MusicCoverStates.confirming, F.data == "music:cover:refresh")
async def refresh_cover(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    await _show_confirmation_callback(callback, state, api_client)


@router.callback_query(MusicCoverStates.confirming, F.data == "music:cover:confirm")
async def confirm_cover(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not bool(data.get("can_submit")):
        await callback.answer("Сначала дождитесь цены и достаточного баланса.", show_alert=True)
        return
    storage_key = data.get("input_storage_key")
    if not isinstance(storage_key, str):
        await callback.answer("Исходный аудиофайл потерян. Загрузите его заново.", show_alert=True)
        return
    custom = bool(data.get("custom_mode"))
    payload: dict[str, object] = {
        "input_storage_key": storage_key,
        "custom_mode": custom,
        "instrumental": bool(data.get("instrumental")) if custom else False,
        "prompt": str(data.get("prompt") or ""),
        "style": str(data.get("style") or "") if custom else "",
        "title": str(data.get("title") or "") if custom else "",
        "negative_tags": str(data.get("negative_tags") or "") if custom else "",
    }
    await state.set_state(MusicCoverStates.submitting)
    await safe_edit_callback_message(
        callback,
        "Ставлю Suno Cover в очередь…",
        answer_callback=False,
    )
    try:
        result = await submit_suno_upload_cover(
            user_id=callback.from_user.id,
            username=callback.from_user.username,
            input_data=payload,
            idempotency_key=str(data.get("idempotency_key") or ""),
        )
    except SunoUploadCoverTransportError as exc:
        await state.set_state(MusicCoverStates.confirming)
        await state.update_data(can_submit=False)
        if callback.message:
            await callback.message.answer(
                f"⚠️ {escape(str(exc))}",
                reply_markup=_confirm_keyboard(False),
            )
        return

    await state.clear()
    if callback.message:
        await callback.message.answer(
            (
                "✅ <b>Suno Cover поставлен в очередь</b>\n\n"
                f"ID: <code>{escape(result.generation_id)}</code>\n"
                "Все варианты будут сохранены и доставлены через общий media pipeline."
            ),
            reply_markup=after_submit_keyboard(result.generation_id),
        )


@router.callback_query(MusicCoverStates.submitting, F.data == "music:cover:confirm")
async def duplicate_cover_submit(callback: CallbackQuery) -> None:
    await callback.answer("Suno Cover уже ставится в очередь.")


@router.callback_query(F.data.startswith("music:cover:back:"))
async def back_cover(callback: CallbackQuery, state: FSMContext) -> None:
    action = (callback.data or "").rsplit(":", 1)[-1]
    if action == "mode":
        await state.set_state(MusicCoverStates.choosing_mode)
        await safe_edit_callback_message(callback, "Выберите режим Cover:", _mode_keyboard())
        return
    if action == "vocal":
        await state.set_state(MusicCoverStates.choosing_vocal_mode)
        await safe_edit_callback_message(callback, "Выберите тип результата:", _vocal_keyboard())
        return
    if action == "prompt":
        await state.set_state(MusicCoverStates.waiting_prompt)
        data = await state.get_data()
        custom = bool(data.get("custom_mode"))
        limit = 5000 if custom else 500
        await safe_edit_callback_message(
            callback,
            f"Отправьте prompt для Cover (до {limit} символов):",
            _nav("music:cover:back:vocal" if custom else "music:cover:back:mode"),
        )
        return
    if action == "style":
        await state.set_state(MusicCoverStates.waiting_style)
        await safe_edit_callback_message(
            callback,
            "Отправьте стиль Cover:",
            _nav("music:cover:back:prompt"),
        )
        return
    if action == "confirm":
        data = await state.get_data()
        await state.update_data(can_submit=False)
        if bool(data.get("custom_mode")):
            await state.set_state(MusicCoverStates.waiting_title)
            await safe_edit_callback_message(
                callback,
                "Отправьте название Cover:",
                _nav("music:cover:back:style"),
            )
        else:
            await state.set_state(MusicCoverStates.waiting_prompt)
            await safe_edit_callback_message(
                callback,
                "Отправьте prompt для быстрого Cover:",
                _nav("music:cover:back:mode"),
            )
        return
    if action == "hub":
        await state.clear()
        await safe_edit_callback_message(
            callback,
            "Откройте раздел «Создать музыку» заново.",
            InlineKeyboardMarkup(inline_keyboard=[[_button("Меню", "nav:menu")]]),
        )
        return
    await callback.answer("Эта кнопка устарела.", show_alert=True)


@router.message(MusicCoverStates.choosing_mode)
@router.message(MusicCoverStates.choosing_vocal_mode)
@router.message(MusicCoverStates.confirming)
async def invalid_cover_message(message: Message) -> None:
    await message.answer("Используйте кнопки текущего шага или /menu.")
