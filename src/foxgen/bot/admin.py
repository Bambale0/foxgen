from __future__ import annotations

import html
import json
from typing import Any
from uuid import uuid4

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from foxgen.bot.admin_api_client import AdminApiClient, AdminApiClientError


router = Router(name="foxgen-admin")


class AdminStates(StatesGroup):
    user_lookup = State()
    balance_amount = State()
    balance_reason = State()
    balance_confirm = State()
    block_reason = State()
    block_confirm = State()
    tariff_payload = State()
    tariff_confirm = State()
    promo_lookup = State()
    promo_create = State()
    broadcast_name = State()
    broadcast_message = State()
    broadcast_segment = State()
    broadcast_confirm = State()
    prompt_reject_reason = State()
    support_reply = State()
    operation_refund_reason = State()
    model_toggle_slug = State()


def admin_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Статистика", callback_data="adm:summary"),
                InlineKeyboardButton(text="Пользователи", callback_data="adm:users"),
            ],
            [
                InlineKeyboardButton(text="Финансы", callback_data="adm:finance"),
                InlineKeyboardButton(text="Платежи", callback_data="adm:payments"),
            ],
            [
                InlineKeyboardButton(text="Партнёры", callback_data="adm:partners"),
                InlineKeyboardButton(text="Выводы", callback_data="adm:withdrawals"),
            ],
            [
                InlineKeyboardButton(text="Тарифы", callback_data="adm:tariffs"),
                InlineKeyboardButton(text="Промо", callback_data="adm:promos"),
            ],
            [
                InlineKeyboardButton(text="Промпты", callback_data="adm:prompts"),
                InlineKeyboardButton(text="Рассылка", callback_data="adm:broadcast"),
            ],
            [
                InlineKeyboardButton(text="Поддержка", callback_data="adm:support"),
                InlineKeyboardButton(text="Операции", callback_data="adm:operations"),
            ],
            [
                InlineKeyboardButton(text="Runtime", callback_data="adm:runtime"),
                InlineKeyboardButton(text="AI admin", callback_data="adm:ai"),
            ],
            [
                InlineKeyboardButton(text="CMS", callback_data="adm:cms"),
                InlineKeyboardButton(text="Экспорт", callback_data="adm:exports"),
            ],
            [InlineKeyboardButton(text="Закрыть", callback_data="adm:close")],
        ]
    )


def _back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="← Админка", callback_data="adm:home")]]
    )


def _confirm_keyboard(confirm_callback: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Подтвердить", callback_data=confirm_callback)],
            [InlineKeyboardButton(text="Отмена", callback_data="adm:home")],
        ]
    )


@router.message(Command("admin"))
async def admin_command(
    message: Message,
    state: FSMContext,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    await state.clear()
    user_id = await _authorize_message(message, admin_api_client)
    if user_id is None:
        return
    health = await _call(admin_api_client, "health", user_id)
    if health is None:
        return
    await message.answer(
        "<b>FoxGen Admin</b>\n"
        f"Роль: <code>{html.escape(str(health.get('role', 'admin')))}</code>\n"
        "Все write-действия проходят server-side RBAC, audit и idempotency.",
        reply_markup=admin_main_keyboard(),
    )


@router.callback_query(F.data == "adm:home")
async def admin_home(
    callback: CallbackQuery,
    state: FSMContext,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    await state.clear()
    user_id = await _authorize_callback(callback, admin_api_client)
    if user_id is None:
        return
    await _edit(callback, "<b>FoxGen Admin</b>\nВыберите раздел.", admin_main_keyboard())


@router.callback_query(F.data == "adm:close")
async def admin_close(
    callback: CallbackQuery,
    state: FSMContext,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    await state.clear()
    if await _authorize_callback(callback, admin_api_client) is None:
        return
    if callback.message:
        await callback.message.edit_text("Админ-панель закрыта.")
    await callback.answer()


@router.callback_query(
    F.data.in_({"adm:summary", "adm:finance", "adm:partners", "adm:runtime", "adm:ai"})
)
async def admin_read_summary(
    callback: CallbackQuery,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorize_callback(callback, admin_api_client)
    if user_id is None or callback.data is None:
        return
    routes = {
        "adm:summary": "/internal/admin/summary",
        "adm:finance": "/internal/admin/finance",
        "adm:partners": "/internal/admin/partners/summary",
        "adm:runtime": "/internal/admin/runtime",
        "adm:ai": "/internal/admin/ai/diagnostics",
    }
    data = await _request(admin_api_client, "GET", routes[callback.data], user_id)
    if data is None:
        await callback.answer()
        return
    keyboard = _back_keyboard()
    if callback.data == "adm:runtime":
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Подписка: ON",
                        callback_data="adm:sub:on",
                    ),
                    InlineKeyboardButton(
                        text="Подписка: OFF",
                        callback_data="adm:sub:off",
                    ),
                ],
                [InlineKeyboardButton(text="Модель ON/OFF", callback_data="adm:modeltoggle")],
                [InlineKeyboardButton(text="← Админка", callback_data="adm:home")],
            ]
        )
    await _edit(callback, _json_text(data), keyboard)


