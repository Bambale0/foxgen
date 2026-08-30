from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.channel_link import ChannelLinkError, consume_channel_link_token
from bot.database import get_or_create_user
from bot.handlers.payments import _package_lava_offer_config
from bot.services.lava_service import lava_service
from bot.services.preset_manager import preset_manager
from bot.services.yookassa_service import yookassa_service

router = Router()
_START_LINK_RE = re.compile(
    r"^/start(?:@[A-Za-z0-9_]+)?\s+iglink_([A-Za-z0-9_-]{8,64})$"
)
_INSTAGRAM_PAYMENT_PROVIDERS = {"yookassa", "lava"}


def extract_link_token(text: str | None) -> str:
    match = _START_LINK_RE.fullmatch(str(text or "").strip())
    return match.group(1) if match else ""


def _link_error_text(error: ChannelLinkError) -> str:
    if error.code == "expired":
        return (
            "Ссылка на привязку Instagram уже истекла.\n\n"
            "Вернитесь в Direct HappyFox и запросите новую ссылку."
        )
    if error.code == "used":
        return (
            "Эта ссылка уже использована.\n\n"
            "Если Instagram ещё не привязан, запросите новую ссылку в Direct."
        )
    if error.code == "conflict":
        return (
            "Этот Instagram уже привязан к другому аккаунту HappyFox.\n\n"
            "Для смены аккаунта обратитесь в поддержку."
        )
    return (
        "Не получилось подтвердить привязку Instagram.\n\n"
        "Запросите новую ссылку в Direct HappyFox и попробуйте ещё раз."
    )


def get_instagram_topup_provider_keyboard() -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💳 ЮKassa", callback_data="instagram_topup_yookassa")
    builder.button(text="🔥 Lava Top", callback_data="instagram_topup_lava")
    builder.adjust(1)
    return builder.as_markup()


def _package_button_label(package: dict[str, Any]) -> str:
    name = str(package.get("name") or package.get("id") or "Пакет").strip()
    credits = package.get("credits")
    price_rub = package.get("price_rub")
    return f"{name} · {credits} 🐾 · {price_rub} ₽"


def get_instagram_provider_packages_keyboard(
    provider: str,
    packages: Iterable[dict[str, Any]],
) -> types.InlineKeyboardMarkup:
    provider_key = str(provider or "").strip().lower()
    if provider_key not in _INSTAGRAM_PAYMENT_PROVIDERS:
        raise ValueError(f"Unsupported Instagram payment provider: {provider_key}")

    builder = InlineKeyboardBuilder()
    for package in packages:
        package_id = str(package.get("id") or "").strip()
        if not package_id:
            continue
        if provider_key == "yookassa":
            callback_data = f"buy_yookassa_{package_id}"
        else:
            callback_data = f"instagram_topup_lava_package_{package_id}"
        builder.button(
            text=_package_button_label(package),
            callback_data=callback_data,
        )
    builder.button(
        text="◀️ Способы оплаты",
        callback_data="instagram_topup_providers",
    )
    builder.adjust(1)
    return builder.as_markup()


def get_instagram_lava_method_keyboard(package_id: str) -> types.InlineKeyboardMarkup:
    normalized_package_id = str(package_id or "").strip()
    if not normalized_package_id:
        raise ValueError("package_id is required")

    builder = InlineKeyboardBuilder()
    builder.button(
        text="💳 Картой через Lava Top",
        callback_data=f"buy_lava_card_{normalized_package_id}",
    )
    builder.button(
        text="⚡ СБП через Lava Top",
        callback_data=f"buy_lava_sbp_{normalized_package_id}",
    )
    builder.button(
        text="◀️ Пакеты Lava Top",
        callback_data="instagram_topup_lava",
    )
    builder.adjust(1)
    return builder.as_markup()


def _lava_packages() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for package in preset_manager.get_packages():
        offer_id, currency = _package_lava_offer_config(package)
        if offer_id and str(currency or "").upper() == "RUB":
            result.append(package)
    return result


