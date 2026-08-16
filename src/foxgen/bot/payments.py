from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message, PreCheckoutQuery

from foxgen.bot.api_client import FoxGenApiClient, FoxGenApiError


router = Router(name="foxgen-payments")


async def _user_api_request(
    api_client: FoxGenApiClient,
    method: str,
    path: str,
    *,
    user_id: int,
    username: str | None = None,
    json: dict[str, object] | None = None,
) -> Any:
    return await api_client._user_request(  # noqa: SLF001 - shared trusted bot transport
        method,
        path,
        user_id=user_id,
        username=username,
        json=json,
    )


@router.message(Command("promo"))
async def redeem_promo(
    message: Message,
    api_client: FoxGenApiClient,
) -> None:
    user = message.from_user
    if user is None:
        return
    text = message.text or ""
    code = text.partition(" ")[2].strip()
    if not code:
        await message.answer(
            "Введите промокод после команды:\n"
            "<code>/promo FOX500</code>"
        )
        return

    try:
        payload = await _user_api_request(
            api_client,
            "POST",
            "/v1/user-portal/promos/redeem",
            user_id=user.id,
            username=user.username,
            json={"code": code},
        )
    except FoxGenApiError as exc:
        await message.answer(f"Промокод не активирован: {exc.message}")
        return

    if not isinstance(payload, dict):
        await message.answer("Промокод обработан. Проверьте баланс в Happy Fox.")
        return

    reward = int(payload.get("reward_units", 0))
    available = int(payload.get("available_units", 0))
    replayed = payload.get("replayed") is True
    if replayed:
        await message.answer(
            "ℹ️ Этот промокод уже был активирован.\n\n"
            f"Баланс: <b>{available} CREDIT</b>"
        )
        return
    await message.answer(
        "✅ Промокод активирован\n\n"
        f"Начислено: <b>{reward} CREDIT</b>\n"
        f"Баланс: <b>{available} CREDIT</b>"
    )


@router.pre_checkout_query()
async def validate_stars_pre_checkout(
    query: PreCheckoutQuery,
    api_client: FoxGenApiClient,
) -> None:
    try:
        payload = await _user_api_request(
            api_client,
            "POST",
            "/v1/user-portal/payments/stars/pre-checkout",
            user_id=query.from_user.id,
            username=query.from_user.username,
            json={
                "invoice_payload": query.invoice_payload,
                "currency": query.currency,
                "total_amount": query.total_amount,
            },
        )
    except FoxGenApiError as exc:
        await query.answer(
            ok=False,
            error_message=exc.message[:200],
        )
        return

    if not isinstance(payload, dict) or payload.get("ok") is not True:
        error_message = "Не удалось проверить заказ. Создайте новую оплату."
        if isinstance(payload, dict) and isinstance(payload.get("error_message"), str):
            error_message = str(payload["error_message"])
        await query.answer(ok=False, error_message=error_message[:200])
        return
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def apply_stars_payment(
    message: Message,
    api_client: FoxGenApiClient,
) -> None:
    payment = message.successful_payment
    user = message.from_user
    if payment is None or user is None:
        return

    request_payload: dict[str, object] = {
        "invoice_payload": payment.invoice_payload,
        "currency": payment.currency,
        "total_amount": payment.total_amount,
        "telegram_payment_charge_id": payment.telegram_payment_charge_id,
        "provider_payment_charge_id": payment.provider_payment_charge_id,
    }
    try:
        payload = await _user_api_request(
            api_client,
            "POST",
            "/v1/user-portal/payments/stars/success",
            user_id=user.id,
            username=user.username,
            json=request_payload,
        )
    except FoxGenApiError:
        await message.answer(
            "Оплата получена Telegram, но зачисление ещё не подтверждено FoxGen. "
            "Не оплачивайте повторно — откройте /menu и обратитесь в поддержку, если баланс не обновится."
        )
        return

    if not isinstance(payload, dict):
        await message.answer(
            "Оплата получена. Не оплачивайте повторно: статус зачисления можно проверить в балансе."
        )
        return
    credited = int(payload.get("credited_units", 0))
    available = int(payload.get("available_units", 0))
    await message.answer(
        f"✅ Оплата подтверждена\n\n"
        f"Зачислено: <b>{credited} CREDIT</b>\n"
        f"Баланс: <b>{available} CREDIT</b>"
    )
