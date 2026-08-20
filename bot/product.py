from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProductConfig:
    product_id: str
    brand_name: str
    brand_description: str
    welcome_text: str


_PRODUCTS: dict[str, ProductConfig] = {
    "happyfox": ProductConfig(
        product_id="happyfox",
        brand_name="HappyFox",
        brand_description="HappyFox — создание фото, видео и AI-контента в Telegram",
        welcome_text=(
            "Привет 👋\n\n"
            "Я <b>HappyFox</b> — удобный AI-сервис для создания изображений, видео и другого контента.\n\n"
            "👇 Выбирай генерацию в боте или открывай приложение, чтобы начать."
        ),
    ),
    "neuromix": ProductConfig(
        product_id="neuromix",
        brand_name="NEUROMIX",
        brand_description="NEUROMIX — студия генерации фото и видео с помощью AI",
        welcome_text=(
            "Привет 👋\n\n"
            "Я <b>NEUROMIX</b> — самый выгодный и очень удобный бот для генерации изображений и видео.\n\n"
            "👇 Пользуйся текстовым вариантом генераций или открой приложение, чтобы начать творить 🚀"
        ),
    ),
}


def load_product_config() -> ProductConfig:
    product_id = os.getenv("PRODUCT_ID", "happyfox").strip().lower() or "happyfox"
    try:
        return _PRODUCTS[product_id]
    except KeyError as exc:
        supported = ", ".join(sorted(_PRODUCTS))
        raise RuntimeError(f"Unsupported PRODUCT_ID={product_id!r}; expected one of: {supported}") from exc


product = load_product_config()
