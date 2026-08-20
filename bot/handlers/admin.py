import asyncio
import csv
import io
import json
import logging
import html as html_utils
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from aiogram import Bot, F, Router, types
from aiogram.exceptions import TelegramAPIError, TelegramEntityTooLarge
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile

from bot import db as db_backend
from bot.config import config
from bot.database import (
    add_credits,
    approve_prompt,
    create_promo_code,
    deactivate_prompt,
    deduct_credits,
    export_users_for_admin,
    get_admin_finance_report,
    get_admin_referral_burst_autobans,
    get_admin_partner_details,
    get_admin_partner_payment_report,
    get_admin_partner_stats,
    get_admin_promo_stats,
    get_admin_prompt_details,
    get_admin_prompt_stats,
    get_admin_prompts,
    get_admin_stats,
    get_bot_setting,
    get_existing_user_stats,
    get_partner_withdrawal_request,
    get_pending_partner_withdrawals,
    get_promo_code_by_code,
    get_promo_code_details,
    get_promo_code_by_id,
    get_user_stats,
    is_channel_subscription_required,
    normalize_promo_code,
    set_maintenance_mode,
    reject_prompt,
    set_channel_subscription_required,
    set_promo_code_active,
    set_user_banned,
)
from bot.keyboards import (
    get_admin_keyboard,
    get_back_keyboard,
    get_main_menu_button_keyboard,
)
from bot.services.preset_manager import preset_manager
from bot.services.subscription_service import (
    REQUIRED_CHANNEL_USERNAME,
    clear_required_subscription_cache,
)
from bot.services.admin_ai_service import (
    admin_ai_service,
    normalize_plan,
    summarize_plan_actions,
    validate_plan,
)
from bot.states import AdminStates

logger = logging.getLogger(__name__)
router = Router()
PRICE_PATH = Path(config.PRICE_PATH)
BROADCAST_MESSAGE_LIMIT = 4096
BROADCAST_PHOTO_CAPTION_LIMIT = 1024
ADMIN_FINANCE_PREVIEW_LIMIT = 25
ADMIN_FINANCE_XLS_LIMIT = 5000
ADMIN_FINANCE_XLS_FALLBACK_LIMIT = 1000
ADMIN_FINANCE_TELEGRAM_MAX_BYTES = 45 * 1024 * 1024
ADMIN_PARTNER_XLS_REFERRALS_LIMIT = 5000
ADMIN_PARTNER_XLS_PAYMENTS_LIMIT = 5000
ADMIN_PARTNER_XLS_FALLBACK_LIMIT = 1000
ADMIN_PROMPTS_PREVIEW_LIMIT = 10
ADMIN_PROMPT_TEXT_LIMIT = 1400


async def _safe_admin_edit(
    callback: types.CallbackQuery,
    text: str,
    *,
    reply_markup=None,
    parse_mode: str | None = "HTML",
) -> None:
    message = callback.message
    if message is not None:
        try:
            await message.edit_text(
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            return
        except TelegramAPIError as exc:
            logger.warning(
                "Admin message edit failed for %s: %s",
                callback.data,
                exc,
            )
            try:
                await message.answer(
                    text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
                return
            except TelegramAPIError as send_exc:
                logger.warning(
                    "Admin fallback answer failed for %s: %s",
                    callback.data,
                    send_exc,
                )

    await callback.bot.send_message(
        chat_id=callback.from_user.id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
    )

ADMIN_PROMPT_STATUS_TITLES = {
    "all": "Все промпты",
    "pending": "На проверке",
    "approved": "Опубликованные",
    "rejected": "Отклонённые",
    "deactivated": "Скрытые",
}
ADMIN_PROMPT_STATUS_BADGES = {
    "pending": "🕒",
    "approved": "✅",
    "rejected": "🚫",
    "deactivated": "🗄",
}
ADMIN_FINANCE_LONG_CELL_LIMITS = {
    "prompt": 1200,
    "request_data": 1500,
    "requisites": 1200,
    "result_url": 800,
}
ADMIN_AI_MEMORY_LIMIT = 8
ADMIN_AI_RESULT_PREVIEW_LIMIT = 1200
ADMIN_AI_MESSAGE_LIMIT = 3900
ADMIN_AI_LOG_PATHS = (
    Path("logs/bot.log"),
    Path("logs/bot_output.log"),
    Path("logs/watchdog.log"),
)

ADMIN_FINANCE_SECTION_ORDER = [
    "topups",
    "deductions",
    "referrals_l1",
    "referrals_l2",
    "partner_commissions",
    "withdrawals",
]
ADMIN_FINANCE_SECTION_TITLES = {
    "topups": "Пополнения",
    "deductions": "Списания",
    "referrals_l1": "Рефералы 1 линии",
    "referrals_l2": "Рефералы 2 линии",
    "partner_commissions": "Партнёрские начисления",
    "withdrawals": "Выводы партнёров",
}


def _format_admin_panel_text(stats: dict, subscription_required: bool) -> str:
    subscription_status = "включена" if subscription_required else "выключена"
    return f"""
🔧 <b>Админ-панель</b>

📊 <b>Статистика:</b>
• Пользователей: <code>{stats['total_users']}</code>
• Генераций: <code>{stats['total_generations']}</code>
• Транзакций: <code>{stats['total_transactions']}</code>
• Выручка: <code>{stats['total_revenue']:.0f}</code> ₽
• Подписка на @{REQUIRED_CHANNEL_USERNAME}: <b>{subscription_status}</b>

Выберите действие:
"""
ADMIN_FINANCE_COLUMNS = {
    "topups": [
        ("id", "ID"),
        ("created_at", "Дата"),
        ("telegram_id", "Telegram ID"),
        ("user_db_id", "User DB ID"),
        ("credits", "Бананы"),
        ("promo_bonus_credits", "Промо бонус, 🍌"),
        ("promo_code", "Промокод"),
        ("promo_partner_name", "Промо партнёр"),
        ("promo_partner_telegram_id", "Промо партнёр Telegram ID"),
        ("amount_rub", "Сумма, ₽"),
        ("status", "Статус"),
        ("provider", "Провайдер"),
        ("order_id", "Order ID"),
        ("payment_id", "Payment ID"),
        ("user_balance", "Баланс после/текущий"),
        ("referrer_telegram_id", "Реферер Telegram ID"),
        ("referrer_code", "Код реферера"),
        ("referral_code", "Код пользователя"),
    ],
    "deductions": [
        ("source", "Источник"),
        ("id", "ID"),
        ("created_at", "Дата"),
        ("telegram_id", "Telegram ID"),
        ("user_db_id", "User DB ID"),
        ("cost", "Списано, 🍌"),
        ("status", "Статус"),
        ("task_id", "Task/Job ID"),
        ("type", "Тип"),
        ("preset_id", "Preset"),
        ("model", "Модель"),
        ("duration", "Длительность"),
        ("aspect_ratio", "Формат"),
        ("results_count", "Результатов"),
        ("prompt", "Промпт"),
        ("result_url", "Результат"),
        ("request_data", "Request data"),
        ("completed_at", "Завершено"),
        ("updated_at", "Обновлено"),
        ("user_balance", "Текущий баланс"),
        ("referrer_telegram_id", "Реферер Telegram ID"),
        ("referrer_code", "Код реферера"),
    ],
    "referrals_l1": [
        ("id", "Referral ID"),
        ("referral_created_at", "Дата привязки"),
        ("referrer_telegram_id", "Партнёр L1 Telegram ID"),
        ("referrer_user_id", "Партнёр L1 DB ID"),
        ("referrer_code", "Код партнёра"),
        ("referrer_tier", "Тир партнёра"),
        ("referrer_balance_rub", "Баланс партнёра, ₽"),
        ("referrer_total_revenue_rub", "Оборот партнёра, ₽"),
        ("referred_telegram_id", "Реферал Telegram ID"),
        ("referred_user_id", "Реферал DB ID"),
        ("referred_code", "Код реферала"),
        ("referred_created_at", "Дата регистрации"),
        ("referred_balance", "Баланс реферала"),
        ("referred_has_paid", "Оплачивал"),
        ("payments_count", "Оплат"),
        ("paid_rub", "Оплачено, ₽"),
        ("paid_credits", "Куплено 🍌"),
        ("last_payment_at", "Последняя оплата"),
        ("subrefs_count", "Рефералов 2 линии"),
        ("bonus_credits", "Бонус пригласившему, 🍌"),
    ],
    "referrals_l2": [
        ("root_partner_telegram_id", "Корневой партнёр Telegram ID"),
        ("root_partner_user_id", "Корневой партнёр DB ID"),
        ("root_partner_code", "Код корневого партнёра"),
        ("root_partner_tier", "Тир корневого партнёра"),
        ("line1_telegram_id", "Партнёр 1 линии Telegram ID"),
        ("line1_user_id", "Партнёр 1 линии DB ID"),
        ("line1_code", "Код партнёра 1 линии"),
        ("line1_created_at", "Дата регистрации 1 линии"),
        ("line2_telegram_id", "Реферал 2 линии Telegram ID"),
        ("line2_user_id", "Реферал 2 линии DB ID"),
        ("line2_code", "Код реферала 2 линии"),
        ("line2_created_at", "Дата регистрации 2 линии"),
        ("line2_balance", "Баланс 2 линии"),
        ("line2_has_paid", "Оплачивал"),
        ("referral_created_at", "Дата привязки"),
        ("payments_count", "Оплат"),
        ("paid_rub", "Оплачено, ₽"),
        ("paid_credits", "Куплено 🍌"),
        ("last_payment_at", "Последняя оплата"),
        ("bonus_credits", "Бонус, 🍌"),
    ],
    "partner_commissions": [
        ("transaction_id", "Transaction ID"),
        ("created_at", "Дата оплаты"),
        ("order_id", "Order ID"),
        ("provider", "Провайдер"),
        ("payer_telegram_id", "Плательщик Telegram ID"),
        ("payer_user_id", "Плательщик DB ID"),
        ("payer_code", "Код плательщика"),
        ("credits", "Куплено 🍌"),
        ("amount_rub", "Сумма оплаты, ₽"),
        ("level1_partner_telegram_id", "Партнёр L1 Telegram ID"),
        ("level1_partner_user_id", "Партнёр L1 DB ID"),
        ("level1_partner_code", "Код партнёра L1"),
        ("level1_partner_tier", "Тир партнёра L1"),
        ("level1_percent", "Процент L1"),
        ("level1_commission_rub", "Начисление L1, ₽"),
        ("level2_partner_telegram_id", "Партнёр L2 Telegram ID"),
        ("level2_partner_user_id", "Партнёр L2 DB ID"),
        ("level2_partner_code", "Код партнёра L2"),
        ("level2_partner_tier", "Тир партнёра L2"),
        ("level2_percent", "Процент L2"),
        ("level2_commission_rub", "Начисление L2, ₽"),
    ],
    "withdrawals": [
        ("id", "ID заявки"),
        ("created_at", "Создана"),
        ("updated_at", "Обновлена"),
        ("telegram_id", "Telegram ID"),
        ("user_db_id", "User DB ID"),
        ("amount_rub", "Сумма, ₽"),
        ("status", "Статус"),
        ("method", "Метод"),
        ("requisites", "Реквизиты"),
        ("current_balance_rub", "Текущий баланс, ₽"),
        ("withdrawn_rub", "Выведено всего, ₽"),
        ("total_revenue_rub", "Партнёрский оборот, ₽"),
    ],
}
ADMIN_PARTNER_REFERRAL_XLS_COLUMNS = [
    ("telegram_id", "Реферал Telegram ID"),
    ("created_at", "Дата регистрации"),
    ("referral_created_at", "Дата привязки"),
    ("has_paid", "Платил"),
    ("payments_count", "Оплат после привязки"),
    ("spent_rub", "Сумма оплат после привязки, ₽"),
    ("credits", "Текущий баланс, 🍌"),
    ("subrefs_count", "Рефералов 2 уровня"),
]
ADMIN_PARTNER_PAYMENT_XLS_COLUMNS = [
    ("transaction_id", "Transaction ID"),
    ("created_at", "Дата оплаты"),
    ("referred_telegram_id", "Реферал Telegram ID"),
    ("referred_user_id", "Реферал DB ID"),
    ("referred_code", "Код реферала"),
    ("referral_created_at", "Дата привязки"),
    ("amount_rub", "Сумма, ₽"),
    ("credits", "Куплено 🍌"),
    ("provider", "Провайдер"),
    ("order_id", "Order ID"),
    ("payment_id", "Payment ID"),
]


def _broadcast_confirm_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="✅ Отправить", callback_data="admin_broadcast_confirm"
                ),
                types.InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back"),
            ]
        ]
    )


def _admin_ai_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="📘 Инструкция", callback_data="admin_ai_help")],
            [types.InlineKeyboardButton(text="🔙 Админ-панель", callback_data="admin_back")],
            [types.InlineKeyboardButton(text="🏠 Домой", callback_data="back_main")],
        ]
    )


def _admin_ai_confirm_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="✅ Выполнить", callback_data="admin_ai_confirm"
                ),
                types.InlineKeyboardButton(
                    text="❌ Отмена", callback_data="admin_ai_cancel"
                ),
            ],
            [types.InlineKeyboardButton(text="🔙 Админ-панель", callback_data="admin_back")],
        ]
    )


def _admin_price_menu_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="📦 Пакеты пополнения", callback_data="admin_prices_packages"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🖼 Цены фото", callback_data="admin_prices_images"
                ),
                types.InlineKeyboardButton(
                    text="🎬 Цены видео", callback_data="admin_prices_videos"
                ),
            ],
                        [
                types.InlineKeyboardButton(
                    text="🤝 Обмен партнёров", callback_data="admin_prices_partner_exchange"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🎞 Видео-промпт", callback_data="admin_prices_video_prompt"
                )
            ],
            [types.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")],
        ]
    )


def _promo_rules_lines(bonus_by_credits: dict | None = None) -> list[str]:
    items = bonus_by_credits or {25: 5, 50: 10, 100: 15, 200: 20, 500: 50}
    return [
        f"• <code>{credits}</code>🍌 → +<code>{bonus}</code>🍌"
        for credits, bonus in sorted(
            ((int(credits), int(bonus)) for credits, bonus in items.items()),
            key=lambda item: item[0],
        )
    ]


def _admin_promocodes_keyboard(promocodes: list[dict]) -> types.InlineKeyboardMarkup:
    rows: list[list[types.InlineKeyboardButton]] = [
        [
            types.InlineKeyboardButton(
                text="➕ Создать промокод", callback_data="admin_promo_create"
            )
        ],
        [
            types.InlineKeyboardButton(
                text="🔎 Найти по коду", callback_data="admin_promo_lookup"
            ),
            types.InlineKeyboardButton(
                text="🔄 Обновить", callback_data="admin_promocodes"
            ),
        ],
    ]

    for promo in promocodes[:10]:
        status = "✅" if promo.get("is_active") else "⏸"
        code = str(promo.get("code") or "")
        usage = int(promo.get("usage_count") or 0)
        bonus = int(promo.get("total_bonus_credits") or 0)
        rows.append(
            [
                types.InlineKeyboardButton(
                    text=f"{status} {code} • {usage} оплат • +{bonus}🍌",
                    callback_data=f"admin_promo_view_{promo['id']}",
                )
            ]
        )

    rows.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def _admin_promo_detail_keyboard(promo: dict) -> types.InlineKeyboardMarkup:
    promo_id = int(promo["id"])
    is_active = bool(promo.get("is_active"))
    toggle_text = "⏸ Выключить" if is_active else "▶️ Включить"
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text=toggle_text, callback_data=f"admin_promo_toggle_{promo_id}"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🔄 Обновить", callback_data=f"admin_promo_view_{promo_id}"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🔙 К промокодам", callback_data="admin_promocodes"
                )
            ],
        ]
    )


def _admin_finance_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="📥 Пополнения", callback_data="admin_finance_topups"
                ),
                types.InlineKeyboardButton(
                    text="🍌 Списания", callback_data="admin_finance_deductions"
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text="🤝 1 линия", callback_data="admin_finance_referrals_l1"
                ),
                types.InlineKeyboardButton(
                    text="🧬 2 линия", callback_data="admin_finance_referrals_l2"
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text="💰 Начисления",
                    callback_data="admin_finance_partner_commissions",
                ),
                types.InlineKeyboardButton(
                    text="🏦 Выводы", callback_data="admin_finance_withdrawals"
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text="📤 XLS весь отчёт", callback_data="admin_finance_xls_all"
                )
            ],
            [types.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")],
        ]
    )


def _admin_finance_section_keyboard(section: str) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="📤 XLS раздела",
                    callback_data=f"admin_finance_xls_{section}",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🔙 К отчёту", callback_data="admin_finance"
                ),
                types.InlineKeyboardButton(
                    text="🏠 Админка", callback_data="admin_back"
                ),
            ],
        ]
    )


def _admin_prompts_menu_keyboard(stats: dict) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text=f"🕒 На проверке ({stats.get('pending', 0)})",
                    callback_data="admin_prompts_status_pending",
                ),
                types.InlineKeyboardButton(
                    text=f"✅ Опубликованные ({stats.get('approved', 0)})",
                    callback_data="admin_prompts_status_approved",
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text=f"🚫 Отклонённые ({stats.get('rejected', 0)})",
                    callback_data="admin_prompts_status_rejected",
                ),
                types.InlineKeyboardButton(
                    text=f"🗄 Скрытые ({stats.get('deactivated', 0)})",
                    callback_data="admin_prompts_status_deactivated",
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text=f"📚 Все ({stats.get('total', 0)})",
                    callback_data="admin_prompts_status_all",
                ),
                types.InlineKeyboardButton(
                    text="🔎 Открыть по ID", callback_data="admin_prompt_lookup"
                ),
            ],
            [types.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")],
        ]
    )


