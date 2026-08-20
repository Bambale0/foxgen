import math
from typing import Any

from bot.config import config


TELEGRAM_STARS_PROVIDER = "telegram_stars"
TELEGRAM_STARS_CURRENCY = "XTR"
TELEGRAM_STARS_PAYLOAD_PREFIX = "stars"


def package_bonus_credits(package: dict[str, Any]) -> int:
    return int(package.get("bonus_credits", 0) or 0)


def total_package_credits(package: dict[str, Any], promo_bonus: int = 0) -> int:
    return int(package["credits"]) + package_bonus_credits(package) + int(promo_bonus or 0)


def package_stars_amount(package: dict[str, Any]) -> int:
    explicit = package.get("price_stars", package.get("stars_price"))
    if explicit not in (None, ""):
        return max(1, int(round(float(explicit))))

    multiplier = max(0.01, float(config.TELEGRAM_STARS_PER_RUB or 1))
    flat_fee = max(0, int(config.TELEGRAM_STARS_FLAT_FEE or 0))
    return max(1, int(math.ceil(float(package["price_rub"]) * multiplier)) + flat_fee)


def build_stars_invoice_payload(order_id: str, stars_amount: int) -> str:
    return f"{TELEGRAM_STARS_PAYLOAD_PREFIX}:{order_id}:{int(stars_amount)}"


def parse_stars_invoice_payload(payload: str | None) -> tuple[str, int] | None:
    parts = str(payload or "").split(":")
    if len(parts) != 3 or parts[0] != TELEGRAM_STARS_PAYLOAD_PREFIX:
        return None
    order_id = parts[1].strip()
    try:
        stars_amount = int(parts[2])
    except (TypeError, ValueError):
        return None
    if not order_id or stars_amount < 1:
        return None
    return order_id, stars_amount
