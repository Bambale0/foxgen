from __future__ import annotations

import functools
import inspect

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.services.preset_manager import preset_manager

STANDARD_VIDEO_TYPES = {"text", "imgtxt", "video"}
DEDICATED_VIDEO_MODELS = {"seedance_2_5"}

# HappyFox mirrors the v7_kate interaction contract, but only exposes models that
# are already implemented by this runtime. Provider payloads remain owned by the
# existing generation service. Dedicated models can be shown in this selector,
# but their callback opens the provider-specific flow instead of the generic
# settings keyboard.
VIDEO_TYPE_ROWS: dict[str, tuple[str, ...]] = {
    "text": (
        "seedance_2_5",
        "v3_pro",
        "v3_std",
        "v26_pro",
        "seedance_2",
        "gemini_omni",
        "veo3",
        "veo3_fast",
        "veo3_lite",
    ),
    "imgtxt": (
        "seedance_2_5",
        "v3_pro",
        "v3_std",
        "v26_pro",
        "grok_imagine",
        "grok_imagine_v15",
        "seedance_2",
        "gemini_omni",
        "veo3_fast",
    ),
    "video": (
        "seedance_2_5",
        "seedance_2",
        "glow",
        "gemini_omni",
    ),
}

VIDEO_MODEL_LABELS = {
    "seedance_2_5": "🔥🆕 Seedance 2.5",
    "v3_pro": "💎 Kling 3.0",
    "v3_std": "⚡ Kling v3",
    "v26_pro": "🌀 Kling 2.5 Turbo",
    "grok_imagine": "🧠 Grok Imagine",
    "grok_imagine_v15": "🧠 Grok Imagine 1.5 🔥",
    "seedance_2": "🎞 Seedance 2.0",
    "gemini_omni": "🔷 Gemini Omni",
    "veo3": "🎥 Veo 3.1 Quality",
    "veo3_fast": "🚀 Veo 3.1 Fast",
    "veo3_lite": "🌿 Veo 3.1 Lite",
    "glow": "✨ Kling Glow",
}

DEFAULT_DURATION = {
    "grok_imagine": 6,
    "grok_imagine_v15": 8,
    "gemini_omni": 6,
    "veo3": 6,
    "veo3_fast": 6,
    "veo3_lite": 6,
}

LEGACY_NAV_CALLBACKS = {"video_change_model", "video_change_media"}
PRICE_LOOKUP_ERRORS = (KeyError, TypeError, ValueError, RuntimeError)


def _selector_model(model: str) -> str:
    if model == "gemini_omni" or model.startswith("gemini_omni_"):
        return "gemini_omni"
    return model


def is_video_model_compatible(v_type: str, model: str) -> bool:
    return _selector_model(model) in VIDEO_TYPE_ROWS.get(v_type, ())


def compatible_video_model(v_type: str, model: str | None) -> str:
    """Keep a generic model when valid; never auto-enter a dedicated flow."""
    current = str(model or "")
    selector = _selector_model(current)
    models = VIDEO_TYPE_ROWS.get(v_type, ())

    if current and selector in models and selector not in DEDICATED_VIDEO_MODELS:
        return current

    for candidate in models:
        if candidate not in DEDICATED_VIDEO_MODELS:
            return candidate
    return current or "v3_pro"


def _format_amount(value: float) -> str:
    amount = float(value)
    return str(int(amount)) if amount.is_integer() else f"{amount:g}"


def _model_price_label(model: str) -> str:
    duration = DEFAULT_DURATION.get(model, 5)
    try:
        if model == "gemini_omni":
            cost = preset_manager.get_video_cost_with_quality(
                "gemini_omni_video", duration, "720p"
            )
            return f"от {_format_amount(cost)}🐾"

        quality = "720p" if model == "seedance_2_5" or model.startswith("veo3") else None
        per_second = preset_manager.get_video_cost_per_second(model, duration, quality)
        return f"{_format_amount(per_second)}🐾/с"
    except PRICE_LOOKUP_ERRORS:
        try:
            cost = preset_manager.get_video_cost(model, duration)
            return f"{_format_amount(cost)}🐾"
        except PRICE_LOOKUP_ERRORS:
            return "🐾"


def _is_selected_model(current_model: str, model: str) -> bool:
    return _selector_model(current_model) == model


