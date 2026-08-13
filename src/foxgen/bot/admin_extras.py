from __future__ import annotations

import html
import json
from uuid import uuid4

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from foxgen.bot.admin_api_client import AdminApiClient, AdminApiClientError


router = Router(name="foxgen-admin-extras")


@router.callback_query(F.data == "adm:analytics")
async def admin_analytics(
    callback: CallbackQuery,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorized(callback, admin_api_client)
    if user_id is None or admin_api_client is None:
        return
    try:
        data = await admin_api_client.request(
            "GET",
            "/internal/admin/analytics",
            admin_user_id=user_id,
            params={"hours": 24},
        )
    except AdminApiClientError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    await _edit_json(callback, data)


@router.callback_query(F.data.startswith("adm:exportxls:"))
async def admin_export_xls(
    callback: CallbackQuery,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorized(callback, admin_api_client)
    if (
        user_id is None
        or admin_api_client is None
        or callback.data is None
        or callback.message is None
    ):
        return
    kind = callback.data.split(":", 2)[2]
    path = {
        "users": "/internal/admin/exports/users.xls",
        "finance": "/internal/admin/exports/finance.xls",
    }.get(kind)
    if path is None:
        await callback.answer("Неизвестный export", show_alert=True)
        return
    try:
        content, _ = await admin_api_client.download(path, admin_user_id=user_id)
    except AdminApiClientError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    await callback.message.answer_document(
        BufferedInputFile(content, filename=f"foxgen-{kind}.xls")
    )
    await callback.answer("Готово")


@router.callback_query(F.data == "adm:withdrawals:approved")
async def approved_withdrawals(
    callback: CallbackQuery,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorized(callback, admin_api_client)
    if user_id is None or admin_api_client is None:
        return
    try:
        data = await admin_api_client.request(
            "GET",
            "/internal/admin/partners/withdrawals",
            admin_user_id=user_id,
            params={"status": "approved", "limit": 20},
        )
    except AdminApiClientError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    if not isinstance(data, list):
        await callback.answer("Повреждённый ответ API", show_alert=True)
        return

    lines = ["<b>Одобренные выводы</b>"]
    rows: list[list[InlineKeyboardButton]] = []
    for raw in data[:10]:
        if not isinstance(raw, dict):
            continue
        withdrawal_id = raw.get("id")
        if not isinstance(withdrawal_id, str):
            continue
        lines.append(
            "\n"
            f"<code>{html.escape(withdrawal_id)}</code> · "
            f"user {raw.get('user_id')} · {raw.get('amount_units')} CREDIT"
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="Отметить выплаченным",
                    callback_data=f"adm:wdpay:{withdrawal_id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="← Админка", callback_data="adm:home")])
    if callback.message:
        await callback.message.edit_text(
            "".join(lines),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:wdpay:"))
async def mark_withdrawal_paid(
    callback: CallbackQuery,
    admin_api_client: AdminApiClient | None = None,
) -> None:
    user_id = await _authorized(callback, admin_api_client)
    if user_id is None or admin_api_client is None or callback.data is None:
        return
    withdrawal_id = callback.data.split(":", 2)[2]
    try:
        result = await admin_api_client.request(
            "POST",
            f"/internal/admin/partners/withdrawals/{withdrawal_id}/actions",
            admin_user_id=user_id,
            payload={"action": "mark_paid"},
            idempotency_key=str(uuid4()),
            confirm=True,
        )
    except AdminApiClientError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    await _edit_json(callback, result)


async def _authorized(
    callback: CallbackQuery,
    client: AdminApiClient | None,
) -> int | None:
    if client is None:
        await callback.answer("Admin API не настроен", show_alert=True)
        return None
    user_id = callback.from_user.id
    try:
        await client.health(user_id)
    except AdminApiClientError as exc:
        message = "Нет доступа" if exc.status_code in {401, 403, 404} else exc.message
        await callback.answer(message, show_alert=True)
        return None
    return user_id


async def _edit_json(callback: CallbackQuery, value: object) -> None:
    rendered = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    if len(rendered) > 3600:
        rendered = rendered[:3580] + "\n…[truncated]"
    if callback.message:
        await callback.message.edit_text(
            f"<pre>{html.escape(rendered)}</pre>",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="← Админка", callback_data="adm:home")]
                ]
            ),
        )
    await callback.answer()
