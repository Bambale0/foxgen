from __future__ import annotations

from typing import Any

from bot.max_api import callback_button, inline_keyboard, link_button
from bot.max_catalog import MaxPresetManager, max_preset_manager

IMAGE_LABELS = {
    "gemini_2_5_flash": "Gemini 2.5 Flash",
    "gemini_3_pro": "Gemini 3 Pro",
    "banana_2": "Nano Banana 2",
    "nano-banana-2-lite": "Nano Banana 2 Lite",
    "z_image_turbo": "Z-Image Turbo",
    "seedream": "Seedream",
    "seedream_45": "Seedream 4.5",
    "flux_pro": "Flux Pro",
    "nano-banana-pro": "Nano Banana Pro",
    "seedream_edit": "Seedream 5 Pro",
    "grok_imagine_i2i": "Grok Imagine",
    "wan_27": "Wan 2.7",
}

VIDEO_LABELS = {
    "v3_std": "Kling 3.0 Standard",
    "v3_pro": "Kling 3.0 Pro",
    "v26_pro": "Kling 2.6 Pro",
    "v26_motion_pro": "Kling 2.6 Motion",
    "motion_control_v26": "Motion Control 2.6",
    "motion_control_v30": "Motion Control 3.0",
    "grok_imagine": "Grok Imagine",
    "grok_imagine_v15": "Grok Imagine 1.5",
    "seedance_2": "Seedance 2.0",
    "seedance_2_5": "Seedance 2.5",
    "gemini_omni_video": "Gemini Omni Video",
    "gemini_omni_audio": "Gemini Omni Audio",
    "gemini_omni_character": "Gemini Omni Character",
    "veo3": "Veo 3",
    "veo3_fast": "Veo 3 Fast",
    "veo3_lite": "Veo 3 Lite",
    "glow": "Glow",
}


def _rows(items: list[dict[str, Any]], width: int = 2) -> list[list[dict[str, Any]]]:
    return [items[index : index + width] for index in range(0, len(items), width)]


def main_menu(balance: float, *, mini_app_url: str = "") -> list[dict[str, Any]]:
    """MAX copy of the HappyFox Telegram main menu.

    MAX has its own state/storage. Callback payloads are MAX-owned even when the
    labels intentionally match Telegram 1:1.
    """
    rows: list[list[dict[str, Any]]] = []
    if mini_app_url:
        rows.append([link_button("🚀 Mini App", mini_app_url)])
    rows.extend(
        [
            [
                callback_button("🖼 Создать фото", "max:create_image"),
                callback_button("🎙 Создать озвучку", "max:omni_audio"),
            ],
            [
                callback_button("🎬 Создать видео", "max:create_video"),
                callback_button("🎵 Создать музыку · Suno", "max:music"),
            ],
            [
                callback_button("🎯 Motion Control", "max:motion_control"),
                callback_button("✨ Промпты", "max:prompts"),
            ],
            [
                callback_button("🔷 Gemini Omni", "max:gemini_omni"),
                callback_button("🤖 AI-помощник", "max:assistant"),
            ],
            [
                callback_button("🔗 Ссылки на работы", "max:history"),
                callback_button("💬 Поддержка", "max:support"),
            ],
            [
                callback_button(f"🐾 Баланс: {balance:g}", "max:balance"),
                callback_button("🤝 Партнёры", "max:partners"),
            ],
            [callback_button("💳 Тарифы", "max:topup")],
        ]
    )
    return [inline_keyboard(rows)]


def image_model_menu(catalog: MaxPresetManager = max_preset_manager) -> list[dict[str, Any]]:
    buttons: list[dict[str, Any]] = []
    for model, cost in catalog.image_models().items():
        label = IMAGE_LABELS.get(model, model)
        buttons.append(callback_button(f"{label} · {float(cost):g} 🐾", f"max:image:{model}"))
    rows = _rows(buttons)
    rows.append([callback_button("🏠 Главное меню", "max:home")])
    return [inline_keyboard(rows)]


def _video_base_cost(value: Any) -> float:
    if isinstance(value, dict):
        return float(value.get("base") or 0)
    return float(value or 0)


def video_model_menu(catalog: MaxPresetManager = max_preset_manager) -> list[dict[str, Any]]:
    buttons: list[dict[str, Any]] = []
    for model, config in catalog.video_models().items():
        label = VIDEO_LABELS.get(model, model)
        buttons.append(
            callback_button(
                f"{label} · от {_video_base_cost(config):g} 🐾",
                f"max:video:{model}",
            )
        )
    rows = _rows(buttons)
    rows.append([callback_button("🏠 Главное меню", "max:home")])
    return [inline_keyboard(rows)]


def topup_menu(catalog: MaxPresetManager = max_preset_manager) -> list[dict[str, Any]]:
    rows: list[list[dict[str, Any]]] = []
    for package in catalog.get_packages():
        rows.append(
            [
                callback_button(
                    f"{package['name']} · {package['credits']} 🐾 · {package['price_rub']} ₽",
                    f"max:package:{package['id']}",
                )
            ]
        )
    rows.append([callback_button("🏠 Главное меню", "max:home")])
    return [inline_keyboard(rows)]


def generation_confirm_menu() -> list[dict[str, Any]]:
    return [
        inline_keyboard(
            [
                [callback_button("🚀 Запустить", "max:generate")],
                [callback_button("⬅️ Назад", "max:cancel"), callback_button("🏠 Меню", "max:home")],
            ]
        )
    ]


def back_home_menu() -> list[dict[str, Any]]:
    return [inline_keyboard([[callback_button("🏠 Главное меню", "max:home")]])]
