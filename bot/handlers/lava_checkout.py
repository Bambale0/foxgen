from __future__ import annotations

import html
import logging
import re
import time
from email.utils import parseaddr
from typing import Any

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import config
from bot.database import create_transaction, get_or_create_user
from bot.handlers.payments import (
    _get_selected_promo,
    _package_lava_offer_config,
    _promo_bonus_for_package,
)
from bot.keyboards import get_back_keyboard, get_payment_confirmation_keyboard
from bot.payment_utils import (
    package_bonus_credits,
    package_stars_amount,
    total_package_credits,
)
from bot.services.cryptobot_service import cryptobot_service
from bot.services.freekassa_service import freekassa_service
from bot.services.lava_service import lava_service
from bot.services.preset_manager import preset_manager
from bot.services.yookassa_service import yookassa_service
from bot.states import PaymentStates

logger = logging.getLogger(__name__)
router = Router()

LAVA_CHECKOUT_SBP = "sbp"
LAVA_CHECKOUT_CARD = "card"

LAVA_RUB_SBP_PAYMENT_PROVIDER = "PAY2ME"
LAVA_RUB_SBP_PAYMENT_METHOD = "SBP"
LAVA_RUB_CARD_PAYMENT_METHOD = "CARD"

# Backward-compatible names used by existing tests and integrations.
LAVA_RUB_PAYMENT_PROVIDER = LAVA_RUB_SBP_PAYMENT_PROVIDER
LAVA_RUB_PAYMENT_METHOD = LAVA_RUB_SBP_PAYMENT_METHOD

_EMAIL_LOCAL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+$")
_EMAIL_DOMAIN_LABEL_RE = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)
_EMAIL_IGNORED_CHARACTERS = str.maketrans(
    "",
    "",
    "\u200b\u200c\u200d\u2060\ufeff",
)
_BLOCKED_EMAIL_DOMAINS = {
    "example.com",
    "example.net",
    "example.org",
    "localhost",
    "invalid",
}
_BLOCKED_EMAILS = {
    "buyer@example.com",
    "client@example.com",
    "test@example.com",
}


def _extract_email_candidate(value: Any) -> str:
    raw = str(value or "").translate(_EMAIL_IGNORED_CHARACTERS).strip()
    if raw.lower().startswith("mailto:"):
        raw = raw[7:].strip()

    _, parsed_address = parseaddr(raw)
    if parsed_address and "@" in parsed_address:
        raw = parsed_address

    return raw.strip().strip("<>").strip().lower()


def normalize_lava_customer_email(value: Any) -> str | None:
    """Normalize a real buyer email without rejecting addresses with digits."""

    email = _extract_email_candidate(value)
    if not email or len(email) > 254 or email.count("@") != 1:
        return None

    local_part, domain = email.rsplit("@", 1)
    if (
        not local_part
        or len(local_part) > 64
        or local_part.startswith(".")
        or local_part.endswith(".")
        or ".." in local_part
        or not _EMAIL_LOCAL_RE.fullmatch(local_part)
    ):
        return None

    try:
        ascii_domain = domain.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None

    if (
        not ascii_domain
        or len(ascii_domain) > 253
        or "." not in ascii_domain
        or ascii_domain.startswith(".")
        or ascii_domain.endswith(".")
        or ".." in ascii_domain
    ):
        return None

    labels = ascii_domain.split(".")
    if any(
        len(label) > 63 or not _EMAIL_DOMAIN_LABEL_RE.fullmatch(label)
        for label in labels
    ):
        return None

    normalized = f"{local_part}@{ascii_domain}"
    if normalized in _BLOCKED_EMAILS:
        return None
    if ascii_domain in _BLOCKED_EMAIL_DOMAINS or ascii_domain.endswith(".invalid"):
        return None
    return normalized


def parse_lava_checkout_callback(value: Any) -> tuple[str, str]:
    """Return checkout mode and package ID from current and legacy callbacks."""

    payload = str(value or "").removeprefix("buy_lava_")
    for mode in (LAVA_CHECKOUT_SBP, LAVA_CHECKOUT_CARD):
        prefix = f"{mode}_"
        if payload.startswith(prefix):
            return mode, payload.removeprefix(prefix)

    # Old already-sent buttons used buy_lava_<package>. Keep them working without
    # restoring the removed intermediate provider screen.
    return LAVA_CHECKOUT_SBP, payload


