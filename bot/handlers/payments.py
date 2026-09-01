import json
import logging
import time
import html
from datetime import datetime, timedelta


from typing import Any
from aiogram import Bot, F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiohttp import web

from bot import db as db_backend
from bot.config import config
from bot.database import (
    PROMO_BONUS_BY_CREDITS,
    add_credits,
    complete_payment_atomic,
    create_miniapp_notification,
    create_transaction,
    credit_first_payment_referral_bonus,
    get_promo_bonus_for_credits,
    get_promo_code_by_code,
    get_or_create_user,
    get_telegram_id_by_user_id,
    get_transaction_by_order,
    get_user_settings,
    normalize_promo_code,
    record_promo_redemption,
    update_transaction_payment_id,
    update_transaction_status,
)
from bot.keyboards import (
    get_back_keyboard,
    get_main_menu_keyboard,
    get_payment_confirmation_keyboard,
    get_payment_method_keyboard,
    get_payment_packages_keyboard,
)
from bot.payment_utils import (
    TELEGRAM_STARS_CURRENCY,
    TELEGRAM_STARS_PROVIDER,
    build_stars_invoice_payload,
    package_bonus_credits,
    package_stars_amount,
    parse_stars_invoice_payload,
    total_package_credits,
)
from bot.services.cryptobot_service import cryptobot_service
from bot.services.lava_service import lava_service
from bot.services.preset_manager import preset_manager
from bot.services.yookassa_service import yookassa_service
from bot.states import PaymentStates

logger = logging.getLogger(__name__)
router = Router()


def _package_lava_offer_config(package: dict) -> tuple[str, str]:
    package_id = str(package.get("id") or "")
    currency = str(package.get("lava_currency") or "RUB").strip().upper() or "RUB"
    offer_id = str(package.get("lava_offer_id") or "").strip()
    if offer_id:
        return offer_id, currency
    return config.lava_offer_id_for_package(package_id), currency


def _is_ignored_telegram_error(error: Exception) -> bool:
    error_msg = str(error).lower()
    return (
        "chat not found" in error_msg
        or "bot was blocked" in error_msg
        or "user is deactivated" in error_msg
        or "bot can't initiate conversation" in error_msg
        or "forbidden" in error_msg
        or "chat is deactivated" in error_msg
    )


async def _notify_user(bot: Bot, telegram_id: int, text: str, *, parse_mode=None):
    try:
        await bot.send_message(telegram_id, text, parse_mode=parse_mode)
    except TelegramBadRequest as e:
        if _is_ignored_telegram_error(e):
            raise
        raise


def _build_bonus_text(referral_bonus: dict[str, Any]) -> str:
    if referral_bonus.get("mode") == "partner":
        return f"\n🎁 Партнёрский бонус: <code>{referral_bonus['value']}</code> ₽"
    if referral_bonus.get("mode") == "banana":
        return f"\n🎁 Реферальный бонус: <code>{referral_bonus['value']}</code> бананов"
    return ""


def _format_money(value: Any) -> str:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        amount = 0.0
    return f"{amount:.2f}".rstrip("0").rstrip(".")


def _user_display_parts(user: Any) -> tuple[str, str]:
    username = str(getattr(user, "username", "") or "").strip().lstrip("@")
    full_name = str(getattr(user, "full_name", "") or "").strip()
    if not full_name:
        full_name = " ".join(
            str(value).strip()
            for value in (
                getattr(user, "first_name", None),
                getattr(user, "last_name", None),
        )
            if value and str(value).strip()
        )

    display_name = html.escape(full_name or username or "Реферал")
    username_line = f"\n@{html.escape(username)}" if username else ""
    return display_name, username_line


async def _notify_referrers_about_purchase(
    bot: Bot | None,
    *,
    buyer_telegram_id: int,
    transaction,
    referral_bonus: dict[str, Any],
) -> None:
    if not bot or referral_bonus.get("mode") != "partner":
        return

    buyer = await get_or_create_user(buyer_telegram_id)
    buyer_name, buyer_username_line = _user_display_parts(buyer)
    amount_rub = _format_money(getattr(transaction, "amount_rub", 0))
    credits = getattr(transaction, "credits", 0)

    targets: list[dict[str, Any]] = []
    referrer_telegram_id = referral_bonus.get("referrer_telegram_id")
    if referrer_telegram_id and float(referral_bonus.get("value") or 0) > 0:
        targets.append(
            {
                "telegram_id": int(referrer_telegram_id),
                "title": "🛒 <b>Покупка реферала</b>",
                "bonus_label": "Ваше начисление",
                "bonus_value": referral_bonus.get("value"),
            }
        )

    level2_referrer_telegram_id = referral_bonus.get("level2_referrer_telegram_id")
    if level2_referrer_telegram_id and float(referral_bonus.get("level2_value") or 0) > 0:
        targets.append(
            {
                "telegram_id": int(level2_referrer_telegram_id),
                "title": "🛒 <b>Покупка реферала 2 уровня</b>",
                "bonus_label": "Начисление 2 уровня",
                "bonus_value": referral_bonus.get("level2_value"),
            }
        )

    for target in targets:
        target_telegram_id = target["telegram_id"]
        try:
            settings = await get_user_settings(target_telegram_id)
            if not settings.get("referral_purchase_notifications_enabled", True):
                continue

            text = (
                f"{target['title']}\n\n"
                f"Реферал: <b>{buyer_name}</b>{buyer_username_line}\n"
                f"Покупка: <code>{credits}</code>🍌 на <code>{amount_rub}</code> ₽\n"
                f"{target['bonus_label']}: "
                f"<code>{_format_money(target['bonus_value'])}</code> ₽"
            )
            await bot.send_message(target_telegram_id, text, parse_mode="HTML")
            logger.info(
                "Referral purchase notification sent: referrer=%s buyer=%s order=%s",
                target_telegram_id,
                buyer_telegram_id,
                getattr(transaction, "order_id", "?"),
            )
        except Exception as exc:
            if _is_ignored_telegram_error(exc):
                logger.warning(
                    "Skipping referral purchase notification for user %s: %s",
                    target_telegram_id,
                    exc,
                )
                continue
            logger.exception(
                "Failed to notify referrer %s about referral purchase order=%s",
                target_telegram_id,
                getattr(transaction, "order_id", "?"),
            )


def _build_promo_rules_text() -> str:
    return "\n".join(
        f"• {credits}🍌 → +<code>{bonus}</code>🍌"
        for credits, bonus in PROMO_BONUS_BY_CREDITS.items()
    )


def _build_promo_bonus_text(promo_bonus: dict[str, Any] | None) -> str:
    if not promo_bonus or int(promo_bonus.get("bonus_credits") or 0) <= 0:
        return ""
    code = normalize_promo_code(promo_bonus.get("code"))
    code_part = f" <code>{code}</code>" if code else ""
    return (
        f"\n🎟 Промокод{code_part}: +<code>{promo_bonus['bonus_credits']}</code> бананов"
    )


