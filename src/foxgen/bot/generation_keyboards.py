from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from foxgen.bot.generation_capabilities import (
    IMAGE_MODELS,
    VIDEO_MODELS,
    ImageModelCapability,
    VideoGenerationType,
    VideoModelCapability,
)


def image_model_keyboard(current: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for item in IMAGE_MODELS.values():
        check = "✅ " if item.key == current else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{check}{item.title} — {item.summary}",
                    callback_data=f"gw:i:model:{item.key}",
                )
            ]
        )
    rows.extend(_back_cancel_rows())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def image_reference_keyboard(*, count: int, max_count: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if count:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"✅ Референсы добавлены ({count}/{max_count})",
                    callback_data="gw:i:refs:done",
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="🗑 Очистить референсы",
                    callback_data="gw:i:refs:clear",
                )
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Пропустить без референсов",
                    callback_data="gw:i:refs:skip",
                )
            ]
        )
    rows.extend(_back_cancel_rows())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def image_settings_keyboard(
    capability: ImageModelCapability,
    data: dict[str, object],
) -> InlineKeyboardMarkup:
    ratio = str(data.get("aspect_ratio") or capability.default_aspect_ratio)
    resolution = str(data.get("resolution") or capability.default_resolution or "")
    quality = str(data.get("quality") or capability.default_quality or "")
    output_format = str(data.get("output_format") or capability.default_output_format)
    rows: list[list[InlineKeyboardButton]] = []
    rows.extend(
        _choice_rows(
            capability.aspect_ratios,
            current=ratio,
            prefix="gw:i:ratio:",
            transform=lambda value: value.replace(":", "x"),
            width=3,
        )
    )
    if capability.resolutions:
        rows.extend(
            _choice_rows(
                capability.resolutions,
                current=resolution,
                prefix="gw:i:resolution:",
                width=3,
            )
        )
    if capability.qualities:
        labels = {"basic": "Basic", "high": "High"}
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{'✅ ' if value == quality else ''}{labels.get(value, value)}",
                    callback_data=f"gw:i:quality:{value}",
                )
                for value in capability.qualities
            ]
        )
    if len(capability.output_formats) > 1:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{'✅ ' if value == output_format else ''}{value.upper()}",
                    callback_data=f"gw:i:format:{value}",
                )
                for value in capability.output_formats
            ]
        )
    rows.append([InlineKeyboardButton(text="Продолжить →", callback_data="gw:i:settings:done")])
    rows.extend(_back_cancel_rows())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def video_model_keyboard(current: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for item in VIDEO_MODELS.values():
        check = "✅ " if item.key == current else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{check}{item.title} — {item.summary}",
                    callback_data=f"gw:v:model:{item.key}",
                )
            ]
        )
    rows.extend(_back_cancel_rows())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def video_type_keyboard(
    capability: VideoModelCapability,
    current: VideoGenerationType | None = None,
) -> InlineKeyboardMarkup:
    labels = {
        VideoGenerationType.TEXT: "✨ Текст → видео",
        VideoGenerationType.FIRST_FRAME: "🖼 Первый кадр → видео",
        VideoGenerationType.FIRST_LAST: "🎞 Первый + последний кадр",
        VideoGenerationType.REFERENCES: "🧩 Мультимодальные референсы",
    }
    rows = [
        [
            InlineKeyboardButton(
                text=f"{'✅ ' if item == current else ''}{labels[item]}",
                callback_data=f"gw:v:type:{item.value}",
            )
        ]
        for item in capability.generation_types
    ]
    rows.extend(_back_cancel_rows())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def video_media_keyboard(
    *,
    generation_type: VideoGenerationType,
    count: int,
    can_continue: bool,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if can_continue:
        label = "Продолжить →"
        if generation_type == VideoGenerationType.REFERENCES:
            label = f"✅ Референсы добавлены ({count})"
        rows.append([InlineKeyboardButton(text=label, callback_data="gw:v:media:done")])
    if count:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🗑 Очистить медиа",
                    callback_data="gw:v:media:clear",
                )
            ]
        )
    rows.extend(_back_cancel_rows())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def video_settings_keyboard(
    capability: VideoModelCapability,
    data: dict[str, object],
) -> InlineKeyboardMarkup:
    ratio = str(data.get("aspect_ratio") or capability.default_aspect_ratio)
    duration = int(data.get("duration") or capability.default_duration)
    resolution = str(data.get("resolution") or capability.default_resolution)
    generate_audio = bool(data.get("generate_audio"))
    return_last_frame = bool(data.get("return_last_frame"))
    web_search = bool(data.get("web_search"))
    rows: list[list[InlineKeyboardButton]] = []
    rows.extend(
        _choice_rows(
            capability.aspect_ratios,
            current=ratio,
            prefix="gw:v:ratio:",
            transform=lambda value: value.replace(":", "x"),
            width=3,
        )
    )
    rows.extend(
        _choice_rows(
            tuple(str(value) for value in capability.durations),
            current=str(duration),
            prefix="gw:v:duration:",
            suffix=" сек",
            width=3,
        )
    )
    if len(capability.resolutions) > 1:
        rows.extend(
            _choice_rows(
                capability.resolutions,
                current=resolution,
                prefix="gw:v:resolution:",
                width=3,
            )
        )
    toggles: list[InlineKeyboardButton] = []
    if capability.supports_generated_audio:
        toggles.append(
            InlineKeyboardButton(
                text=f"{'✅' if generate_audio else '⬜'} Звук",
                callback_data="gw:v:toggle:audio",
            )
        )
    if capability.supports_return_last_frame:
        toggles.append(
            InlineKeyboardButton(
                text=f"{'✅' if return_last_frame else '⬜'} Последний кадр",
                callback_data="gw:v:toggle:last",
            )
        )
    if capability.supports_web_search:
        toggles.append(
            InlineKeyboardButton(
                text=f"{'✅' if web_search else '⬜'} Web search",
                callback_data="gw:v:toggle:web",
            )
        )
    for index in range(0, len(toggles), 2):
        rows.append(toggles[index : index + 2])
    rows.append([InlineKeyboardButton(text="Продолжить →", callback_data="gw:v:settings:done")])
    rows.extend(_back_cancel_rows())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def prompt_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=_back_cancel_rows())


def _choice_rows(
    values: tuple[str, ...],
    *,
    current: str,
    prefix: str,
    width: int,
    suffix: str = "",
    transform: object | None = None,
) -> list[list[InlineKeyboardButton]]:
    converter = transform if callable(transform) else lambda value: value
    buttons = [
        InlineKeyboardButton(
            text=f"{'✅ ' if value == current else ''}{value}{suffix}",
            callback_data=f"{prefix}{converter(value)}",
        )
        for value in values
    ]
    return [buttons[index : index + width] for index in range(0, len(buttons), width)]


def _back_cancel_rows() -> list[list[InlineKeyboardButton]]:
    return [
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="gw:back")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="nav:cancel")],
    ]
