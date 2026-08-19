from __future__ import annotations

import html
import logging

from aiogram import F, Router, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext

from bot.config import config
from bot.services.partner_approval_service import (
    PARTNER_APPLICATION_APPROVED,
    PARTNER_APPLICATION_AVAILABLE,
    PARTNER_APPLICATION_PENDING,
    PARTNER_APPLICATION_REJECTED,
    get_partner_application_state,
    notify_admins_about_partner_application,
    notify_user_about_partner_review,
    review_partner_application,
    submit_partner_application,
)

logger = logging.getLogger(__name__)

user_router = Router()
admin_router = Router()


def _preapproval_keyboard(status: str) -> types.InlineKeyboardMarkup:
    rows: list[list[types.InlineKeyboardButton]] = [
        [
            types.InlineKeyboardButton(
                text="📜 Публичная оферта",
                callback_data="partner_offer",
            )
        ]
    ]
    if status == PARTNER_APPLICATION_AVAILABLE:
        rows.append(
            [
                types.InlineKeyboardButton(
                    text="🚀 Активировать партнёрскую ссылку",
                    callback_data="partner_accept",
                )
            ]
        )
    elif status == PARTNER_APPLICATION_REJECTED:
        rows.append(
            [
                types.InlineKeyboardButton(
                    text="🔁 Подать заявку повторно",
                    callback_data="partner_accept",
                )
            ]
        )
    elif status == PARTNER_APPLICATION_PENDING:
        rows.append(
            [
                types.InlineKeyboardButton(
                    text="🔄 Проверить статус",
                    callback_data="menu_partner",
                )
            ]
        )
    rows.append(
        [types.InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_main")]
    )
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def _preapproval_text(status: str) -> str:
    if status == PARTNER_APPLICATION_PENDING:
        return (
            "⏳ <b>Заявка на партнёрский кабинет рассматривается</b>\n\n"
            "Администратор уже получил заявку и ссылку на ваш Telegram-аккаунт. "
            "После одобрения здесь автоматически откроются статистика, баланс и "
            "ваша активная реферальная ссылка.\n\n"
            "Пока заявка не одобрена, реферальный код не привязывает новых пользователей."
        )
    if status == PARTNER_APPLICATION_REJECTED:
        return (
            "❌ <b>Заявка в партнёрскую программу отклонена</b>\n\n"
            "Партнёрская ссылка сейчас не активна. Если обстоятельства изменились, "
            "можно подать заявку повторно — она снова уйдёт администратору на рассмотрение."
        )
    return (
        "🤝 <b>Партнёрская программа</b>\n\n"
        "Для новых партнёров кабинет активируется вручную администратором.\n\n"
        "1. Ознакомьтесь с публичной офертой.\n"
        "2. Нажмите <b>«Активировать партнёрскую ссылку»</b>.\n"
        "3. Администратор получит заявку и ссылку на ваш Telegram-аккаунт.\n"
        "4. После одобрения откроются полноценный кабинет, статистика и реферальная ссылка.\n\n"
        "До одобрения реферальная ссылка не работает и новых пользователей за вами не закрепляет."
    )


async def _render_partner_entry(target: types.Message, telegram_id: int) -> None:
    state = await get_partner_application_state(telegram_id)
    if state["status"] == PARTNER_APPLICATION_APPROVED:
        # Keep the established partner dashboard for approved / legacy partners.
        from bot.handlers.common import render_partner_program

        await render_partner_program(target, user_id=telegram_id)
        return

    await target.answer(
        _preapproval_text(str(state["status"])),
        reply_markup=_preapproval_keyboard(str(state["status"])),
        parse_mode="HTML",
    )


@user_router.message(Command("ref", "earn", "partner"), StateFilter(None))
async def partner_command(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    await _render_partner_entry(message, message.from_user.id)


@user_router.callback_query(F.data.in_({"menu_referrals", "menu_partner"}))
async def partner_menu(callback: types.CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    partner_state = await get_partner_application_state(callback.from_user.id)
    if partner_state["status"] == PARTNER_APPLICATION_APPROVED:
        from bot.handlers.common import render_partner_program

        await render_partner_program(callback.message, user_id=callback.from_user.id)
    else:
        await callback.message.edit_text(
            _preapproval_text(str(partner_state["status"])),
            reply_markup=_preapproval_keyboard(str(partner_state["status"])),
            parse_mode="HTML",
        )
    await callback.answer()


@user_router.callback_query(F.data == "partner_stats")
async def partner_stats_gate(callback: types.CallbackQuery) -> None:
    """Block stale legacy partner-stat buttons until admin approval."""

    partner_state = await get_partner_application_state(callback.from_user.id)
    if partner_state["status"] == PARTNER_APPLICATION_APPROVED:
        from bot.handlers.common import partner_stats

        await partner_stats(callback)
        return

    await callback.message.edit_text(
        _preapproval_text(str(partner_state["status"])),
        reply_markup=_preapproval_keyboard(str(partner_state["status"])),
        parse_mode="HTML",
    )
    await callback.answer("Партнёрский кабинет ещё не активирован")


@user_router.callback_query(F.data == "partner_accept")
async def partner_application_submit(callback: types.CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    result = await submit_partner_application(
        callback.from_user.id,
        source="telegram_bot",
    )

    if result.get("status") == PARTNER_APPLICATION_APPROVED:
        from bot.handlers.common import render_partner_program

        await render_partner_program(callback.message, user_id=callback.from_user.id)
        await callback.answer("Партнёрский кабинет уже активирован")
        return

    application_id = result.get("application_id")
    if result.get("created") and application_id:
        await notify_admins_about_partner_application(callback.bot, int(application_id))

    await callback.message.edit_text(
        _preapproval_text(PARTNER_APPLICATION_PENDING),
        reply_markup=_preapproval_keyboard(PARTNER_APPLICATION_PENDING),
        parse_mode="HTML",
    )
    await callback.answer(
        "Заявка отправлена администратору"
        if result.get("created")
        else "Заявка уже рассматривается"
    )


async def _review_application(
    callback: types.CallbackQuery,
    *,
    application_id: int,
    approve: bool,
) -> None:
    if not config.is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    result = await review_partner_application(
        application_id,
        approve=approve,
        admin_telegram_id=callback.from_user.id,
    )
    if not result.get("ok"):
        reason = str(result.get("reason") or "")
        if reason == "already_processed":
            await callback.answer(
                f"Заявка уже обработана: {result.get('status') or '—'}",
                show_alert=True,
            )
        elif reason == "not_found":
            await callback.answer("Заявка не найдена", show_alert=True)
        else:
            await callback.answer("Не удалось обработать заявку", show_alert=True)
        return

    application = result.get("application") or {}
    telegram_id = application.get("telegram_id")
    username = str(application.get("username") or "").strip().lstrip("@")
    display = f"@{username}" if username else f"ID {telegram_id or '—'}"
    verdict = "✅ Одобрено" if approve else "❌ Отклонено"

    if callback.message:
        try:
            await callback.message.edit_text(
                "🤝 <b>Заявка в партнёрскую программу</b>\n\n"
                f"Пользователь: <code>{html.escape(display)}</code>\n"
                f"Telegram ID: <code>{telegram_id or '—'}</code>\n"
                f"Решение: <b>{verdict}</b>\n"
                f"Администратор: <code>{callback.from_user.id}</code>",
                parse_mode="HTML",
                reply_markup=None,
            )
        except Exception:
            logger.exception("Failed to update partner application review card")

    await notify_user_about_partner_review(
        callback.bot,
        application,
        approved=approve,
    )
    await callback.answer("Кабинет активирован" if approve else "Заявка отклонена")


@admin_router.callback_query(F.data.startswith("partner_app_approve_"))
async def approve_partner_application_callback(callback: types.CallbackQuery) -> None:
    try:
        application_id = int(callback.data.rsplit("_", 1)[1])
    except (TypeError, ValueError):
        await callback.answer("Некорректный ID заявки", show_alert=True)
        return
    await _review_application(
        callback,
        application_id=application_id,
        approve=True,
    )


@admin_router.callback_query(F.data.startswith("partner_app_reject_"))
async def reject_partner_application_callback(callback: types.CallbackQuery) -> None:
    try:
        application_id = int(callback.data.rsplit("_", 1)[1])
    except (TypeError, ValueError):
        await callback.answer("Некорректный ID заявки", show_alert=True)
        return
    await _review_application(
        callback,
        application_id=application_id,
        approve=False,
    )
