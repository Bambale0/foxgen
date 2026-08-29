from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProductConfig:
    product_id: str
    brand_name: str
    brand_description: str
    welcome_text: str
    credit_name: str
    credit_name_few: str
    credit_name_plural: str
    credit_short: str
    credit_emoji: str
    support_contact: str

    def credit_label(self, amount: float) -> str:
        value = abs(float(amount))
        if not value.is_integer():
            return self.credit_name_plural

        integer = int(value)
        last_two = integer % 100
        last = integer % 10
        if 11 <= last_two <= 14:
            return self.credit_name_plural
        if last == 1:
            return self.credit_name
        if 2 <= last <= 4:
            return self.credit_name_few
        return self.credit_name_plural

    def format_credits(self, amount: float) -> str:
        value = float(amount)
        rendered = str(int(value)) if value.is_integer() else f"{value:g}"
        return f"{rendered} {self.credit_label(value)}"


HAPPYFOX_PRODUCT = ProductConfig(
    product_id="happyfox",
    brand_name="HappyFox",
    brand_description="HappyFox — создание фото, видео и AI-контента в Telegram",
    welcome_text=(
        "Привет 👋\n\n"
        "Я <b>HappyFox</b> — удобный AI-сервис для создания изображений, видео и другого контента.\n\n"
        "👇 Выбирай генерацию в боте или открывай приложение, чтобы начать."
    ),
    credit_name="лапка",
    credit_name_few="лапки",
    credit_name_plural="лапок",
    credit_short="🐾",
    credit_emoji="🐾",
    support_contact=os.getenv("SUPPORT_CONTACT", "").strip(),
)


def load_product_config() -> ProductConfig:
    product_id = os.getenv("PRODUCT_ID", "happyfox").strip().lower() or "happyfox"
    if product_id != "happyfox":
        raise RuntimeError(
            f"Unsupported PRODUCT_ID={product_id!r}; Bambale0/foxgen is HappyFox-only"
        )
    return HAPPYFOX_PRODUCT


product = load_product_config()