def _admin_prompts_list_keyboard(
    status: str, prompts: list[dict], page: int, total: int
) -> types.InlineKeyboardMarkup:
    rows: list[list[types.InlineKeyboardButton]] = []
    for prompt in prompts[:ADMIN_PROMPTS_PREVIEW_LIMIT]:
        prompt_id = prompt.get("id")
        badge = ADMIN_PROMPT_STATUS_BADGES.get(str(prompt.get("status")), "•")
        title = _short(prompt.get("title") or prompt.get("prompt_text"), 34)
        rows.append(
            [
                types.InlineKeyboardButton(
                    text=f"{badge} #{prompt_id} • {title}",
                    callback_data=f"admin_prompt_view_{prompt_id}",
                )
            ]
        )

    nav_row: list[types.InlineKeyboardButton] = []
    if page > 1:
        nav_row.append(
            types.InlineKeyboardButton(
                text="◀️ Назад",
                callback_data=f"admin_prompts_status_{status}_{page - 1}",
            )
        )
    if page * ADMIN_PROMPTS_PREVIEW_LIMIT < total:
        nav_row.append(
            types.InlineKeyboardButton(
                text="Вперёд ▶️",
                callback_data=f"admin_prompts_status_{status}_{page + 1}",
            )
        )
    if nav_row:
        rows.append(nav_row)

    rows.extend(
        [
            [
                types.InlineKeyboardButton(
                    text="🔄 Обновить",
                    callback_data=f"admin_prompts_status_{status}_{page}",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🔙 К промптам", callback_data="admin_prompts"
                ),
                types.InlineKeyboardButton(
                    text="🏠 Админка", callback_data="admin_back"
                ),
            ],
        ]
    )
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def _admin_prompt_detail_keyboard(prompt: dict) -> types.InlineKeyboardMarkup:
    prompt_id = int(prompt["id"])
    status = str(prompt.get("status") or "pending")
    rows: list[list[types.InlineKeyboardButton]] = []

    moderation_row: list[types.InlineKeyboardButton] = []
    if status != "approved":
        moderation_row.append(
            types.InlineKeyboardButton(
                text="✅ Опубликовать",
                callback_data=f"admin_prompt_approve_{prompt_id}",
            )
        )
    if status != "rejected":
        moderation_row.append(
            types.InlineKeyboardButton(
                text="🚫 Отклонить",
                callback_data=f"admin_prompt_reject_{prompt_id}",
            )
        )
    if moderation_row:
        rows.append(moderation_row)

    if status != "deactivated":
        rows.append(
            [
                types.InlineKeyboardButton(
                    text="🗄 Скрыть",
                    callback_data=f"admin_prompt_deactivate_{prompt_id}",
                )
            ]
        )

    rows.extend(
        [
            [
                types.InlineKeyboardButton(
                    text="🔄 Обновить",
                    callback_data=f"admin_prompt_view_{prompt_id}",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🔙 К списку",
                    callback_data=f"admin_prompts_status_{status}",
                ),
                types.InlineKeyboardButton(
                    text="📚 Промпты", callback_data="admin_prompts"
                ),
            ],
        ]
    )
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def _admin_partners_keyboard(top_partners: list[dict]) -> types.InlineKeyboardMarkup:
    rows: list[list[types.InlineKeyboardButton]] = [
        [
            types.InlineKeyboardButton(
                text="💸 Заявки на вывод",
                callback_data="admin_partner_withdrawals",
            )
        ],
        [
            types.InlineKeyboardButton(
                text="🚨 Burst autobans",
                callback_data="admin_partner_burst_autobans",
            )
        ],
        [
            types.InlineKeyboardButton(
                text="🔎 Открыть по Telegram ID",
                callback_data="admin_partner_lookup",
            )
        ]
    ]

    for partner in top_partners[:8]:
        rows.append(
            [
                types.InlineKeyboardButton(
                    text=(
                        f"ID {partner['telegram_id']} • "
                        f"{partner['balance_rub']:.0f}₽ • "
                        f"{partner['level1_count']} реф."
                    ),
                    callback_data=f"admin_partner_view_{partner['telegram_id']}",
                )
            ]
        )

    rows.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def _admin_partner_detail_keyboard(telegram_id: int) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="🔄 Обновить",
                    callback_data=f"admin_partner_view_{telegram_id}",
                ),
                types.InlineKeyboardButton(
                    text="📤 XLS по партнёру",
                    callback_data=f"admin_partner_xls_{telegram_id}",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🔎 Открыть другого", callback_data="admin_partner_lookup"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🔙 К партнёрам", callback_data="admin_partners"
                )
            ],
        ]
    )


def _admin_partner_burst_autobans_keyboard(items: list[dict]) -> types.InlineKeyboardMarkup:
    rows: list[list[types.InlineKeyboardButton]] = [
        [
            types.InlineKeyboardButton(
                text="🔄 Обновить",
                callback_data="admin_partner_burst_autobans",
            )
        ]
    ]

    for item in items[:10]:
        referrer_telegram_id = item.get("referrer_telegram_id")
        if not referrer_telegram_id:
            continue
        rows.append(
            [
                types.InlineKeyboardButton(
                    text=(
                        f"ID {referrer_telegram_id} • "
                        f"{item.get('referral_code') or '—'} • "
                        f"{'бан' if item.get('referrer_is_banned') else 'нет бана'}"
                    ),
                    callback_data=f"admin_partner_view_{referrer_telegram_id}",
                )
            ]
        )

    rows.append([types.InlineKeyboardButton(text="🔙 К партнёрам", callback_data="admin_partners")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def _admin_withdrawals_keyboard(withdrawals: list[dict]) -> types.InlineKeyboardMarkup:
    rows: list[list[types.InlineKeyboardButton]] = []
    for item in withdrawals[:12]:
        rows.append(
            [
                types.InlineKeyboardButton(
                    text=(
                        f"#{item['id']} • ID {item['telegram_id']} • "
                        f"{item['amount_rub']:.0f}₽"
                    ),
                    callback_data=f"admin_partner_withdrawal_{item['id']}",
                )
            ]
        )

    rows.append(
        [types.InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_partner_withdrawals")]
    )
    rows.append([types.InlineKeyboardButton(text="🔙 К партнёрам", callback_data="admin_partners")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def _admin_withdrawal_detail_keyboard(withdrawal_id: int) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data=f"partner_withdraw_approve_{withdrawal_id}",
                ),
                types.InlineKeyboardButton(
                    text="❌ Отменить",
                    callback_data=f"partner_withdraw_cancel_{withdrawal_id}",
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text="🔄 Обновить",
                    callback_data=f"admin_partner_withdrawal_{withdrawal_id}",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🔙 К заявкам", callback_data="admin_partner_withdrawals"
                )
            ],
        ]
    )


def _chunk_buttons(
    buttons: list[types.InlineKeyboardButton], per_row: int = 1
) -> list[list[types.InlineKeyboardButton]]:
    return [buttons[i : i + per_row] for i in range(0, len(buttons), per_row)]


def _admin_packages_keyboard() -> types.InlineKeyboardMarkup:
    buttons = []
    for pkg in preset_manager.get_packages():
        buttons.append(
            types.InlineKeyboardButton(
                text=f"{pkg['name']} • {pkg['price_rub']}₽ / {pkg['credits']}🍌",
                callback_data=f"admin_price_package_{pkg['id']}",
            )
        )
    rows = _chunk_buttons(buttons) + [
        [types.InlineKeyboardButton(text="🔙 К разделам", callback_data="admin_prices")]
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def _admin_package_fields_keyboard(package_id: str) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="💳 Цена в ₽",
                    callback_data=f"admin_price_package_field_{package_id}_price_rub",
                ),
                types.InlineKeyboardButton(
                    text="🍌 Кол-во бананов",
                    callback_data=f"admin_price_package_field_{package_id}_credits",
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text="🔙 К пакетам", callback_data="admin_prices_packages"
                )
            ],
        ]
    )