async def _show_instagram_provider_packages(
    callback: types.CallbackQuery,
    provider: str,
) -> None:
    provider_key = provider.strip().lower()
    if provider_key == "yookassa":
        if not yookassa_service.enabled:
            await callback.message.edit_text(
                "ЮKassa сейчас временно недоступна. Попробуйте Lava Top.",
                reply_markup=get_instagram_topup_provider_keyboard(),
            )
            await callback.answer()
            return
        packages = list(preset_manager.get_packages())
        title = "💳 ЮKassa"
    elif provider_key == "lava":
        if not lava_service.enabled:
            await callback.message.edit_text(
                "Lava Top сейчас временно недоступна. Попробуйте ЮKassa.",
                reply_markup=get_instagram_topup_provider_keyboard(),
            )
            await callback.answer()
            return
        packages = _lava_packages()
        title = "🔥 Lava Top"
    else:
        await callback.answer("Способ оплаты не поддерживается", show_alert=True)
        return

    if not packages:
        await callback.message.edit_text(
            f"{title} сейчас не может создать оплату для доступных пакетов. "
            "Попробуйте другой способ.",
            reply_markup=get_instagram_topup_provider_keyboard(),
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        f"{title}\n\nВыберите пакет лапок. После оплаты вернитесь в Instagram Direct "
        "и напишите «Продолжить».",
        reply_markup=get_instagram_provider_packages_keyboard(provider_key, packages),
    )
    await callback.answer()


@router.message(F.text.regexp(_START_LINK_RE.pattern))
async def confirm_instagram_account_link(
    message: types.Message,
    state: FSMContext,
) -> None:
    token = extract_link_token(message.text)
    if not token:
        return

    await state.clear()
    user = await get_or_create_user(message.from_user.id)
    try:
        await consume_channel_link_token(token, user.id)
    except ChannelLinkError as error:
        await message.answer(_link_error_text(error))
        return

    await message.answer(
        "✅ Instagram привязан к HappyFox.\n\n"
        "Баланс и история теперь общие. Пополнение для Instagram — через "
        "ЮKassa или Lava Top.\n\n"
        "После оплаты вернитесь в Direct и нажмите или напишите «Продолжить».",
        reply_markup=get_instagram_topup_provider_keyboard(),
    )


@router.callback_query(F.data == "instagram_topup_providers")
async def show_instagram_topup_providers(callback: types.CallbackQuery) -> None:
    await callback.message.edit_text(
        "💳 Выберите способ пополнения для Instagram:\n\n"
        "• ЮKassa\n"
        "• Lava Top",
        reply_markup=get_instagram_topup_provider_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "instagram_topup_yookassa")
async def show_instagram_yookassa_packages(callback: types.CallbackQuery) -> None:
    await _show_instagram_provider_packages(callback, "yookassa")


@router.callback_query(F.data == "instagram_topup_lava")
async def show_instagram_lava_packages(callback: types.CallbackQuery) -> None:
    await _show_instagram_provider_packages(callback, "lava")


@router.callback_query(F.data.startswith("instagram_topup_lava_package_"))
async def show_instagram_lava_methods(callback: types.CallbackQuery) -> None:
    package_id = callback.data.replace("instagram_topup_lava_package_", "", 1).strip()
    package = preset_manager.get_package(package_id)
    if not package:
        await callback.answer("Пакет не найден", show_alert=True)
        return

    offer_id, currency = _package_lava_offer_config(package)
    if not lava_service.enabled or not offer_id or str(currency or "").upper() != "RUB":
        await callback.message.edit_text(
            "Lava Top сейчас недоступна для этого пакета. Выберите другой пакет "
            "или ЮKassa.",
            reply_markup=get_instagram_topup_provider_keyboard(),
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        "🔥 Lava Top\n\nВыберите удобный способ оплаты:",
        reply_markup=get_instagram_lava_method_keyboard(package_id),
    )
    await callback.answer()
