from __future__ import annotations

from html import escape
from uuid import uuid4

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from foxgen.bot.api_client import FoxGenApiClient, FoxGenApiError
from foxgen.bot.callbacks import safe_edit_callback_message
from foxgen.bot.keyboards import after_submit_keyboard, main_menu
from foxgen.bot.music import begin_music
from foxgen.bot.states import MusicExtendStates
from foxgen.bot.suno_extend_transport import (
    SunoExtendTransportError,
    SunoSourceView,
    list_suno_sources,
    submit_suno_extend,
)


router = Router(name="music-suno-extend")

SUNO_EXTEND_MODEL_SLUG = "suno-v5-extend"
SUNO_EXTEND_MODEL_TITLE = "Suno V5 Extend"


def _hub_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="♫ Новый трек", callback_data="music:new")],
            [
                InlineKeyboardButton(
                    text="↗ Продолжить свой трек",
                    callback_data="music:extend:start",
                )
            ],
            [InlineKeyboardButton(text="← Главное меню", callback_data="music:extend:menu")],
        ]
    )


def _source_keyboard(items: list[dict[str, object]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, item in enumerate(items[:20]):
        title = str(item.get("title") or "Suno track")
        duration_raw = item.get("duration_seconds")
        duration = (
            f" · {float(duration_raw):.1f} сек"
            if isinstance(duration_raw, (int, float)) and not isinstance(duration_raw, bool)
            else ""
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{title[:38]}{duration}",
                    callback_data=f"music:extend:source:{index}",
                )
            ]
        )
    rows.extend(
        [
            [InlineKeyboardButton(text="Обновить список", callback_data="music:extend:start")],
            [InlineKeyboardButton(text="← Музыка", callback_data="music:extend:hub")],
            [InlineKeyboardButton(text="Отмена", callback_data="nav:cancel")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _extend_mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Продолжить как есть",
                    callback_data="music:extend:mode:inherit",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Кастомное продолжение",
                    callback_data="music:extend:mode:custom",
                )
            ],
            [InlineKeyboardButton(text="← К трекам", callback_data="music:extend:back:sources")],
            [InlineKeyboardButton(text="Отмена", callback_data="nav:cancel")],
        ]
    )


def _nav_keyboard(back_callback: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="← Назад", callback_data=back_callback)],
            [
                InlineKeyboardButton(text="Отмена", callback_data="nav:cancel"),
                InlineKeyboardButton(text="Меню", callback_data="nav:menu"),
            ],
        ]
    )


