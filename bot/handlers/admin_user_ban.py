from __future__ import annotations

import html
import logging

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext

from bot.config import config
from bot.database import get_existing_user_stats, set_user_banned
from bot.states import AdminStates

logger = logging.getLogger(__name__)
router = Router()


def _is_admin(user_id: int) -> bool:
    return config.is_admin(user_id)


def _parse_target_id(callback_data: str, prefix: str) -> int | None:
    raw_value = str(callback_data or "").removeprefix(prefix).strip()
    if not raw_value.isdigit():
        return None
    value = int(raw_value)
    return value if value > 0 else None


def _user_status_text(is_banned: bool) -> str:
    return "🔴 Заблокирован" if is_banned else "🟢 Активен"


def _user_profile_link(telegram_id: int, stats: dict) -> str:
    username = str(stats.get("username") or "").strip().lstrip("@")
    if username:
        url = f"https://t.me/{username}"
    else:
        url = f"tg://user?id={telegram_id}"
    return f'<a href="{html.escape(url, quote=True)}">{html.escape(url)}</a>'


def _user_card_text(telegram_id: int, stats: dict) -> str:
    is_banned = bool(stats.get("is_banned"))
    return "\n".join(
        [
            "👤 <b>Пользователь</b>",
            "",
            f"🆔 Telegram ID: <code>{telegram_id}</code>",
            f"🔗 Ссылка: {_user_profile_link(telegram_id, stats)}",
            f"🚦 Статус: <b>{_user_status_text(is_banned)}</b>",
            f"💰 Кредитов: <code>{html.escape(str(stats.get('credits', 0)))}</code>",
            f"📊 Генераций: <code>{html.escape(str(stats.get('generations', 0)))}</code>",
            f"💸 Потрачено: <code>{html.escape(str(stats.get('total_spent', 0)))}</code>",
            f"📅 Регистрация: <code>{html.escape(str(stats.get('member_since') or '—'))}</code>",
            f"🤝 Рефералов: <code>{html.escape(str(stats.get('referrals_count', 0)))}</code>",
            f"🎁 Заработано по рефке: <code>{html.escape(str(stats.get('referral_earned', 0)))}</code> 🍌",
            f"🔗 Рефкод: <code>{html.escape(str(stats.get('referral_code') or '—'))}</code>",
            "",
            "Выберите действие:",
        ]
    )


def _user_card_keyboard(telegram_id: int, *, is_banned: bool) -> types.InlineKeyboardMarkup:
    ban_button = (
        types.InlineKeyboardButton(
            text="✅ Разбанить",
            callback_data=f"admin_unban_user_{telegram_id}",
        )
        if is_banned
        else types.InlineKeyboardButton(
            text="🚫 Забанить",
            callback_data=f"admin_ban_user_{telegram_id}",
        )
    )
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="➕ Добавить кредиты",
                    callback_data=f"admin_add_credits_{telegram_id}",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="➖ Списать кредиты",
                    callback_data=f"admin_deduct_credits_{telegram_id}",
                )
            ],
            [ban_button],
            [
                types.InlineKeyboardButton(
                    text="🤝 Реферальная статистика",
                    callback_data=f"admin_partner_view_{telegram_id}",
                )
            ],
            [types.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")],
        ]
    )


def _ban_confirm_keyboard(telegram_id: int) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="🚫 Да, забанить",
                    callback_data=f"admin_ban_confirm_{telegram_id}",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="↩️ Отмена",
                    callback_data=f"admin_user_card_{telegram_id}",
                )
            ],
        ]
    )


async def _load_existing_user(telegram_id: int) -> dict | None:
    try:
        return await get_existing_user_stats(telegram_id)
    except Exception:
        logger.exception("Admin user card lookup failed: telegram_id=%s", telegram_id)
        return None