def _lava_checkout_params(mode: str) -> tuple[str | None, str, str]:
    if mode == LAVA_CHECKOUT_CARD:
        return None, LAVA_RUB_CARD_PAYMENT_METHOD, "Картой"
    return (
        LAVA_RUB_SBP_PAYMENT_PROVIDER,
        LAVA_RUB_SBP_PAYMENT_METHOD,
        "СБП",
    )


def _payment_options_keyboard(
    package_id: str,
    *,
    stars: bool,
    direct_rub: bool,
    crypto: bool,
    freekassa: bool,
    yookassa: bool,
    eur: bool,
) -> types.InlineKeyboardMarkup:
    """Show every enabled payment method as an independent option."""

    builder = InlineKeyboardBuilder()
    if yookassa:
        builder.button(
            text="💳 ЮKassa · ₽ / СБП",
            callback_data=f"buy_yookassa_{package_id}",
        )
    if eur:
        builder.button(
            text="💶 EUR",
            callback_data=f"buy_eur_{package_id}",
        )
    if freekassa:
        builder.button(
            text="🇷🇺 РФ — KASSA (резерв)",
            callback_data=f"buy_freekassa_{package_id}",
        )
    if direct_rub:
        builder.button(
            text="💳 Картой",
            callback_data=f"buy_lava_card_{package_id}",
        )
        builder.button(
            text="⚡ СБП",
            callback_data=f"buy_lava_sbp_{package_id}",
        )
    if stars:
        builder.button(
            text="⭐ Stars",
            callback_data=f"buy_stars_{package_id}",
        )
    if crypto:
        builder.button(
            text="₿ Криптовалюта",
            callback_data=f"buy_crypto_{package_id}",
        )
    builder.button(text="◀️ Назад", callback_data="menu_topup")
    builder.adjust(1)
    return builder.as_markup()


def _email_request_keyboard() -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отменить оплату", callback_data="cancel_lava_email")
    return builder.as_markup()


def _format_lava_error(response: dict[str, Any] | None) -> str:
    """Return a compact provider error for server logs only."""

    data = response or {}
    error = data.get("error") or data.get("message") or data.get("raw")
    if isinstance(error, dict):
        error = error.get("message") or error.get("error") or str(error)
    return str(error or "payment provider did not create an invoice")[:700]


def _validate_lava_package(package_id: str) -> tuple[dict[str, Any] | None, str | None]:
    package = preset_manager.get_package(package_id)
    if not package:
        return None, "Пакет не найден."

    offer_id, currency = _package_lava_offer_config(package)
    if not offer_id:
        return None, "Этот способ оплаты пока недоступен для выбранного пакета."
    if str(currency or "").upper() != "RUB":
        logger.error(
            "Blocked non-RUB Lava checkout: package=%s currency=%s",
            package_id,
            currency,
        )
        return None, "Этот способ оплаты пока недоступен для выбранного пакета."
    return package, None


def _checkout_title(mode: str) -> str:
    if mode == LAVA_CHECKOUT_CARD:
        return "💳 <b>Оплата картой</b>"
    return "⚡ <b>Оплата по СБП</b>"


