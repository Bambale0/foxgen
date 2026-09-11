from __future__ import annotations

from typing import Any

from bot.max_api import callback_button, inline_keyboard, open_app_button
from bot.max_catalog import MaxPresetManager, max_preset_manager

IMAGE_LABELS = {
    "nano-banana-2-lite": "🍌 Nano Banana 2 Lite 🔥 НОВИНКА",
    "seedream_5_pro": "🌟 Seedream 5 Pro 🔥 НОВИНКА",
    "banana_pro": "💎 Nano Banana Pro",
    "banana_2": "🍌 Nano Banana 2",
    "flux_pro": "🧩 GPT Image 2",
    "seedream_edit": "🖌 Seedream 4.5",
    "grok_imagine_i2i": "🧠 Grok Imagine",
    "wan_27": "🧪 Wan 2.7 Pro",
}

VIDEO_LABELS = {
    "v3_pro": "💎 Kling 3.0",
    "v3_std": "⚡ Kling v3",
    "v26_pro": "🌀 Kling 2.5 Turbo",
    "grok_imagine": "🧠 Grok Imagine",
    "grok_imagine_v15": "🧠 Grok Imagine 1.5 NEW🔥🔥🔥",
    "seedance_2_5": "🧪 Seedance 2.5",
    "seedance_2": "🎞 Seedance 2.0",
    "gemini_omni": "🔷 Gemini Omni",
    "veo3": "🎥 Veo 3.1 Quality",
    "veo3_fast": "🚀 Veo 3.1 Fast",
    "veo3_lite": "🌿 Veo 3.1 Lite",
    "glow": "✨ Kling Glow",
}

VIDEO_TYPE_LABELS = {
    "text": "📝 Текст",
    "imgtxt": "🖼 Фото",
    "video": "🎬 Видео",
}


def _rows(items: list[dict[str, Any]], width: int = 2) -> list[list[dict[str, Any]]]:
    return [items[index : index + width] for index in range(0, len(items), width)]


def _format_amount(value: float) -> str:
    amount = float(value)
    return str(int(amount)) if amount.is_integer() else f"{amount:g}"


