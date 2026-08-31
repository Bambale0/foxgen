from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bot.database import get_bot_setting, set_bot_setting

DEFAULTS_PATH = Path(__file__).resolve().parent.parent / "data" / "suno_price_defaults.json"
SUNO_CHANNELS = ("telegram", "max")
SUNO_MODELS = ("V5_5", "V5", "V4_5PLUS", "V4_5", "V4_5ALL", "V4")
MODEL_PRICED_OPERATIONS = frozenset(
    {
        "generate",
        "extend",
        "upload_extend",
        "upload_cover",
        "add_vocals",
        "add_instrumental",
    }
)
SUNO_OPERATION_LABELS: dict[str, str] = {
    "generate": "Создать трек",
    "extend": "Продолжить трек",
    "upload_extend": "Upload + продолжить",
    "upload_cover": "Cover по аудио",
    "add_vocals": "Добавить вокал",
    "add_instrumental": "Добавить инструментал",
    "lyrics": "Сгенерировать текст",
    "separate_vocal": "Вокал / инструментал",
    "split_stem": "Разделить на стемы",
    "split_stem_advanced": "Точный стем",
    "wav": "Конвертация WAV",
    "music_video": "Music Video",
    "persona": "Persona",
    "timestamped_lyrics": "Текст с таймкодами",
    "midi": "MIDI из стемов",
    "sounds": "Звуки / ambience",
    "voice_validate": "Suno Voice: фраза",
    "voice_generate": "Suno Voice: создать голос",
}
SUNO_OPERATIONS = tuple(SUNO_OPERATION_LABELS)


@dataclass(frozen=True)
class SunoPriceEntry:
    channel: str
    operation: str
    variant: str
    price: float
    overridden: bool


def _load_defaults() -> dict[str, Any]:
    with DEFAULTS_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise RuntimeError("Suno price defaults must be a JSON object")
    return payload


def _validate_channel(channel: str) -> str:
    value = str(channel or "").strip().lower()
    if value not in SUNO_CHANNELS:
        raise ValueError("Unknown Suno channel")
    return value


def _validate_operation(operation: str) -> str:
    value = str(operation or "").strip().lower()
    if value not in SUNO_OPERATION_LABELS:
        raise ValueError("Unknown Suno operation")
    return value


def _variant_for(operation: str, model: str | None) -> str:
    if operation in MODEL_PRICED_OPERATIONS:
        value = str(model or "").strip().upper()
        if value not in SUNO_MODELS:
            raise ValueError("Unsupported Suno model")
        return value
    return "default"


def _setting_key(channel: str, operation: str, variant: str) -> str:
    return f"suno_price:{channel}:{operation}:{variant}"


def default_suno_price(channel: str, operation: str, model: str | None = None) -> float:
    clean_channel = _validate_channel(channel)
    clean_operation = _validate_operation(operation)
    variant = _variant_for(clean_operation, model)
    defaults = _load_defaults()
    try:
        raw = defaults[clean_channel][clean_operation][variant]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(
            f"Missing Suno price default: {clean_channel}/{clean_operation}/{variant}"
        ) from exc
    value = float(raw)
    if value < 0:
        raise RuntimeError("Suno default price cannot be negative")
    return value


async def get_suno_price(
    channel: str,
    operation: str,
    model: str | None = None,
) -> float:
    clean_channel = _validate_channel(channel)
    clean_operation = _validate_operation(operation)
    variant = _variant_for(clean_operation, model)
    fallback = default_suno_price(clean_channel, clean_operation, variant)
    raw = await get_bot_setting(
        _setting_key(clean_channel, clean_operation, variant),
        default=None,
    )
    if raw in (None, ""):
        return fallback
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return fallback
    return value if value >= 0 else fallback


async def set_suno_price(
    channel: str,
    operation: str,
    value: float,
    *,
    model: str | None = None,
    updated_by_telegram_id: int | None = None,
) -> float:
    clean_channel = _validate_channel(channel)
    clean_operation = _validate_operation(operation)
    variant = _variant_for(clean_operation, model)
    price = round(float(value), 4)
    if not 0 <= price <= 100_000:
        raise ValueError("Цена Suno должна быть от 0 до 100000")
    await set_bot_setting(
        _setting_key(clean_channel, clean_operation, variant),
        price,
        updated_by_telegram_id=updated_by_telegram_id,
    )
    return price


async def list_suno_prices(channel: str) -> list[SunoPriceEntry]:
    clean_channel = _validate_channel(channel)
    entries: list[SunoPriceEntry] = []
    for operation in SUNO_OPERATIONS:
        variants = SUNO_MODELS if operation in MODEL_PRICED_OPERATIONS else ("default",)
        for variant in variants:
            default = default_suno_price(clean_channel, operation, variant)
            raw = await get_bot_setting(
                _setting_key(clean_channel, operation, variant),
                default=None,
            )
            overridden = raw not in (None, "")
            price = await get_suno_price(
                clean_channel,
                operation,
                variant if operation in MODEL_PRICED_OPERATIONS else None,
            )
            entries.append(
                SunoPriceEntry(
                    channel=clean_channel,
                    operation=operation,
                    variant=variant,
                    price=price,
                    overridden=overridden and abs(price - default) >= 0,
                )
            )
    return entries


async def copy_suno_prices(
    source_channel: str,
    target_channel: str,
    *,
    updated_by_telegram_id: int | None = None,
) -> int:
    source = _validate_channel(source_channel)
    target = _validate_channel(target_channel)
    if source == target:
        return 0
    changed = 0
    for entry in await list_suno_prices(source):
        await set_suno_price(
            target,
            entry.operation,
            entry.price,
            model=(entry.variant if entry.operation in MODEL_PRICED_OPERATIONS else None),
            updated_by_telegram_id=updated_by_telegram_id,
        )
        changed += 1
    return changed