@router.callback_query(F.data.startswith("choose_pay_"))
async def show_direct_payment_methods(
    callback: types.CallbackQuery,
    state: FSMContext,
) -> None:
    """Render one flat payment-method list before legacy provider handlers."""

    package_id = callback.data.replace("choose_pay_", "", 1)
    package = preset_manager.get_package(package_id)
    if not package:
        await callback.answer("Пакет не найден", show_alert=True)
        return

    lava_offer_id, lava_currency = _package_lava_offer_config(package)
    has_direct_rub = bool(
        lava_service.enabled
        and lava_offer_id
        and str(lava_currency or "").upper() == "RUB"
    )
    has_freekassa = bool(freekassa_service.enabled)
    has_yookassa = bool(yookassa_service.enabled)
    has_eur = bool(lava_service.enabled and lava_offer_id)
    has_stars = bool(config.TELEGRAM_STARS_ENABLED)
    has_crypto = bool(cryptobot_service.enabled)

    if not any(
        (
            has_direct_rub,
            has_freekassa,
            has_yookassa,
            has_eur,
            has_stars,
            has_crypto,
        )
    ):
        await callback.message.edit_text(
            "❌ Способы оплаты временно недоступны. Обратитесь в поддержку.",
            reply_markup=get_back_keyboard("menu_topup"),
        )
        await callback.answer()
        return

    promo = await _get_selected_promo(state)
    package_bonus = package_bonus_credits(package)
    promo_bonus = _promo_bonus_for_package(promo, package)
    total_credits = total_package_credits(package, promo_bonus)

    bonus_lines: list[str] = []
    if package_bonus > 0:
        bonus_lines.append(f"Бонус пакета: <code>{package_bonus}</code>🍌")
    if promo_bonus > 0 and promo:
        bonus_lines.append(
            f"Промокод <code>{html.escape(promo.code)}</code>: "
            f"+<code>{promo_bonus}</code>🍌"
        )
    bonus_text = ("\n" + "\n".join(bonus_lines)) if bonus_lines else ""

    amount_parts = [f"<code>{package['price_rub']}</code>₽"]
    if has_stars:
        amount_parts.append(f"<code>{package_stars_amount(package)}</code>⭐")

    await callback.message.edit_text(
        "💳 <b>Выберите способ оплаты</b>\n\n"
        f"Пакет: <b>{html.escape(str(package['name']))}</b>\n"
        f"Бананы: <code>{total_credits}</code>🍌\n"
        f"Сумма: {' / '.join(amount_parts)}{bonus_text}",
        reply_markup=_payment_options_keyboard(
            package_id,
            stars=has_stars,
            direct_rub=has_direct_rub,
            crypto=has_crypto,
            freekassa=has_freekassa,
            yookassa=has_yookassa,
            eur=has_eur,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("buy_eur_"))
async def handle_eur_checkout(
    callback: types.CallbackQuery, state: FSMContext
) -> None:
    """Create a Lava EUR invoice for any package with a configured Lava offer."""
    package_id = callback.data.replace("buy_eur_", "", 1)
    package = preset_manager.get_package(package_id)
    if not package:
        await callback.answer("Пакет не найден", show_alert=True)
        return

    offer_id, _ = _package_lava_offer_config(package)
    if not lava_service.enabled or not offer_id:
        await callback.message.edit_text(
            "💶 EUR сейчас недоступен для этого пакета. "
            "Выберите другой способ оплаты.",
            reply_markup=get_back_keyboard("menu_topup"),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    promo = await _get_selected_promo(state)
    package_bonus = package_bonus_credits(package)
    promo_bonus = _promo_bonus_for_package(promo, package)
    total_credits = total_package_credits(package, promo_bonus)
    order_id = f"{callback.from_user.id}_{int(time.time() * 1000)}_{package_id}"

    result = await lava_service.create_invoice(
        email=config.LAVA_DEFAULT_EMAIL,
        offer_id=offer_id,
        currency="EUR",
        buyer_language="RU",
        client_utm={
            "telegram_id": str(callback.from_user.id),
            "order_id": order_id,
            "package_id": package_id,
            "payment_mode": "eur",
        },
    )
    if not result.get("ok"):
        logger.error(
            "Lava EUR invoice creation failed: user=%s package=%s status=%s error=%s",
            callback.from_user.id,
            package_id,
            result.get("status"),
            _format_lava_error(result),
        )
        await callback.message.edit_text(
            "Не удалось создать оплату в EUR. Попробуйте ещё раз или выберите другой способ.",
            reply_markup=get_back_keyboard("menu_topup"),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    invoice_id = lava_service.extract_invoice_id(result)
    contract_id = lava_service.extract_contract_id(result)
    payment_url = lava_service.extract_payment_url(result)
    if not invoice_id or not payment_url:
        await callback.message.edit_text(
            "Не удалось получить ссылку на оплату в EUR. Выберите другой способ.",
            reply_markup=get_back_keyboard("menu_topup"),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    user = await get_or_create_user(callback.from_user.id)
    payment_id = contract_id or str(invoice_id)
    created = await create_transaction(
        order_id=order_id,
        user_id=user.id,
        payment_id=payment_id,
        provider="lava",
        credits=total_credits,
        amount_rub=float(package["price_rub"]),
        status="pending",
        promo_code_id=promo.id if promo and promo_bonus > 0 else None,
        promo_code=promo.code if promo and promo_bonus > 0 else None,
        promo_bonus_credits=promo_bonus,
    )
    if not created:
        await callback.message.edit_text(
            "Платёж создан, но бот не смог сохранить заказ. "
            "Не оплачивайте эту ссылку и выберите пакет заново.",
            reply_markup=get_back_keyboard("menu_topup"),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        "💶 <b>Оплата банковской картой (EUR, Lava)</b>\n"
        f"• Пакет: <code>{html.escape(str(package['name']))}</code>\n"
        f"• Бананов: <code>{total_credits}</code>🍌\n"
        f"• Сумма: <code>{package['price_rub']}</code> ₽ / EUR\n\n"
        "Нажмите кнопку ниже и завершите оплату.",
        reply_markup=get_payment_confirmation_keyboard(payment_url, order_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("buy_lava_"))
async def handle_lava_checkout_entry(
    callback: types.CallbackQuery,
    state: FSMContext,
) -> None:
    """Collect the buyer email for the selected card or SBP method."""

    if not lava_service.enabled:
        await callback.message.edit_text(
            "Этот способ оплаты временно недоступен. Выберите другой.",
            reply_markup=get_back_keyboard("menu_topup"),
        )
        await callback.answer()
        return

    mode, package_id = parse_lava_checkout_callback(callback.data)
    _, error = _validate_lava_package(package_id)
    if error:
        await callback.message.edit_text(
            f"{error} Выберите другой способ оплаты или напишите в поддержку.",
            reply_markup=get_back_keyboard("menu_topup"),
        )
        await callback.answer()
        return

    _, _, method_label = _lava_checkout_params(mode)
    await state.update_data(
        lava_checkout_package_id=package_id,
        lava_checkout_mode=mode,
    )
    await state.set_state(PaymentStates.waiting_lava_email)
    await callback.message.edit_text(
        "📧 <b>Введите электронную почту</b>\n\n"
        f"Способ оплаты: <b>{method_label}</b>\n\n"
        "Почта нужна для оформления платежа и уведомления об оплате.\n\n"
        "Пример: <code>name2026@gmail.com</code>\n"
        "Цифры в адресе разрешены. Не вводите чужую или тестовую почту.",
        reply_markup=_email_request_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "cancel_lava_email")
async def cancel_lava_email(
    callback: types.CallbackQuery,
    state: FSMContext,
) -> None:
    await state.clear()
    await callback.message.edit_text(
        "Оплата отменена.",
        reply_markup=get_back_keyboard("menu_topup"),
    )
    await callback.answer()


@router.message(PaymentStates.waiting_lava_email, F.text)
async def create_lava_checkout(
    message: types.Message,
    state: FSMContext,
) -> None:
    email = normalize_lava_customer_email(message.text)
    if not email:
        await message.answer(
            "Не получилось распознать реальную почту.\n"
            "Введите адрес в формате <code>name2026@gmail.com</code>. "
            "Цифры разрешены; тестовые адреса вроде "
            "<code>buyer@example.com</code> запрещены.",
            reply_markup=_email_request_keyboard(),
            parse_mode="HTML",
        )
        return

    state_data = await state.get_data()
    package_id = str(state_data.get("lava_checkout_package_id") or "").strip()
    mode = str(state_data.get("lava_checkout_mode") or LAVA_CHECKOUT_SBP).strip()
    package, error = _validate_lava_package(package_id)
    if error:
        await state.clear()
        await message.answer(
            f"{error} Выберите пакет заново или обратитесь в поддержку.",
            reply_markup=get_back_keyboard("menu_topup"),
        )
        return

    offer_id, _ = _package_lava_offer_config(package)
    payment_provider, payment_method, method_label = _lava_checkout_params(mode)

    promo = await _get_selected_promo(state)
    package_bonus = package_bonus_credits(package)
    promo_bonus = _promo_bonus_for_package(promo, package)
    total_credits = total_package_credits(package, promo_bonus)
    order_id = f"{message.from_user.id}_{int(time.time() * 1000)}_{package_id}"

    result = await lava_service.create_invoice(
        email=email,
        offer_id=offer_id,
        currency="RUB",
        payment_provider=payment_provider,
        payment_method=payment_method,
        buyer_language="RU",
        client_utm={
            "telegram_id": str(message.from_user.id),
            "order_id": order_id,
            "package_id": package_id,
            "payment_mode": mode,
        },
    )
    if not result.get("ok"):
        await state.clear()
        logger.error(
            "Lava RUB/%s invoice creation failed: user=%s package=%s status=%s error=%s",
            payment_method,
            message.from_user.id,
            package_id,
            result.get("status"),
            _format_lava_error(result),
        )
        await message.answer(
            f"Не удалось создать оплату ({method_label}). "
            "Попробуйте ещё раз или выберите другой способ.",
            reply_markup=get_back_keyboard("menu_topup"),
        )
        return

    invoice_id = lava_service.extract_invoice_id(result)
    contract_id = lava_service.extract_contract_id(result)
    payment_url = lava_service.extract_payment_url(result)
    if not invoice_id or not payment_url:
        await state.clear()
        logger.error(
            "Lava response has no invoice URL: user=%s package=%s method=%s",
            message.from_user.id,
            package_id,
            payment_method,
        )
        await message.answer(
            "Не удалось получить ссылку на оплату. Выберите другой способ.",
            reply_markup=get_back_keyboard("menu_topup"),
        )
        return

    user = await get_or_create_user(message.from_user.id)
    payment_id = contract_id or str(invoice_id)
    created = await create_transaction(
        order_id=order_id,
        user_id=user.id,
        payment_id=payment_id,
        provider="lava",
        credits=total_credits,
        amount_rub=float(package["price_rub"]),
        status="pending",
        promo_code_id=promo.id if promo and promo_bonus > 0 else None,
        promo_code=promo.code if promo and promo_bonus > 0 else None,
        promo_bonus_credits=promo_bonus,
    )
    if not created:
        await state.clear()
        await message.answer(
            "Платёж создан, но бот не смог сохранить заказ. "
            "Не оплачивайте эту ссылку и выберите пакет заново.",
            reply_markup=get_back_keyboard("menu_topup"),
        )
        return

    await state.clear()
    bonus_lines: list[str] = []
    if package_bonus > 0:
        bonus_lines.append(f"Бонус пакета: <code>{package_bonus}</code> бананов")
    if promo and promo_bonus > 0:
        bonus_lines.append(
            f"Промокод <code>{html.escape(promo.code)}</code>: "
            f"+<code>{promo_bonus}</code> бананов"
        )
    bonus_text = "\n" + "\n".join(bonus_lines) if bonus_lines else ""

    await message.answer(
        f"{_checkout_title(mode)}\n"
        f"• Пакет: <code>{html.escape(str(package['name']))}</code>\n"
        f"• Бананов: <code>{total_credits}</code>{bonus_text}\n"
        f"• Сумма: <code>{package['price_rub']}</code> ₽\n"
        f"• Почта: <code>{html.escape(email)}</code>\n\n"
        "Проверьте данные и перейдите к оплате.",
        reply_markup=get_payment_confirmation_keyboard(payment_url, order_id),
        parse_mode="HTML",
    )


@router.message(PaymentStates.waiting_lava_email)
async def reject_non_text_lava_email(message: types.Message) -> None:
    await message.answer(
        "Отправьте электронную почту обычным текстовым сообщением.",
        reply_markup=_email_request_keyboard(),
    )