def _confirmation_keyboard(*, can_submit: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if can_submit:
        rows.append(
            [InlineKeyboardButton(text="Запустить Extend", callback_data="music:extend:confirm")]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Обновить цену и баланс",
                    callback_data="music:extend:refresh",
                )
            ]
        )
    rows.extend(
        [
            [InlineKeyboardButton(text="← Назад", callback_data="music:extend:back:confirm")],
            [
                InlineKeyboardButton(text="Отмена", callback_data="nav:cancel"),
                InlineKeyboardButton(text="Меню", callback_data="nav:menu"),
            ],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _source_to_state(item: SunoSourceView) -> dict[str, object]:
    return {
        "generation_id": item.generation_id,
        "model_slug": item.model_slug,
        "audio_id": item.audio_id,
        "title": item.title,
        "duration_seconds": item.duration_seconds,
        "preview_url": item.preview_url,
    }


async def _show_hub(callback: CallbackQuery, state: FSMContext, *, clear: bool) -> None:
    if clear:
        await state.clear()
    await state.set_state(MusicExtendStates.choosing_action)
    await safe_edit_callback_message(
        callback,
        (
            "<b>Музыка · Suno V5</b>\n\n"
            "Создайте новый трек или продолжите один из своих уже сохранённых вариантов."
        ),
        _hub_keyboard(),
    )


@router.callback_query(F.data.in_({"create:music", "planned:music"}))
async def begin_music_hub(callback: CallbackQuery, state: FSMContext) -> None:
    await _show_hub(callback, state, clear=True)


@router.callback_query(MusicExtendStates.choosing_action, F.data == "music:new")
async def begin_new_music(callback: CallbackQuery, state: FSMContext) -> None:
    await begin_music(callback, state)


@router.callback_query(MusicExtendStates.choosing_action, F.data == "music:extend:menu")
async def return_main_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await safe_edit_callback_message(callback, "Главное меню", main_menu())


@router.callback_query(
    MusicExtendStates.choosing_action,
    F.data.in_({"music:extend:start", "music:extend:hub"}),
)
@router.callback_query(MusicExtendStates.choosing_source, F.data == "music:extend:start")
async def begin_extend(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        sources = await list_suno_sources(user_id=callback.from_user.id)
    except SunoExtendTransportError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    items = [_source_to_state(item) for item in sources]
    await state.update_data(extend_sources=items)
    await state.set_state(MusicExtendStates.choosing_source)
    if not items:
        await safe_edit_callback_message(
            callback,
            (
                "<b>Продолжить трек</b>\n\n"
                "Пока нет подходящих сохранённых Suno-треков. "
                "Сначала создайте новый трек и дождитесь его завершения."
            ),
            _source_keyboard(items),
        )
        return

    await safe_edit_callback_message(
        callback,
        "<b>Выберите свой Suno-трек</b>\n\nПоказываются только ваши завершённые и сохранённые варианты.",
        _source_keyboard(items),
    )


@router.callback_query(MusicExtendStates.choosing_source, F.data == "music:extend:hub")
async def back_to_hub(callback: CallbackQuery, state: FSMContext) -> None:
    await _show_hub(callback, state, clear=False)


@router.callback_query(
    MusicExtendStates.choosing_source,
    F.data.startswith("music:extend:source:"),
)
async def choose_extend_source(callback: CallbackQuery, state: FSMContext) -> None:
    raw = (callback.data or "").rsplit(":", 1)[-1]
    try:
        index = int(raw)
    except ValueError:
        await callback.answer("Источник устарел. Обновите список.", show_alert=True)
        return

    data = await state.get_data()
    sources = data.get("extend_sources")
    if not isinstance(sources, list) or index < 0 or index >= len(sources):
        await callback.answer("Источник устарел. Обновите список.", show_alert=True)
        return
    source = sources[index]
    if not isinstance(source, dict):
        await callback.answer("Источник повреждён. Обновите список.", show_alert=True)
        return

    generation_id = source.get("generation_id")
    audio_id = source.get("audio_id")
    title = source.get("title")
    if not isinstance(generation_id, str) or not isinstance(audio_id, str):
        await callback.answer("Источник повреждён. Обновите список.", show_alert=True)
        return

    await state.update_data(
        extend_source_generation_id=generation_id,
        extend_audio_id=audio_id,
        extend_source_title=str(title or "Suno track"),
        extend_source_duration=source.get("duration_seconds"),
        idempotency_key=f"suno-extend:{callback.from_user.id}:{uuid4().hex}",
        default_param_flag=False,
        prompt="",
        style="",
        title="",
        negative_tags="",
        can_submit=False,
    )
    await state.set_state(MusicExtendStates.choosing_mode)
    duration_raw = source.get("duration_seconds")
    duration = (
        f" · {float(duration_raw):.1f} сек"
        if isinstance(duration_raw, (int, float)) and not isinstance(duration_raw, bool)
        else ""
    )
    await safe_edit_callback_message(
        callback,
        (
            f"<b>{escape(str(title or 'Suno track'))}</b>{duration}\n\n"
            "Продолжить с исходными параметрами или задать новый prompt/style/title и точку перехода?"
        ),
        _extend_mode_keyboard(),
    )


@router.callback_query(MusicExtendStates.choosing_mode, F.data == "music:extend:back:sources")
async def back_to_sources(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    items = data.get("extend_sources")
    safe_items = items if isinstance(items, list) else []
    await state.set_state(MusicExtendStates.choosing_source)
    await safe_edit_callback_message(
        callback,
        "<b>Выберите свой Suno-трек</b>",
        _source_keyboard(safe_items),
    )


@router.callback_query(
    MusicExtendStates.choosing_mode,
    F.data.in_({"music:extend:mode:inherit", "music:extend:mode:custom"}),
)
async def choose_extend_mode(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    custom = (callback.data or "").endswith(":custom")
    await state.update_data(
        default_param_flag=custom,
        prompt="",
        style="",
        title="",
        negative_tags="",
        continue_at=None,
        can_submit=False,
    )
    if not custom:
        await state.set_state(MusicExtendStates.confirming)
        await _show_confirmation_callback(callback, state, api_client)
        return

    await state.set_state(MusicExtendStates.waiting_prompt)
    await safe_edit_callback_message(
        callback,
        "<b>Новый prompt / текст продолжения</b>\n\nДо 5000 символов.",
        _nav_keyboard("music:extend:back:mode"),
    )


@router.message(MusicExtendStates.waiting_prompt, F.text)
async def receive_extend_prompt(message: Message, state: FSMContext) -> None:
    prompt = (message.text or "").strip()
    if not prompt:
        await message.answer("Prompt не может быть пустым.")
        return
    if len(prompt) > 5_000:
        await message.answer("Prompt Suno Extend ограничен 5000 символами.")
        return
    await state.update_data(prompt=prompt, can_submit=False)
    await state.set_state(MusicExtendStates.waiting_style)
    await message.answer(
        "<b>Новый стиль</b>\n\nДо 1000 символов.",
        reply_markup=_nav_keyboard("music:extend:back:prompt"),
    )


@router.message(MusicExtendStates.waiting_style, F.text)
async def receive_extend_style(message: Message, state: FSMContext) -> None:
    style = (message.text or "").strip()
    if not style:
        await message.answer("Стиль не может быть пустым.")
        return
    if len(style) > 1_000:
        await message.answer("Стиль Suno Extend ограничен 1000 символами.")
        return
    await state.update_data(style=style, can_submit=False)
    await state.set_state(MusicExtendStates.waiting_title)
    await message.answer(
        "<b>Название продолжения</b>\n\nДо 100 символов.",
        reply_markup=_nav_keyboard("music:extend:back:style"),
    )


@router.message(MusicExtendStates.waiting_title, F.text)
async def receive_extend_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not title:
        await message.answer("Название не может быть пустым.")
        return
    if len(title) > 100:
        await message.answer("Название Suno Extend ограничено 100 символами.")
        return
    await state.update_data(title=title, can_submit=False)
    await state.set_state(MusicExtendStates.waiting_continue_at)
    data = await state.get_data()
    duration_raw = data.get("extend_source_duration")
    hint = (
        f"Трек длится {float(duration_raw):.1f} сек. Укажите точку раньше конца."
        if isinstance(duration_raw, (int, float)) and not isinstance(duration_raw, bool)
        else "Укажите положительное число секунд."
    )
    await message.answer(
        f"<b>С какой секунды продолжить?</b>\n\n{hint}",
        reply_markup=_nav_keyboard("music:extend:back:title"),
    )


@router.message(MusicExtendStates.waiting_continue_at, F.text)
async def receive_continue_at(
    message: Message,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    raw = (message.text or "").strip().replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        await message.answer("Введите точку продолжения числом в секундах, например 92.5.")
        return
    if value <= 0:
        await message.answer("Точка продолжения должна быть больше 0 секунд.")
        return
    data = await state.get_data()
    duration_raw = data.get("extend_source_duration")
    if (
        isinstance(duration_raw, (int, float))
        and not isinstance(duration_raw, bool)
        and value >= float(duration_raw)
    ):
        await message.answer("Точка продолжения должна быть раньше конца исходного трека.")
        return
    await state.update_data(continue_at=value, can_submit=False)
    await state.set_state(MusicExtendStates.confirming)
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

    quote = prices.get(SUNO_EXTEND_MODEL_SLUG)
    if quote is None:
        await state.update_data(can_submit=False)
        return (
            "⚠️ Для Suno V5 Extend ещё не опубликована активная цена. "
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
    custom = bool(data.get("default_param_flag"))
    lines = [
        "<b>Проверьте Suno Extend</b>",
        "",
        f"Источник: <b>{escape(str(data.get('extend_source_title') or 'Suno track'))}</b>",
        f"Режим: {'кастомный' if custom else 'с исходными параметрами'}",
    ]
    if custom:
        lines.extend(
            [
                f"Prompt: {escape(str(data.get('prompt') or ''))}",
                f"Стиль: {escape(str(data.get('style') or ''))}",
                f"Название: {escape(str(data.get('title') or ''))}",
                f"Продолжить с: {float(data.get('continue_at') or 0):.1f} сек",
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
            "Исходный audioId берётся только из вашего сохранённого Suno-трека.",
        ]
    )
    return "\n".join(lines), enough


async def _show_confirmation_message(
    message: Message,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
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


@router.callback_query(MusicExtendStates.confirming, F.data == "music:extend:refresh")
async def refresh_extend(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    await _show_confirmation_callback(callback, state, api_client)


@router.callback_query(MusicExtendStates.confirming, F.data == "music:extend:confirm")
async def confirm_extend(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    if not bool(data.get("can_submit")):
        await callback.answer(
            "Сначала дождитесь доступной цены и достаточного баланса.",
            show_alert=True,
        )
        return
    source_generation_id = data.get("extend_source_generation_id")
    audio_id = data.get("extend_audio_id")
    if not isinstance(source_generation_id, str) or not isinstance(audio_id, str):
        await callback.answer("Исходный трек устарел. Выберите его заново.", show_alert=True)
        return

    await state.set_state(MusicExtendStates.submitting)
    await safe_edit_callback_message(
        callback,
        "Ставлю продолжение в очередь…",
        answer_callback=False,
    )
    input_data: dict[str, object] = {
        "default_param_flag": bool(data.get("default_param_flag")),
    }
    if bool(data.get("default_param_flag")):
        input_data.update(
            {
                "prompt": str(data.get("prompt") or ""),
                "style": str(data.get("style") or ""),
                "title": str(data.get("title") or ""),
                "continue_at": float(data.get("continue_at") or 0),
                "negative_tags": str(data.get("negative_tags") or ""),
            }
        )
    try:
        result = await submit_suno_extend(
            user_id=callback.from_user.id,
            username=callback.from_user.username,
            source_generation_id=source_generation_id,
            audio_id=audio_id,
            input_data=input_data,
            idempotency_key=str(data.get("idempotency_key") or ""),
        )
    except SunoExtendTransportError as exc:
        await state.set_state(MusicExtendStates.confirming)
        await state.update_data(can_submit=False)
        if callback.message:
            await callback.message.answer(
                f"⚠️ {escape(str(exc))}\n\nОбновите цену/баланс и повторите.",
                reply_markup=_confirmation_keyboard(can_submit=False),
            )
        return

    await state.clear()
    if callback.message:
        replay = (
            "\nПовторный запуск безопасно переиспользовал существующую задачу."
            if result.replayed
            else ""
        )
        await callback.message.answer(
            (
                "✅ <b>Suno Extend поставлен в очередь</b>\n\n"
                f"ID: <code>{escape(result.generation_id)}</code>\n"
                "Все варианты будут сохранены и доставлены через общий media pipeline."
                f"{replay}"
            ),
            reply_markup=after_submit_keyboard(result.generation_id),
        )


@router.callback_query(MusicExtendStates.submitting, F.data == "music:extend:confirm")
async def duplicate_extend_submit(callback: CallbackQuery) -> None:
    await callback.answer("Продолжение уже ставится в очередь.")


@router.callback_query(MusicExtendStates.waiting_prompt, F.data == "music:extend:back:mode")
async def back_prompt_to_mode(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(MusicExtendStates.choosing_mode)
    await safe_edit_callback_message(callback, "Выберите режим продолжения:", _extend_mode_keyboard())


@router.callback_query(MusicExtendStates.waiting_style, F.data == "music:extend:back:prompt")
async def back_style_to_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(MusicExtendStates.waiting_prompt)
    await safe_edit_callback_message(
        callback,
        "Отправьте новый prompt продолжения:",
        _nav_keyboard("music:extend:back:mode"),
    )


@router.callback_query(MusicExtendStates.waiting_title, F.data == "music:extend:back:style")
async def back_title_to_style(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(MusicExtendStates.waiting_style)
    await safe_edit_callback_message(
        callback,
        "Отправьте новый стиль:",
        _nav_keyboard("music:extend:back:prompt"),
    )


@router.callback_query(
    MusicExtendStates.waiting_continue_at,
    F.data == "music:extend:back:title",
)
async def back_continue_to_title(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(MusicExtendStates.waiting_title)
    await safe_edit_callback_message(
        callback,
        "Отправьте новое название:",
        _nav_keyboard("music:extend:back:style"),
    )


@router.callback_query(MusicExtendStates.confirming, F.data == "music:extend:back:confirm")
async def back_from_extend_confirmation(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(can_submit=False)
    if bool(data.get("default_param_flag")):
        await state.set_state(MusicExtendStates.waiting_continue_at)
        await safe_edit_callback_message(
            callback,
            "Введите точку продолжения в секундах:",
            _nav_keyboard("music:extend:back:title"),
        )
        return
    await state.set_state(MusicExtendStates.choosing_mode)
    await safe_edit_callback_message(callback, "Выберите режим продолжения:", _extend_mode_keyboard())


@router.message(MusicExtendStates.choosing_action)
@router.message(MusicExtendStates.choosing_source)
@router.message(MusicExtendStates.choosing_mode)
@router.message(MusicExtendStates.confirming)
async def invalid_extend_message(message: Message) -> None:
    await message.answer("Используйте кнопки текущего шага или /menu.")
