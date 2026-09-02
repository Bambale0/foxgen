from __future__ import annotations

from typing import Any

from bot.max_api import callback_button, inline_keyboard, link_button
from bot.max_catalog import MaxPresetManager, max_preset_manager

IMAGE_LABELS = {
    "nano-banana-2-lite": "🍌 Nano Banana 2 Lite 🔥 НОВИНКА",
    "seedream_5_pro": "🌟 Seedream 5 Pro 🔥 НОВИНКА",
    "banana_pro": "💎 Nano Banana Pro",
    "banana_2": "✨ Nano Banana 2",
    "flux_pro": "🎨 GPT Image 2",
    "seedream_edit": "🌱 Seedream 4.5",
    "grok_imagine_i2i": "🧠 Grok Imagine",
    "wan_27": "🌊 Wan 2.7 Pro",
}

VIDEO_LABELS = {
    "v3_pro": "💎 Kling 3.0",
    "v3_std": "⚡ Kling v3",
    "v26_pro": "🌀 Kling 2.5 Turbo",
    "grok_imagine": "🧠 Grok Imagine",
    "grok_imagine_v15": "🧠 Grok Imagine 1.5 🔥",
    "seedance_2_5": "🔥🆕 Seedance 2.5",
    "seedance_2": "🎞 Seedance 2.0",
    "gemini_omni": "🔷 Gemini Omni",
    "veo3": "🎥 Veo 3.1 Quality",
    "veo3_fast": "🚀 Veo 3.1 Fast",
    "veo3_lite": "🌿 Veo 3.1 Lite",
    "glow": "✨ Kling Glow",
}

VIDEO_TYPE_LABELS = {
    "text": "📝 Текст → Видео",
    "imgtxt": "🖼 Фото → Видео",
    "video": "🎬 Видео → Видео",
}


def _rows(items: list[dict[str, Any]], width: int = 2) -> list[list[dict[str, Any]]]:
    return [items[index : index + width] for index in range(0, len(items), width)]


def _format_amount(value: float) -> str:
    amount = float(value)
    return str(int(amount)) if amount.is_integer() else f"{amount:g}"


def main_menu(balance: float, *, mini_app_url: str = "") -> list[dict[str, Any]]:
    """MAX copy of the HappyFox Telegram main menu."""
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


def image_model_menu(
    catalog: MaxPresetManager = max_preset_manager,
) -> list[dict[str, Any]]:
    buttons: list[dict[str, Any]] = []
    for model, cost in catalog.image_models().items():
        label = IMAGE_LABELS.get(model, model)
        buttons.append(
            callback_button(
                f"{label} · {_format_amount(cost)} 🐾",
                f"max:image:{model}",
            )
        )
    rows = _rows(buttons)
    rows.append([callback_button("🏠 Главное меню", "max:home")])
    return [inline_keyboard(rows)]


def video_type_menu() -> list[dict[str, Any]]:
    return [
        inline_keyboard(
            [
                [
                    callback_button(VIDEO_TYPE_LABELS["text"], "max:vtype:text"),
                    callback_button(VIDEO_TYPE_LABELS["imgtxt"], "max:vtype:imgtxt"),
                ],
                [callback_button(VIDEO_TYPE_LABELS["video"], "max:vtype:video")],
                [callback_button("🏠 Главное меню", "max:home")],
            ]
        )
    ]


def _video_price_label(
    catalog: MaxPresetManager,
    model: str,
    *,
    duration: int = 5,
) -> str:
    quality = (
        "720p"
        if model.startswith("veo3") or model in {"gemini_omni", "seedance_2_5"}
        else None
    )
    try:
        cost = catalog.video_cost(model, duration=duration, quality=quality)
        return f"от {_format_amount(cost)} 🐾"
    except (KeyError, TypeError, ValueError, RuntimeError):
        return "🐾"


def video_model_menu(
    generation_type: str,
    catalog: MaxPresetManager = max_preset_manager,
) -> list[dict[str, Any]]:
    buttons: list[dict[str, Any]] = []
    for model in catalog.video_models(generation_type):
        label = VIDEO_LABELS.get(model, model)
        buttons.append(
            callback_button(
                f"{label} · {_video_price_label(catalog, model)}",
                f"max:video:{generation_type}:{model}",
            )
        )
    rows = _rows(buttons)
    rows.append([callback_button("⬅️ Тип видео", "max:create_video")])
    rows.append([callback_button("🏠 Главное меню", "max:home")])
    return [inline_keyboard(rows)]


def topup_menu(
    catalog: MaxPresetManager = max_preset_manager,
) -> list[dict[str, Any]]:
    rows: list[list[dict[str, Any]]] = []
    for package in catalog.get_packages():
        rows.append(
            [
                callback_button(
                    f"{package['name']} · {package['credits']} 🐾 · "
                    f"{package['price_rub']} ₽",
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
                [
                    callback_button("⬅️ Назад", "max:cancel"),
                    callback_button("🏠 Меню", "max:home"),
                ],
            ]
        )
    ]


def back_home_menu() -> list[dict[str, Any]]:
    return [inline_keyboard([[callback_button("🏠 Главное меню", "max:home")]])]