def _type_row(current_v_type: str) -> list[InlineKeyboardButton]:
    choices = (
        ("text", "📝 Текст → Видео", "v_type_text"),
        ("imgtxt", "🖼 Фото → Видео", "v_type_imgtxt"),
        ("video", "🎬 Видео → Видео", "v_type_video"),
    )
    return [
        InlineKeyboardButton(
            text=f"{'✅ ' if current_v_type == value else ''}{label}",
            callback_data=callback,
        )
        for value, label, callback in choices
    ]


def _model_rows(current_v_type: str, current_model: str) -> list[list[InlineKeyboardButton]]:
    models = VIDEO_TYPE_ROWS.get(current_v_type, ())
    buttons = [
        InlineKeyboardButton(
            text=(
                f"{'✅ ' if _is_selected_model(current_model, model) else ''}"
                f"{VIDEO_MODEL_LABELS[model]} • {_model_price_label(model)}"
            ),
            callback_data=f"v_model_{model}",
        )
        for model in models
    ]
    return [buttons[index : index + 2] for index in range(0, len(buttons), 2)]


def _paw_text(text: str) -> str:
    value = str(text or "")
    # Escaped legacy literals are intentional: the build-time HappyFox normalizer
    # must not rewrite this compatibility adapter before Python executes it.
    replacements = (
        ("\U0001f34c", "🐾"),
        ("\u0431\u0430\u043d\u0430\u043d\u043e\u0432", "лапок"),
        ("\u0431\u0430\u043d\u0430\u043d\u044b", "лапки"),
        ("\u0431\u0430\u043d\u0430\u043d\u0430", "лапки"),
        ("\u0431\u0430\u043d\u0430\u043d", "лапка"),
        ("\u043a\u0440\u0435\u0434\u0438\u0442\u043e\u0432", "лапок"),
        ("\u043a\u0440\u0435\u0434\u0438\u0442\u044b", "лапки"),
        ("\u043a\u0440\u0435\u0434\u0438\u0442\u0430", "лапки"),
        ("\u043a\u0440\u0435\u0434\u0438\u0442", "лапка"),
    )
    for old, new in replacements:
        value = value.replace(old, new)
    # Nano Banana is a real model name, not the HappyFox currency.
    return value.replace("🐾 Nano Banana", "✨ Nano Banana")


def _copy_button_with_paws(button: InlineKeyboardButton) -> InlineKeyboardButton:
    return button.model_copy(update={"text": _paw_text(button.text)})


def _clean_settings_rows(markup: InlineKeyboardMarkup) -> list[list[InlineKeyboardButton]]:
    cleaned: list[list[InlineKeyboardButton]] = []
    for row in markup.inline_keyboard:
        buttons = []
        for button in row:
            callback = str(button.callback_data or "")
            if callback in LEGACY_NAV_CALLBACKS:
                continue
            buttons.append(_copy_button_with_paws(button))
        if buttons:
            cleaned.append(buttons)
    return cleaned


def compose_happyfox_video_keyboard(
    settings_markup: InlineKeyboardMarkup,
    *,
    current_v_type: str,
    current_model: str,
) -> InlineKeyboardMarkup:
    """Compose the v7-style single-screen HappyFox video keyboard."""
    settings_rows = _clean_settings_rows(settings_markup)
    if current_v_type not in STANDARD_VIDEO_TYPES:
        return InlineKeyboardMarkup(inline_keyboard=settings_rows)

    rows: list[list[InlineKeyboardButton]] = [_type_row(current_v_type)]
    rows.extend(_model_rows(current_v_type, current_model))
    rows.extend(settings_rows)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def happyfox_dynamic_video_keyboard(settings_builder):
    """Decorate the proven settings keyboard with the v7-style dynamic selector.

    Keeping model-specific controls in the existing builder avoids duplicating provider
    contracts. HappyFox owns only the composition: type → compatible models → settings.
    """
    signature = inspect.signature(settings_builder)

    @functools.wraps(settings_builder)
    def wrapped(*args, **kwargs) -> InlineKeyboardMarkup:
        bound = signature.bind_partial(*args, **kwargs)
        bound.apply_defaults()
        current_v_type = str(bound.arguments.get("current_v_type", "text"))
        current_model = str(
            bound.arguments.get("current_video_model")
            or bound.arguments.get("current_model", "v3_std")
        )
        settings_markup = settings_builder(*args, **kwargs)
        return compose_happyfox_video_keyboard(
            settings_markup,
            current_v_type=current_v_type,
            current_model=current_model,
        )

    return wrapped