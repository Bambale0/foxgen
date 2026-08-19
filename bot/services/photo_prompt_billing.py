from __future__ import annotations

from dataclasses import dataclass

from bot.config import config
from bot.database import add_credits, deduct_credits, get_or_create_user
from bot.services.preset_manager import preset_manager


@dataclass(frozen=True)
class PhotoPromptCharge:
    telegram_id: int
    cost_credits: float
    price_rub: float
    charged: bool
    balance_after: float


class PhotoPromptInsufficientBalance(ValueError):
    def __init__(self, *, balance: float, cost_credits: float, price_rub: float):
        self.balance = round(float(balance), 4)
        self.cost_credits = round(float(cost_credits), 4)
        self.price_rub = round(float(price_rub), 2)
        super().__init__(
            f"Недостаточно бананов. Стоимость: {self.price_rub:g} ₽ "
            f"({self.cost_credits:g} 🍌), баланс: {self.balance:g} 🍌."
        )


def photo_prompt_price_rub() -> float:
    return preset_manager.get_photo_prompt_price_rub()


def photo_prompt_cost_credits() -> float:
    return preset_manager.get_photo_prompt_cost()


def _format_price_number(value: float) -> str:
    return f"{float(value):g}".replace(".", ",")


def photo_prompt_price_label() -> str:
    return (
        f"{_format_price_number(photo_prompt_price_rub())} ₽ "
        f"({_format_price_number(photo_prompt_cost_credits())} 🍌)"
    )


async def reserve_photo_prompt_charge(telegram_id: int) -> PhotoPromptCharge:
    price_rub = photo_prompt_price_rub()
    cost_credits = photo_prompt_cost_credits()
    user = await get_or_create_user(telegram_id)

    if config.is_admin(telegram_id):
        return PhotoPromptCharge(
            telegram_id=telegram_id,
            cost_credits=cost_credits,
            price_rub=price_rub,
            charged=False,
            balance_after=round(float(user.credits), 4),
        )

    if float(user.credits) + 1e-9 < cost_credits:
        raise PhotoPromptInsufficientBalance(
            balance=float(user.credits),
            cost_credits=cost_credits,
            price_rub=price_rub,
        )

    deducted = await deduct_credits(telegram_id, cost_credits)
    if not deducted:
        current = await get_or_create_user(telegram_id)
        raise PhotoPromptInsufficientBalance(
            balance=float(current.credits),
            cost_credits=cost_credits,
            price_rub=price_rub,
        )

    current = await get_or_create_user(telegram_id)
    return PhotoPromptCharge(
        telegram_id=telegram_id,
        cost_credits=cost_credits,
        price_rub=price_rub,
        charged=True,
        balance_after=round(float(current.credits), 4),
    )


async def refund_photo_prompt_charge(charge: PhotoPromptCharge | None) -> float | None:
    if charge is None:
        return None
    if charge.charged:
        await add_credits(charge.telegram_id, charge.cost_credits)
    current = await get_or_create_user(charge.telegram_id)
    return round(float(current.credits), 4)