async def _edit_user_card(
    callback: types.CallbackQuery,
    telegram_id: int,
    *,
    notice: str | None = None,
) -> None:
    stats = await _load_existing_user(telegram_id)
    if not stats:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    text = _user_card_text(telegram_id, stats)
    if notice:
        text = f"{html.escape(notice)}\n\n{text}"
    if callback.message is not None:
        await callback.message.edit_text(
            text,
            reply_markup=_user_card_keyboard(
                telegram_id,
                is_banned=bool(stats.get("is_banned")),
            ),
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(AdminStates.waiting_user_id)
async def admin_process_user_id_with_ban(message: types.Message, state: FSMContext) -> None:
    """Render the existing admin user card with ban/unban controls."""
    if not message.from_user or not _is_admin(message.from_user.id):
        await message.answer("⛔ Нет доступа")
        await state.clear()
        return

    raw_value = str(message.text or "").strip()
    if not raw_value.isdigit() or int(raw_value) <= 0:
        await message.answer("❌ Неверный формат ID. Введите Telegram ID числом:")
        return

    telegram_id = int(raw_value)
    stats = await _load_existing_user(telegram_id)
    if not stats:
        await message.answer(f"❌ Пользователь с ID {telegram_id} не найден.")
        return

    await message.answer(
        _user_card_text(telegram_id, stats),
        reply_markup=_user_card_keyboard(
            telegram_id,
            is_banned=bool(stats.get("is_banned")),
        ),
        parse_mode="HTML",
    )
    await state.clear()


@router.callback_query(F.data.startswith("admin_user_card_"))
async def admin_user_card(callback: types.CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    telegram_id = _parse_target_id(callback.data or "", "admin_user_card_")
    if telegram_id is None:
        await callback.answer("Некорректный ID", show_alert=True)
        return
    await _edit_user_card(callback, telegram_id)


@router.callback_query(F.data.startswith("admin_ban_user_"))
async def admin_ban_user_prompt(callback: types.CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    telegram_id = _parse_target_id(callback.data or "", "admin_ban_user_")
    if telegram_id is None:
        await callback.answer("Некорректный ID", show_alert=True)
        return
    if _is_admin(telegram_id):
        await callback.answer("Администратора заблокировать нельзя", show_alert=True)
        return

    stats = await _load_existing_user(telegram_id)
    if not stats:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    if bool(stats.get("is_banned")):
        await _edit_user_card(callback, telegram_id)
        return

    if callback.message is not None:
        await callback.message.edit_text(
            "\n".join(
                [
                    "⚠️ <b>Подтвердите блокировку</b>",
                    "",
                    f"Пользователь: <code>{telegram_id}</code>",
                    "",
                    "После подтверждения пользователь потеряет доступ к текстовому боту и Mini App.",
                    "Баланс, история и результаты пользователя не удаляются.",
                ]
            ),
            reply_markup=_ban_confirm_keyboard(telegram_id),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_ban_confirm_"))
async def admin_ban_user_confirm(callback: types.CallbackQuery) -> None:
    admin_id = callback.from_user.id
    if not _is_admin(admin_id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    telegram_id = _parse_target_id(callback.data or "", "admin_ban_confirm_")
    if telegram_id is None:
        await callback.answer("Некорректный ID", show_alert=True)
        return
    if _is_admin(telegram_id):
        await callback.answer("Администратора заблокировать нельзя", show_alert=True)
        return
    if not await _load_existing_user(telegram_id):
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    changed = await set_user_banned(telegram_id, True, admin_id=admin_id)
    if not changed:
        await callback.answer("Не удалось заблокировать пользователя", show_alert=True)
        return

    logger.warning(
        "User banned from Telegram admin panel: admin_id=%s telegram_id=%s",
        admin_id,
        telegram_id,
    )
    await _edit_user_card(callback, telegram_id, notice="✅ Пользователь заблокирован")


@router.callback_query(F.data.startswith("admin_unban_user_"))
async def admin_unban_user(callback: types.CallbackQuery) -> None:
    admin_id = callback.from_user.id
    if not _is_admin(admin_id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    telegram_id = _parse_target_id(callback.data or "", "admin_unban_user_")
    if telegram_id is None:
        await callback.answer("Некорректный ID", show_alert=True)
        return
    if not await _load_existing_user(telegram_id):
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    changed = await set_user_banned(telegram_id, False, admin_id=admin_id)
    if not changed:
        await callback.answer("Не удалось разблокировать пользователя", show_alert=True)
        return

    logger.info(
        "User unbanned from Telegram admin panel: admin_id=%s telegram_id=%s",
        admin_id,
        telegram_id,
    )
    await _edit_user_card(callback, telegram_id, notice="✅ Пользователь разблокирован")
