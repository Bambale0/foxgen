from __future__ import annotations

import html

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import config
from bot.suno_pricing import (
    MODEL_PRICED_OPERATIONS,
    SUNO_MODELS,
    SUNO_OPERATION_LABELS,
    copy_suno_prices,
    default_suno_price,
    get_suno_price,
    set_suno_price,
)

router = Router()


class SunoAdminStates(StatesGroup):
    waiting_price = State()


def _kb(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _fmt(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _is_admin(user_id: int) -> bool:
    return config.is_admin(int(user_id))


async def _channel_keyboard(channel: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for operation, label in SUNO_OPERATION_LABELS.items():
        if operation in MODEL_PRICED_OPERATIONS:
            price = await get_suno_price(channel, operation, "V5_5")
            suffix = f"V5.5 {_fmt(price)}"
        else:
            price = await get_suno_price(channel, operation)
            suffix = _fmt(price)
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{label} · {suffix}",
                    callback_data=f"admin:suno:op:{channel}:{operation}",
                )
            ]
        )
    other = "max" if channel == "telegram" else "telegram"
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    text=f"📋 Скопировать цены → {other.upper()}",
                    callback_data=f"admin:suno:copy:{channel}:{other}",
                )
            ],
            [InlineKeyboardButton(text="↔️ Другой канал", callback_data=f"admin:suno:channel:{other}")],
            [InlineKeyboardButton(text="⬅️ Админ-панель", callback_data="admin_back")],
        ]
    )
    return _kb(rows)


async def _operation_keyboard(channel: str, operation: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    variants = SUNO_MODELS if operation in MODEL_PRICED_OPERATIONS else ("default",)
    for variant in variants:
        model = variant if operation in MODEL_PRICED_OPERATIONS else None
        price = await get_suno_price(channel, operation, model)
        default = default_suno_price(channel, operation, model)
        label = variant if model else "Цена"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"✏️ {label}: {_fmt(price)} (default {_fmt(default)})",
                    callback_data=f"admin:suno:set:{channel}:{operation}:{variant}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="⬅️ Suno цены", callback_data=f"admin:suno:channel:{channel}")])
    return _kb(rows)


@router.callback_query(F.data == "admin_suno_prices")
async def admin_suno_prices(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    await state.clear()
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "🎵 <b>Suno · live цены</b>\n\n"
            "Цены хранятся в базе и применяются к новым задачам сразу. Telegram и MAX можно настраивать независимо.",
            reply_markup=_kb(
                [
                    [InlineKeyboardButton(text="✈️ Telegram", callback_data="admin:suno:channel:telegram")],
                    [InlineKeyboardButton(text="🟣 MAX", callback_data="admin:suno:channel:max")],
                    [InlineKeyboardButton(text="⬅️ Админ-панель", callback_data="admin_back")],
                ]
            ),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("admin:suno:channel:"))
async def admin_suno_channel(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    channel = str(callback.data).rsplit(":", 1)[-1]
    if channel not in {"telegram", "max"}:
        await callback.answer("Канал неизвестен", show_alert=True)
        return
    await state.clear()
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            f"🎵 <b>Suno цены · {html.escape(channel.upper())}</b>\n\nВыберите операцию. Для генеративных операций каждая версия Suno имеет свою цену.",
            reply_markup=await _channel_keyboard(channel),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("admin:suno:op:"))
async def admin_suno_operation(callback: types.CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    parts = str(callback.data).split(":", 4)
    if len(parts) != 5:
        await callback.answer("Некорректная кнопка", show_alert=True)
        return
    channel, operation = parts[3], parts[4]
    if operation not in SUNO_OPERATION_LABELS:
        await callback.answer("Операция неизвестна", show_alert=True)
        return
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            f"🎵 <b>{html.escape(SUNO_OPERATION_LABELS[operation])}</b>\nКанал: <b>{html.escape(channel.upper())}</b>",
            reply_markup=await _operation_keyboard(channel, operation),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("admin:suno:set:"))
async def admin_suno_set(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    parts = str(callback.data).split(":", 5)
    if len(parts) != 6:
        await callback.answer("Некорректная кнопка", show_alert=True)
        return
    channel, operation, variant = parts[3], parts[4], parts[5]
    model = variant if operation in MODEL_PRICED_OPERATIONS else None
    current = await get_suno_price(channel, operation, model)
    await state.set_state(SunoAdminStates.waiting_price)
    await state.update_data(suno_channel=channel, suno_operation=operation, suno_variant=variant)
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "💸 <b>Новая цена Suno</b>\n\n"
            f"Канал: <b>{html.escape(channel.upper())}</b>\n"
            f"Операция: <b>{html.escape(SUNO_OPERATION_LABELS[operation])}</b>\n"
            f"Вариант: <b>{html.escape(variant)}</b>\n"
            f"Сейчас: <b>{_fmt(current)}</b>\n\n"
            "Пришлите новое число. Можно дробное, например <code>12.5</code>.",
            parse_mode="HTML",
        )


@router.message(SunoAdminStates.waiting_price)
async def admin_suno_price_value(message: types.Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        await state.clear()
        return
    raw = str(message.text or "").strip().replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        await message.answer("Пришлите цену числом, например 15 или 12.5.")
        return
    data = await state.get_data()
    channel = str(data.get("suno_channel") or "")
    operation = str(data.get("suno_operation") or "")
    variant = str(data.get("suno_variant") or "default")
    model = variant if operation in MODEL_PRICED_OPERATIONS else None
    try:
        price = await set_suno_price(
            channel,
            operation,
            value,
            model=model,
            updated_by_telegram_id=message.from_user.id,
        )
    except (TypeError, ValueError) as exc:
        await message.answer(f"Цена не сохранена: {html.escape(str(exc))}", parse_mode="HTML")
        return
    await state.clear()
    await message.answer(
        f"✅ Цена сохранена: <b>{_fmt(price)}</b>\nИзменение уже действует для новых задач {html.escape(channel.upper())}.",
        reply_markup=await _operation_keyboard(channel, operation),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin:suno:copy:"))
async def admin_suno_copy(callback: types.CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    parts = str(callback.data).split(":", 4)
    if len(parts) != 5:
        await callback.answer("Некорректная кнопка", show_alert=True)
        return
    source, target = parts[3], parts[4]
    changed = await copy_suno_prices(source, target, updated_by_telegram_id=callback.from_user.id)
    await callback.answer(f"Скопировано цен: {changed}", show_alert=True)
    if callback.message:
        await callback.message.edit_text(
            f"✅ Цены {html.escape(source.upper())} скопированы в {html.escape(target.upper())}.\n\nИзменения уже действуют.",
            reply_markup=await _channel_keyboard(target),
            parse_mode="HTML",
        )