def _admin_image_prices_keyboard() -> types.InlineKeyboardMarkup:
    image_models = (
        preset_manager.get_price_config()
        .get("costs_reference", {})
        .get("image_models", {})
    )
    labels = {
        "nano-banana-pro": "Nano Banana Pro",
        "banana_2": "Nano Banana 2",
        "seedream_edit": "Seedream 4.5 Edit",
        "flux_pro": "GPT Image 2",
        "grok_imagine_i2i": "Grok Imagine",
        "wan_27": "Wan 2.7 Pro",
    }
    buttons = []
    for key, value in image_models.items():
        buttons.append(
            types.InlineKeyboardButton(
                text=f"{labels.get(key, key)} • {value}🍌",
                callback_data=f"admin_price_image_{key}",
            )
        )
    rows = _chunk_buttons(buttons) + [
        [types.InlineKeyboardButton(text="🔙 К разделам", callback_data="admin_prices")]
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


VIDEO_MODEL_LABELS = {
    "v3_std": "Kling v3 Std",
    "v3_pro": "Kling 3.0 Pro",
    "v26_pro": "Kling 2.5 Turbo",
    "v26_motion_pro": "Motion Pro",
    "motion_control_v26": "Motion Control 2.6",
    "motion_control_v30": "Motion Control 3.0",
    "grok_imagine": "Grok Imagine",
    "veo3": "Veo 3.1 Quality",
    "veo3_fast": "Veo 3.1 Fast",
    "veo3_lite": "Veo 3.1 Lite",
    "gemini_omni_video": "Gemini Omni Video",
    "gemini_omni_audio": "Gemini Omni Audio",
    "gemini_omni_character": "Gemini Omni Character",
    "glow": "Kling Glow",
}


def _model_per_sec(model_cfg: dict) -> str:
    """Возвращает строку 'X🍌/с' для модели."""
    def _format_per_sec(value: float) -> str:
        return f"{value:.2f}".rstrip("0").rstrip(".")

    quality_costs = (model_cfg or {}).get("quality_costs", {})
    if quality_costs:
        values = [float(value) for value in quality_costs.values()]
        if not values:
            return "?"
        min_value = min(values)
        max_value = max(values)
        if min_value == max_value:
            return _format_per_sec(min_value)
        return f"{_format_per_sec(min_value)}-{_format_per_sec(max_value)}"

    duration_costs = (model_cfg or {}).get("duration_costs", {})
    if duration_costs:
        ref_dur = 5 if "5" in duration_costs else int(min(duration_costs, key=int))
        cost = duration_costs[str(ref_dur)]
        per_sec = cost / ref_dur
        return _format_per_sec(per_sec)
    base = (model_cfg or {}).get("base", (model_cfg or {}).get("cost"))
    return str(base) if base is not None else "?"


def _admin_video_prices_keyboard() -> types.InlineKeyboardMarkup:
    """Одна кнопка на модель с отображением цены за секунду."""
    video_models = (
        preset_manager.get_price_config()
        .get("costs_reference", {})
        .get("video_models", {})
    )
    buttons = []
    for model_key, model_cfg in video_models.items():
        per_sec = _model_per_sec(model_cfg)
        label = VIDEO_MODEL_LABELS.get(model_key, model_key)
        buttons.append(
            types.InlineKeyboardButton(
                text=f"{label} • {per_sec}🍌/с",
                callback_data=f"admin_video_model_{model_key}",
            )
        )
    rows = _chunk_buttons(buttons, 1) + [
        [types.InlineKeyboardButton(text="🔙 К разделам", callback_data="admin_prices")]
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def _admin_video_model_keyboard(model_key: str) -> types.InlineKeyboardMarkup:
    """Детальный экран модели: каждая длительность + кнопка 'цена за 1с'."""
    video_models = (
        preset_manager.get_price_config()
        .get("costs_reference", {})
        .get("video_models", {})
    )
    model_cfg = video_models.get(model_key, {})
    quality_costs = model_cfg.get("quality_costs", {})
    duration_costs = model_cfg.get("duration_costs", {})
    quality_order = {"720p": 0, "1080p": 1, "4k": 2}

    buttons = []
    if quality_costs:
        for quality in sorted(
            quality_costs.keys(),
            key=lambda q: (quality_order.get(str(q).lower(), 99), str(q)),
        ):
            cost = quality_costs[quality]
            buttons.append(
                types.InlineKeyboardButton(
                    text=f"{quality} → {cost}🍌/с",
                    callback_data=f"admin_price_video_{model_key}_q{quality}",
                )
            )
    elif duration_costs:
        for dur_str, cost in sorted(duration_costs.items(), key=lambda x: int(x[0])):
            buttons.append(
                types.InlineKeyboardButton(
                    text=f"{dur_str}с → {cost}🍌",
                    callback_data=f"admin_price_video_{model_key}_{dur_str}",
                )
            )
        buttons.append(
            types.InlineKeyboardButton(
                text="⚡ Установить цену за 1с (пересчёт всех)",
                callback_data=f"admin_price_video_{model_key}_persec",
            )
        )
    else:
        base = model_cfg.get("base", model_cfg.get("cost"))
        buttons.append(
            types.InlineKeyboardButton(
                text=f"Базовая цена → {base}🍌",
                callback_data=f"admin_price_video_{model_key}_base",
            )
        )

    rows = _chunk_buttons(buttons, 2) + [
        [
            types.InlineKeyboardButton(
                text="🔙 К моделям", callback_data="admin_prices_videos"
            )
        ]
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def _read_price_config() -> dict:
    with open(PRICE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _parse_price_value(raw_value: str, current_value):
    raw_value = raw_value.strip().replace(",", ".")
    if isinstance(current_value, int):
        value = int(raw_value)
    else:
        value = float(raw_value)
        if value.is_integer():
            value = int(value)
    if value <= 0:
        raise ValueError
    return value


def _parse_promo_create_payload(raw_value: str) -> tuple[str, str | None, int | None]:
    parts = [
        part.strip()
        for part in str(raw_value or "").replace("\n", "|").split("|")
        if part.strip()
    ]
    if not parts:
        raise ValueError("empty")

    code = normalize_promo_code(parts[0])
    if len(code) < 2:
        raise ValueError("invalid_code")

    partner_name = parts[1] if len(parts) >= 2 else parts[0].strip()
    partner_telegram_id = None
    if len(parts) >= 3 and parts[2] not in {"-", "—"}:
        partner_telegram_id = int(parts[2])

    return code, partner_name, partner_telegram_id


def _update_price_value(target: str, key: str, field: str, value):
    price_config = _read_price_config()

    if target == "package":
        packages = price_config.get("packages", [])
        package = next((pkg for pkg in packages if pkg.get("id") == key), None)
        if not package or field not in {"price_rub", "credits"}:
            raise KeyError("package")
        old_value = package[field]
        package[field] = value
        preset_manager.update_price_config(price_config)
        return old_value

    if target == "image":
        image_models = price_config["costs_reference"]["image_models"]
        if key not in image_models:
            raise KeyError("image")
        old_value = image_models[key]
        image_models[key] = value
        preset_manager.update_price_config(price_config)
        return old_value

    if target == "video":
        video_models = price_config["costs_reference"]["video_models"]
        model = video_models.get(key)
        if not model:
            raise KeyError("video")
        if field == "persec":
            # Пересчитываем все длительности по новой цене за секунду
            per_sec = float(value)
            duration_costs = model.get("duration_costs", {})
            if duration_costs:
                old_ref_dur = (
                    5 if "5" in duration_costs else int(min(duration_costs, key=int))
                )
                old_value = round(duration_costs[str(old_ref_dur)] / old_ref_dur, 2)
                new_durations = {}
                for dur_str in duration_costs:
                    new_durations[dur_str] = round(per_sec * int(dur_str))
                model["duration_costs"] = new_durations
                ref_dur = (
                    5 if "5" in new_durations else int(min(new_durations, key=int))
                )
                model["base"] = new_durations[str(ref_dur)]
            else:
                old_value = model.get("base", model.get("cost", 0))
                model["base"] = round(per_sec * 5)
        elif field == "base":
            target_key = "base" if "base" in model else "cost"
            old_value = model[target_key]
            model[target_key] = value
        elif field.startswith("q"):
            quality = field[1:]
            quality_costs = model.get("quality_costs")
            if not quality_costs or quality not in quality_costs:
                raise KeyError("video_quality")
            old_value = quality_costs[quality]
            quality_costs[quality] = value
        else:
            duration_costs = model.setdefault("duration_costs", {})
            old_value = duration_costs[field]
            duration_costs[field] = value
        preset_manager.update_price_config(price_config)
        return old_value

    if target == "partner_exchange":
        exchange_cfg = price_config.setdefault("partner_exchange", {})
        if field != "rub_per_credit":
            raise KeyError("partner_exchange")
        old_value = float(exchange_cfg.get("rub_per_credit", 10))
        exchange_cfg["rub_per_credit"] = float(value)
        preset_manager.update_price_config(price_config)
        return old_value

    if target == "service":
        service_prices = price_config.setdefault("service_prices", {})
        if key != "video_prompt" or field != "cost":
            raise KeyError("service")
        old_value = float(service_prices.get("video_prompt", 3))
        service_prices["video_prompt"] = float(value)
        preset_manager.update_price_config(price_config)
        return old_value

    raise KeyError(target)


def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором"""
    return config.is_admin(user_id)


def _format_admin_partners_text(stats: dict) -> str:
    lines = [
        "🤝 <b>Партнёрская статистика</b>",
        "",
        f"• Партнёров всего: <code>{stats['total_partners']}</code>",
        f"• Активных партнёров: <code>{stats['active_partners']}</code>",
        f"• На балансах: <code>{stats['total_balance_rub']:.2f}</code> ₽",
        f"• Выведено: <code>{stats['total_withdrawn_rub']:.2f}</code> ₽",
        f"• Оборот рефералок: <code>{stats['total_partner_revenue_rub']:.2f}</code> ₽",
        f"• Burst autobans за 24ч: <code>{stats.get('burst_autobans_24h', 0)}</code>",
        f"• Burst autobans всего: <code>{stats.get('burst_autobans_total', 0)}</code>",
        "",
        "<b>Топ партнёров:</b>",
    ]

    top_partners = stats.get("top_partners") or []
    if not top_partners:
        lines.append("• Пока нет данных")
    else:
        for index, partner in enumerate(top_partners[:5], start=1):
            lines.append(
                f"{index}. <code>{partner['telegram_id']}</code> "
                f"• {partner['level1_count']} / {partner['level2_count']} реф. "
                f"• баланс <code>{partner['balance_rub']:.2f}</code> ₽"
            )

    lines.extend(["", "Можно открыть карточку партнёра по кнопке или ввести Telegram ID."])
    return "\n".join(lines)


def _format_admin_partner_burst_autobans_text(report: dict) -> str:
    lines = [
        "🚨 <b>Burst autobans</b>",
        "",
        f"• Всего событий: <code>{report.get('total', 0)}</code>",
        f"• За 24 часа: <code>{report.get('last_24h', 0)}</code>",
        f"• Последнее событие: <code>{report.get('latest_created_at') or '—'}</code>",
        "",
        "<b>Последние срабатывания:</b>",
    ]

    items = report.get("items") or []
    if not items:
        lines.append("• Нет событий burst_autoban")
    else:
        for item in items[:10]:
            lines.append(
                f"• <code>{item.get('referrer_telegram_id') or '—'}</code> "
                f"(user_id <code>{item.get('referrer_user_id') or '—'}</code>) "
                f"• код <code>{item.get('referral_code') or '—'}</code> "
                f"• visitor <code>{item.get('visitor_telegram_id') or '—'}</code> "
                f"• source <code>{html_utils.escape(item.get('source') or '—')}</code>"
            )
            lines.append(
                f"  <code>{item.get('created_at') or '—'}</code> "
                f"• start_param <code>{html_utils.escape(item.get('start_param') or '—')}</code> "
                f"• статус <code>{'banned' if item.get('referrer_is_banned') else 'not banned'}</code>"
            )

    return "\n".join(lines)


def _format_admin_partner_details_text(details: dict) -> str:
    overview = details["overview"]
    lines = [
        "👤 <b>Карточка партнёра</b>",
        "",
        f"🆔 Telegram ID: <code>{details['telegram_id']}</code>",
        f"🔗 Рефкод: <code>{details.get('referral_code') or '—'}</code>",
        f"🍌 Баланс пользователя: <code>{details['credits']}</code>",
        f"🤝 Активировал партнёрку: <code>{'да' if details['is_partner'] else 'нет'}</code>",
        f"📅 Активирована: <code>{details.get('partner_agreed_at') or '—'}</code>",
        "",
        "<b>Показатели:</b>",
        f"• 1 уровень: <code>{overview.get('level1_count', 0)}</code>",
        f"• 2 уровень: <code>{overview.get('level2_count', 0)}</code>",
        f"• Баланс к выводу: <code>{overview.get('balance_rub', 0):.2f}</code> ₽",
        f"• Выведено: <code>{overview.get('withdrawn_rub', 0):.2f}</code> ₽",
        f"• Оборот: <code>{overview.get('total_revenue_rub', 0):.2f}</code> ₽",
        f"• Оплат по 1 уровню: <code>{overview.get('total_payments', 0)}</code>",
        f"• Выручка по оплатам 1 уровня: <code>{overview.get('monthly_revenue', 0):.2f}</code> ₽",
        f"• Активных за 7 дней: <code>{overview.get('active_7d', 0)}</code>",
        "",
        "<b>Прямые рефералы:</b>",
    ]

    referrals = details.get("referrals") or []
    if not referrals:
        lines.append("• Нет прямых рефералов")
    else:
        for ref in referrals:
            paid_label = "платил" if ref["has_paid"] else "без оплат"
            lines.append(
                f"• <code>{ref['telegram_id']}</code> "
                f"({paid_label}, {ref['payments_count']} оплат) "
                f"• потратил <code>{ref['spent_rub']:.2f}</code> ₽ "
                f"• 🍌 <code>{ref['credits']}</code> "
                f"• привёл <code>{ref['subrefs_count']}</code>"
            )

    return "\n".join(lines)


def _format_admin_withdrawals_text(withdrawals: list[dict]) -> str:
    lines = [
        "💸 <b>Заявки на вывод</b>",
        "",
        f"• Ожидают обработки: <code>{len(withdrawals)}</code>",
        "",
    ]

    if not withdrawals:
        lines.append("• Сейчас нет ожидающих заявок")
    else:
        for item in withdrawals[:12]:
            lines.append(
                f"• <code>#{item['id']}</code> "
                f"ID <code>{item['telegram_id']}</code> "
                f"— <code>{item['amount_rub']:.2f}</code> ₽ "
                f"(баланс <code>{item['current_balance_rub']:.2f}</code> ₽)"
            )

    return "\n".join(lines)


def _format_admin_withdrawal_detail_text(withdrawal: dict) -> str:
    return "\n".join(
        [
            "💸 <b>Заявка на вывод</b>",
            "",
            f"ID заявки: <code>{withdrawal['id']}</code>",
            f"Telegram ID: <code>{withdrawal['telegram_id']}</code>",
            f"Статус: <code>{withdrawal['status']}</code>",
            f"Сумма: <code>{withdrawal['amount_rub']:.2f}</code> ₽",
            f"Фактический баланс: <code>{withdrawal['current_balance_rub']:.2f}</code> ₽",
            f"Создана: <code>{withdrawal['created_at']}</code>",
            "",
            "Реквизиты:",
            f"<code>{withdrawal['requisites'] or '—'}</code>",
        ]
    )


def _html(value) -> str:
    return html_utils.escape("" if value is None else str(value))


def _code(value) -> str:
    text = "—" if value is None or value == "" else value
    return f"<code>{_html(text)}</code>"


def _short(value, limit: int = 72) -> str:
    if value is None or value == "":
        return "—"
    text = str(value).replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"


def _truncate_plain(value: Any, limit: int = ADMIN_AI_RESULT_PREVIEW_LIMIT) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 20)].rstrip()}... [сокращено]"


def _format_admin_ai_help_text() -> str:
    return """📘 <b>Инструкция: ИИ-админ</b>

Как пользоваться:
1. Откройте /admin → 🤖 ИИ-админ.
2. Напишите задачу обычным текстом.
3. Если действие меняет данные, подтвердите выполнение.

Примеры:
• <code>сделай отчёт по боту</code>
• <code>проанализируй последние логи</code>
• <code>найди новые ИИ для генерации видео и фото</code>
• <code>проверь пользователя 123456789</code>
• <code>начисли 50 бананов пользователю 123456789</code>
• <code>создай промокод VIP20 скидка 20 лимит 100</code>
• <code>очисти контекст</code>"""


def _format_admin_ai_intro() -> str:
    return (
        "🤖 <b>ИИ-админ</b>\n\n"
        "Напишите задачу обычным текстом. Я построю безопасный план, "
        "а изменения данных выполню только после подтверждения.\n\n"
        "Например: <code>сделай отчёт по боту</code> или "
        "<code>проанализируй последние логи</code>."
    )


def _admin_ai_action_title(action: str) -> str:
    return {
        "stats": "статистика",
        "user_info": "карточка пользователя",
        "add_credits": "начислить бананы",
        "deduct_credits": "списать бананы",
        "ban_user": "забанить пользователя",
        "unban_user": "разбанить пользователя",
        "maintenance_status": "статус техрежима",
        "maintenance_set": "изменить техрежим",
        "create_promo": "создать промокод",
        "deactivate_promo": "отключить промокод",
        "list_promos": "список промокодов",
        "export_users": "экспорт пользователей",
        "bot_report": "отчёт по боту",
        "analyze_logs": "анализ логов",
        "research_ai": "research AI",
        "clear_context": "очистить контекст",
        "help": "инструкция",
    }.get(action, action)


def _format_admin_ai_params(params: dict[str, Any]) -> str:
    if not params:
        return "—"
    parts = []
    for key, value in params.items():
        parts.append(f"{_html(key)}={_code(value)}")
    return ", ".join(parts)


def _format_admin_ai_plan_preview(plan: dict[str, Any]) -> str:
    normalized = normalize_plan(plan)
    actions = normalized.get("actions") or []
    lines = [
        "🤖 <b>План ИИ-админа</b>",
        "",
        f"Описание: {_html(normalized.get('summary'))}",
        f"Уверенность: {_code(round(float(normalized.get('confidence', 0)) * 100))}%",
        "",
    ]
    if actions:
        lines.append("<b>Шаги:</b>")
        for index, item in enumerate(actions, start=1):
            lines.append(
                f"{index}. {_html(_admin_ai_action_title(item['action']))} "
                f"({_format_admin_ai_params(item.get('params') or {})})"
            )
    else:
        lines.extend(
            [
                f"Действие: <b>{_html(_admin_ai_action_title(normalized['action']))}</b>",
                f"Параметры: {_format_admin_ai_params(normalized.get('params') or {})}",
            ]
        )

    if normalized.get("requires_confirmation"):
        lines.extend(["", "⚠️ Действие изменяет данные или выгружает персональные данные."])
    return "\n".join(lines)


def _format_admin_ai_stats(stats: dict) -> str:
    return "\n".join(
        [
            "Статистика бота",
            f"Пользователей: {stats['total_users']}",
            f"Генераций: {stats['total_generations']}",
            f"Транзакций: {stats['total_transactions']}",
            f"Выручка: {float(stats['total_revenue'] or 0):.0f} ₽",
            f"Пакетных задач: {stats.get('total_batch_jobs', 0)}",
            f"Рефералов: {stats.get('total_referrals', 0)}",
        ]
    )


def _format_admin_ai_user_stats(telegram_id: int, stats: dict) -> str:
    status = "забанен" if stats.get("is_banned") else "активен"
    return "\n".join(
        [
            "Пользователь",
            f"Telegram ID: {telegram_id}",
            f"Статус: {status}",
            f"Баланс: {stats['credits']} бананов",
            f"Генераций: {stats['generations']}",
            f"Потрачено: {stats['total_spent']}",
            f"Регистрация: {stats['member_since']}",
            f"Рефералов: {stats['referrals_count']}",
            f"Заработано по рефке: {stats['referral_earned']} 🍌",
            f"Рефкод: {stats['referral_code'] or '—'}",
        ]
    )


def _format_admin_ai_promos(stats: dict) -> str:
    lines = [
        "Промокоды",
        f"Всего: {stats.get('total_codes', 0)}",
        f"Активных: {stats.get('active_codes', 0)}",
        f"Использований: {stats.get('usage_count', 0)}",
        f"Начислено бонусов: {stats.get('total_bonus_credits', 0)} 🍌",
    ]
    promocodes = stats.get("promocodes") or []
    if promocodes:
        lines.append("")
        lines.append("Последние/активные:")
        for promo in promocodes[:10]:
            status = "активен" if promo.get("is_active") else "выключен"
            lines.append(
                f"• {promo.get('code')} — {status}, использований: {promo.get('usage_count', 0)}"
            )
    return "\n".join(lines)


def _format_admin_ai_maintenance(enabled: bool) -> str:
    return f"Техрежим: {'включён' if enabled else 'выключен'}."


def _default_bot_report_actions() -> list[dict[str, Any]]:
    return [
        {"action": "stats", "params": {}, "summary": "Собрать статистику"},
        {"action": "maintenance_status", "params": {}, "summary": "Проверить техрежим"},
        {"action": "list_promos", "params": {}, "summary": "Показать промокоды"},
        {
            "action": "analyze_logs",
            "params": {"lines": 250},
            "summary": "Проанализировать последние логи",
        },
    ]


def _read_admin_ai_logs(lines: int = 250) -> tuple[str, dict[str, int]]:
    safe_lines = max(50, min(int(lines or 250), 1000))
    sections: list[str] = []
    metrics = {"ERROR": 0, "WARNING": 0, "WEBHOOK": 0, "RESTART": 0}

    for path in ADMIN_AI_LOG_PATHS:
        if not path.exists() or not path.is_file():
            continue
        try:
            with path.open("r", encoding="utf-8", errors="replace") as file_obj:
                tail = list(deque(file_obj, maxlen=safe_lines))
        except OSError as exc:
            sections.append(f"== {path} ==\nНе удалось прочитать: {exc}")
            continue

        text = "".join(tail)
        upper_text = text.upper()
        metrics["ERROR"] += upper_text.count("ERROR") + upper_text.count("EXCEPTION")
        metrics["WARNING"] += upper_text.count("WARNING")
        metrics["WEBHOOK"] += upper_text.count("WEBHOOK")
        metrics["RESTART"] += upper_text.count("RESTART")
        sections.append(f"== {path} ==\n{text[-8000:]}")

    if not sections:
        return "Лог-файлы из allowlist не найдены.", metrics
    return "\n\n".join(sections), metrics


def _build_users_csv(rows: list[dict[str, Any]]) -> bytes:
    output = io.StringIO()
    fieldnames = [
        "telegram_id",
        "username",
        "first_name",
        "last_name",
        "credits",
        "is_banned",
        "referral_code",
        "referred_by",
        "has_paid",
        "created_at",
        "updated_at",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in fieldnames})
    return output.getvalue().encode("utf-8-sig")


async def _send_admin_ai_result(
    message: types.Message,
    result: str,
    *,
    title: str = "🤖 ИИ-админ",
) -> None:
    plain = _truncate_plain(result, ADMIN_AI_MESSAGE_LIMIT - 80)
    await message.answer(
        f"<b>{_html(title)}</b>\n\n{_html(plain)}",
        reply_markup=_admin_ai_keyboard(),
        parse_mode="HTML",
    )


async def _remember_admin_ai_context(
    state: FSMContext,
    *,
    request: str,
    plan: dict[str, Any],
    result: str,
) -> None:
    data = await state.get_data()
    memory = list(data.get("admin_ai_memory") or [])
    memory.append(
        {
            "request": _truncate_plain(request, 300),
            "plan": {
                "action": normalize_plan(plan).get("action"),
                "actions": summarize_plan_actions(plan),
            },
            "result": _truncate_plain(result, 500),
        }
    )
    await state.update_data(admin_ai_memory=memory[-ADMIN_AI_MEMORY_LIMIT:])


async def execute_admin_ai_action(
    action: str,
    params: dict[str, Any],
    *,
    admin_id: int,
    message: types.Message,
) -> str:
    params = params or {}

    if action == "stats":
        return _format_admin_ai_stats(await get_admin_stats())

    if action == "user_info":
        telegram_id = int(params["telegram_id"])
        stats = await get_existing_user_stats(telegram_id)
        if not stats:
            return f"Пользователь {telegram_id} не найден."
        return _format_admin_ai_user_stats(telegram_id, stats)

    if action == "add_credits":
        telegram_id = int(params["telegram_id"])
        amount = float(params["amount"])
        if not await get_existing_user_stats(telegram_id):
            return f"Пользователь {telegram_id} не найден."
        success = await add_credits(telegram_id, amount)
        stats = await get_existing_user_stats(telegram_id)
        if not success or not stats:
            return "Не удалось начислить бананы."
        return (
            f"Начислено {amount:g} бананов пользователю {telegram_id}.\n"
            f"Текущий баланс: {stats['credits']}."
        )

    if action == "deduct_credits":
        telegram_id = int(params["telegram_id"])
        amount = float(params["amount"])
        if not await get_existing_user_stats(telegram_id):
            return f"Пользователь {telegram_id} не найден."
        success = await deduct_credits(telegram_id, amount)
        stats = await get_existing_user_stats(telegram_id)
        if not success or not stats:
            return "Не удалось списать бананы. Возможно, недостаточно баланса."
        return (
            f"Списано {amount:g} бананов у пользователя {telegram_id}.\n"
            f"Текущий баланс: {stats['credits']}."
        )

    if action == "ban_user":
        telegram_id = int(params["telegram_id"])
        if await set_user_banned(telegram_id, True, admin_id=admin_id):
            return f"Пользователь {telegram_id} забанен."
        return f"Пользователь {telegram_id} не найден."

    if action == "unban_user":
        telegram_id = int(params["telegram_id"])
        if await set_user_banned(telegram_id, False, admin_id=admin_id):
            return f"Пользователь {telegram_id} разбанен."
        return f"Пользователь {telegram_id} не найден."

    if action == "maintenance_status":
        enabled = (await get_bot_setting("maintenance_mode", "0")) == "1"
        return _format_admin_ai_maintenance(enabled)

    if action == "maintenance_set":
        enabled = bool(params["enabled"])
        await set_maintenance_mode(enabled, updated_by_telegram_id=admin_id)
        return _format_admin_ai_maintenance(enabled)

    if action == "list_promos":
        return _format_admin_ai_promos(await get_admin_promo_stats())

    if action == "create_promo":
        code = str(params["code"])
        existing = await get_promo_code_by_code(code, active_only=False)
        if existing:
            return f"Промокод {existing.code} уже существует."
        promo = await create_promo_code(
            code,
            partner_name=params.get("partner_name") or code,
            partner_telegram_id=params.get("partner_telegram_id"),
            created_by_telegram_id=admin_id,
        )
        if not promo:
            return "Не удалось создать промокод."
        notes = []
        unsupported = [
            key
            for key in ("discount_percent", "limit", "bonus_credits")
            if params.get(key)
        ]
        if unsupported:
            notes.append(
                "Текущая схема промокодов хранит код и партнёра; скидка/лимит/фиксированный бонус не сохранялись."
            )
        suffix = f"\n{' '.join(notes)}" if notes else ""
        return f"Промокод {promo.code} создан и активен.{suffix}"

    if action == "deactivate_promo":
        promo = await get_promo_code_by_code(str(params["code"]), active_only=False)
        if not promo:
            return f"Промокод {params['code']} не найден."
        await set_promo_code_active(promo.id, False)
        return f"Промокод {promo.code} отключён."

    if action == "export_users":
        rows = await export_users_for_admin()
        file_bytes = _build_users_csv(rows)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        await message.answer_document(
            BufferedInputFile(file_bytes, filename=f"users_export_{stamp}.csv"),
            caption=f"Экспорт пользователей: {len(rows)} строк.",
        )
        return f"Экспорт пользователей подготовлен: {len(rows)} строк."

    if action == "analyze_logs":
        log_text, metrics = _read_admin_ai_logs(int(params.get("lines") or 250))
        return await admin_ai_service.analyze_logs(log_text, metrics)

    if action == "research_ai":
        return await admin_ai_service.research_ai(str(params.get("query") or ""))

    if action == "help":
        return "Открыта инструкция ИИ-админа."

    if action == "clear_context":
        return "Контекст ИИ-админа очищен."

    return f"Действие {action} не реализовано."


async def execute_admin_ai_plan(
    plan: dict[str, Any],
    *,
    admin_id: int,
    message: types.Message,
) -> str:
    normalized = normalize_plan(plan)
    actions = normalized.get("actions") or []
    if not actions and normalized["action"] == "bot_report":
        actions = [normalize_plan(item) for item in _default_bot_report_actions()]

    if not actions:
        return await execute_admin_ai_action(
            normalized["action"],
            normalized.get("params") or {},
            admin_id=admin_id,
            message=message,
        )

    sections = []
    for index, item in enumerate(actions, start=1):
        result = await execute_admin_ai_action(
            item["action"],
            item.get("params") or {},
            admin_id=admin_id,
            message=message,
        )
        sections.append(f"Шаг {index}: {_admin_ai_action_title(item['action'])}\n{result}")
    return "\n\n".join(sections)


def _format_admin_promocodes_text(stats: dict) -> str:
    total_amount = f"{float(stats.get('total_amount_rub') or 0):.2f}"
    lines = [
        "🎟 <b>Промокоды</b>",
        "",
        f"• Всего кодов: {_code(stats.get('total_codes', 0))}",
        f"• Активных: {_code(stats.get('active_codes', 0))}",
        f"• Использований: {_code(stats.get('usage_count', 0))}",
        f"• Начислено бонусов: {_code(stats.get('total_bonus_credits', 0))}🍌",
        f"• Оборот по промокодам: {_code(total_amount)} ₽",
        "",
        "<b>Бонусная сетка:</b>",
        *_promo_rules_lines(stats.get("bonus_by_credits")),
        "",
        "Код можно использовать много раз. Бонус считается автоматически по количеству бананов в пакете.",
    ]
    return "\n".join(lines)


def _format_admin_promo_details_text(details: dict) -> str:
    promo = details["promo"]
    status = "активен" if promo.get("is_active") else "выключен"
    partner_name = promo.get("partner_name") or "—"
    partner_tg = promo.get("partner_telegram_id") or promo.get(
        "linked_partner_telegram_id"
    )
    total_amount = f"{float(promo.get('total_amount_rub') or 0):.2f}"

    lines = [
        "🎟 <b>Промокод</b>",
        "",
        f"Код: {_code(promo.get('code'))}",
        f"Статус: {_code(status)}",
        f"Партнёр: {_code(partner_name)}",
        f"Telegram ID партнёра: {_code(partner_tg or '—')}",
        f"Использований: {_code(promo.get('usage_count', 0))}",
        f"Начислено бонусов: {_code(promo.get('total_bonus_credits', 0))}🍌",
        f"Оборот: {_code(total_amount)} ₽",
        f"Создан: {_code(_short(promo.get('created_at'), 19))}",
        "",
        "<b>Бонусная сетка:</b>",
        *_promo_rules_lines(details.get("bonus_by_credits")),
        "",
        "<b>Последние оплаты:</b>",
    ]

    redemptions = details.get("redemptions") or []
    if not redemptions:
        lines.append("• Пока нет использований")
    else:
        for row in redemptions:
            row_amount = f"{float(row.get('amount_rub') or 0):.2f}"
            lines.append(
                f"• ID {_code(row.get('telegram_id'))} "
                f"• {_code(row_amount)} ₽ "
                f"• +{_code(row.get('bonus_credits'))}🍌 "
                f"• {_code(_short(row.get('created_at'), 19))}"
            )

    return "\n".join(lines)


def _clip_multiline(value, limit: int = 1000) -> str:
    if value is None or value == "":
        return "—"
    text = str(value).strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"


def _prompt_author_label(prompt: dict) -> str:
    username = str(prompt.get("author_username") or "").strip()
    if username:
        return f"@{username}"

    name = " ".join(
        part
        for part in (
            str(prompt.get("author_first_name") or "").strip(),
            str(prompt.get("author_last_name") or "").strip(),
        )
        if part
    )
    if name:
        return name

    telegram_id = prompt.get("author_telegram_id")
    return f"ID {telegram_id}" if telegram_id else f"DB ID {prompt.get('author_id')}"


def _format_admin_prompts_overview(stats: dict) -> str:
    return "\n".join(
        [
            "📚 <b>Управление промптами</b>",
            "",
            f"• Всего: {_code(stats.get('total', 0))}",
            f"• На проверке: {_code(stats.get('pending', 0))}",
            f"• Опубликовано: {_code(stats.get('approved', 0))}",
            f"• Отклонено: {_code(stats.get('rejected', 0))}",
            f"• Скрыто: {_code(stats.get('deactivated', 0))}",
            f"• Публичных сейчас: {_code(stats.get('public', 0))}",
            "",
            "Выберите статус или откройте карточку по ID.",
        ]
    )


def _format_admin_prompts_list_text(
    status: str, prompts: list[dict], stats: dict, page: int
) -> str:
    title = ADMIN_PROMPT_STATUS_TITLES.get(status, status)
    total = stats.get("total" if status == "all" else status, 0)
    shown_from = ((page - 1) * ADMIN_PROMPTS_PREVIEW_LIMIT + 1) if prompts else 0
    shown_to = (page - 1) * ADMIN_PROMPTS_PREVIEW_LIMIT + len(prompts)
    lines = [
        f"📚 <b>{_html(title)}</b>",
        "",
        f"• Всего в разделе: {_code(total)}",
        f"• Страница: {_code(page)}",
        f"• Показано: {_code(f'{shown_from}-{shown_to}' if prompts else 0)}",
        "",
    ]

    if not prompts:
        lines.append("Промптов в этом разделе пока нет.")
    else:
        for prompt in prompts:
            badge = ADMIN_PROMPT_STATUS_BADGES.get(str(prompt.get("status")), "•")
            author = _prompt_author_label(prompt)
            lines.append(
                f"{badge} <code>#{prompt['id']}</code> "
                f"{_html(_short(prompt.get('title'), 44))}\n"
                f"   Автор: {_html(author)} • "
                f"категория {_code(prompt.get('category'))} • "
                f"👍 {_code(prompt.get('likes', 0))} • "
                f"исп. {_code(prompt.get('uses_count', 0))}"
            )

    return "\n".join(lines)


def _format_admin_prompt_detail_text(prompt: dict) -> str:
    status = str(prompt.get("status") or "pending")
    tags = ", ".join(str(tag) for tag in prompt.get("tags") or []) or "—"
    author = _prompt_author_label(prompt)
    preview_lines: list[str] = []
    if prompt.get("preview_url"):
        preview_lines.extend(["", f"Preview: {_code(prompt.get('preview_url'))}"])
    ai_lines: list[str] = []
    if prompt.get("ai_moderation_decision") or prompt.get("ai_moderation_reason"):
        ai_lines.extend(
            [
                "",
                "<b>AI-модерация:</b>",
                f"• Решение: {_code(prompt.get('ai_moderation_decision'))}",
                f"• Риск: {_code(prompt.get('ai_moderation_risk'))}",
                f"• Причина: {_html(_clip_multiline(prompt.get('ai_moderation_reason'), 400))}",
            ]
        )

    reject_lines: list[str] = []
    if prompt.get("reject_reason"):
        reject_lines.extend(
            [
                "",
                "<b>Причина отклонения:</b>",
                _html(_clip_multiline(prompt.get("reject_reason"), 400)),
            ]
        )

    lines = [
        "📚 <b>Карточка промпта</b>",
        "",
        f"ID: {_code(prompt.get('id'))}",
        f"Статус: {_code(status)}",
        f"Публичный: {_code('да' if prompt.get('is_public') else 'нет')}",
        f"Автор: {_html(author)}",
        f"Telegram ID: {_code(prompt.get('author_telegram_id'))}",
        f"Refcode: {_code(prompt.get('author_referral_code'))}",
        f"Создан: {_code(_short(prompt.get('created_at'), 19))}",
        "",
        f"<b>{_html(prompt.get('title') or 'Без названия')}</b>",
        _html(_clip_multiline(prompt.get("description"), 500)),
        "",
        f"Категория: {_code(prompt.get('category'))}",
        f"Модель: {_code(prompt.get('model'))}",
        f"Теги: {_html(tags)}",
        f"👍 {_code(prompt.get('likes', 0))} • использований {_code(prompt.get('uses_count', 0))}",
        *preview_lines,
        *reject_lines,
        *ai_lines,
        "",
        "<b>Prompt:</b>",
        _html(_clip_multiline(prompt.get("prompt_text"), ADMIN_PROMPT_TEXT_LIMIT)),
    ]
    return "\n".join(lines)


async def _notify_prompt_author(bot: Bot, prompt: dict, text: str) -> None:
    telegram_id = prompt.get("author_telegram_id")
    if not telegram_id:
        return
    try:
        await bot.send_message(int(telegram_id), text, parse_mode="HTML")
    except TelegramAPIError:
        logger.exception(
            "Failed to notify prompt author: prompt_id=%s telegram_id=%s",
            prompt.get("id"),
            telegram_id,
        )


def _as_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _money(value) -> str:
    return f"{_as_float(value):.2f}"


def _admin_finance_total_for_section(section: str, summary: dict) -> int:
    mapping = {
        "topups": "topups_count",
        "deductions": "deductions_count",
        "referrals_l1": "referrals_l1_count",
        "referrals_l2": "referrals_l2_count",
        "partner_commissions": "commission_rows_count",
        "withdrawals": "withdrawals_count",
    }
    return int(summary.get(mapping.get(section, ""), 0) or 0)


def _format_admin_finance_overview(report: dict) -> str:
    summary = report.get("summary") or {}
    promo_line = ""
    if int(summary.get("completed_promo_count", 0) or 0) > 0:
        promo_line = (
            f"• Промокоды: {_code(summary.get('completed_promo_count', 0))} оплат "
            f"на +{_code(summary.get('completed_promo_bonus_credits', 0))}🍌"
        )
    lines = [
        "📒 <b>Финансы и рефералы</b>",
        "",
        "<b>Пополнения:</b>",
        f"• Всего: {_code(summary.get('topups_count', 0))}",
        f"• Завершено: {_code(summary.get('completed_topups_count', 0))} "
        f"на {_code(_money(summary.get('completed_revenue_rub')))} ₽",
        f"• Ожидают: {_code(summary.get('pending_topups_count', 0))} "
        f"• ошибок/отмен: {_code(summary.get('failed_topups_count', 0))}",
        f"• Куплено бананов: {_code(summary.get('completed_credits', 0))}",
        "",
        "<b>Списания:</b>",
        f"• Операций: {_code(summary.get('deductions_count', 0))}",
        f"• Списано: {_code(_money(summary.get('deductions_cost')))} 🍌",
        "",
        "<b>Реферальные линии:</b>",
        f"• 1 линия: {_code(summary.get('referrals_l1_count', 0))} "
        f"(платящих: {_code(summary.get('paid_referrals_l1_count', 0))})",
        f"• 2 линия: {_code(summary.get('referrals_l2_count', 0))}",
        "",
        "<b>Партнёрские выводы:</b>",
        f"• Заявок всего: {_code(summary.get('withdrawals_count', 0))}",
        f"• В ожидании: {_code(_money(summary.get('withdrawals_requested_rub')))} ₽",
        f"• Выплачено: {_code(_money(summary.get('withdrawals_completed_rub')))} ₽",
        "",
        "Откройте нужный раздел для последних строк или скачайте XLS целиком.",
    ]
    if promo_line:
        lines.insert(7, promo_line)
    return "\n".join(lines)


def _format_admin_finance_preview_row(section: str, row: dict) -> str:
    if section == "topups":
        promo = ""
        if row.get("promo_code"):
            promo = (
                f" • 🎟 {_code(row.get('promo_code'))}"
                f" +{_code(row.get('promo_bonus_credits') or 0)}🍌"
            )
        return (
            f"• #{_html(row.get('id'))} "
            f"ID {_code(row.get('telegram_id'))} "
            f"• {_code(_money(row.get('amount_rub')))} ₽ "
            f"• {_code(row.get('credits'))}🍌 "
            f"• {_code(row.get('status'))} "
            f"• {_code(_short(row.get('created_at'), 19))}"
            f"{promo}"
        )
    if section == "deductions":
        model = row.get("model") or row.get("preset_id") or row.get("type") or row.get("source")
        return (
            f"• {_html(row.get('source'))} #{_html(row.get('id'))} "
            f"ID {_code(row.get('telegram_id'))} "
            f"• {_code(_money(row.get('cost')))}🍌 "
            f"• {_code(row.get('status'))} "
            f"• {_code(_short(model, 28))} "
            f"• {_code(_short(row.get('created_at'), 19))}"
        )
    if section == "referrals_l1":
        return (
            f"• {_code(row.get('referrer_telegram_id'))} → "
            f"{_code(row.get('referred_telegram_id'))} "
            f"• оплат {_code(row.get('payments_count'))} "
            f"• {_code(_money(row.get('paid_rub')))} ₽ "
            f"• 2 линия {_code(row.get('subrefs_count'))}"
        )
    if section == "referrals_l2":
        return (
            f"• {_code(row.get('root_partner_telegram_id'))} → "
            f"{_code(row.get('line1_telegram_id'))} → "
            f"{_code(row.get('line2_telegram_id'))} "
            f"• оплат {_code(row.get('payments_count'))} "
            f"• {_code(_money(row.get('paid_rub')))} ₽"
        )
    if section == "partner_commissions":
        return (
            f"• tx#{_html(row.get('transaction_id'))} "
            f"payer {_code(row.get('payer_telegram_id'))} "
            f"• {_code(_money(row.get('amount_rub')))} ₽ "
            f"• L1 {_code(row.get('level1_partner_telegram_id'))}: "
            f"{_code(_money(row.get('level1_commission_rub')))} ₽ "
            f"• L2 {_code(row.get('level2_partner_telegram_id') or '—')}: "
            f"{_code(_money(row.get('level2_commission_rub')))} ₽"
        )
    if section == "withdrawals":
        return (
            f"• #{_html(row.get('id'))} "
            f"ID {_code(row.get('telegram_id'))} "
            f"• {_code(_money(row.get('amount_rub')))} ₽ "
            f"• {_code(row.get('status'))} "
            f"• {_code(_short(row.get('method'), 24))} "
            f"• {_code(_short(row.get('created_at'), 19))}"
        )
    return f"• {_code(row)}"


def _format_admin_finance_section_text(section: str, report: dict) -> str:
    title = ADMIN_FINANCE_SECTION_TITLES.get(section, section)
    rows = report.get(section) or []
    summary = report.get("summary") or {}
    total = _admin_finance_total_for_section(section, summary)
    lines = [
        f"📒 <b>{_html(title)}</b>",
        "",
        f"• Всего строк: {_code(total)}",
        f"• Показано: {_code(min(len(rows), 10))} из {_code(len(rows))}",
        "",
    ]
    if section == "partner_commissions":
        lines.extend(
            [
                "Начисления восстановлены расчётно по завершённым платежам "
                "и текущим процентам программы.",
                "",
            ]
        )

    if not rows:
        lines.append("Нет данных в этом разделе.")
    else:
        for row in rows[:10]:
            lines.append(_format_admin_finance_preview_row(section, row))

    lines.extend(["", "Для полной детализации скачайте XLS раздела."])
    return "\n".join(lines)


def _xls_cell_limit(key: str) -> int:
    return ADMIN_FINANCE_LONG_CELL_LIMITS.get(key, 8000)


def _xls_safe(value, max_chars: int = 8000) -> str:
    if value is None:
        text = ""
    elif isinstance(value, float):
        text = f"{value:.2f}"
    else:
        text = str(value)
    text = text.replace("\x00", "")
    if len(text) > max_chars:
        text = f"{text[: max_chars - 3]}..."
    if text[:1] in {"=", "+", "-", "@"}:
        text = f"'{text}"
    return html_utils.escape(text)


def _build_admin_finance_xls(report: dict, section: str) -> tuple[bytes, str]:
    if section == "all":
        section_keys = ADMIN_FINANCE_SECTION_ORDER
        title = "Финансово-реферальный отчёт"
        file_suffix = "all"
    else:
        section_keys = [section]
        title = ADMIN_FINANCE_SECTION_TITLES.get(section, section)
        file_suffix = section

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    parts = [
        "\ufeff<html><head><meta charset=\"utf-8\">",
        "<style>",
        "body{font-family:Arial,sans-serif;font-size:12px}",
        "table{border-collapse:collapse;margin-bottom:24px}",
        "th,td{border:1px solid #999;padding:4px;vertical-align:top}",
        "th{background:#e8eef7;font-weight:bold}",
        "td{mso-number-format:'\\@'}",
        "</style></head><body>",
        f"<h1>{_xls_safe(title)}</h1>",
        f"<p>Сформировано: {_xls_safe(generated_at)}. "
        f"Лимит строк на раздел: {_xls_safe(report.get('limit'))}.</p>",
    ]

    for section_key in section_keys:
        rows = report.get(section_key) or []
        columns = ADMIN_FINANCE_COLUMNS[section_key]
        parts.append(
            f"<h2>{_xls_safe(ADMIN_FINANCE_SECTION_TITLES[section_key])}</h2>"
        )
        parts.append("<table><thead><tr>")
        for _, label in columns:
            parts.append(f"<th>{_xls_safe(label)}</th>")
        parts.append("</tr></thead><tbody>")
        if not rows:
            parts.append(
                f"<tr><td colspan=\"{len(columns)}\">Нет данных</td></tr>"
            )
        else:
            for row in rows:
                parts.append("<tr>")
                for key, _ in columns:
                    parts.append(
                        f"<td>{_xls_safe(row.get(key), _xls_cell_limit(key))}</td>"
                    )
                parts.append("</tr>")
        parts.append("</tbody></table>")

    notes = report.get("notes") or []
    if notes:
        parts.append("<h2>Примечания</h2><ul>")
        for note in notes:
            parts.append(f"<li>{_xls_safe(note)}</li>")
        parts.append("</ul>")

    parts.append("</body></html>")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"admin_finance_{file_suffix}_{stamp}.xls"
    return "".join(parts).encode("utf-8"), filename


def _xls_yes_no(value: Any) -> str:
    return "да" if bool(value) else "нет"


def _build_admin_partner_xls(report: dict) -> tuple[bytes, str]:
    overview = report.get("overview") or {}
    payments_summary = report.get("payments_summary") or {}
    limits = report.get("limits") or {}
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    summary_rows = [
        ("Telegram ID партнёра", report.get("telegram_id")),
        ("Рефкод", report.get("referral_code") or "—"),
        ("Активировал партнёрку", _xls_yes_no(report.get("is_partner"))),
        ("Активирована", report.get("partner_agreed_at") or "—"),
        ("1 уровень", overview.get("level1_count", 0)),
        ("2 уровень", overview.get("level2_count", 0)),
        ("Оплат по 1 уровню", payments_summary.get("payments_count", 0)),
        ("Выручка по оплатам 1 уровня, ₽", payments_summary.get("paid_rub", 0)),
        ("Куплено бананов 1 уровнем", payments_summary.get("paid_credits", 0)),
        ("Баланс к выводу, ₽", overview.get("balance_rub", 0)),
        ("Выведено, ₽", overview.get("withdrawn_rub", 0)),
        ("Оборот партнёра, ₽", overview.get("total_revenue_rub", 0)),
        ("Лимит рефералов в файле", limits.get("referrals", "")),
        ("Лимит оплат в файле", limits.get("payments", "")),
    ]

    parts = [
        "\ufeff<html><head><meta charset=\"utf-8\">",
        "<style>",
        "body{font-family:Arial,sans-serif;font-size:12px}",
        "table{border-collapse:collapse;margin-bottom:24px}",
        "th,td{border:1px solid #999;padding:4px;vertical-align:top}",
        "th{background:#e8eef7;font-weight:bold}",
        "td{mso-number-format:'\\@'}",
        "</style></head><body>",
        f"<h1>Отчёт по партнёру {_xls_safe(report.get('telegram_id'))}</h1>",
        f"<p>Сформировано: {_xls_safe(generated_at)}.</p>",
        "<h2>Сводка</h2><table><tbody>",
    ]
    for label, value in summary_rows:
        parts.append(
            f"<tr><th>{_xls_safe(label)}</th><td>{_xls_safe(value)}</td></tr>"
        )
    parts.append("</tbody></table>")

    referrals = report.get("referrals") or []
    parts.append("<h2>Прямые рефералы</h2><table><thead><tr>")
    for _, label in ADMIN_PARTNER_REFERRAL_XLS_COLUMNS:
        parts.append(f"<th>{_xls_safe(label)}</th>")
    parts.append("</tr></thead><tbody>")
    if not referrals:
        parts.append(
            f"<tr><td colspan=\"{len(ADMIN_PARTNER_REFERRAL_XLS_COLUMNS)}\">Нет прямых рефералов</td></tr>"
        )
    else:
        for referral in referrals:
            parts.append("<tr>")
            for key, _ in ADMIN_PARTNER_REFERRAL_XLS_COLUMNS:
                value = _xls_yes_no(referral.get(key)) if key == "has_paid" else referral.get(key)
                parts.append(f"<td>{_xls_safe(value)}</td>")
            parts.append("</tr>")
    parts.append("</tbody></table>")

    payments = report.get("payments") or []
    parts.append("<h2>Оплаты 1 уровня</h2><table><thead><tr>")
    for _, label in ADMIN_PARTNER_PAYMENT_XLS_COLUMNS:
        parts.append(f"<th>{_xls_safe(label)}</th>")
    parts.append("</tr></thead><tbody>")
    if not payments:
        parts.append(
            f"<tr><td colspan=\"{len(ADMIN_PARTNER_PAYMENT_XLS_COLUMNS)}\">Нет оплат 1 уровня</td></tr>"
        )
    else:
        for payment in payments:
            parts.append("<tr>")
            for key, _ in ADMIN_PARTNER_PAYMENT_XLS_COLUMNS:
                parts.append(f"<td>{_xls_safe(payment.get(key), _xls_cell_limit(key))}</td>")
            parts.append("</tr>")
    parts.append("</tbody></table>")

    parts.append("</body></html>")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"partner_{report.get('telegram_id')}_level1_payments_{stamp}.xls"
    return "".join(parts).encode("utf-8"), filename


@router.message(Command("admin"))
async def cmd_admin(message: types.Message):
    """Открывает админ-панель"""
    if not is_admin(message.from_user.id):
        await message.answer(
            "⛔ У вас нет доступа к админ-панели.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return

    stats = await get_admin_stats()
    subscription_required = await is_channel_subscription_required()
    text = _format_admin_panel_text(stats, subscription_required)

    await message.answer(
        text,
        reply_markup=get_admin_keyboard(subscription_required),
        parse_mode="HTML",
    )


@router.message(Command("admin_ai"))
async def cmd_admin_ai(message: types.Message, state: FSMContext):
    """Открывает ИИ-админа."""
    if not is_admin(message.from_user.id):
        await message.answer(
            "⛔ У вас нет доступа к ИИ-админу.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return

    await state.set_state(AdminStates.waiting_ai_request)
    await message.answer(
        _format_admin_ai_intro(),
        reply_markup=_admin_ai_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_ai")
async def admin_ai_open(callback: types.CallbackQuery, state: FSMContext):
    """Открывает ИИ-админа из панели."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await state.set_state(AdminStates.waiting_ai_request)
    await callback.message.edit_text(
        _format_admin_ai_intro(),
        reply_markup=_admin_ai_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_ai_help")
async def admin_ai_help(callback: types.CallbackQuery, state: FSMContext):
    """Показывает инструкцию ИИ-админа."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await state.set_state(AdminStates.waiting_ai_request)
    await callback.message.edit_text(
        _format_admin_ai_help_text(),
        reply_markup=_admin_ai_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.waiting_ai_request)
async def admin_ai_process_request(message: types.Message, state: FSMContext):
    """Строит и выполняет безопасный план по текстовому запросу админа."""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Нет доступа")
        await state.clear()
        return

    request = (message.text or "").strip()
    if not request:
        await message.answer(
            "Напишите задачу текстом.",
            reply_markup=_admin_ai_keyboard(),
        )
        return

    await message.bot.send_chat_action(message.chat.id, "typing")
    data = await state.get_data()
    memory = list(data.get("admin_ai_memory") or [])
    plan = await admin_ai_service.plan_action(
        request,
        context={
            "admin_id": message.from_user.id,
            "session_memory": memory[-6:],
            "maintenance_mode": await get_bot_setting("maintenance_mode", "0"),
        },
    )
    plan = normalize_plan(plan)
    error = validate_plan(plan)
    if error:
        await message.answer(
            f"⚠️ {_html(error)}",
            reply_markup=_admin_ai_keyboard(),
            parse_mode="HTML",
        )
        return

    if plan["action"] == "clear_context":
        await state.update_data(admin_ai_memory=[], admin_ai_plan=None)
        await message.answer(
            "✅ Контекст ИИ-админа очищен.",
            reply_markup=_admin_ai_keyboard(),
        )
        return

    if plan["action"] == "help":
        await message.answer(
            _format_admin_ai_help_text(),
            reply_markup=_admin_ai_keyboard(),
            parse_mode="HTML",
        )
        return

    if plan.get("requires_confirmation"):
        await state.update_data(admin_ai_plan=plan, admin_ai_request=request)
        await state.set_state(AdminStates.confirming_ai_action)
        await message.answer(
            _format_admin_ai_plan_preview(plan),
            reply_markup=_admin_ai_confirm_keyboard(),
            parse_mode="HTML",
        )
        return

    result = await execute_admin_ai_plan(
        plan,
        admin_id=message.from_user.id,
        message=message,
    )
    await _remember_admin_ai_context(
        state,
        request=request,
        plan=plan,
        result=result,
    )
    await state.set_state(AdminStates.waiting_ai_request)
    await _send_admin_ai_result(message, result)


@router.callback_query(F.data == "admin_ai_confirm")
async def admin_ai_confirm(callback: types.CallbackQuery, state: FSMContext):
    """Выполняет подтверждённый план ИИ-админа."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    data = await state.get_data()
    plan = normalize_plan(data.get("admin_ai_plan"))
    request = str(data.get("admin_ai_request") or "")
    if not plan or plan.get("action") == "unknown":
        await callback.message.edit_text(
            "❌ План не найден. Напишите задачу заново.",
            reply_markup=_admin_ai_keyboard(),
        )
        await state.set_state(AdminStates.waiting_ai_request)
        await callback.answer()
        return

    error = validate_plan(plan)
    if error:
        await callback.message.edit_text(
            f"⚠️ {_html(error)}",
            reply_markup=_admin_ai_keyboard(),
            parse_mode="HTML",
        )
        await state.set_state(AdminStates.waiting_ai_request)
        await callback.answer()
        return

    await state.update_data(admin_ai_plan=None)
    await state.set_state(AdminStates.waiting_ai_request)
    await callback.message.edit_text("🤖 Выполняю план ИИ-админа...")
    result = await execute_admin_ai_plan(
        plan,
        admin_id=callback.from_user.id,
        message=callback.message,
    )
    await _remember_admin_ai_context(
        state,
        request=request,
        plan=plan,
        result=result,
    )
    await callback.message.edit_text(
        f"<b>🤖 ИИ-админ</b>\n\n{_html(_truncate_plain(result, ADMIN_AI_MESSAGE_LIMIT - 80))}",
        reply_markup=_admin_ai_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer("Готово")


@router.callback_query(F.data == "admin_ai_cancel")
async def admin_ai_cancel(callback: types.CallbackQuery, state: FSMContext):
    """Отменяет сохранённый план ИИ-админа."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await state.update_data(admin_ai_plan=None, admin_ai_request=None)
    await state.set_state(AdminStates.waiting_ai_request)
    await callback.message.edit_text(
        "❌ План отменён. Можно написать новую задачу.",
        reply_markup=_admin_ai_keyboard(),
    )
    await callback.answer("Отменено")


@router.callback_query(F.data == "admin_reload")
async def admin_reload_presets(callback: types.CallbackQuery):
    """Перезагружает пресеты из JSON"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    success = preset_manager.reload()
    await callback.answer(
        (
            "✅ Прайс и конфиг перезагружены"
            if success
            else "❌ Не удалось перезагрузить конфиг"
        ),
        show_alert=True,
    )


@router.callback_query(F.data == "admin_required_subscription_toggle")
async def admin_required_subscription_toggle(callback: types.CallbackQuery):
    """Toggle required subscription to the public prompt channel."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    current = await is_channel_subscription_required()
    enabled = not current
    updated = await set_channel_subscription_required(
        enabled,
        updated_by_telegram_id=callback.from_user.id,
    )
    if not updated:
        await callback.answer("Не удалось обновить настройку", show_alert=True)
        return

    if not enabled:
        clear_required_subscription_cache()

    stats = await get_admin_stats()
    await callback.message.edit_text(
        _format_admin_panel_text(stats, enabled),
        reply_markup=get_admin_keyboard(enabled),
        parse_mode="HTML",
    )
    await callback.answer(
        "Проверка подписки включена" if enabled else "Проверка подписки выключена",
        show_alert=True,
    )


@router.callback_query(F.data == "admin_prices")
async def admin_prices_menu(callback: types.CallbackQuery, state: FSMContext):
    """Меню управления ценами."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await state.clear()
    await callback.message.edit_text(
        "💸 <b>Управление ценами</b>\n\n" "Выберите раздел, который нужно обновить.",
        reply_markup=_admin_price_menu_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_prices_packages")
async def admin_prices_packages(callback: types.CallbackQuery):
    """Список пакетов пополнения."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await callback.message.edit_text(
        "📦 <b>Пакеты пополнения</b>\n\n"
        "Выберите пакет, чтобы поменять цену в рублях или количество бананов.",
        reply_markup=_admin_packages_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_prices_images")
async def admin_prices_images(callback: types.CallbackQuery):
    """Список цен на фото-модели."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await callback.message.edit_text(
        "🖼 <b>Цены на фото</b>\n\n"
        "Выберите модель и отправьте новую стоимость в бананах.",
        reply_markup=_admin_image_prices_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_prices_videos")
async def admin_prices_videos(callback: types.CallbackQuery):
    """Список видео-моделей с ценой за секунду."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await callback.message.edit_text(
        "🎬 <b>Цены на видео</b>\n\n"
        "Цена указана за <b>1 секунду</b>. Выберите модель для редактирования.",
        reply_markup=_admin_video_prices_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_prices_partner_exchange")
async def admin_prices_partner_exchange(callback: types.CallbackQuery, state: FSMContext):
    """Экран настройки курса обмена партнёрского баланса в бананы."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await state.clear()
    current_value = preset_manager.get_partner_exchange_rub_per_credit()
    await state.set_state(AdminStates.waiting_price_value)
    await state.update_data(
        price_target="partner_exchange",
        price_key="partner_exchange",
        price_field="rub_per_credit",
        current_price_value=current_value,
        return_to="admin_prices_partner_exchange",
    )
    await callback.message.edit_text(
        "🤝 <b>Обмен партнёрского баланса</b>\n\n"
        f"Текущий курс: <code>{current_value:g}</code> ₽ → <code>1</code> 🍌\n\n"
        "Отправьте новую цену одного банана в рублях.\n"
        "Например: <code>10</code> — это 10 ₽ за 1 🍌.",
        reply_markup=get_back_keyboard("admin_prices"),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_prices_video_prompt")
async def admin_prices_video_prompt(callback: types.CallbackQuery, state: FSMContext):
    """Экран настройки стоимости сервиса «видео-промпт»."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await state.clear()
    current_value = preset_manager.get_video_prompt_cost()
    await state.set_state(AdminStates.waiting_price_value)
    await state.update_data(
        price_target="service",
        price_key="video_prompt",
        price_field="cost",
        current_price_value=current_value,
        return_to="admin_prices_video_prompt",
    )
    await callback.message.edit_text(
        "🎞 <b>Видео-промпт</b>\n\n"
        f"Текущая стоимость: <code>{current_value:g}</code> 🍌\n\n"
        "Отправьте новую стоимость одним сообщением.",
        reply_markup=get_back_keyboard("admin_prices"),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_video_model_"))
async def admin_video_model(callback: types.CallbackQuery):
    """Детальный экран модели: все длительности + кнопка цены/с."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    model_key = callback.data.replace("admin_video_model_", "", 1)
    video_models = (
        preset_manager.get_price_config()
        .get("costs_reference", {})
        .get("video_models", {})
    )
    model_cfg = video_models.get(model_key)
    if not model_cfg:
        await callback.answer("Модель не найдена", show_alert=True)
        return

    label = VIDEO_MODEL_LABELS.get(model_key, model_key)
    per_sec = _model_per_sec(model_cfg)
    quality_costs = model_cfg.get("quality_costs", {})
    duration_costs = model_cfg.get("duration_costs", {})
    quality_order = {"720p": 0, "1080p": 1, "4k": 2}

    if quality_costs:
        lines = "\n".join(
            f"• {quality} → <code>{cost}</code>🍌/с"
            for quality, cost in sorted(
                quality_costs.items(),
                key=lambda item: (
                    quality_order.get(str(item[0]).lower(), 99),
                    str(item[0]),
                ),
            )
        )
        detail = f"Цены по качеству за 1 секунду:\n{lines}"
    elif duration_costs:
        lines = "\n".join(
            f"• {dur}с → <code>{cost}</code>🍌"
            for dur, cost in sorted(duration_costs.items(), key=lambda x: int(x[0]))
        )
        detail = (
            f"Текущие длительности:\n{lines}\n\nЦена за 1с: <code>{per_sec}</code>🍌"
        )
    else:
        base = model_cfg.get("base", model_cfg.get("cost"))
        detail = f"Базовая стоимость: <code>{base}</code>🍌"

    await callback.message.edit_text(
        f"🎬 <b>{label}</b>\n\n{detail}\n\n" "Выберите параметр для изменения:",
        reply_markup=_admin_video_model_keyboard(model_key),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^admin_price_package_[a-z0-9-]+$"))
async def admin_price_package(callback: types.CallbackQuery):
    """Выбор полей пакета для редактирования."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    package_id = callback.data.replace("admin_price_package_", "", 1)
    package = preset_manager.get_package(package_id)
    if not package:
        await callback.answer("Пакет не найден", show_alert=True)
        return

    await callback.message.edit_text(
        "📦 <b>Редактирование пакета</b>\n\n"
        f"Пакет: <code>{package['name']}</code>\n"
        f"Цена: <code>{package['price_rub']}</code> ₽\n"
        f"Бананы: <code>{package['credits']}</code> 🍌\n\n"
        "Что хотите изменить?",
        reply_markup=_admin_package_fields_keyboard(package_id),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_price_package_field_"))
async def admin_price_package_field(callback: types.CallbackQuery, state: FSMContext):
    """Запрашивает новое значение для поля пакета."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    prefix = "admin_price_package_field_"
    payload = callback.data[len(prefix) :]
    if payload.endswith("_price_rub"):
        package_id = payload[: -len("_price_rub")]
        field = "price_rub"
    elif payload.endswith("_credits"):
        package_id = payload[: -len("_credits")]
        field = "credits"
    else:
        package_id = payload
        field = ""
    package = preset_manager.get_package(package_id)
    if not package or field not in {"price_rub", "credits"}:
        await callback.answer("Некорректное поле", show_alert=True)
        return

    field_label = "цену в ₽" if field == "price_rub" else "количество бананов"
    current_value = package[field]
    await state.set_state(AdminStates.waiting_price_value)
    await state.update_data(
        price_target="package",
        price_key=package_id,
        price_field=field,
        current_price_value=current_value,
        return_to="admin_prices_packages",
    )

    await callback.message.edit_text(
        f"✏️ <b>Изменение пакета {package['name']}</b>\n\n"
        f"Текущее значение за {field_label}: <code>{current_value}</code>\n"
        "Отправьте новое число одним сообщением.",
        reply_markup=get_back_keyboard("admin_prices_packages"),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_price_image_"))
async def admin_price_image(callback: types.CallbackQuery, state: FSMContext):
    """Запрашивает новую цену для фото-модели."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    model_key = callback.data.replace("admin_price_image_", "", 1)
    image_models = (
        preset_manager.get_price_config()
        .get("costs_reference", {})
        .get("image_models", {})
    )
    current_value = image_models.get(model_key)
    if current_value is None:
        await callback.answer("Модель не найдена", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_price_value)
    await state.update_data(
        price_target="image",
        price_key=model_key,
        price_field="cost",
        current_price_value=current_value,
        return_to="admin_prices_images",
    )

    await callback.message.edit_text(
        f"🖼 <b>Изменение цены фото-модели</b>\n\n"
        f"Модель: <code>{model_key}</code>\n"
        f"Текущая стоимость: <code>{current_value}</code> 🍌\n\n"
        "Отправьте новую стоимость одним сообщением.",
        reply_markup=get_back_keyboard("admin_prices_images"),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_price_video_"))
async def admin_price_video(callback: types.CallbackQuery, state: FSMContext):
    """Запрашивает новую цену для видео-модели (конкретная длительность, base или persec)."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    payload = callback.data.replace("admin_price_video_", "", 1)
    model_key, field = payload.rsplit("_", 1)
    video_models = (
        preset_manager.get_price_config()
        .get("costs_reference", {})
        .get("video_models", {})
    )
    model = video_models.get(model_key)
    if not model:
        await callback.answer("Модель не найдена", show_alert=True)
        return

    model_label = VIDEO_MODEL_LABELS.get(model_key, model_key)
    return_to = f"admin_video_model_{model_key}"

    if field == "persec":
        current_value = float(_model_per_sec(model))
        hint_text = (
            "Введите новую цену за <b>1 секунду</b>.\n"
            "Все длительности будут пересчитаны автоматически."
        )
        param_label = "цена/с"
    elif field == "base":
        current_value = model.get("base", model.get("cost"))
        hint_text = "Введите новую базовую стоимость."
        param_label = "базовая цена"
    elif field.startswith("q"):
        quality = field[1:]
        quality_costs = model.get("quality_costs") or {}
        current_value = quality_costs.get(quality)
        hint_text = f"Введите стоимость качества <b>{quality}</b> за <b>1 секунду</b>."
        param_label = f"качество {quality}"
    else:
        current_value = (model.get("duration_costs") or {}).get(field)
        hint_text = f"Введите новую стоимость для длительности <b>{field} сек</b>."
        param_label = f"{field} сек"

    if current_value is None:
        await callback.answer("Цена не найдена", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_price_value)
    await state.update_data(
        price_target="video",
        price_key=model_key,
        price_field=field,
        current_price_value=current_value,
        return_to=return_to,
    )

    await callback.message.edit_text(
        f"🎬 <b>{model_label}</b> — {param_label}\n\n"
        f"Текущее значение: <code>{current_value}</code>🍌\n\n"
        f"{hint_text}",
        reply_markup=get_back_keyboard(return_to),
        parse_mode="HTML",
    )


@router.message(AdminStates.waiting_price_value)
async def admin_process_price_value(message: types.Message, state: FSMContext):
    """Сохраняет новое значение цены."""
    data = await state.get_data()
    target = data.get("price_target")
    key = data.get("price_key")
    field = data.get("price_field")
    current_value = data.get("current_price_value")
    return_to = data.get("return_to", "admin_prices")

    try:
        new_value = _parse_price_value(message.text or "", current_value)
        old_value = _update_price_value(target, key, field, new_value)
    except ValueError:
        await message.answer(
            "❌ Неверное значение. Отправьте положительное число.",
            reply_markup=get_back_keyboard(return_to),
        )
        return
    except Exception as e:
        logger.exception("Failed to update price: %s", e)
        await message.answer(
            "❌ Не удалось обновить цену.",
            reply_markup=get_back_keyboard(return_to),
        )
        await state.clear()
        return

    field = data.get("price_field", "")
    if field == "persec":
        success_text = (
            "✅ <b>Цена за секунду обновлена</b>\n\n"
            f"Было: <code>{old_value}</code>🍌/с\n"
            f"Стало: <code>{new_value}</code>🍌/с\n\n"
            "Все длительности пересчитаны автоматически."
        )
    else:
        success_text = (
            "✅ <b>Цена обновлена</b>\n\n"
            f"Было: <code>{old_value}</code>\n"
            f"Стало: <code>{new_value}</code>"
        )

    await message.answer(
        success_text,
        reply_markup=get_back_keyboard(return_to),
        parse_mode="HTML",
    )
    await state.clear()


@router.callback_query(F.data == "admin_promocodes")
async def admin_promocodes_menu(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await state.clear()
    stats = await get_admin_promo_stats()
    await callback.message.edit_text(
        _format_admin_promocodes_text(stats),
        reply_markup=_admin_promocodes_keyboard(stats.get("promocodes", [])),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_promo_create")
async def admin_promo_create_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await state.set_state(AdminStates.waiting_promo_code_value)
    await state.update_data(promo_admin_action="create")
    await callback.message.edit_text(
        "➕ <b>Создание промокода</b>\n\n"
        "Отправьте данные в формате:\n"
        "<code>CODE | Имя партнёра | Telegram ID</code>\n\n"
        "Telegram ID можно не указывать:\n"
        "<code>MARIA | Мария</code>\n\n"
        "Код будет многоразовым, а бонусы начислятся по количеству бананов в пакете автоматически.",
        reply_markup=get_back_keyboard("admin_promocodes"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_promo_lookup")
async def admin_promo_lookup_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await state.set_state(AdminStates.waiting_promo_code_value)
    await state.update_data(promo_admin_action="lookup")
    await callback.message.edit_text(
        "🔎 <b>Поиск промокода</b>\n\nОтправьте код одним сообщением.",
        reply_markup=get_back_keyboard("admin_promocodes"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.waiting_promo_code_value)
async def admin_process_promo_code_value(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Нет доступа")
        await state.clear()
        return

    data = await state.get_data()
    action = data.get("promo_admin_action")

    if action == "lookup":
        promo = await get_promo_code_by_code(message.text or "", active_only=False)
        if not promo:
            await message.answer(
                "❌ Промокод не найден.",
                reply_markup=get_back_keyboard("admin_promocodes"),
            )
            return
        details = await get_promo_code_details(promo.id)
        await message.answer(
            _format_admin_promo_details_text(details),
            reply_markup=_admin_promo_detail_keyboard(details["promo"]),
            parse_mode="HTML",
        )
        await state.clear()
        return

    try:
        code, partner_name, partner_telegram_id = _parse_promo_create_payload(
            message.text or ""
        )
    except (TypeError, ValueError):
        await message.answer(
            "❌ Не получилось разобрать данные.\n\n"
            "Используйте формат: <code>CODE | Имя партнёра | Telegram ID</code>",
            reply_markup=get_back_keyboard("admin_promocodes"),
            parse_mode="HTML",
        )
        return

    existing = await get_promo_code_by_code(code, active_only=False)
    if existing:
        await message.answer(
            f"❌ Промокод <code>{existing.code}</code> уже существует.",
            reply_markup=get_back_keyboard("admin_promocodes"),
            parse_mode="HTML",
        )
        await state.clear()
        return

    promo = await create_promo_code(
        code,
        partner_name=partner_name,
        partner_telegram_id=partner_telegram_id,
        created_by_telegram_id=message.from_user.id,
    )
    if not promo:
        await message.answer(
            "❌ Не удалось создать промокод.",
            reply_markup=get_back_keyboard("admin_promocodes"),
        )
        await state.clear()
        return

    details = await get_promo_code_details(promo.id)
    await message.answer(
        "✅ <b>Промокод создан</b>\n\n"
        + _format_admin_promo_details_text(details),
        reply_markup=_admin_promo_detail_keyboard(details["promo"]),
        parse_mode="HTML",
    )
    await state.clear()


@router.callback_query(F.data.startswith("admin_promo_view_"))
async def admin_promo_view(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    promo_id = int(callback.data.replace("admin_promo_view_", ""))
    details = await get_promo_code_details(promo_id)
    if not details:
        await callback.answer("Промокод не найден", show_alert=True)
        return

    await callback.message.edit_text(
        _format_admin_promo_details_text(details),
        reply_markup=_admin_promo_detail_keyboard(details["promo"]),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_promo_toggle_"))
async def admin_promo_toggle(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    promo_id = int(callback.data.replace("admin_promo_toggle_", ""))
    promo = await get_promo_code_by_id(promo_id)
    if not promo:
        await callback.answer("Промокод не найден", show_alert=True)
        return

    updated = await set_promo_code_active(promo_id, not promo.is_active)
    if not updated:
        await callback.answer("Не удалось обновить промокод", show_alert=True)
        return

    details = await get_promo_code_details(promo_id)
    await callback.message.edit_text(
        _format_admin_promo_details_text(details),
        reply_markup=_admin_promo_detail_keyboard(details["promo"]),
        parse_mode="HTML",
    )
    await callback.answer("Готово")


@router.callback_query(F.data == "admin_stats")
async def admin_show_stats(callback: types.CallbackQuery):
    """Показывает детальную статистику"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    stats = await get_admin_stats()

    text = f"""
📊 <b>Детальная статистика</b>

👥 <b>Пользователи:</b>
• Всего: <code>{stats['total_users']}</code>

🎨 <b>Генерации:</b>
• Всего: <code>{stats['total_generations']}</code>

💳 <b>Платежи:</b>
• Транзакций: <code>{stats['total_transactions']}</code>
• Выручка: <code>{stats['total_revenue']:.0f}</code> ₽
"""

    await callback.message.edit_text(
        text, reply_markup=get_back_keyboard("admin_back"), parse_mode="HTML"
    )


@router.callback_query(F.data == "admin_finance")
async def admin_finance_menu(callback: types.CallbackQuery, state: FSMContext):
    """Сводка по пополнениям, списаниям и реферальным линиям."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await state.clear()
    report = await get_admin_finance_report(ADMIN_FINANCE_PREVIEW_LIMIT)
    await callback.message.edit_text(
        _format_admin_finance_overview(report),
        reply_markup=_admin_finance_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_finance_xls_"))
async def admin_finance_xls(callback: types.CallbackQuery):
    """Отправляет Excel-совместимый XLS по финансовому разделу."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    section = callback.data.replace("admin_finance_xls_", "", 1)
    if section != "all" and section not in ADMIN_FINANCE_SECTION_TITLES:
        await callback.answer("Раздел не найден", show_alert=True)
        return

    await callback.answer("Готовлю XLS...")
    report = await get_admin_finance_report(ADMIN_FINANCE_XLS_LIMIT)
    file_bytes, filename = _build_admin_finance_xls(report, section)
    limited_by_size = False
    if len(file_bytes) > ADMIN_FINANCE_TELEGRAM_MAX_BYTES:
        logger.warning(
            "Admin finance XLS too large before send: section=%s size=%s, retrying with limit=%s",
            section,
            len(file_bytes),
            ADMIN_FINANCE_XLS_FALLBACK_LIMIT,
        )
        report = await get_admin_finance_report(ADMIN_FINANCE_XLS_FALLBACK_LIMIT)
        file_bytes, filename = _build_admin_finance_xls(report, section)
        limited_by_size = True

    title = (
        "весь финансово-реферальный отчёт"
        if section == "all"
        else ADMIN_FINANCE_SECTION_TITLES[section]
    )
    caption = f"📤 XLS: {title}"
    if limited_by_size:
        caption += "\nФайл был уменьшен до 1000 строк на раздел, чтобы пройти лимит Telegram."

    try:
        await callback.message.answer_document(
            BufferedInputFile(file_bytes, filename=filename),
            caption=caption,
        )
    except TelegramEntityTooLarge:
        logger.exception(
            "Admin finance XLS is still too large: section=%s size=%s",
            section,
            len(file_bytes),
        )
        await callback.message.answer(
            "❌ XLS всё ещё слишком большой для Telegram. "
            "Скачайте отдельные разделы или напишите мне — уменьшу выгрузку ещё сильнее.",
            reply_markup=_admin_finance_keyboard(),
        )
    except TelegramAPIError:
        logger.exception("Failed to send admin finance XLS: section=%s", section)
        await callback.message.answer(
            "❌ Не удалось отправить XLS. Ошибка Telegram уже записана в лог.",
            reply_markup=_admin_finance_keyboard(),
        )


@router.callback_query(F.data.startswith("admin_finance_"))
async def admin_finance_section(callback: types.CallbackQuery, state: FSMContext):
    """Показывает предпросмотр выбранного финансового раздела."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    section = callback.data.replace("admin_finance_", "", 1)
    if section not in ADMIN_FINANCE_SECTION_TITLES:
        await callback.answer("Раздел не найден", show_alert=True)
        return

    await state.clear()
    report = await get_admin_finance_report(ADMIN_FINANCE_PREVIEW_LIMIT)
    await callback.message.edit_text(
        _format_admin_finance_section_text(section, report),
        reply_markup=_admin_finance_section_keyboard(section),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_prompts")
async def admin_prompts_menu(callback: types.CallbackQuery, state: FSMContext):
    """Меню управления пользовательскими промптами."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await state.clear()
    stats = await get_admin_prompt_stats()
    await callback.message.edit_text(
        _format_admin_prompts_overview(stats),
        reply_markup=_admin_prompts_menu_keyboard(stats),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_prompts_status_"))
async def admin_prompts_status(callback: types.CallbackQuery, state: FSMContext):
    """Показывает список промптов по выбранному статусу."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    payload = callback.data.replace("admin_prompts_status_", "", 1)
    status = payload
    page = 1
    maybe_status, separator, maybe_page = payload.rpartition("_")
    if separator and maybe_page.isdigit() and maybe_status in ADMIN_PROMPT_STATUS_TITLES:
        status = maybe_status
        page = max(int(maybe_page), 1)
    if status not in ADMIN_PROMPT_STATUS_TITLES:
        await callback.answer("Раздел не найден", show_alert=True)
        return

    await state.clear()
    stats = await get_admin_prompt_stats()
    total = int(stats.get("total" if status == "all" else status, 0) or 0)
    max_page = max((total - 1) // ADMIN_PROMPTS_PREVIEW_LIMIT + 1, 1)
    if page > max_page:
        page = max_page
    prompts = await get_admin_prompts(
        status,
        limit=ADMIN_PROMPTS_PREVIEW_LIMIT,
        offset=(page - 1) * ADMIN_PROMPTS_PREVIEW_LIMIT,
    )
    await callback.message.edit_text(
        _format_admin_prompts_list_text(status, prompts, stats, page),
        reply_markup=_admin_prompts_list_keyboard(status, prompts, page, total),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_prompt_lookup")
async def admin_prompt_lookup(callback: types.CallbackQuery, state: FSMContext):
    """Запрашивает ID промпта для открытия карточки."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await state.set_state(AdminStates.waiting_prompt_id)
    await callback.message.edit_text(
        "🔎 <b>Поиск промпта</b>\n\nВведите ID промпта из библиотеки.",
        reply_markup=get_back_keyboard("admin_prompts"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.waiting_prompt_id)
async def admin_process_prompt_id(message: types.Message, state: FSMContext):
    """Открывает карточку промпта по введённому ID."""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Нет доступа")
        await state.clear()
        return

    try:
        prompt_id = int((message.text or "").strip())
    except ValueError:
        await message.answer(
            "❌ Неверный формат ID. Введите число.",
            reply_markup=get_back_keyboard("admin_prompts"),
        )
        return

    prompt = await get_admin_prompt_details(prompt_id)
    if not prompt:
        await message.answer(
            f"❌ Промпт #{prompt_id} не найден.",
            reply_markup=get_back_keyboard("admin_prompts"),
        )
        return

    await message.answer(
        _format_admin_prompt_detail_text(prompt),
        reply_markup=_admin_prompt_detail_keyboard(prompt),
        parse_mode="HTML",
    )
    await state.clear()


@router.callback_query(F.data.startswith("admin_prompt_view_"))
async def admin_prompt_view(callback: types.CallbackQuery, state: FSMContext):
    """Показывает детальную карточку промпта."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    prompt_id = int(callback.data.replace("admin_prompt_view_", "", 1))
    prompt = await get_admin_prompt_details(prompt_id)
    if not prompt:
        await callback.answer("Промпт не найден", show_alert=True)
        return

    await state.clear()
    await callback.message.edit_text(
        _format_admin_prompt_detail_text(prompt),
        reply_markup=_admin_prompt_detail_keyboard(prompt),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_prompt_approve_"))
async def admin_prompt_approve(
    callback: types.CallbackQuery, state: FSMContext, bot: Bot
):
    """Публикует или восстанавливает промпт."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    prompt_id = int(callback.data.replace("admin_prompt_approve_", "", 1))
    prompt = await approve_prompt(prompt_id)
    if not prompt:
        await callback.answer("Промпт не найден", show_alert=True)
        return

    prompt = await get_admin_prompt_details(prompt_id)
    await _notify_prompt_author(
        bot,
        prompt,
        "✅ <b>Ваш промпт опубликован</b>\n\n"
        f"Промпт <code>#{prompt_id}</code> теперь доступен в библиотеке.",
    )
    await state.clear()
    await callback.message.edit_text(
        _format_admin_prompt_detail_text(prompt),
        reply_markup=_admin_prompt_detail_keyboard(prompt),
        parse_mode="HTML",
    )
    await callback.answer("✅ Промпт опубликован")


@router.callback_query(F.data.startswith("admin_prompt_deactivate_"))
async def admin_prompt_deactivate(
    callback: types.CallbackQuery, state: FSMContext, bot: Bot
):
    """Скрывает промпт из публичной библиотеки."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    prompt_id = int(callback.data.replace("admin_prompt_deactivate_", "", 1))
    prompt = await deactivate_prompt(prompt_id)
    if not prompt:
        await callback.answer("Промпт не найден", show_alert=True)
        return

    prompt = await get_admin_prompt_details(prompt_id)
    await _notify_prompt_author(
        bot,
        prompt,
        "🗄 <b>Промпт скрыт</b>\n\n"
        f"Промпт <code>#{prompt_id}</code> больше не показывается в библиотеке.",
    )
    await state.clear()
    await callback.message.edit_text(
        _format_admin_prompt_detail_text(prompt),
        reply_markup=_admin_prompt_detail_keyboard(prompt),
        parse_mode="HTML",
    )
    await callback.answer("🗄 Промпт скрыт")


@router.callback_query(F.data.startswith("admin_prompt_reject_"))
async def admin_prompt_reject_prompt(callback: types.CallbackQuery, state: FSMContext):
    """Запрашивает причину отклонения промпта."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    prompt_id = int(callback.data.replace("admin_prompt_reject_", "", 1))
    prompt = await get_admin_prompt_details(prompt_id)
    if not prompt:
        await callback.answer("Промпт не найден", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_prompt_reject_reason)
    await state.update_data(admin_prompt_id=prompt_id)
    await callback.message.edit_text(
        "🚫 <b>Отклонение промпта</b>\n\n"
        f"Промпт: <code>#{prompt_id}</code> — {_html(_short(prompt.get('title'), 80))}\n\n"
        "Отправьте причину отклонения одним сообщением. "
        "Если причина не нужна, отправьте <code>-</code>.",
        reply_markup=get_back_keyboard(f"admin_prompt_view_{prompt_id}"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.waiting_prompt_reject_reason)
async def admin_process_prompt_reject_reason(
    message: types.Message, state: FSMContext, bot: Bot
):
    """Отклоняет промпт с причиной от администратора."""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Нет доступа")
        await state.clear()
        return

    data = await state.get_data()
    prompt_id = int(data.get("admin_prompt_id") or 0)
    reason = (message.text or "").strip()
    if reason == "-":
        reason = ""

    prompt = await reject_prompt(prompt_id, reason)
    if not prompt:
        await message.answer(
            "❌ Промпт не найден.",
            reply_markup=get_back_keyboard("admin_prompts"),
        )
        await state.clear()
        return

    prompt = await get_admin_prompt_details(prompt_id)
    reason_text = (
        f"\n\nПричина: {_html(reason)}"
        if reason
        else ""
    )
    await _notify_prompt_author(
        bot,
        prompt,
        "🚫 <b>Промпт отклонён</b>\n\n"
        f"Промпт <code>#{prompt_id}</code> не был опубликован.{reason_text}",
    )
    await message.answer(
        _format_admin_prompt_detail_text(prompt),
        reply_markup=_admin_prompt_detail_keyboard(prompt),
        parse_mode="HTML",
    )
    await state.clear()


@router.callback_query(F.data == "admin_partners")
async def admin_partners_menu(callback: types.CallbackQuery, state: FSMContext):
    """Сводка по партнёрам и реферальной статистике."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    logger.info("admin_partners pressed by %s", callback.from_user.id)
    try:
        await callback.answer("Открываю партнёров…")
    except TelegramAPIError as exc:
        error_msg = str(exc).lower()
        if "query is too old" not in error_msg and "query id is invalid" not in error_msg:
            raise
        logger.info(
            "Ignoring stale admin_partners callback for user_id=%s: %s",
            callback.from_user.id,
            exc,
        )

    user_id = callback.from_user.id

    async def _send_partners_menu() -> None:
        try:
            await state.clear()
            stats = await get_admin_partner_stats()
            await callback.bot.send_message(
                user_id,
                _format_admin_partners_text(stats),
                reply_markup=_admin_partners_keyboard(stats.get("top_partners", [])),
                parse_mode="HTML",
            )
        except Exception:
            logger.exception("admin_partners failed for %s", user_id)
            await callback.bot.send_message(
                user_id,
                "❌ Не удалось открыть партнёров. Ошибку уже поймал в лог.",
                reply_markup=get_back_keyboard("admin_back"),
            )

    asyncio.create_task(_send_partners_menu())


@router.callback_query(F.data == "admin_partner_withdrawals")
async def admin_partner_withdrawals(callback: types.CallbackQuery, state: FSMContext):
    """Показывает очередь заявок на вывод партнёров."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await state.clear()
    withdrawals = await get_pending_partner_withdrawals()
    await _safe_admin_edit(
        callback,
        _format_admin_withdrawals_text(withdrawals),
        reply_markup=_admin_withdrawals_keyboard(withdrawals),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_partner_burst_autobans")
async def admin_partner_burst_autobans(callback: types.CallbackQuery, state: FSMContext):
    """Показывает отдельный экран со срабатываниями burst_autoban."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await state.clear()
    report = await get_admin_referral_burst_autobans()
    await _safe_admin_edit(
        callback,
        _format_admin_partner_burst_autobans_text(report),
        reply_markup=_admin_partner_burst_autobans_keyboard(report.get("items", [])),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_partner_withdrawal_"))
async def admin_partner_withdrawal_detail(
    callback: types.CallbackQuery, state: FSMContext
):
    """Показывает детальную карточку заявки на вывод."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    withdrawal_id = int(callback.data.replace("admin_partner_withdrawal_", ""))
    withdrawal = await get_partner_withdrawal_request(withdrawal_id)
    if not withdrawal:
        await callback.answer("Заявка не найдена", show_alert=True)
        return

    await state.clear()
    await _safe_admin_edit(
        callback,
        _format_admin_withdrawal_detail_text(withdrawal),
        reply_markup=_admin_withdrawal_detail_keyboard(withdrawal_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_partner_lookup")
async def admin_partner_lookup(callback: types.CallbackQuery, state: FSMContext):
    """Запрашивает Telegram ID партнёра для просмотра статистики."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    logger.info("admin_partner_lookup pressed by %s", callback.from_user.id)
    await callback.answer("Открываю поиск…")
    try:
        await state.set_state(AdminStates.waiting_partner_user_id)
        await _safe_admin_edit(
            callback,
            "🤝 <b>Поиск партнёра</b>\n\n"
            "Введите Telegram ID пользователя, чтобы открыть его реферальную статистику и баланс.",
            reply_markup=get_back_keyboard("admin_partners"),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("admin_partner_lookup failed for %s", callback.from_user.id)
        await callback.bot.send_message(
            callback.from_user.id,
            "❌ Не удалось открыть поиск партнёра.",
            reply_markup=get_back_keyboard("admin_back"),
        )


@router.callback_query(F.data.startswith("admin_partner_xls_"))
async def admin_partner_xls(callback: types.CallbackQuery, state: FSMContext):
    """Отправляет XLS с оплатами прямых рефералов конкретного партнёра."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    try:
        telegram_id = int(callback.data.replace("admin_partner_xls_", "", 1))
    except (TypeError, ValueError):
        await callback.answer("Партнёр не найден", show_alert=True)
        return

    await state.clear()
    await callback.answer("Готовлю XLS...")
    report = await get_admin_partner_payment_report(
        telegram_id,
        referrals_limit=ADMIN_PARTNER_XLS_REFERRALS_LIMIT,
        payments_limit=ADMIN_PARTNER_XLS_PAYMENTS_LIMIT,
    )
    if not report:
        await callback.message.answer(
            f"❌ Пользователь с ID {telegram_id} не найден.",
            reply_markup=get_back_keyboard("admin_partners"),
        )
        return

    file_bytes, filename = _build_admin_partner_xls(report)
    limited_by_size = False
    if len(file_bytes) > ADMIN_FINANCE_TELEGRAM_MAX_BYTES:
        logger.warning(
            "Admin partner XLS too large before send: partner=%s size=%s, retrying with limit=%s",
            telegram_id,
            len(file_bytes),
            ADMIN_PARTNER_XLS_FALLBACK_LIMIT,
        )
        report = await get_admin_partner_payment_report(
            telegram_id,
            referrals_limit=ADMIN_PARTNER_XLS_FALLBACK_LIMIT,
            payments_limit=ADMIN_PARTNER_XLS_FALLBACK_LIMIT,
        )
        file_bytes, filename = _build_admin_partner_xls(report)
        limited_by_size = True

    payments_summary = report.get("payments_summary") or {}
    caption = (
        f"📤 XLS по партнёру {telegram_id}\n"
        f"Оплат 1 уровня: {payments_summary.get('payments_count', 0)}, "
        f"сумма: {_money(payments_summary.get('paid_rub', 0))} ₽"
    )
    if limited_by_size:
        caption += "\nФайл был уменьшен до 1000 строк, чтобы пройти лимит Telegram."

    try:
        await callback.message.answer_document(
            BufferedInputFile(file_bytes, filename=filename),
            caption=caption,
        )
    except TelegramEntityTooLarge:
        logger.exception(
            "Admin partner XLS is still too large: partner=%s size=%s",
            telegram_id,
            len(file_bytes),
        )
        await callback.message.answer(
            "❌ XLS всё ещё слишком большой для Telegram. "
            "Напишите мне — уменьшу выгрузку ещё сильнее.",
            reply_markup=_admin_partner_detail_keyboard(telegram_id),
        )
    except TelegramAPIError:
        logger.exception("Failed to send admin partner XLS: partner=%s", telegram_id)
        await callback.message.answer(
            "❌ Не удалось отправить XLS. Ошибка Telegram уже записана в лог.",
            reply_markup=_admin_partner_detail_keyboard(telegram_id),
        )


@router.callback_query(F.data.startswith("admin_partner_view_"))
async def admin_partner_view(callback: types.CallbackQuery, state: FSMContext):
    """Показывает детальную партнёрскую карточку."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    logger.info("admin_partner_view pressed by %s data=%s", callback.from_user.id, callback.data)
    await callback.answer("Открываю карточку…")
    try:
        telegram_id = int(callback.data.replace("admin_partner_view_", ""))
        details = await get_admin_partner_details(telegram_id)
        if not details:
            await callback.bot.send_message(callback.from_user.id, "❌ Пользователь не найден")
            return

        await state.clear()
        await _safe_admin_edit(
            callback,
            _format_admin_partner_details_text(details),
            reply_markup=_admin_partner_detail_keyboard(telegram_id),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("admin_partner_view failed for %s data=%s", callback.from_user.id, callback.data)
        await callback.bot.send_message(
            callback.from_user.id,
            "❌ Не удалось открыть карточку партнёра.",
            reply_markup=get_back_keyboard("admin_partners"),
        )


@router.message(AdminStates.waiting_partner_user_id)
async def admin_process_partner_user_id(message: types.Message, state: FSMContext):
    """Открывает партнёрскую статистику по введённому Telegram ID."""
    try:
        telegram_id = int((message.text or "").strip())
    except ValueError:
        await message.answer(
            "❌ Неверный формат ID. Введите число.",
            reply_markup=get_back_keyboard("admin_partners"),
        )
        return

    details = await get_admin_partner_details(telegram_id)
    if not details:
        await message.answer(
            f"❌ Пользователь с ID {telegram_id} не найден.",
            reply_markup=get_back_keyboard("admin_partners"),
        )
        return

    await message.answer(
        _format_admin_partner_details_text(details),
        reply_markup=_admin_partner_detail_keyboard(telegram_id),
        parse_mode="HTML",
    )
    await state.clear()


@router.callback_query(F.data == "admin_users")
async def admin_users_menu(callback: types.CallbackQuery, state: FSMContext):
    """Меню управления пользователями"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await callback.message.edit_text(
        "👥 <b>Управление пользователями</b>\n\nВведите Telegram ID пользователя:",
        reply_markup=get_back_keyboard("admin_back"),
        parse_mode="HTML",
    )

    await state.set_state(AdminStates.waiting_user_id)


@router.message(AdminStates.waiting_user_id)
async def admin_process_user_id(message: types.Message, state: FSMContext):
    """Обрабатывает ввод ID пользователя"""
    try:
        user_id = int(message.text)
    except ValueError:
        await message.answer(
            "❌ Неверный формат ID. Введите число:",
            reply_markup=get_back_keyboard("admin_back"),
        )
        return

    # Получаем статистику пользователя
    try:
        stats = await get_user_stats(user_id)
    except Exception as e:
        logger.warning(f"User {user_id} not found: {e}")
        await message.answer(
            f"❌ Пользователь с ID {user_id} не найден.",
            reply_markup=get_back_keyboard("admin_back"),
        )
        return

    await state.update_data(target_user_id=user_id)

    text = f"""
👤 <b>Пользователь</b>

🆔 ID: <code>{user_id}</code>
💰 Кредитов: <code>{stats['credits']}</code>
📊 Генераций: <code>{stats['generations']}</code>
💸 Потрачено: <code>{stats['total_spent']}</code>
📅 Регистрация: <code>{stats['member_since']}</code>
🤝 Рефералов: <code>{stats['referrals_count']}</code>
🎁 Заработано по рефке: <code>{stats['referral_earned']}</code> 🍌
🔗 Рефкод: <code>{stats['referral_code'] or '—'}</code>

Выберите действие:
"""

    await message.answer(
        text,
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="➕ Добавить кредиты",
                        callback_data=f"admin_add_credits_{user_id}",
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="➖ Списать кредиты",
                        callback_data=f"admin_deduct_credits_{user_id}",
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="🤝 Реферальная статистика",
                        callback_data=f"admin_partner_view_{user_id}",
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="🔙 Назад", callback_data="admin_back"
                    )
                ],
            ]
        ),
        parse_mode="HTML",
    )

    await state.clear()


@router.callback_query(F.data.startswith("admin_add_credits_"))
async def admin_add_credits_prompt(callback: types.CallbackQuery, state: FSMContext):
    """Запрашивает количество кредитов для добавления"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    user_id = int(callback.data.replace("admin_add_credits_", ""))
    await state.update_data(target_user_id=user_id, action="add")

    await callback.message.edit_text(
        f"➕ <b>Добавление кредитов</b>\n\n"
        f"Пользователь ID: <code>{user_id}</code>\n"
        f"Введите количество кредитов для добавления:",
        reply_markup=get_back_keyboard("admin_back"),
        parse_mode="HTML",
    )

    await state.set_state(AdminStates.waiting_credits_amount)


@router.callback_query(F.data.startswith("admin_deduct_credits_"))
async def admin_deduct_credits_prompt(callback: types.CallbackQuery, state: FSMContext):
    """Запрашивает количество кредитов для списания"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    user_id = int(callback.data.replace("admin_deduct_credits_", ""))
    await state.update_data(target_user_id=user_id, action="deduct")

    await callback.message.edit_text(
        f"➖ <b>Списание кредитов</b>\n\n"
        f"Пользователь ID: <code>{user_id}</code>\n"
        f"Введите количество кредитов для списания:",
        reply_markup=get_back_keyboard("admin_back"),
        parse_mode="HTML",
    )

    await state.set_state(AdminStates.waiting_credits_amount)


@router.message(AdminStates.waiting_credits_amount)
async def admin_process_credits_amount(message: types.Message, state: FSMContext):
    """Обрабатывает ввод количества кредитов"""
    try:
        amount = int(message.text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Неверное количество. Введите положительное число:")
        return

    data = await state.get_data()
    user_id = data.get("target_user_id")
    action = data.get("action")

    if action == "add":
        success = await add_credits(user_id, amount)
        action_text = f"добавлено <code>{amount}</code> кредитов"
    else:
        # Для списания нужно реализовать deduct_credits_by_admin
        from bot.database import deduct_credits

        success = await deduct_credits(user_id, amount)
        action_text = f"списано <code>{amount}</code> кредитов"

    if success:
        stats = await get_user_stats(user_id)
        await message.answer(
            f"✅ <b>Успешно!</b>\n\n"
            f"Пользователь ID: <code>{user_id}</code>\n"
            f"Действие: {action_text}\n"
            f"Текущий баланс: <code>{stats['credits']}</code> кредитов",
            reply_markup=get_admin_keyboard(),
            parse_mode="HTML",
        )
    else:
        await message.answer(
            f"❌ Ошибка! Возможно, недостаточно кредитов для списания.",
            reply_markup=get_admin_keyboard(),
        )

    await state.clear()


@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_prompt(callback: types.CallbackQuery, state: FSMContext):
    """Запрашивает текст или фото для рассылки"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await callback.message.edit_text(
        "📢 <b>Рассылка всем пользователям</b>\n\n"
        "Отправьте текст сообщения или фото с подписью.\n"
        "Можно отправить фото без подписи — пользователи получат только изображение.\n\n"
        "<i>В тексте и подписи поддерживается HTML-форматирование</i>",
        reply_markup=get_back_keyboard("admin_back"),
        parse_mode="HTML",
    )

    await state.set_state(AdminStates.waiting_broadcast_text)


@router.message(AdminStates.waiting_broadcast_text)
async def admin_process_broadcast_text(message: types.Message, state: FSMContext):
    """Показывает превью рассылки"""
    broadcast_media_type = None
    broadcast_media_file_id = None

    if message.photo:
        broadcast_media_type = "photo"
        broadcast_media_file_id = message.photo[-1].file_id
        broadcast_text = (message.caption or "").strip()

        if len(broadcast_text) > BROADCAST_PHOTO_CAPTION_LIMIT:
            await message.answer(
                "❌ Подпись к фото слишком длинная.\n"
                f"Максимум: <code>{BROADCAST_PHOTO_CAPTION_LIMIT}</code> символов.",
                reply_markup=get_back_keyboard("admin_back"),
                parse_mode="HTML",
            )
            return
    elif message.video:
        broadcast_media_type = "video"
        broadcast_media_file_id = message.video.file_id
        broadcast_text = (message.caption or "").strip()

        if len(broadcast_text) > BROADCAST_PHOTO_CAPTION_LIMIT:
            await message.answer(
                "❌ Подпись к видео слишком длинная.\n"
                f"Максимум: <code>{BROADCAST_PHOTO_CAPTION_LIMIT}</code> символов.",
                reply_markup=get_back_keyboard("admin_back"),
                parse_mode="HTML",
            )
            return
    elif message.text:
        broadcast_text = message.text.strip()

        if not broadcast_text:
            await message.answer(
                "❌ Текст рассылки пустой. Отправьте текст, фото или видео.",
                reply_markup=get_back_keyboard("admin_back"),
            )
            return

        if len(broadcast_text) > BROADCAST_MESSAGE_LIMIT:
            await message.answer(
                "❌ Текст рассылки слишком длинный.\n"
                f"Максимум: <code>{BROADCAST_MESSAGE_LIMIT}</code> символов.",
                reply_markup=get_back_keyboard("admin_back"),
                parse_mode="HTML",
            )
            return
    else:
        await message.answer(
            "❌ Для рассылки отправьте текст, фото или видео с необязательной подписью.",
            reply_markup=get_back_keyboard("admin_back"),
        )
        return

    await state.update_data(
        broadcast_text=broadcast_text,
        broadcast_media_type=broadcast_media_type,
        broadcast_media_file_id=broadcast_media_file_id,
    )

    if broadcast_media_type == "photo":
        await message.answer_photo(
            photo=broadcast_media_file_id,
            caption=broadcast_text or None,
            parse_mode="HTML" if broadcast_text else None,
        )
        await message.answer(
            "📢 <b>Превью рассылки с фото выше.</b>\n\n"
            "Подтверждаете отправку?",
            reply_markup=_broadcast_confirm_keyboard(),
            parse_mode="HTML",
        )
    elif broadcast_media_type == "video":
        await message.answer_video(
            video=broadcast_media_file_id,
            caption=broadcast_text or None,
            parse_mode="HTML" if broadcast_text else None,
        )
        await message.answer(
            "📢 <b>Превью рассылки с видео выше.</b>\n\n"
            "Подтверждаете отправку?",
            reply_markup=_broadcast_confirm_keyboard(),
            parse_mode="HTML",
        )
    else:
        await message.answer(
            "📢 <b>Превью рассылки:</b>\n"
            "───────────────\n"
            f"{broadcast_text}\n"
            "───────────────\n"
            "Подтверждаете отправку?",
            reply_markup=_broadcast_confirm_keyboard(),
            parse_mode="HTML",
        )

    await state.set_state(AdminStates.confirming_broadcast)


@router.callback_query(F.data == "admin_broadcast_confirm")
async def admin_execute_broadcast(
    callback: types.CallbackQuery, state: FSMContext, bot: Bot
):
    """Запускает рассылку в фоне, чтобы не блокировать обработку апдейтов."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    data = await state.get_data()
    broadcast_text = data.get("broadcast_text")
    broadcast_media_type = data.get("broadcast_media_type")
    broadcast_media_file_id = data.get("broadcast_media_file_id")

    if not broadcast_text and not broadcast_media_file_id:
        await callback.message.edit_text(
            "❌ Не найден текст, фото или видео для рассылки.",
            reply_markup=get_admin_keyboard(),
        )
        await state.clear()
        return

    status_message = callback.message
    if status_message is None:
        await callback.answer("❌ Не найдено сообщение для статуса рассылки")
        return

    await status_message.edit_text(
        "📢 <b>Создаю устойчивую рассылку...</b>",
        parse_mode="HTML",
    )
    try:
        campaign_id, total = await _create_admin_broadcast_campaign(
            bot=bot,
            created_by=callback.from_user.id,
            broadcast_text=broadcast_text,
            broadcast_media_type=broadcast_media_type,
            broadcast_media_file_id=broadcast_media_file_id,
        )
    except Exception:
        logger.exception("Failed to create durable broadcast campaign")
        await status_message.edit_text(
            "❌ Не удалось создать устойчивую рассылку. Попробуйте ещё раз.",
            reply_markup=get_admin_keyboard(),
        )
        await state.clear()
        return

    await status_message.edit_text(
        f"📢 <b>Рассылка запущена устойчиво</b>\n\n"
        f"ID кампании: <code>{campaign_id}</code>\n"
        f"Получателей в очереди: <code>{total}</code>\n\n"
        "Если бот перезапустится, рассылка продолжится с очереди, а не начнётся заново.",
        parse_mode="HTML",
    )
    await state.clear()
    await callback.answer("Рассылка запущена")

    asyncio.create_task(_watch_admin_broadcast_campaign(status_message, campaign_id))


async def _create_admin_broadcast_campaign(
    *,
    bot: Bot,
    created_by: int,
    broadcast_text: str | None,
    broadcast_media_type: str | None,
    broadcast_media_file_id: str | None,
) -> tuple[int, int]:
    from bot.internal_admin_notification_schema import ensure_internal_admin_notification_schema
    from bot.notification_service import ensure_notification_campaign_worker

    await ensure_internal_admin_notification_schema()
    ensure_notification_campaign_worker(bot)

    segment = {"type": "all"}
    message_payload = {
        "text": broadcast_text or "",
        "media_type": broadcast_media_type,
        "media_file_id": broadcast_media_file_id,
        "parse_mode": "HTML" if broadcast_text else None,
        "disable_web_page_preview": True,
    }
    reason = "Telegram admin broadcast"
    request_id = f"telegram-admin-{created_by}-{datetime.utcnow().timestamp()}"

    async with db_backend.connect() as connection:
        connection.row_factory = db_backend.Row
        count_cursor = await connection.execute(
            """
            SELECT COUNT(*) AS audience_count
            FROM users
            WHERE COALESCE(is_banned, 0) = 0
              AND telegram_id IS NOT NULL
            """
        )
        count_row = await count_cursor.fetchone()
        audience_count = int(count_row["audience_count"] or 0) if count_row else 0

        campaign_cursor = await connection.execute(
            """
            INSERT INTO notification_campaigns (
                name, channel, status, segment, message, audience_count,
                queued_count, created_by, reason, request_id,
                idempotency_key, started_at
            ) VALUES (?, 'telegram', ?, CAST(? AS JSONB), CAST(? AS JSONB), ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            RETURNING id
            """,
            (
                "Telegram admin broadcast",
                "running" if audience_count else "completed",
                json.dumps(segment, ensure_ascii=False),
                json.dumps(message_payload, ensure_ascii=False),
                audience_count,
                audience_count,
                str(created_by),
                reason,
                request_id,
                request_id,
            ),
        )
        campaign = await campaign_cursor.fetchone()
        campaign_id = int(campaign["id"])

        if audience_count:
            await connection.execute(
                """
                INSERT INTO notification_deliveries (campaign_id, user_id, telegram_id)
                SELECT ?, u.id, u.telegram_id
                FROM users u
                WHERE COALESCE(u.is_banned, 0) = 0
                  AND u.telegram_id IS NOT NULL
                ON CONFLICT (campaign_id, telegram_id) DO NOTHING
                """,
                (campaign_id,),
            )
        await connection.commit()

    return campaign_id, audience_count


async def _watch_admin_broadcast_campaign(
    status_message: types.Message,
    campaign_id: int,
) -> None:
    for _ in range(240):
        await asyncio.sleep(30)
        try:
            async with db_backend.connect() as connection:
                connection.row_factory = db_backend.Row
                cursor = await connection.execute(
                    """
                    SELECT status, audience_count, queued_count, sent_count,
                           failed_count, blocked_count, cancelled_count
                    FROM notification_campaigns
                    WHERE id = ?
                    """,
                    (campaign_id,),
                )
                row = await cursor.fetchone()
            if not row:
                return
            await status_message.edit_text(
                f"📢 <b>Рассылка #{campaign_id}</b>\n\n"
                f"Статус: <code>{row['status']}</code>\n"
                f"📬 Всего: <code>{int(row['audience_count'] or 0)}</code>\n"
                f"⏳ Очередь: <code>{int(row['queued_count'] or 0)}</code>\n"
                f"✅ Отправлено: <code>{int(row['sent_count'] or 0)}</code>\n"
                f"⛔ Заблокировали/чат недоступен: <code>{int(row['blocked_count'] or 0)}</code>\n"
                f"❌ Ошибок: <code>{int(row['failed_count'] or 0)}</code>",
                parse_mode="HTML",
            )
            if str(row["status"]) in {"completed", "cancelled", "failed"}:
                return
        except Exception:
            logger.exception("Failed to update broadcast campaign status")
            return


async def _run_admin_broadcast(
    *,
    bot: Bot,
    status_message: types.Message,
    broadcast_text: str | None,
    broadcast_media_type: str | None,
    broadcast_media_file_id: str | None,
) -> None:
    """Выполняет рассылку с throttling и корректной обработкой ошибок."""

    from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError, TelegramBadRequest

    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute("SELECT telegram_id FROM users WHERE telegram_id IS NOT NULL")
        users = await cursor.fetchall()

    BATCH_SIZE = 25
    BATCH_SLEEP = 0.75
    MESSAGE_SLEEP = 0.02
    PROGRESS_INTERVAL = 250

    success_count = 0
    error_count = 0
    blocked_count = 0
    total = len(users)
    logger.info("Broadcast background started: total=%s media_type=%s", total, broadcast_media_type)

    for idx, user in enumerate(users):
        tid = user["telegram_id"]
        if not tid:
            continue

        try:
            if broadcast_media_type == "photo":
                await bot.send_photo(
                    tid,
                    photo=broadcast_media_file_id,
                    caption=broadcast_text or None,
                    parse_mode="HTML" if broadcast_text else None,
                )
            elif broadcast_media_type == "video":
                await bot.send_video(
                    tid,
                    video=broadcast_media_file_id,
                    caption=broadcast_text or None,
                    parse_mode="HTML" if broadcast_text else None,
                )
            else:
                await bot.send_message(tid, broadcast_text, parse_mode="HTML")
            success_count += 1
        except TelegramForbiddenError:
            blocked_count += 1
        except TelegramBadRequest as e:
            if "bot was blocked" in str(e).lower() or "user is deactivated" in str(e).lower():
                blocked_count += 1
            else:
                logger.warning("Broadcast bad request for %s: %s", tid, e)
                error_count += 1
        except TelegramRetryAfter as e:
            retry_after = e.retry_after if hasattr(e, "retry_after") else 10
            logger.warning("Broadcast rate limit: sleeping %.1f seconds", retry_after)
            await asyncio.sleep(retry_after)
            try:
                if broadcast_media_type == "photo":
                    await bot.send_photo(
                        tid,
                        photo=broadcast_media_file_id,
                        caption=broadcast_text or None,
                        parse_mode="HTML" if broadcast_text else None,
                    )
                elif broadcast_media_type == "video":
                    await bot.send_video(
                        tid,
                        video=broadcast_media_file_id,
                        caption=broadcast_text or None,
                        parse_mode="HTML" if broadcast_text else None,
                    )
                else:
                    await bot.send_message(tid, broadcast_text, parse_mode="HTML")
                success_count += 1
            except Exception as e_retry:
                logger.warning("Broadcast retry failed for %s: %s", tid, e_retry)
                error_count += 1
        except Exception as e:
            logger.warning("Broadcast failed for %s: %s", tid, e)
            error_count += 1

        await asyncio.sleep(MESSAGE_SLEEP)

        if (idx + 1) % BATCH_SIZE == 0:
            await asyncio.sleep(BATCH_SLEEP)

        if (idx + 1) % PROGRESS_INTERVAL == 0 or idx == total - 1:
            try:
                await status_message.edit_text(
                    f"📢 <b>Рассылка...</b>\n"
                    f"📨 Обработано: <code>{idx + 1}/{total}</code>\n"
                    f"✅ Успешно: <code>{success_count}</code>\n"
                    f"⛔ Заблокировали: <code>{blocked_count}</code>\n"
                    f"❌ Ошибок: <code>{error_count}</code>",
                    parse_mode="HTML",
                )
            except Exception:
                pass

    try:
        await status_message.edit_text(
            f"📢 <b>Рассылка завершена!</b>\n\n"
            f"✅ Успешно: <code>{success_count}</code>\n"
            f"⛔ Заблокировали бота: <code>{blocked_count}</code>\n"
            f"❌ Ошибок: <code>{error_count}</code>\n"
            f"📬 Всего: <code>{total}</code>",
            reply_markup=get_admin_keyboard(),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Broadcast final status update failed")
    logger.info(
        "Broadcast background finished: total=%s success=%s blocked=%s errors=%s",
        total,
        success_count,
        blocked_count,
        error_count,
    )


@router.callback_query(F.data == "admin_back")
async def admin_back_to_menu(callback: types.CallbackQuery, state: FSMContext):
    """Возврат в админ-меню"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await state.clear()
    stats = await get_admin_stats()
    subscription_required = await is_channel_subscription_required()
    text = _format_admin_panel_text(stats, subscription_required)

    await _safe_admin_edit(
        callback,
        text,
        reply_markup=get_admin_keyboard(subscription_required),
        parse_mode="HTML",
    )