def _service_price(
    catalog: MaxPresetManager,
    key: str,
    *,
    default: float = 0,
) -> float:
    raw = catalog.get_price_config().get("service_prices", {}) or {}
    try:
        return float(raw.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def main_menu(
    balance: float,
    *,
    mini_app_url: str = "",
    mini_app_bot_name: str = "",
    catalog: MaxPresetManager = max_preset_manager,
) -> list[dict[str, Any]]:
    """MAX mirror of the HappyFox Telegram main menu."""
    rows: list[list[dict[str, Any]]] = []
    if mini_app_url:
        rows.append(
            [open_app_button("🚀 Открыть Mini App", web_app=mini_app_bot_name)]
        )

    video_prompt_price = _service_price(catalog, "video_prompt", default=3)
    rows.extend(
        [
            [
                callback_button("🖼 Создать фото", "max:create_image"),
                callback_button("🎬 Создать видео", "max:create_video"),
            ],
            [
                callback_button("🎯 Motion Control", "max:motion_control"),
                callback_button("✍️ Промпт по описанию", "max:photo_prompt"),
            ],
            [
                callback_button(
                    f"🎞 Промпт по видео • {_format_amount(video_prompt_price)}🍌",
                    "max:video_prompt",
                ),
                callback_button("🤖 AI-помощник", "max:assistant"),
            ],
            [
                callback_button("📚 Библиотека промптов", "max:prompts"),
                callback_button("🖼 Лента", "max:feed"),
            ],
            [
                callback_button(
                    f"🍌 Баланс: {_format_amount(balance)}",
                    "max:balance",
                ),
                callback_button("💬 Поддержка", "max:support"),
            ],
            [
                callback_button("🤝 Партнёрам", "max:partners"),
                callback_button("⋯ Ещё", "max:more"),
            ],
        ]
    )
    return [inline_keyboard(rows)]


def more_menu() -> list[dict[str, Any]]:
    """Telegram `get_more_menu_keyboard()` mirrored for MAX."""
    return [
        inline_keyboard(
            [
                [
                    callback_button("❓ Как пользоваться", "max:help"),
                    callback_button("💬 Поддержка", "max:support"),
                ],
                [callback_button("💰 Пополнить", "max:topup")],
                [callback_button("🏠 Главное меню", "max:home")],
            ]
        )
    ]


def image_model_menu(
    catalog: MaxPresetManager = max_preset_manager,
) -> list[dict[str, Any]]:
    buttons: list[dict[str, Any]] = []
    for model, cost in catalog.image_models().items():
        label = IMAGE_LABELS.get(model, model)
        buttons.append(
            callback_button(
                f"{label} • {_format_amount(cost)}🍌",
                f"max:image:{model}",
            )
        )
    rows = [[button] for button in buttons]
    rows.append([callback_button("🏠 Главное меню", "max:home")])
    return [inline_keyboard(rows)]


def video_model_selection_menu(
    catalog: MaxPresetManager = max_preset_manager,
) -> list[dict[str, Any]]:
    """Telegram-first video step: model before media/generation type."""
    rows: list[list[dict[str, Any]]] = []
    default_durations = {
        "grok_imagine": 6,
        "grok_imagine_v15": 8,
        "gemini_omni": 6,
        "veo3": 6,
        "veo3_fast": 6,
        "veo3_lite": 6,
    }
    for model in catalog.video_models():
        duration = default_durations.get(model, 5)
        pricing_quality = (
            "720p"
            if model.startswith("veo3") or model in {"gemini_omni", "seedance_2_5"}
            else None
        )
        try:
            cost = catalog.video_cost(
                model,
                duration=duration,
                quality=pricing_quality,
            )
            per_second = cost / max(duration, 1)
            price_label = f"{_format_amount(per_second)}🍌/с"
        except (KeyError, TypeError, ValueError, RuntimeError):
            price_label = "🍌"
        rows.append(
            [
                callback_button(
                    f"{VIDEO_LABELS.get(model, model)} • {price_label}",
                    f"max:video_model:{model}",
                )
            ]
        )
    rows.append([callback_button("🏠 Главное меню", "max:home")])
    return [inline_keyboard(rows)]


def video_type_menu(
    *,
    model: str = "",
    catalog: MaxPresetManager = max_preset_manager,
) -> list[dict[str, Any]]:
    supported = [
        generation_type
        for generation_type in ("text", "imgtxt", "video")
        if not model or model in catalog.video_models(generation_type)
    ]
    buttons = [
        callback_button(VIDEO_TYPE_LABELS[generation_type], f"max:vtype:{generation_type}")
        for generation_type in supported
    ]
    rows = _rows(buttons, width=3)
    rows.append([callback_button("🤖 Сменить модель", "max:create_video")])
    rows.append([callback_button("🏠 Главное меню", "max:home")])
    return [inline_keyboard(rows)]


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
        return f"от {_format_amount(cost)}🍌"
    except (KeyError, TypeError, ValueError, RuntimeError):
        return "🍌"


def video_model_menu(
    generation_type: str,
    catalog: MaxPresetManager = max_preset_manager,
) -> list[dict[str, Any]]:
    """Backward-compatible menu retained for old callback paths."""
    buttons: list[dict[str, Any]] = []
    for model in catalog.video_models(generation_type):
        label = VIDEO_LABELS.get(model, model)
        buttons.append(
            callback_button(
                f"{label} • {_video_price_label(catalog, model)}",
                f"max:video:{generation_type}:{model}",
            )
        )
    rows = [[button] for button in buttons]
    rows.append([callback_button("🤖 Сменить модель", "max:create_video")])
    rows.append([callback_button("🏠 Главное меню", "max:home")])
    return [inline_keyboard(rows)]


def topup_menu(
    catalog: MaxPresetManager = max_preset_manager,
) -> list[dict[str, Any]]:
    rows: list[list[dict[str, Any]]] = []
    for package in catalog.get_packages():
        popular = " 🔥" if package.get("popular") else ""
        rows.append(
            [
                callback_button(
                    f"{package['name']}: {package['credits']}🍌 за "
                    f"{package['price_rub']}₽{popular}",
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
                [
                    callback_button("✅ Подтвердить", "max:generate"),
                    callback_button("❌ Отмена", "max:cancel"),
                ],
                [callback_button("🏠 Главное меню", "max:home")],
            ]
        )
    ]


def back_home_menu() -> list[dict[str, Any]]:
    return [inline_keyboard([[callback_button("🏠 Главное меню", "max:home")]])]