@router.callback_query(F.data == "adm:users")
async def admin_users_start(
    callback: CallbackQuery,
    state: FSMContext,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    if await _authorize_callback(callback, admin_api_client, state=state) is None:
        return
    await state.set_state(AdminStates.user_lookup)
    await _edit(
        callback,
        "Введите Telegram/internal ID или часть username пользователя.",
        _back_keyboard(),
    )


@router.message(AdminStates.user_lookup)
async def admin_user_lookup_message(
    message: Message,
    state: FSMContext,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorize_message(message, admin_api_client, state=state)
    if user_id is None:
        return
    query = (message.text or "").strip()
    if not query:
        await message.answer("Нужен ID или username.")
        return
    result = await _request(
        admin_api_client,
        "GET",
        "/internal/admin/users",
        user_id,
        params={"q": query, "limit": 20},
    )
    if not isinstance(result, list):
        return
    await state.clear()
    if not result:
        await message.answer("Пользователь не найден.", reply_markup=_back_keyboard())
        return
    rows: list[list[InlineKeyboardButton]] = []
    lines = ["<b>Пользователи</b>"]
    for raw in result[:10]:
        if not isinstance(raw, dict):
            continue
        target_id = raw.get("id")
        if not isinstance(target_id, int):
            continue
        balance = raw.get("balance") if isinstance(raw.get("balance"), dict) else {}
        lines.append(
            f"\n<code>{target_id}</code> @{html.escape(str(raw.get('username') or '—'))} "
            f"· баланс {balance.get('available_units', 0)} "
            f"· {'BLOCKED' if raw.get('blocked') else 'active'}"
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"Баланс {target_id}", callback_data=f"adm:ubal:{target_id}"
                ),
                InlineKeyboardButton(text="Block", callback_data=f"adm:ublock:{target_id}"),
                InlineKeyboardButton(text="Unblock", callback_data=f"adm:uunblock:{target_id}"),
            ]
        )
    rows.append([InlineKeyboardButton(text="← Админка", callback_data="adm:home")])
    await message.answer("".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("adm:ubal:"))