def _transaction_promo_text(transaction) -> str:
    if int(getattr(transaction, "promo_bonus_credits", 0) or 0) <= 0:
        return ""
    return _build_promo_bonus_text(
        {
            "code": getattr(transaction, "promo_code", "") or "",
            "bonus_credits": getattr(transaction, "promo_bonus_credits", 0),
        }
    )


async def _get_selected_promo(state: FSMContext | None):
    if state is None:
        return None
    data = await state.get_data()
    code = data.get("promo_code")
    if not code:
        return None
    promo = await get_promo_code_by_code(str(code), active_only=True)
    if not promo:
        await state.update_data(promo_code=None, promo_code_id=None)
        return None
    return promo


def _promo_bonus_for_package(promo, package: dict[str, Any]) -> int:
    if not promo:
        return 0
    return get_promo_bonus_for_credits(package.get("credits"))


def _extract_first(obj: Any, keys: list[str] | tuple[str, ...]) -> Any:
    """Recursively find the first non-empty value for any key in a webhook payload."""
    if isinstance(obj, dict):
        for key in keys:
            value = obj.get(key)
            if value not in (None, ""):
                return value
        for value in obj.values():
            found = _extract_first(value, keys)
            if found not in (None, ""):
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _extract_first(value, keys)
            if found not in (None, ""):
                return found
    return None


async def _resolve_payment_state(transaction) -> dict[str, Any]:
    provider = (getattr(transaction, "provider", None) or "cryptobot").lower()
    payment_id = getattr(transaction, "payment_id", None)

    if not payment_id:
        return {"provider": provider, "status": "", "paid": False, "failed": False}

    try:
        if provider == "lava":
            if not lava_service.enabled:
                return {"provider": provider, "status": "service_disabled", "paid": False, "failed": False}
            invoice = await lava_service.get_invoice(payment_id)
            status = str((invoice or {}).get("status") or "").lower()
            return {
                "provider": provider,
                "status": status,
                "paid": status == "completed",
                "failed": status in {"cancelled", "canceled", "failed", "expired"},
                "invoice": invoice,
            }

        if provider == "yookassa":
            if not yookassa_service.enabled:
                return {"provider": provider, "status": "service_disabled", "paid": False, "failed": False}
            invoice = await yookassa_service.get_payment(payment_id)
            status = str((invoice or {}).get("status") or "").lower()
            paid = bool((invoice or {}).get("paid")) or status in {"succeeded", "paid", "captured"}
            failed = status in {"canceled", "cancelled", "failed", "rejected"}
            return {
                "provider": provider,
                "status": status,
                "paid": paid,
                "failed": failed,
                "invoice": invoice,
            }

        if not cryptobot_service.enabled:
            return {"provider": provider, "status": "service_disabled", "paid": False, "failed": False}
        invoice = await cryptobot_service.get_invoice(payment_id)
        status = str((invoice or {}).get("status") or "").lower()
        failed = status in {"expired", "cancelled", "canceled", "invalid"}
        if status == "active" and _is_pending_past_ttl(transaction):
            failed = True
            status = "expired_local_ttl"
        return {
            "provider": provider,
            "status": status,
            "paid": status == "paid",
            "failed": failed,
            "invoice": invoice,
        }
    except Exception as exc:
        logger.exception(
            "Payment state resolve failed for order=%s provider=%s: %s",
            getattr(transaction, "order_id", "?"),
            provider,
            exc,
        )
        return {
            "provider": provider,
            "status": "lookup_error",
            "paid": False,
            "failed": False,
            "error": str(exc),
        }


def _is_pending_past_ttl(transaction, ttl_days: int | None = None) -> bool:
    ttl_days = ttl_days or max(1, int(config.CRYPTOBOT_PENDING_TTL_DAYS or 7))
    created_at = getattr(transaction, "created_at", None)
    if not created_at:
        return False

    try:
        cutoff = datetime.now(created_at.tzinfo) - timedelta(days=ttl_days)
    except Exception:
        cutoff = datetime.utcnow() - timedelta(days=ttl_days)
    return created_at < cutoff


async def cleanup_stale_cryptobot_pending(limit: int = 500) -> dict[str, int]:
    """Обрабатывает зависшие pending-транзакции CryptoBot.

    - Если на стороне CryptoBot платёж `paid`, завершает через
      `complete_payment_atomic()` с защитой `already_completed`.
    - Если платёж истёк или отменён — помечает как `failed` в атомарном
      статус-переходе, чтобы не было race-условия с вебхуком.
    - Если платёж всё ещё активен — оставляет как есть (пользователь
      ещё может оплатить).
    """
    stats = {"checked": 0, "completed": 0, "failed": 0, "kept": 0}

    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        rows = await (await db.execute(
            "SELECT order_id, payment_id, created_at FROM transactions WHERE provider = 'cryptobot' AND status = 'pending' ORDER BY created_at ASC LIMIT ?",
            (limit,),
        )).fetchall()

    for row in rows:
        stats["checked"] += 1
        created_at_raw = row["created_at"]
        try:
            created_at = datetime.fromisoformat(created_at_raw)
        except Exception:
            stats["kept"] += 1
            continue

        stub = type("TxStub", (), {
            "created_at": created_at,
            "order_id": row["order_id"],
        })()
        if not _is_pending_past_ttl(stub):
            stats["kept"] += 1
            continue

        payment_id = row["payment_id"]
        order_id = row["order_id"]
        invoice = await cryptobot_service.get_invoice(payment_id)
        status = str((invoice or {}).get("status") or "").lower()

        if status in {"paid"}:
            # Платёж успешен на стороне CryptoBot — завершаем атомарно.
            # complete_payment_atomic использует pending→processing→completed
            # с already_completed-защитой, поэтому race с вебхуком безопасен.
            completion = await complete_payment_atomic(order_id)
            if completion.get("ok") and not completion.get("already_completed"):
                stats["completed"] += 1
                logger.info(
                    "Cleanup completed CryptoBot payment order=%s via complete_payment_atomic",
                    order_id,
                )
            elif completion.get("already_completed"):
                # Вебхук уже обработал — всё в порядке
                stats["completed"] += 1
                logger.info(
                    "Cleanup: CryptoBot order=%s already completed via webhook",
                    order_id,
                )
            else:
                # complete_payment_atomic вернул ошибку — не трогаем
                stats["kept"] += 1
                logger.warning(
                    "Cleanup: complete_payment_atomic failed for order=%s reason=%s",
                    order_id,
                    completion.get("reason"),
                )
            continue

        if status in {"active", "expired", "cancelled", "canceled", "invalid", ""}:
            # Платеж истёк или отменён — помечаем failed, но только если
            # он всё ещё pending (не был обработан вебхуком).
            # Используем прямое UPDATE с проверкой status='pending',
            # чтобы не перезаписать результат вебхука.
            async with db_backend.connect() as db:
                cursor = await db.execute(
                    "UPDATE transactions SET status = 'failed' WHERE order_id = ? AND status = 'pending'",
                    (order_id,),
                )
                await db.commit()
                if cursor.rowcount > 0:
                    stats["failed"] += 1
                else:
                    # Уже был изменён вебхуком или другим процессом
                    stats["kept"] += 1
            continue

        stats["kept"] += 1

    logger.info(
        "CryptoBot stale pending cleanup finished: checked=%s completed=%s failed=%s kept=%s ttl_days=%s",
        stats["checked"],
        stats["completed"],
        stats["failed"],
        stats["kept"],
        config.CRYPTOBOT_PENDING_TTL_DAYS,
    )
    return stats