async def admin_balance_start(
    callback: CallbackQuery,
    state: FSMContext,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    if await _authorize_callback(callback, admin_api_client, state=state) is None:
        return
    target_id = _callback_int(callback.data, 2)
    if target_id is None:
        await callback.answer("Повреждённая кнопка", show_alert=True)
        return
    await state.update_data(admin_target_user_id=target_id)
    await state.set_state(AdminStates.balance_amount)
    await _edit(
        callback,
        f"Пользователь <code>{target_id}</code>.\nВведите изменение CREDIT: например <code>500</code> или <code>-200</code>.",
        _back_keyboard(),
    )


@router.message(AdminStates.balance_amount)
async def admin_balance_amount(
    message: Message,
    state: FSMContext,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    if await _authorize_message(message, admin_api_client, state=state) is None:
        return
    raw = (message.text or "").strip()
    try:
        amount = int(raw)
    except ValueError:
        await message.answer("Нужно целое число CREDIT.")
        return
    if amount == 0:
        await message.answer("Изменение не может быть нулевым.")
        return
    await state.update_data(admin_balance_amount=amount)
    await state.set_state(AdminStates.balance_reason)
    await message.answer("Укажите причину корректировки.", reply_markup=_back_keyboard())


@router.message(AdminStates.balance_reason)
async def admin_balance_reason(
    message: Message,
    state: FSMContext,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    if await _authorize_message(message, admin_api_client, state=state) is None:
        return
    reason = (message.text or "").strip()
    if not reason:
        await message.answer("Причина обязательна.")
        return
    data = await state.get_data()
    target_id = data.get("admin_target_user_id")
    amount = data.get("admin_balance_amount")
    if not isinstance(target_id, int) or not isinstance(amount, int):
        await state.clear()
        await message.answer("Состояние устарело. Откройте /admin снова.")
        return
    await state.update_data(admin_balance_reason=reason)
    await state.set_state(AdminStates.balance_confirm)
    await message.answer(
        "<b>Подтверждение корректировки</b>\n"
        f"Пользователь: <code>{target_id}</code>\n"
        f"Изменение: <b>{amount:+d} CREDIT</b>\n"
        f"Причина: {html.escape(reason)}",
        reply_markup=_confirm_keyboard("adm:balance:confirm"),
    )


@router.callback_query(AdminStates.balance_confirm, F.data == "adm:balance:confirm")
async def admin_balance_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorize_callback(callback, admin_api_client, state=state)
    if user_id is None:
        return
    data = await state.get_data()
    target_id = data.get("admin_target_user_id")
    amount = data.get("admin_balance_amount")
    reason = data.get("admin_balance_reason")
    if not isinstance(target_id, int) or not isinstance(amount, int) or not isinstance(reason, str):
        await state.clear()
        await callback.answer("Состояние устарело", show_alert=True)
        return
    result = await _request(
        admin_api_client,
        "POST",
        f"/internal/admin/users/{target_id}/balance-adjustments",
        user_id,
        payload={"amount_units": amount, "reason": reason},
        idempotency_key=str(uuid4()),
        confirm=True,
    )
    await state.clear()
    if result is not None:
        await _edit(callback, _json_text(result), _back_keyboard())


@router.callback_query(F.data.startswith("adm:ublock:"))
async def admin_block_start(
    callback: CallbackQuery,
    state: FSMContext,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    if await _authorize_callback(callback, admin_api_client, state=state) is None:
        return
    target_id = _callback_int(callback.data, 2)
    if target_id is None:
        await callback.answer("Повреждённая кнопка", show_alert=True)
        return
    await state.update_data(admin_target_user_id=target_id)
    await state.set_state(AdminStates.block_reason)
    await _edit(
        callback,
        f"Причина блокировки пользователя <code>{target_id}</code>?",
        _back_keyboard(),
    )


@router.message(AdminStates.block_reason)
async def admin_block_reason(
    message: Message,
    state: FSMContext,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    if await _authorize_message(message, admin_api_client, state=state) is None:
        return
    reason = (message.text or "").strip()
    if not reason:
        await message.answer("Причина обязательна.")
        return
    data = await state.get_data()
    target_id = data.get("admin_target_user_id")
    if not isinstance(target_id, int):
        await state.clear()
        return
    await state.update_data(admin_block_reason=reason)
    await state.set_state(AdminStates.block_confirm)
    await message.answer(
        f"Заблокировать <code>{target_id}</code>?\nПричина: {html.escape(reason)}",
        reply_markup=_confirm_keyboard("adm:block:confirm"),
    )


@router.callback_query(AdminStates.block_confirm, F.data == "adm:block:confirm")
async def admin_block_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorize_callback(callback, admin_api_client, state=state)
    if user_id is None:
        return
    data = await state.get_data()
    target_id = data.get("admin_target_user_id")
    reason = data.get("admin_block_reason")
    if not isinstance(target_id, int) or not isinstance(reason, str):
        await state.clear()
        return
    result = await _request(
        admin_api_client,
        "POST",
        f"/internal/admin/users/{target_id}/block",
        user_id,
        payload={"reason": reason},
        idempotency_key=str(uuid4()),
        confirm=True,
    )
    await state.clear()
    if result is not None:
        await _edit(callback, _json_text(result), _back_keyboard())


@router.callback_query(F.data.startswith("adm:uunblock:"))
async def admin_unblock(
    callback: CallbackQuery,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorize_callback(callback, admin_api_client)
    if user_id is None:
        return
    target_id = _callback_int(callback.data, 2)
    if target_id is None:
        return
    result = await _request(
        admin_api_client,
        "POST",
        f"/internal/admin/users/{target_id}/unblock",
        user_id,
        payload=None,
        idempotency_key=str(uuid4()),
        confirm=True,
    )
    if result is not None:
        await _edit(callback, _json_text(result), _back_keyboard())


@router.callback_query(F.data == "adm:payments")
async def admin_payments(
    callback: CallbackQuery,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorize_callback(callback, admin_api_client)
    if user_id is None:
        return
    data = await _request(
        admin_api_client,
        "GET",
        "/internal/admin/payments",
        user_id,
        params={"limit": 20},
    )
    if data is not None:
        await _edit(callback, _json_text(data), _back_keyboard())


@router.callback_query(F.data == "adm:withdrawals")
async def admin_withdrawals(
    callback: CallbackQuery,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorize_callback(callback, admin_api_client)
    if user_id is None:
        return
    data = await _request(
        admin_api_client,
        "GET",
        "/internal/admin/partners/withdrawals",
        user_id,
        params={"status": "pending", "limit": 20},
    )
    if not isinstance(data, list):
        return
    lines = ["<b>Partner withdrawals</b>"]
    rows: list[list[InlineKeyboardButton]] = []
    for item in data[:10]:
        if not isinstance(item, dict):
            continue
        withdrawal_id = item.get("id")
        if not isinstance(withdrawal_id, str):
            continue
        lines.append(
            f"\n<code>{html.escape(withdrawal_id)}</code> · user {item.get('user_id')} · {item.get('amount_units')} CREDIT"
        )
        rows.append(
            [
                InlineKeyboardButton(text="Approve", callback_data=f"adm:wd:a:{withdrawal_id}"),
                InlineKeyboardButton(text="Reject", callback_data=f"adm:wd:r:{withdrawal_id}"),
            ]
        )
    rows.append([InlineKeyboardButton(text="← Админка", callback_data="adm:home")])
    await _edit(callback, "".join(lines), InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("adm:wd:"))
async def admin_withdrawal_action(
    callback: CallbackQuery,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorize_callback(callback, admin_api_client)
    if user_id is None or callback.data is None:
        return
    parts = callback.data.split(":", 3)
    if len(parts) != 4:
        return
    action = {"a": "approve", "r": "reject", "p": "mark_paid"}.get(parts[2])
    if action is None:
        return
    withdrawal_id = parts[3]
    result = await _request(
        admin_api_client,
        "POST",
        f"/internal/admin/partners/withdrawals/{withdrawal_id}/actions",
        user_id,
        payload={"action": action},
        idempotency_key=str(uuid4()),
        confirm=True,
    )
    if result is not None:
        await _edit(callback, _json_text(result), _back_keyboard())


@router.callback_query(F.data == "adm:tariffs")
async def admin_tariffs(
    callback: CallbackQuery,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorize_callback(callback, admin_api_client)
    if user_id is None:
        return
    data = await _request(admin_api_client, "GET", "/internal/admin/tariffs", user_id)
    if data is None:
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Опубликовать новую версию", callback_data="adm:tariff:edit"
                )
            ],
            [InlineKeyboardButton(text="← Админка", callback_data="adm:home")],
        ]
    )
    await _edit(callback, _json_text(data), keyboard)


@router.callback_query(F.data == "adm:tariff:edit")
async def admin_tariff_edit(
    callback: CallbackQuery,
    state: FSMContext,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    if await _authorize_callback(callback, admin_api_client, state=state) is None:
        return
    await state.set_state(AdminStates.tariff_payload)
    await _edit(
        callback,
        "Отправьте JSON новой версии тарифа. Поддерживаются sections: "
        "<code>packages</code>, <code>model_prices</code>, <code>image_prices</code>, "
        "<code>video_prices</code>, <code>partner_exchange</code>, <code>prompt_costs</code>, "
        "<code>video_prompt_costs</code>.",
        _back_keyboard(),
    )


@router.message(AdminStates.tariff_payload)
async def admin_tariff_payload(
    message: Message,
    state: FSMContext,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    if await _authorize_message(message, admin_api_client, state=state) is None:
        return
    raw = (message.text or "").strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        await message.answer(f"JSON invalid: {html.escape(str(exc))}")
        return
    if not isinstance(payload, dict):
        await message.answer("Нужен JSON object.")
        return
    await state.update_data(admin_tariff_payload=payload)
    await state.set_state(AdminStates.tariff_confirm)
    await message.answer(
        "<b>Новая версия тарифа</b>\n" + _json_text(payload),
        reply_markup=_confirm_keyboard("adm:tariff:confirm"),
    )


@router.callback_query(AdminStates.tariff_confirm, F.data == "adm:tariff:confirm")
async def admin_tariff_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorize_callback(callback, admin_api_client, state=state)
    if user_id is None:
        return
    payload = (await state.get_data()).get("admin_tariff_payload")
    if not isinstance(payload, dict):
        await state.clear()
        return
    result = await _request(
        admin_api_client,
        "POST",
        "/internal/admin/tariffs/publish",
        user_id,
        payload={"payload": payload},
        idempotency_key=str(uuid4()),
        confirm=True,
    )
    await state.clear()
    if result is not None:
        await _edit(callback, _json_text(result), _back_keyboard())


@router.callback_query(F.data == "adm:promos")
async def admin_promos(
    callback: CallbackQuery,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    if await _authorize_callback(callback, admin_api_client) is None:
        return
    await _edit(
        callback,
        "<b>Промокоды</b>\nВыберите действие.",
        InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Найти", callback_data="adm:promo:lookup")],
                [InlineKeyboardButton(text="Создать", callback_data="adm:promo:create")],
                [InlineKeyboardButton(text="← Админка", callback_data="adm:home")],
            ]
        ),
    )


@router.callback_query(F.data == "adm:promo:lookup")
async def admin_promo_lookup_start(
    callback: CallbackQuery,
    state: FSMContext,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    if await _authorize_callback(callback, admin_api_client, state=state) is None:
        return
    await state.set_state(AdminStates.promo_lookup)
    await _edit(callback, "Введите promo code.", _back_keyboard())


@router.message(AdminStates.promo_lookup)
async def admin_promo_lookup(
    message: Message,
    state: FSMContext,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorize_message(message, admin_api_client, state=state)
    if user_id is None:
        return
    code = (message.text or "").strip().upper()
    result = await _request(admin_api_client, "GET", f"/internal/admin/promos/{code}", user_id)
    await state.clear()
    if isinstance(result, dict):
        active = bool(result.get("active"))
        await message.answer(
            _json_text(result),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Деактивировать" if active else "Активировать",
                            callback_data=f"adm:promo:set:{0 if active else 1}:{code}",
                        )
                    ],
                    [InlineKeyboardButton(text="← Админка", callback_data="adm:home")],
                ]
            ),
        )


@router.callback_query(F.data == "adm:promo:create")
async def admin_promo_create_start(
    callback: CallbackQuery,
    state: FSMContext,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    if await _authorize_callback(callback, admin_api_client, state=state) is None:
        return
    await state.set_state(AdminStates.promo_create)
    await _edit(
        callback,
        "Введите: <code>CODE reward_units max_uses</code>. max_uses можно указать <code>-</code>.",
        _back_keyboard(),
    )


@router.message(AdminStates.promo_create)
async def admin_promo_create(
    message: Message,
    state: FSMContext,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorize_message(message, admin_api_client, state=state)
    if user_id is None:
        return
    parts = (message.text or "").split()
    if len(parts) != 3:
        await message.answer("Формат: CODE reward_units max_uses")
        return
    try:
        reward_units = int(parts[1])
        max_uses = None if parts[2] == "-" else int(parts[2])
    except ValueError:
        await message.answer("reward_units/max_uses должны быть числами.")
        return
    result = await _request(
        admin_api_client,
        "POST",
        "/internal/admin/promos",
        user_id,
        payload={
            "code": parts[0].upper(),
            "reward_units": reward_units,
            "max_uses": max_uses,
            "metadata": {},
        },
        idempotency_key=str(uuid4()),
    )
    await state.clear()
    if result is not None:
        await message.answer(_json_text(result), reply_markup=_back_keyboard())


@router.callback_query(F.data.startswith("adm:promo:set:"))
async def admin_promo_set(
    callback: CallbackQuery,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorize_callback(callback, admin_api_client)
    if user_id is None or callback.data is None:
        return
    parts = callback.data.split(":", 4)
    if len(parts) != 5:
        return
    active = parts[3] == "1"
    code = parts[4]
    result = await _request(
        admin_api_client,
        "POST",
        f"/internal/admin/promos/{code}/active",
        user_id,
        payload={"active": active},
        idempotency_key=str(uuid4()),
        confirm=True,
    )
    if result is not None:
        await _edit(callback, _json_text(result), _back_keyboard())


@router.callback_query(F.data == "adm:prompts")
async def admin_prompts(
    callback: CallbackQuery,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorize_callback(callback, admin_api_client)
    if user_id is None:
        return
    result = await _request(
        admin_api_client,
        "GET",
        "/internal/admin/prompts",
        user_id,
        params={"status": "pending", "limit": 20},
    )
    if not isinstance(result, list):
        return
    rows: list[list[InlineKeyboardButton]] = []
    lines = ["<b>Pending prompts</b>"]
    for item in result[:10]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        item_id = str(item["id"])
        lines.append(f"\n<code>{item_id}</code> · {html.escape(str(item.get('title') or ''))}")
        rows.append([InlineKeyboardButton(text="Открыть", callback_data=f"adm:prompt:{item_id}")])
    rows.append([InlineKeyboardButton(text="← Админка", callback_data="adm:home")])
    await _edit(callback, "".join(lines), InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("adm:prompt:") & ~F.data.startswith("adm:prompt:act:"))
async def admin_prompt_detail(
    callback: CallbackQuery,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorize_callback(callback, admin_api_client)
    if user_id is None or callback.data is None:
        return
    item_id = callback.data.split(":", 2)[2]
    result = await _request(admin_api_client, "GET", f"/internal/admin/prompts/{item_id}", user_id)
    if not isinstance(result, dict):
        return
    await _edit(
        callback,
        _json_text(result),
        InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Approve", callback_data=f"adm:prompt:act:a:{item_id}"
                    ),
                    InlineKeyboardButton(
                        text="Reject", callback_data=f"adm:prompt:act:r:{item_id}"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="Deactivate", callback_data=f"adm:prompt:act:d:{item_id}"
                    )
                ],
                [InlineKeyboardButton(text="← Промпты", callback_data="adm:prompts")],
            ]
        ),
    )


@router.callback_query(F.data.startswith("adm:prompt:act:"))
async def admin_prompt_action(
    callback: CallbackQuery,
    state: FSMContext,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorize_callback(callback, admin_api_client, state=state)
    if user_id is None or callback.data is None:
        return
    parts = callback.data.split(":", 4)
    if len(parts) != 5:
        return
    action = {"a": "approve", "r": "reject", "d": "deactivate"}.get(parts[3])
    item_id = parts[4]
    if action is None:
        return
    if action == "reject":
        await state.update_data(admin_prompt_item_id=item_id)
        await state.set_state(AdminStates.prompt_reject_reason)
        await _edit(callback, "Введите причину reject.", _back_keyboard())
        return
    result = await _request(
        admin_api_client,
        "POST",
        f"/internal/admin/prompts/{item_id}/moderate",
        user_id,
        payload={"action": action, "reason": None},
        idempotency_key=str(uuid4()),
        confirm=True,
    )
    if result is not None:
        await _edit(callback, _json_text(result), _back_keyboard())


@router.message(AdminStates.prompt_reject_reason)
async def admin_prompt_reject_reason(
    message: Message,
    state: FSMContext,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorize_message(message, admin_api_client, state=state)
    if user_id is None:
        return
    data = await state.get_data()
    item_id = data.get("admin_prompt_item_id")
    reason = (message.text or "").strip()
    if not isinstance(item_id, str) or not reason:
        await message.answer("Причина обязательна.")
        return
    result = await _request(
        admin_api_client,
        "POST",
        f"/internal/admin/prompts/{item_id}/moderate",
        user_id,
        payload={"action": "reject", "reason": reason},
        idempotency_key=str(uuid4()),
        confirm=True,
    )
    await state.clear()
    if result is not None:
        await message.answer(_json_text(result), reply_markup=_back_keyboard())


@router.callback_query(F.data == "adm:broadcast")
async def admin_broadcast_start(
    callback: CallbackQuery,
    state: FSMContext,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    if await _authorize_callback(callback, admin_api_client, state=state) is None:
        return
    await state.set_state(AdminStates.broadcast_name)
    await _edit(callback, "Название кампании?", _back_keyboard())


@router.message(AdminStates.broadcast_name)
async def admin_broadcast_name(
    message: Message,
    state: FSMContext,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    if await _authorize_message(message, admin_api_client, state=state) is None:
        return
    name = (message.text or "").strip()
    if not name:
        await message.answer("Название обязательно.")
        return
    await state.update_data(admin_campaign_name=name)
    await state.set_state(AdminStates.broadcast_message)
    await message.answer("Текст рассылки?", reply_markup=_back_keyboard())


@router.message(AdminStates.broadcast_message)
async def admin_broadcast_message(
    message: Message,
    state: FSMContext,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    if await _authorize_message(message, admin_api_client, state=state) is None:
        return
    text = (message.text or "").strip()
    if not text:
        await message.answer("Текст обязателен.")
        return
    await state.update_data(admin_campaign_message=text)
    await state.set_state(AdminStates.broadcast_segment)
    await message.answer(
        "Segment JSON. Для всех пользователей отправьте <code>{}</code>. "
        "Поддерживаются user_ids, created_after, created_before.",
        reply_markup=_back_keyboard(),
    )


@router.message(AdminStates.broadcast_segment)
async def admin_broadcast_segment(
    message: Message,
    state: FSMContext,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorize_message(message, admin_api_client, state=state)
    if user_id is None:
        return
    try:
        segment = json.loads((message.text or "{}").strip())
    except json.JSONDecodeError:
        await message.answer("Невалидный JSON segment.")
        return
    if not isinstance(segment, dict):
        await message.answer("Segment должен быть JSON object.")
        return
    data = await state.get_data()
    name = data.get("admin_campaign_name")
    text = data.get("admin_campaign_message")
    if not isinstance(name, str) or not isinstance(text, str):
        await state.clear()
        return
    preview = await _request(
        admin_api_client,
        "POST",
        "/internal/admin/notifications/preview",
        user_id,
        payload={"message": text, "segment": segment},
    )
    if not isinstance(preview, dict):
        return
    await state.update_data(admin_campaign_segment=segment)
    await state.set_state(AdminStates.broadcast_confirm)
    await message.answer(
        "<b>Broadcast preview</b>\n"
        f"Название: {html.escape(name)}\n"
        f"Получателей: <b>{preview.get('recipient_count', 0)}</b>\n\n"
        f"{html.escape(text)}",
        reply_markup=_confirm_keyboard("adm:broadcast:confirm"),
    )


@router.callback_query(AdminStates.broadcast_confirm, F.data == "adm:broadcast:confirm")
async def admin_broadcast_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorize_callback(callback, admin_api_client, state=state)
    if user_id is None:
        return
    data = await state.get_data()
    name = data.get("admin_campaign_name")
    text = data.get("admin_campaign_message")
    segment = data.get("admin_campaign_segment")
    if not isinstance(name, str) or not isinstance(text, str) or not isinstance(segment, dict):
        await state.clear()
        return
    created = await _request(
        admin_api_client,
        "POST",
        "/internal/admin/notifications/campaigns",
        user_id,
        payload={"name": name, "message": text, "segment": segment},
        idempotency_key=str(uuid4()),
    )
    if not isinstance(created, dict) or not isinstance(created.get("campaign_id"), str):
        return
    campaign_id = str(created["campaign_id"])
    started = await _request(
        admin_api_client,
        "POST",
        f"/internal/admin/notifications/campaigns/{campaign_id}/start",
        user_id,
        payload=None,
        idempotency_key=str(uuid4()),
        confirm=True,
    )
    await state.clear()
    if started is not None:
        await _edit(callback, _json_text(started), _back_keyboard())


@router.callback_query(F.data == "adm:support")
async def admin_support(
    callback: CallbackQuery,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorize_callback(callback, admin_api_client)
    if user_id is None:
        return
    data = await _request(
        admin_api_client,
        "GET",
        "/internal/admin/tickets",
        user_id,
        params={"limit": 20},
    )
    if not isinstance(data, list):
        return
    rows: list[list[InlineKeyboardButton]] = []
    lines = ["<b>Support tickets</b>"]
    for item in data[:10]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        ticket_id = str(item["id"])
        lines.append(
            f"\n<code>{ticket_id}</code> · user {item.get('user_id')} · {html.escape(str(item.get('status')))}"
        )
        rows.append([InlineKeyboardButton(text="Открыть", callback_data=f"adm:ticket:{ticket_id}")])
    rows.append([InlineKeyboardButton(text="← Админка", callback_data="adm:home")])
    await _edit(callback, "".join(lines), InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("adm:ticket:"))
async def admin_ticket_detail(
    callback: CallbackQuery,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorize_callback(callback, admin_api_client)
    if user_id is None or callback.data is None:
        return
    ticket_id = callback.data.split(":", 2)[2]
    result = await _request(
        admin_api_client, "GET", f"/internal/admin/tickets/{ticket_id}", user_id
    )
    if result is None:
        return
    await _edit(
        callback,
        _json_text(result),
        InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Ответить", callback_data=f"adm:ticketreply:{ticket_id}"
                    )
                ],
                [InlineKeyboardButton(text="← Тикеты", callback_data="adm:support")],
            ]
        ),
    )


@router.callback_query(F.data.startswith("adm:ticketreply:"))
async def admin_ticket_reply_start(
    callback: CallbackQuery,
    state: FSMContext,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    if (
        await _authorize_callback(callback, admin_api_client, state=state) is None
        or callback.data is None
    ):
        return
    ticket_id = callback.data.split(":", 2)[2]
    await state.update_data(admin_ticket_id=ticket_id)
    await state.set_state(AdminStates.support_reply)
    await _edit(callback, "Введите ответ пользователю.", _back_keyboard())


@router.message(AdminStates.support_reply)
async def admin_ticket_reply(
    message: Message,
    state: FSMContext,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorize_message(message, admin_api_client, state=state)
    if user_id is None:
        return
    data = await state.get_data()
    ticket_id = data.get("admin_ticket_id")
    text = (message.text or "").strip()
    if not isinstance(ticket_id, str) or not text:
        await message.answer("Ответ не может быть пустым.")
        return
    result = await _request(
        admin_api_client,
        "POST",
        f"/internal/admin/tickets/{ticket_id}/reply",
        user_id,
        payload={"body": text},
        idempotency_key=str(uuid4()),
        confirm=True,
    )
    await state.clear()
    if result is not None:
        await message.answer(_json_text(result), reply_markup=_back_keyboard())


@router.callback_query(F.data == "adm:operations")
async def admin_operations(
    callback: CallbackQuery,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorize_callback(callback, admin_api_client)
    if user_id is None:
        return
    result = await _request(
        admin_api_client,
        "GET",
        "/internal/admin/operations",
        user_id,
        params={"limit": 20},
    )
    if not isinstance(result, list):
        return
    rows: list[list[InlineKeyboardButton]] = []
    lines = ["<b>Operations</b>"]
    for item in result[:10]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        operation_id = str(item["id"])
        lines.append(
            f"\n<code>{operation_id}</code> · {html.escape(str(item.get('operation_type')))} · {html.escape(str(item.get('status')))}"
        )
        rows.append([InlineKeyboardButton(text="Открыть", callback_data=f"adm:op:{operation_id}")])
    rows.append([InlineKeyboardButton(text="← Админка", callback_data="adm:home")])
    await _edit(callback, "".join(lines), InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("adm:op:") & ~F.data.startswith("adm:op:replay:"))
async def admin_operation_detail(
    callback: CallbackQuery,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorize_callback(callback, admin_api_client)
    if user_id is None or callback.data is None:
        return
    operation_id = callback.data.split(":", 2)[2]
    result = await _request(
        admin_api_client,
        "GET",
        f"/internal/admin/operations/{operation_id}/timeline",
        user_id,
    )
    if result is None:
        return
    await _edit(
        callback,
        _json_text(result),
        InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Replay safe op", callback_data=f"adm:op:replay:{operation_id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Refund", callback_data=f"adm:op:refund:{operation_id}"
                    )
                ],
                [InlineKeyboardButton(text="← Operations", callback_data="adm:operations")],
            ]
        ),
    )


@router.callback_query(F.data.startswith("adm:op:replay:"))
async def admin_operation_replay(
    callback: CallbackQuery,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorize_callback(callback, admin_api_client)
    if user_id is None or callback.data is None:
        return
    operation_id = callback.data.split(":", 3)[3]
    result = await _request(
        admin_api_client,
        "POST",
        f"/internal/admin/operations/{operation_id}/replay",
        user_id,
        payload=None,
        idempotency_key=str(uuid4()),
        confirm=True,
    )
    if result is not None:
        await _edit(callback, _json_text(result), _back_keyboard())


@router.callback_query(F.data.startswith("adm:op:refund:"))
async def admin_operation_refund_start(
    callback: CallbackQuery,
    state: FSMContext,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    if (
        await _authorize_callback(callback, admin_api_client, state=state) is None
        or callback.data is None
    ):
        return
    operation_id = callback.data.split(":", 3)[3]
    await state.update_data(admin_operation_id=operation_id)
    await state.set_state(AdminStates.operation_refund_reason)
    await _edit(callback, "Причина refund?", _back_keyboard())


@router.message(AdminStates.operation_refund_reason)
async def admin_operation_refund(
    message: Message,
    state: FSMContext,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorize_message(message, admin_api_client, state=state)
    if user_id is None:
        return
    data = await state.get_data()
    operation_id = data.get("admin_operation_id")
    reason = (message.text or "").strip()
    if not isinstance(operation_id, str) or not reason:
        await message.answer("Причина обязательна.")
        return
    result = await _request(
        admin_api_client,
        "POST",
        f"/internal/admin/operations/{operation_id}/refund",
        user_id,
        payload={"reason": reason},
        idempotency_key=str(uuid4()),
        confirm=True,
    )
    await state.clear()
    if result is not None:
        await message.answer(_json_text(result), reply_markup=_back_keyboard())


@router.callback_query(F.data == "adm:cms")
async def admin_cms(
    callback: CallbackQuery,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorize_callback(callback, admin_api_client)
    if user_id is None:
        return
    result = await _request(admin_api_client, "GET", "/internal/admin/cms/documents", user_id)
    if result is not None:
        await _edit(callback, _json_text(result), _back_keyboard())


@router.callback_query(F.data == "adm:exports")
async def admin_exports(
    callback: CallbackQuery,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    if await _authorize_callback(callback, admin_api_client) is None:
        return
    await _edit(
        callback,
        "Выберите выгрузку.",
        InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Users CSV", callback_data="adm:export:users")],
                [InlineKeyboardButton(text="Finance CSV", callback_data="adm:export:finance")],
                [InlineKeyboardButton(text="← Админка", callback_data="adm:home")],
            ]
        ),
    )


@router.callback_query(F.data.startswith("adm:export:"))
async def admin_export_download(
    callback: CallbackQuery,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorize_callback(callback, admin_api_client)
    if (
        user_id is None
        or callback.data is None
        or callback.message is None
        or admin_api_client is None
    ):
        return
    kind = callback.data.split(":", 2)[2]
    path = {
        "users": "/internal/admin/exports/users.csv",
        "finance": "/internal/admin/exports/finance.csv",
    }.get(kind)
    if path is None:
        return
    try:
        content, _ = await admin_api_client.download(path, admin_user_id=user_id)
    except AdminApiClientError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    await callback.message.answer_document(
        BufferedInputFile(content, filename=f"foxgen-{kind}.csv")
    )
    await callback.answer("Готово")


@router.callback_query(F.data.in_({"adm:sub:on", "adm:sub:off"}))
async def admin_subscription_toggle(
    callback: CallbackQuery,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorize_callback(callback, admin_api_client)
    if user_id is None:
        return
    enabled = callback.data == "adm:sub:on"
    result = await _request(
        admin_api_client,
        "POST",
        "/internal/admin/runtime/flags/subscription_required",
        user_id,
        payload={"enabled": enabled, "value": {}},
        idempotency_key=str(uuid4()),
        confirm=True,
    )
    if result is not None:
        await _edit(callback, _json_text(result), _back_keyboard())


@router.callback_query(F.data == "adm:modeltoggle")
async def admin_model_toggle_start(
    callback: CallbackQuery,
    state: FSMContext,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    if await _authorize_callback(callback, admin_api_client, state=state) is None:
        return
    await state.set_state(AdminStates.model_toggle_slug)
    await _edit(
        callback,
        "Введите <code>model_slug on</code> или <code>model_slug off</code>.",
        _back_keyboard(),
    )


@router.message(AdminStates.model_toggle_slug)
async def admin_model_toggle(
    message: Message,
    state: FSMContext,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorize_message(message, admin_api_client, state=state)
    if user_id is None:
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or parts[1].lower() not in {"on", "off"}:
        await message.answer("Формат: model_slug on|off")
        return
    slug = parts[0]
    enabled = parts[1].lower() == "on"
    result = await _request(
        admin_api_client,
        "POST",
        f"/internal/admin/models/{slug}/availability",
        user_id,
        payload={"enabled": enabled, "reason": "telegram_admin"},
        idempotency_key=str(uuid4()),
        confirm=True,
    )
    await state.clear()
    if result is not None:
        await message.answer(_json_text(result), reply_markup=_back_keyboard())


async def _authorize_message(
    message: Message,
    client: AdminApiClient | None,
    *,
    state: FSMContext | None = None,
) -> int | None:
    if client is None:
        if state is not None:
            await state.clear()
        await message.answer("Admin API не настроен.")
        return None
    if message.from_user is None:
        return None
    user_id = message.from_user.id
    try:
        await client.health(user_id)
    except AdminApiClientError as exc:
        if state is not None:
            await state.clear()
        if exc.status_code in {401, 403, 404}:
            await message.answer("Доступ к админ-панели запрещён.")
        else:
            await message.answer(html.escape(exc.message))
        return None
    return user_id


async def _authorize_callback(
    callback: CallbackQuery,
    client: AdminApiClient | None,
    *,
    state: FSMContext | None = None,
) -> int | None:
    if client is None:
        if state is not None:
            await state.clear()
        await callback.answer("Admin API не настроен", show_alert=True)
        return None
    user_id = callback.from_user.id
    try:
        await client.health(user_id)
    except AdminApiClientError as exc:
        if state is not None:
            await state.clear()
        message = "Нет доступа" if exc.status_code in {401, 403, 404} else exc.message
        await callback.answer(message, show_alert=True)
        return None
    return user_id


async def _request(
    client: AdminApiClient | None,
    method: str,
    path: str,
    admin_user_id: int,
    *,
    params: dict[str, object] | None = None,
    payload: dict[str, object] | None = None,
    idempotency_key: str | None = None,
    confirm: bool = False,
) -> Any | None:
    if client is None:
        return None
    try:
        return await client.request(
            method,
            path,
            admin_user_id=admin_user_id,
            params=params,
            payload=payload,
            idempotency_key=idempotency_key,
            confirm=confirm,
        )
    except AdminApiClientError:
        return None


async def _call(
    client: AdminApiClient | None, method: str, admin_user_id: int
) -> dict[str, object] | None:
    if client is None:
        return None
    try:
        func = getattr(client, method)
        result: Any = await func(admin_user_id)
    except (AdminApiClientError, AttributeError):
        return None
    return result if isinstance(result, dict) else None


async def _edit(
    callback: CallbackQuery,
    text: str,
    keyboard: InlineKeyboardMarkup,
) -> None:
    if callback.message:
        await callback.message.edit_text(_truncate(text), reply_markup=keyboard)
    await callback.answer()


def _json_text(value: object) -> str:
    rendered = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    return f"<pre>{html.escape(_truncate(rendered, limit=3600))}</pre>"


def _truncate(value: str, *, limit: int = 3900) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 20] + "\n…[truncated]"


def _callback_int(value: str | None, index: int) -> int | None:
    if value is None:
        return None
    parts = value.split(":")
    if index >= len(parts):
        return None
    try:
        return int(parts[index])
    except ValueError:
        return None