async def reconcile_lava_pending_transactions(
    *,
    limit: int = 200,
    bot: Bot | None = None,
) -> list[dict[str, Any]]:
    """Poll Lava for pending invoices and complete paid transactions.

    Pending-инвойсы старше ``config.LAVA_PENDING_TTL_HOURS`` часов считаются
    брошенными: они помечаются ``failed`` без опроса Lava API, чтобы не
    блокировать очередь reconcile (Lava держит их в ``in_progress`` очень долго).
    """

    if not lava_service.enabled:
        return []

    results: list[dict[str, Any]] = []

    # TTL-очистка: протухшие pending -> failed (без запроса к Lava API)
    ttl_hours = max(int(getattr(config, "LAVA_PENDING_TTL_HOURS", 24) or 24), 1)
    ttl_cutoff = (datetime.now() - timedelta(hours=ttl_hours)).isoformat()
    async with db_backend.connect() as db:
        cursor = await db.execute(
            """
            UPDATE transactions
            SET status = 'failed'
            WHERE provider = 'lava' AND status = 'pending' AND created_at < ?
            """,
            (ttl_cutoff,),
        )
        await db.commit()
        expired_count = cursor.rowcount or 0
    if expired_count:
        logger.info(
            "Lava reconcile: expired %s stale pending transactions (ttl=%sh)",
            expired_count,
            ttl_hours,
        )

    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        rows = await (
            await db.execute(
                """
                SELECT order_id, payment_id
                FROM transactions
                WHERE provider = 'lava' AND status = 'pending'
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        ).fetchall()

    for row in rows:
        order_id = row["order_id"]
        payment_id = row["payment_id"]
        item: dict[str, Any] = {"order_id": order_id, "payment_id": payment_id}
        try:
            invoice = await lava_service.get_invoice(payment_id)
            status = str((invoice or {}).get("status") or "").lower()
            item["status"] = status or "unknown"

            if status == "completed":
                completion = await _complete_transaction(order_id, bot=bot)
                item["action"] = (
                    "already_completed"
                    if completion.get("already_completed")
                    else "completed"
                    if completion.get("ok")
                    else "complete_failed"
                )
                if not completion.get("ok"):
                    item["reason"] = completion.get("reason")
                elif not completion.get("already_completed") and bot:
                    transaction = completion.get("transaction")
                    telegram_id = completion.get("telegram_id")
                    bonus_text = (
                        _build_promo_bonus_text(completion.get("promo_bonus") or {})
                        + _build_bonus_text(completion.get("referral_bonus") or {})
                    )
                    try:
                        await _notify_user(
                            bot,
                            telegram_id,
                            "✅ <b>Оплата Lava успешно обработана</b>\n"
                            f"• Начислено: <code>{transaction.credits}</code> бананов\n"
                            f"• Сумма: <code>{transaction.amount_rub}</code> ₽{bonus_text}",
                            parse_mode="HTML",
                        )
                    except TelegramBadRequest as notify_error:
                        if _is_ignored_telegram_error(notify_error):
                            logger.warning(
                                "Skipping Lava reconcile notification for user %s: %s",
                                telegram_id,
                                notify_error,
                            )
                        else:
                            logger.error(
                                "Failed to notify user %s after Lava reconcile: %s",
                                telegram_id,
                                notify_error,
                            )
            elif status in {"cancelled", "canceled", "failed", "expired"}:
                item["action"] = (
                    "failed"
                    if await update_transaction_status(order_id, "failed")
                    else "already_failed"
                )
            else:
                item["action"] = "still_pending"
        except Exception as exc:
            logger.exception(
                "Lava reconcile failed for order_id=%s payment_id=%s",
                order_id,
                payment_id,
            )
            item["action"] = "error"
            item["error"] = str(exc)
        results.append(item)

    return results


async def _complete_transaction(order_id: str, bot: Bot | None = None) -> dict[str, Any]:
    """Атомарно завершает платёж через complete_payment_atomic.

    Все начисления (credits, referral, promo, partner_commissions) происходят в одной
    DB-транзакции. Уведомления отправляются только после успешного commit.
    """
    result = await complete_payment_atomic(order_id)

    if not result.get("ok"):
        return result

    if result.get("already_completed"):
        return result

    # Post-commit: уведомления партнёрам (вне транзакции)
    transaction = result.get("transaction")
    telegram_id = result.get("telegram_id")
    referral_bonus = result.get("referral_bonus") or {}
    promo_bonus = result.get("promo_bonus") or {}

    if transaction and telegram_id:
        await _notify_referrers_about_purchase(
            bot,
            buyer_telegram_id=telegram_id,
            transaction=transaction,
            referral_bonus=referral_bonus,
        )

    return result

async def _render_topup_menu(message: types.Message, state: FSMContext | None = None):
    packages = preset_manager.get_packages()
    promo = await _get_selected_promo(state)
    promo_text = ""
    if promo:
        promo_text = (
            f"\n\n🎟 Активный промокод: <code>{promo.code}</code>\n"
            "Бонус будет начислен автоматически по количеству бананов в пакете."
        )
    text = (
        "🍌 <b>Пополнение баланса</b>\n\n"
        "Оплата выполняется через выбранного платёжного провайдера.\n"
        "Выберите пакет бананов ниже.\n\n"
        "<b>Бонусы по промокоду:</b>\n"
        f"{_build_promo_rules_text()}\n\n"
        "<i>Чем больше пакет, тем выгоднее цена за банан.</i>"
        f"{promo_text}"
    )

    await message.edit_text(
        text,
        reply_markup=get_payment_packages_keyboard(packages, promo_active=bool(promo)),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu_topup")
async def show_topup_menu(callback: types.CallbackQuery, state: FSMContext):
    if await state.get_state() == PaymentStates.waiting_promo_code.state:
        await state.set_state(None)
    await _render_topup_menu(callback.message, state)


@router.callback_query(F.data == "menu_buy_credits")
async def show_packages(callback: types.CallbackQuery, state: FSMContext):
    if await state.get_state() == PaymentStates.waiting_promo_code.state:
        await state.set_state(None)
    await _render_topup_menu(callback.message, state)


@router.callback_query(F.data == "topup_enter_promo")
async def topup_enter_promo(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(PaymentStates.waiting_promo_code)
    await callback.message.edit_text(
        "🎟 <b>Промокод</b>\n\n"
        "Отправьте промокод одним сообщением. Он многоразовый: после ввода можно "
        "пополнять баланс с этим кодом снова.\n\n"
        "<b>Бонусы:</b>\n"
        f"{_build_promo_rules_text()}",
        reply_markup=get_back_keyboard("menu_topup"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "topup_remove_promo")
async def topup_remove_promo(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(promo_code=None, promo_code_id=None)
    await state.set_state(None)
    await callback.answer("Промокод убран")
    await _render_topup_menu(callback.message, state)


@router.message(PaymentStates.waiting_promo_code)
async def topup_process_promo(message: types.Message, state: FSMContext):
    code = normalize_promo_code(message.text)
    promo = await get_promo_code_by_code(code, active_only=True)
    if not promo:
        await message.answer(
            "❌ Промокод не найден или выключен. Проверьте написание и отправьте код ещё раз.",
            reply_markup=get_back_keyboard("menu_topup"),
        )
        return

    await state.update_data(promo_code=promo.code, promo_code_id=promo.id)
    await state.set_state(None)

    packages = preset_manager.get_packages()
    await message.answer(
        "✅ <b>Промокод применён</b>\n\n"
        f"Код: <code>{promo.code}</code>\n"
        "Теперь выберите пакет. Бонус добавится автоматически по количеству бананов.\n\n"
        f"{_build_promo_rules_text()}",
        reply_markup=get_payment_packages_keyboard(packages, promo_active=True),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("choose_pay_"))
async def choose_payment_method(callback: types.CallbackQuery, state: FSMContext):
    """Показывает доступные способы оплаты для выбранного пакета."""
    package_id = callback.data.replace("choose_pay_", "", 1)
    package = preset_manager.get_package(package_id)
    if not package:
        await callback.answer("Пакет не найден", show_alert=True)
        return

    has_crypto = cryptobot_service.enabled
    lava_offer_id, lava_currency = _package_lava_offer_config(package)
    has_lava = lava_service.enabled and bool(lava_offer_id)
    has_yookassa = yookassa_service.enabled
    has_stars = bool(config.TELEGRAM_STARS_ENABLED)

    if not has_crypto and not has_lava and not has_yookassa and not has_stars:
        await callback.message.edit_text(
            "❌ Платёжные системы временно недоступны.\nОбратитесь в поддержку.",
            reply_markup=get_back_keyboard("menu_topup"),
        )
        return

    available_count = sum(
        1 for value in (has_crypto, has_lava, has_yookassa, has_stars) if value
    )
    if available_count == 1:
        await callback.answer()
        if has_stars:
            fake = callback.model_copy(update={"data": f"buy_stars_{package_id}"})
            return await initiate_payment(fake, state)
        if has_crypto:
            fake = callback.model_copy(update={"data": f"buy_crypto_{package_id}"})
            return await initiate_payment(fake, state)
        if has_yookassa:
            fake = callback.model_copy(update={"data": f"buy_yookassa_{package_id}"})
            return await initiate_payment(fake, state)
        fake = callback.model_copy(update={"data": f"buy_lava_{package_id}"})
        return await initiate_payment(fake, state)

    promo = await _get_selected_promo(state)
    package_bonus = package_bonus_credits(package)
    promo_bonus = _promo_bonus_for_package(promo, package)
    total_credits = total_package_credits(package, promo_bonus)
    stars_amount = package_stars_amount(package)
    bonus_lines = []
    if package_bonus > 0:
        bonus_lines.append(f"Бонус пакета: <code>{package_bonus}</code>🍌")
    if promo_bonus > 0 and promo:
        bonus_lines.append(
            f"Промокод <code>{promo.code}</code>: +<code>{promo_bonus}</code>🍌"
        )
    bonus_text = "\n".join(bonus_lines)
    bonus_text = f"\n{bonus_text}" if bonus_text else ""
    await callback.message.edit_text(
        f"💳 <b>Выберите способ оплаты</b>\n\n"
        f"Пакет: <b>{package['name']}</b>\n"
        f"Бананы: <code>{total_credits}</code>🍌\n"
        f"Сумма: <code>{package['price_rub']}</code>₽ / <code>{stars_amount}</code>⭐"
        f"{bonus_text}",
        reply_markup=get_payment_method_keyboard(
            package_id,
            has_crypto,
            has_lava,
            has_stars=has_stars,
            has_yookassa=has_yookassa,
            lava_currency=lava_currency,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("buy_"))
async def initiate_payment(callback: types.CallbackQuery, state: FSMContext):
    """Создаёт инвойс у выбранного платёжного провайдера."""
    payload = callback.data.replace("buy_", "", 1)
    if payload.startswith("yookassa_"):
        provider = "yookassa"
    elif payload.startswith("crypto_"):
        provider = "cryptobot"
    elif payload.startswith("lava_"):
        provider = "lava"
    elif payload.startswith("stars_"):
        provider = TELEGRAM_STARS_PROVIDER
    else:
        provider = config.payment_provider

    if provider == "lava" and not lava_service.enabled:
        await callback.message.edit_text(
            "Не удалось создать оплату: Lava не настроена.\n"
            "Проверьте переменную окружения <code>LAVA_API_KEY</code>.",
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )
        return

    if provider == "yookassa" and not yookassa_service.enabled:
        await callback.message.edit_text(
            "YooKassa временно недоступна. Попробуйте другой способ оплаты.",
            reply_markup=get_back_keyboard("menu_topup"),
            parse_mode="HTML",
        )
        return

    if provider in ("cryptobot", "cryptopay") and not cryptobot_service.enabled:
        await callback.message.edit_text(
            "CryptoBot временно недоступен. Попробуйте другой способ оплаты.",
            reply_markup=get_back_keyboard("menu_topup"),
            parse_mode="HTML",
        )
        return

    if provider == TELEGRAM_STARS_PROVIDER and not config.TELEGRAM_STARS_ENABLED:
        await callback.message.edit_text(
            "Оплата Telegram Stars временно отключена. Попробуйте другой способ оплаты.",
            reply_markup=get_back_keyboard("menu_topup"),
            parse_mode="HTML",
        )
        return

    payload = callback.data.replace("buy_", "", 1)
    if payload.startswith("yookassa_"):
        package_id = payload.replace("yookassa_", "", 1)
    elif payload.startswith("crypto_"):
        package_id = payload.replace("crypto_", "", 1)
    elif payload.startswith("lava_"):
        package_id = payload.replace("lava_", "", 1)
    elif payload.startswith("stars_"):
        package_id = payload.replace("stars_", "", 1)
    elif "_" in payload:
        package_id = payload.split("_", 1)[1]
    else:
        package_id = payload
    package = preset_manager.get_package(package_id)
    if not package:
        await callback.answer("Пакет не найден", show_alert=True)
        return

    order_id = f"{callback.from_user.id}_{int(time.time() * 1000)}_{package_id}"

    bot_info = await callback.bot.get_me()
    success_url = f"https://t.me/{bot_info.username}?start=success_{order_id}"

    promo = await _get_selected_promo(state)
    package_bonus = package_bonus_credits(package)
    promo_bonus = _promo_bonus_for_package(promo, package)
    total_credits = total_package_credits(package, promo_bonus)
    description = f"Покупка {total_credits} бананов ({package['name']})"

    if provider == TELEGRAM_STARS_PROVIDER:
        stars_amount = package_stars_amount(package)
        invoice_payload = build_stars_invoice_payload(order_id, stars_amount)
        user = await get_or_create_user(callback.from_user.id)
        created = await create_transaction(
            order_id=order_id,
            user_id=user.id,
            payment_id=f"pending:{stars_amount}",
            provider=TELEGRAM_STARS_PROVIDER,
            credits=total_credits,
            amount_rub=float(package["price_rub"]),
            status="pending",
            promo_code_id=promo.id if promo and promo_bonus > 0 else None,
            promo_code=promo.code if promo and promo_bonus > 0 else None,
            promo_bonus_credits=promo_bonus,
        )
        if not created:
            await callback.message.edit_text(
                "Не удалось создать платёж. Попробуйте выбрать пакет ещё раз.",
                reply_markup=get_back_keyboard("menu_topup"),
                parse_mode="HTML",
            )
            return

        try:
            await callback.message.answer_invoice(
                title=f"{package['name']} · {total_credits}🍌",
                description=description,
                payload=invoice_payload,
                currency=TELEGRAM_STARS_CURRENCY,
                prices=[
                    types.LabeledPrice(
                        label=f"{total_credits} бананов",
                        amount=stars_amount,
                    )
                ],
                provider_token="",
            )
        except Exception as exc:
            await update_transaction_status(order_id, "failed")
            logger.exception("Failed to send Telegram Stars invoice order=%s", order_id)
            await callback.message.edit_text(
                "Не удалось открыть оплату Telegram Stars.\n"
                f"Причина: <code>{html.escape(str(exc))}</code>",
                reply_markup=get_back_keyboard("menu_topup"),
                parse_mode="HTML",
            )
            return

        bonus_text = ""
        if package_bonus > 0:
            bonus_text += f"\n• Бонус пакета: <code>{package_bonus}</code> бананов"
        if promo and promo_bonus > 0:
            bonus_text += (
                f"\n• Промокод <code>{promo.code}</code>: +<code>{promo_bonus}</code> бананов"
            )
        elif promo:
            bonus_text += "\n• Промокод применён, но для этой суммы бонуса нет"

        await callback.message.edit_text(
            "⭐ <b>Оплата Telegram Stars</b>\n"
            f"• Пакет: <code>{package['name']}</code>\n"
            f"• Бананов: <code>{total_credits}</code>{bonus_text}\n"
            f"• К оплате: <code>{stars_amount}</code>⭐\n\n"
            "Счёт отправлен отдельным сообщением. После оплаты бананы начислятся автоматически.",
            reply_markup=get_back_keyboard("menu_topup"),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    if provider == "lava":
        offer_id, lava_currency = _package_lava_offer_config(package)
        if not offer_id:
            await callback.message.edit_text(
                "Не удалось создать оплату: для пакета не задан Lava offerId.\n"
                "Добавьте <code>lava_offer_id</code> в <code>data/price.json</code> "
                f"или проверьте переменную окружения <code>LAVA_OFFER_ID_{package_id.upper()}</code>.",
                reply_markup=get_back_keyboard("menu_topup"),
                parse_mode="HTML",
            )
            return

        result = await lava_service.create_invoice(
            email=config.LAVA_DEFAULT_EMAIL,
            offer_id=offer_id,
            currency=lava_currency,
            buyer_language="RU",
            client_utm={
                "telegram_id": str(callback.from_user.id),
                "order_id": order_id,
                "package_id": package_id,
            },
        )
    else:
        if provider == "yookassa":
            if not yookassa_service.enabled:
                await callback.message.edit_text(
                    "Не удалось создать оплату: YooKassa не настроена.\n"
                    "Проверьте переменные окружения YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY.",
                    reply_markup=get_back_keyboard("back_main"),
                    parse_mode="HTML",
                )
                return

            result = await yookassa_service.create_payment(
                amount_rub=float(package["price_rub"]),
                order_id=order_id,
                description=description,
                return_url=success_url,
                notification_url=config.yookassa_notification_url,
            )
        else:
            result = await cryptobot_service.create_invoice(
                amount_rub=float(package["price_rub"]),
                description=description,
                order_id=order_id,
                paid_btn_url=success_url,
            )

    # Normalize success check for different providers
    creation_ok = False
    if provider == "lava":
        creation_ok = bool(result and result.get("ok"))
    elif provider == "yookassa":
        # yookassa_service returns {'Success': True, 'PaymentId': ..., 'PaymentURL': ...}
        creation_ok = bool(
            result and (result.get("Success") or result.get("PaymentId"))
        )
    else:
        creation_ok = bool(result and result.get("ok"))

    if not creation_ok:
        error_msg = (
            (result or {}).get("error")
            or (result or {}).get("message")
            or (result or {}).get("raw")
            or (result or {}).get("Message")
            or "Не удалось создать инвойс"
        )
        await callback.message.edit_text(
            "Не удалось создать платёж.\n" f"Причина: <code>{error_msg}</code>",
            reply_markup=get_back_keyboard("menu_topup"),
            parse_mode="HTML",
        )
        return

    contract_id = None
    if provider == "lava":
        invoice_id = lava_service.extract_invoice_id(result)
        contract_id = lava_service.extract_contract_id(result)
        payment_url = lava_service.extract_payment_url(result)
    elif provider == "yookassa":
        invoice_id = result.get("PaymentId") if result else None
        payment_url = result.get("PaymentURL") if result else None
    else:
        invoice = result.get("result") or {}
        invoice_id = str(invoice.get("invoice_id"))
        payment_url = (
            invoice.get("bot_invoice_url")
            or invoice.get("mini_app_invoice_url")
            or invoice.get("web_app_invoice_url")
        )

    if not invoice_id or not payment_url:
        await callback.message.edit_text(
            f"Не удалось получить ссылку на оплату от {provider}.",
            reply_markup=get_back_keyboard("menu_topup"),
            parse_mode="HTML",
        )
        return

    user = await get_or_create_user(callback.from_user.id)
    await create_transaction(
        order_id=order_id,
        user_id=user.id,
        payment_id=contract_id or str(invoice_id),
        provider=provider,
        credits=total_credits,
        amount_rub=float(package["price_rub"]),
        status="pending",
        promo_code_id=promo.id if promo and promo_bonus > 0 else None,
        promo_code=promo.code if promo and promo_bonus > 0 else None,
        promo_bonus_credits=promo_bonus,
    )

    bonus_text = ""
    if package_bonus > 0:
        bonus_text += f"\n• Бонус пакета: <code>{package_bonus}</code> бананов"
    if promo and promo_bonus > 0:
        bonus_text += (
            f"\n• Промокод <code>{promo.code}</code>: +<code>{promo_bonus}</code> бананов"
        )
    elif promo:
        bonus_text += "\n• Промокод применён, но для этой суммы бонуса нет"

    provider_label = {
        "lava": "Lava",
        "yookassa": "YooKassa (банковская карта)",
        "cryptobot": "CryptoBot (криптовалюта)",
    }.get(provider, provider.capitalize())

    await callback.message.edit_text(
        f"💳 <b>Оплата через {provider_label}</b>\n"
        f"• Пакет: <code>{package['name']}</code>\n"
        f"• Бананов: <code>{total_credits}</code>{bonus_text}\n"
        f"• Сумма: <code>{package['price_rub']}</code> ₽\n\n"
        "Нажмите кнопку ниже и завершите оплату.",
        reply_markup=get_payment_confirmation_keyboard(payment_url, order_id),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("check_payment_"))
async def check_payment_status(callback: types.CallbackQuery):
    """Ручная проверка статуса платежа у текущего провайдера."""
    order_id = callback.data.replace("check_payment_", "")
    transaction = await get_transaction_by_order(order_id)

    if not transaction:
        await callback.answer("Транзакция не найдена", show_alert=True)
        return

    if transaction.status == "completed":
        promo_text = _transaction_promo_text(transaction)
        await callback.message.edit_text(
            "✅ <b>Оплата подтверждена</b>\n"
            f"• Начислено: <code>{transaction.credits}</code> бананов\n"
            f"• Сумма: <code>{transaction.amount_rub}</code> ₽{promo_text}",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML",
        )
        return

    state = await _resolve_payment_state(transaction)
    if state.get("failed"):
        await update_transaction_status(order_id, "failed")
        await callback.answer("Платёж отменён или не прошёл", show_alert=True)
        return

    if not state.get("paid"):
        await callback.answer("Платёж ещё в обработке", show_alert=True)
        return

    result = await _complete_transaction(order_id, bot=callback.bot)
    if not result.get("ok"):
        await callback.answer("Не удалось завершить оплату", show_alert=True)
        return

    if result.get("already_completed"):
        await callback.answer("Оплата уже была зачислена ранее", show_alert=True)
        return

    bonus_text = (
        _build_promo_bonus_text(result.get("promo_bonus") or {})
        + _build_bonus_text(result.get("referral_bonus") or {})
    )
    transaction = result["transaction"]
    await callback.message.edit_text(
        "✅ <b>Оплата подтверждена</b>\n"
        f"• Начислено: <code>{transaction.credits}</code> бананов\n"
        f"• Сумма: <code>{transaction.amount_rub}</code> ₽{bonus_text}",
        reply_markup=get_main_menu_keyboard(),
        parse_mode="HTML",
    )


@router.pre_checkout_query()
async def process_stars_pre_checkout(query: types.PreCheckoutQuery):
    parsed = parse_stars_invoice_payload(query.invoice_payload)
    if not parsed:
        await query.bot.answer_pre_checkout_query(
            query.id,
            ok=False,
            error_message="Некорректный счёт. Создайте оплату заново.",
        )
        return

    order_id, stars_amount = parsed
    transaction = await get_transaction_by_order(order_id)
    if not transaction or transaction.provider != TELEGRAM_STARS_PROVIDER:
        await query.bot.answer_pre_checkout_query(
            query.id,
            ok=False,
            error_message="Транзакция не найдена. Создайте оплату заново.",
        )
        return

    if transaction.status == "completed":
        await query.bot.answer_pre_checkout_query(
            query.id,
            ok=False,
            error_message="Эта оплата уже была обработана.",
        )
        return

    telegram_id = await get_telegram_id_by_user_id(transaction.user_id)
    if telegram_id != query.from_user.id:
        await query.bot.answer_pre_checkout_query(
            query.id,
            ok=False,
            error_message="Этот счёт создан для другого пользователя.",
        )
        return

    if query.currency != TELEGRAM_STARS_CURRENCY or query.total_amount != stars_amount:
        logger.warning(
            "Rejected Stars pre-checkout order=%s currency=%s amount=%s expected=%s",
            order_id,
            query.currency,
            query.total_amount,
            stars_amount,
        )
        await query.bot.answer_pre_checkout_query(
            query.id,
            ok=False,
            error_message="Сумма счёта не совпадает. Создайте оплату заново.",
        )
        return

    await query.bot.answer_pre_checkout_query(query.id, ok=True)


@router.message(F.successful_payment)
async def process_successful_stars_payment(message: types.Message):
    payment = message.successful_payment
    if not payment:
        return

    parsed = parse_stars_invoice_payload(payment.invoice_payload)
    if not parsed or payment.currency != TELEGRAM_STARS_CURRENCY:
        logger.warning(
            "Successful payment with unsupported payload/currency payload=%s currency=%s",
            payment.invoice_payload,
            payment.currency,
        )
        return

    order_id, stars_amount = parsed
    if payment.total_amount != stars_amount:
        logger.warning(
            "Successful Stars payment amount mismatch order=%s amount=%s expected=%s",
            order_id,
            payment.total_amount,
            stars_amount,
        )

    charge_id = payment.telegram_payment_charge_id or f"stars:{order_id}"
    await update_transaction_payment_id(order_id, charge_id)

    result = await _complete_transaction(order_id, bot=message.bot)
    if not result.get("ok"):
        logger.error(
            "Failed to complete successful Stars payment order=%s reason=%s",
            order_id,
            result.get("reason"),
        )
        await message.answer(
            "Оплата Stars прошла, но бананы не начислились автоматически. "
            "Напишите в поддержку, мы проверим транзакцию.",
            reply_markup=get_main_menu_keyboard(),
        )
        return

    if result.get("already_completed"):
        await message.answer(
            "Эта оплата уже была зачислена ранее.",
            reply_markup=get_main_menu_keyboard(),
        )
        return

    bonus_text = (
        _build_promo_bonus_text(result.get("promo_bonus") or {})
        + _build_bonus_text(result.get("referral_bonus") or {})
    )
    transaction = result["transaction"]
    try:
        await create_miniapp_notification(
            transaction.user_id,
            f"✅ Оплата Stars обработана — {transaction.credits} бананов за {stars_amount}⭐",
        )
    except Exception:
        logger.exception("Failed to create miniapp Stars notification order=%s", order_id)

    await message.answer(
        "✅ <b>Оплата Stars подтверждена</b>\n"
        f"• Начислено: <code>{transaction.credits}</code> бананов\n"
        f"• Списано: <code>{stars_amount}</code>⭐{bonus_text}",
        reply_markup=get_main_menu_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "cancel_payment")
async def cancel_payment(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "Платёж отменён. Вы можете попробовать снова в любое время.",
        reply_markup=get_main_menu_keyboard(),
        parse_mode="HTML",
    )


async def handle_cryptobot_webhook(request: web.Request):
    """Webhook updates from Crypto Pay API."""
    try:
        raw_body = await request.read()
        if not raw_body:
            return web.Response(status=200)

        signature = request.headers.get("crypto-pay-api-signature", "")
        if not cryptobot_service.enabled:
            logger.warning("Rejected CryptoBot webhook: service is disabled")
            return web.Response(status=403)
        if not cryptobot_service.verify_webhook_signature(raw_body, signature):
            logger.warning("Invalid CryptoBot webhook signature")
            return web.Response(status=403)

        try:
            data = json.loads(raw_body.decode("utf-8"))
        except Exception:
            return web.Response(status=200)

        if data.get("update_type") != "invoice_paid":
            return web.Response(status=200)

        invoice = data.get("payload") or {}
        if (invoice.get("status") or "") != "paid":
            return web.Response(status=200)

        order_id = invoice.get("payload")
        if not order_id:
            logger.warning("CryptoBot webhook has no invoice payload order_id")
            return web.Response(status=200)

        transaction = await get_transaction_by_order(order_id)
        if not transaction:
            return web.Response(status=200)
        invoice_id = str(invoice.get("invoice_id") or invoice.get("id") or "")
        if invoice_id and str(transaction.payment_id or "") != invoice_id:
            logger.warning(
                "CryptoBot webhook invoice mismatch order=%s invoice_id=%s",
                order_id,
                invoice_id,
            )
            return web.Response(status=200)

        telegram_id = await get_telegram_id_by_user_id(transaction.user_id)
        if not telegram_id:
            logger.warning(
                "Cannot resolve telegram_id for user_id=%s", transaction.user_id
            )
            return web.Response(status=200)

        # Атомарное завершение — защита от двойного начисления при повторных вебхуках
        completion = await _complete_transaction(order_id, bot=request.app.get("bot"))
        if completion.get("already_completed"):
            logger.info("CryptoBot webhook: order %s already processed, skipping", order_id)
            return web.Response(status=200)
        if not completion.get("ok"):
            logger.error("CryptoBot webhook: failed to complete order %s reason=%s", order_id, completion.get("reason"))
            return web.Response(status=200)

        transaction = completion["transaction"]
        referral_bonus = completion.get("referral_bonus") or {}
        promo_bonus = completion.get("promo_bonus") or {}

        bonus_text = _build_promo_bonus_text(promo_bonus) + _build_bonus_text(
            referral_bonus
        )

        try:
            await _notify_user(
                request.app["bot"],
                telegram_id,
                "✅ <b>Оплата успешно обработана</b>\n"
                f"• Начислено: <code>{transaction.credits}</code> бананов\n"
                f"• Сумма: <code>{transaction.amount_rub}</code> ₽{bonus_text}",
                parse_mode="HTML",
            )
        except TelegramBadRequest as e:
            if _is_ignored_telegram_error(e):
                logger.warning(
                    "Skipping CryptoBot notification for user %s: %s", telegram_id, e
                )
            else:
                logger.error("Failed to notify user %s: %s", telegram_id, e)

        # Создаём уведомление для мини‑аппа (чтобы UI показал результат при следующем bootstrap)
        try:
            note = (
                f"✅ Оплата успешно обработана — {transaction.credits} бананов "
                f"за {transaction.amount_rub} ₽"
            )
            if promo_bonus:
                note += f" (промокод +{promo_bonus['bonus_credits']}🍌)"
            await create_miniapp_notification(transaction.user_id, note)
        except Exception:
            logger.exception(
                "Failed to create miniapp notification for order %s", order_id
            )

        return web.Response(status=200)

    except Exception as e:
        logger.exception("Error processing CryptoBot webhook: %s", e)
        return web.Response(status=200)


async def _resolve_lava_provider_status(transaction, contract_id: str | None) -> str:
    payment_id = str(getattr(transaction, "payment_id", "") or "")
    if contract_id:
        # Пробуем contractId (основной), затем payment_id из БД
        invoice = await lava_service.get_invoice(contract_id)
        if invoice:
            return lava_service.webhook_status(invoice) or str(invoice.get("status") or "").lower()
    if payment_id and payment_id != contract_id:
        invoice = await lava_service.get_invoice(payment_id)
        if invoice:
            return lava_service.webhook_status(invoice) or str(invoice.get("status") or "").lower()
    return ""


async def handle_lava_webhook(request: web.Request):
    """Webhook updates from Lava.top."""
    try:
        raw_body = await request.read()
        if not raw_body:
            return web.Response(status=200)

        logger.info(
            "Lava webhook raw headers: %s raw_body: %s",
            dict(request.headers),
            raw_body[:500] if raw_body else "empty",
        )
        try:
            data = json.loads(raw_body.decode("utf-8"))
        except Exception:
            logger.warning("Lava webhook received invalid JSON")
            return web.Response(status=200)

        logger.info(
            "Lava webhook parsed event_type=%s status=%s data=%s",
            lava_service.webhook_event_type(data) or "unknown",
            lava_service.webhook_status(data) or "unknown",
            json.dumps(data)[:1000],
        )

        if not (
            lava_service.is_success_webhook(data)
            or lava_service.is_failed_webhook(data)
        ):
            logger.info(
                "Lava webhook ignored: not success/failed event event_type=%s status=%s",
                lava_service.webhook_event_type(data) or "unknown",
                lava_service.webhook_status(data) or "unknown",
            )
            return web.Response(status=200)

        contract_id = lava_service.webhook_contract_id(data)
        order_id = _extract_first(data, ("order_id", "orderId"))
        logger.info(
            "Lava webhook received event=%s status=%s order_id=%s contract_id=%s",
            lava_service.webhook_event_type(data) or "unknown",
            lava_service.webhook_status(data) or "unknown",
            order_id or "",
            contract_id or "",
        )

        if order_id:
            transaction = await get_transaction_by_order(str(order_id))
            if transaction and transaction.provider != "lava":
                transaction = None
        else:
            transaction = None

        if not transaction and contract_id:
            async with db_backend.connect() as db:
                db.row_factory = db_backend.Row
                cursor = await db.execute(
                    "SELECT order_id FROM transactions WHERE payment_id = ? AND provider = ? LIMIT 1",
                    (contract_id, "lava"),
                )
                row = await cursor.fetchone()

            if row:
                order_id = row["order_id"]
                transaction = await get_transaction_by_order(order_id)

        if not transaction:
            logger.warning(
                "Lava transaction not found for order_id=%s contract_id=%s",
                order_id,
                contract_id,
            )
            return web.Response(status=200)

        order_id = transaction.order_id
        provider_status = await _resolve_lava_provider_status(transaction, contract_id)
        if not provider_status:
            logger.warning(
                "Lava webhook ignored: cannot verify provider status order=%s contract_id=%s",
                order_id,
                contract_id,
            )
            return web.Response(status=200)

        if lava_service.is_failed_webhook(data):
            if provider_status in {"cancelled", "canceled", "failed", "expired"} and await update_transaction_status(order_id, "failed"):
                logger.info("Lava webhook marked order %s as failed", order_id)
            else:
                logger.info(
                    "Lava failed webhook ignored after provider check order=%s provider_status=%s",
                    order_id,
                    provider_status,
                )
            return web.Response(status=200)

        if provider_status != "completed":
            logger.info(
                "Lava success webhook ignored until provider status is completed order=%s provider_status=%s",
                order_id,
                provider_status,
            )
            return web.Response(status=200)

        telegram_id = await get_telegram_id_by_user_id(transaction.user_id)
        if not telegram_id:
            logger.warning(
                "Cannot resolve telegram_id for user_id=%s", transaction.user_id
            )
            return web.Response(status=200)

        # Атомарное завершение — защита от двойного начисления при повторных вебхуках
        completion = await _complete_transaction(order_id, bot=request.app.get("bot"))
        if completion.get("already_completed"):
            logger.info("Lava webhook: order %s already processed, skipping", order_id)
            return web.Response(status=200)
        if not completion.get("ok"):
            logger.error("Lava webhook: failed to complete order %s reason=%s", order_id, completion.get("reason"))
            return web.Response(status=200)

        transaction = completion["transaction"]
        referral_bonus = completion.get("referral_bonus") or {}
        promo_bonus = completion.get("promo_bonus") or {}

        bonus_text = _build_promo_bonus_text(promo_bonus) + _build_bonus_text(
            referral_bonus
        )

        try:
            await _notify_user(
                request.app["bot"],
                telegram_id,
                "✅ <b>Оплата успешно обработана</b>\n"
                f"• Начислено: <code>{transaction.credits}</code> бананов\n"
                f"• Сумма: <code>{transaction.amount_rub}</code> ₽{bonus_text}",
                parse_mode="HTML",
            )
        except TelegramBadRequest as e:
            if _is_ignored_telegram_error(e):
                logger.warning(
                    "Skipping Lava notification for user %s: %s", telegram_id, e
                )
            else:
                logger.error("Failed to notify user %s: %s", telegram_id, e)

        return web.Response(status=200)

    except Exception as e:
        logger.exception("Error processing Lava webhook: %s", e)
        return web.Response(status=200)


async def handle_yookassa_webhook(request: web.Request):
    """Webhook updates from YooKassa."""
    try:
        raw_body = await request.read()
        if not raw_body:
            return web.Response(status=200)

        # Validate webhook signature if configured
        try:
            secret = config.YOOKASSA_WEBHOOK_SECRET
            if secret:
                import base64
                import hashlib
                import hmac

                verified = False
                # Common header names YooKassa might send
                candidate_headers = [
                    request.headers.get("X-Webhook-Signature"),
                    request.headers.get("X-Checkout-Signature"),
                    request.headers.get("X-Signature"),
                ]
                # Compute HMAC-SHA256
                digest = hmac.new(secret.encode(), raw_body, hashlib.sha256)
                hex_expected = digest.hexdigest()
                b64_expected = base64.b64encode(digest.digest()).decode()

                for hdr in candidate_headers:
                    if not hdr:
                        continue
                    if hmac.compare_digest(hdr, hex_expected) or hmac.compare_digest(
                        hdr, b64_expected
                    ):
                        verified = True
                        break

                if not verified:
                    logger.warning(
                        "Rejected YooKassa webhook: invalid signature header_names=%s",
                        [
                            k
                            for k in request.headers.keys()
                            if "yookassa" in k.lower() or "signature" in k.lower()
                        ],
                    )
                    return web.Response(status=200)
        except Exception:
            logger.exception("Error while validating YooKassa webhook signature")
            return web.Response(status=200)

        try:
            data = json.loads(raw_body.decode("utf-8"))
        except Exception:
            logger.warning("YooKassa webhook received invalid JSON")
            return web.Response(status=200)

        # Try to extract payment id from common YooKassa payload shapes
        payment_id = None
        obj = data.get("object") or {}
        if isinstance(obj, dict):
            payment_id = obj.get("id") or _extract_first(obj, ["id", "payment_id"])

        # Fallback: sometimes payload wraps payment under 'payment'
        if not payment_id:
            payment_id = _extract_first(data, ["payment_id", "id"])  # recursive search

        if not payment_id:
            logger.warning("YooKassa webhook: no payment id found in payload")
            return web.Response(status=200)

        # Fetch payment details from YooKassa SDK
        payment = await yookassa_service.get_payment(payment_id)
        if not payment:
            return web.Response(status=200)

        # Try to resolve order_id from metadata, else lookup by payment_id in DB
        order_id = yookassa_service.extract_order_id(
            payment.get("Raw")
            if isinstance(payment.get("Raw"), dict)
            else payment.get("Raw", {})
        )
        if not order_id:
            # DB lookup by payment_id

            async with db_backend.connect() as db_conn:
                db_conn.row_factory = db_backend.Row
                cursor = await db_conn.execute(
                    "SELECT order_id FROM transactions WHERE payment_id = ? AND provider = ? LIMIT 1",
                    (payment_id, "yookassa"),
                )
                row = await cursor.fetchone()
                if row:
                    order_id = row["order_id"]

        if not order_id:
            logger.warning(
                "YooKassa webhook: cannot resolve order_id for payment %s", payment_id
            )
            return web.Response(status=200)

        transaction = await get_transaction_by_order(order_id)
        if not transaction:
            return web.Response(status=200)

        telegram_id = await get_telegram_id_by_user_id(transaction.user_id)
        if not telegram_id:
            logger.warning(
                "Cannot resolve telegram_id for user_id=%s", transaction.user_id
            )
            return web.Response(status=200)

        paid = bool(payment.get("paid")) or (payment.get("status") or "").lower() in (
            "succeeded",
            "paid",
            "captured",
        )

        if not paid:
            return web.Response(status=200)

        # Атомарное завершение — защита от двойного начисления при повторных вебхуках
        completion = await _complete_transaction(order_id, bot=request.app.get("bot"))
        if completion.get("already_completed"):
            logger.info("YooKassa webhook: order %s already processed, skipping", order_id)
            return web.Response(status=200)
        if not completion.get("ok"):
            logger.error("YooKassa webhook: failed to complete order %s reason=%s", order_id, completion.get("reason"))
            return web.Response(status=200)

        transaction = completion["transaction"]
        referral_bonus = completion.get("referral_bonus") or {}
        promo_bonus = completion.get("promo_bonus") or {}

        bonus_text = _build_promo_bonus_text(promo_bonus) + _build_bonus_text(
            referral_bonus
        )

        try:
            await _notify_user(
                request.app["bot"],
                telegram_id,
                "✅ <b>Оплата успешно обработана</b>\n"
                f"• Начислено: <code>{transaction.credits}</code> бананов\n"
                f"• Сумма: <code>{transaction.amount_rub}</code> ₽{bonus_text}",
                parse_mode="HTML",
            )
        except TelegramBadRequest as e:
            if _is_ignored_telegram_error(e):
                logger.warning(
                    "Skipping YooKassa notification for user %s: %s", telegram_id, e
                )
            else:
                logger.error("Failed to notify user %s: %s", telegram_id, e)

        return web.Response(status=200)

    except Exception as e:
        logger.exception("Error processing YooKassa webhook: %s", e)
        return web.Response(status=200)
