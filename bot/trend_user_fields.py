from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

MAX_USER_FIELDS = 6
MAX_FIELD_KEY_LENGTH = 48
MAX_FIELD_LABEL_LENGTH = 64
MAX_FIELD_VALUE_LENGTH = 160
DEFAULT_TEXT_MAX_LENGTH = 80

_NUMBER_RE = re.compile(r"^-?\d+(?:[\.,]\d+)?$")
_TEMPLATE_RE = re.compile(r"\{\{([^{}]{1,64})\}\}")


class TrendUserFieldsError(ValueError):
    """User-safe validation error for configurable trend fields."""


@dataclass(frozen=True)
class TrendUserFieldSpec:
    key: str
    label: str
    field_type: str
    required: bool
    placeholder: str
    min_value: Decimal | None
    max_value: Decimal | None
    max_length: int


def clean_submitted_user_values(raw_values: Any) -> dict[str, str]:
    if raw_values in (None, ""):
        return {}
    if not isinstance(raw_values, Mapping):
        raise TrendUserFieldsError("Некорректные дополнительные поля тренда")
    if len(raw_values) > MAX_USER_FIELDS:
        raise TrendUserFieldsError("Слишком много дополнительных полей")

    cleaned: dict[str, str] = {}
    for raw_key, raw_value in raw_values.items():
        key = str(raw_key or "").strip()
        if not key or len(key) > MAX_FIELD_KEY_LENGTH or "{{" in key or "}}" in key:
            raise TrendUserFieldsError("Некорректное дополнительное поле")
        if isinstance(raw_value, (Mapping, list, tuple, set)):
            raise TrendUserFieldsError(f"Некорректное значение поля «{key}»")
        value = str(raw_value if raw_value is not None else "").strip()
        if len(value) > MAX_FIELD_VALUE_LENGTH:
            raise TrendUserFieldsError(f"Слишком длинное значение поля «{key}»")
        cleaned[key] = value
    return cleaned


def _decimal_setting(raw_value: Any, *, field_label: str) -> Decimal | None:
    if raw_value in (None, ""):
        return None
    try:
        return Decimal(str(raw_value))
    except (InvalidOperation, ValueError):
        raise TrendUserFieldsError(
            f"Некорректные ограничения поля «{field_label}»"
        ) from None


def _field_specs(settings: Mapping[str, Any]) -> tuple[TrendUserFieldSpec, ...]:
    raw_fields = settings.get("user_fields")
    if raw_fields in (None, ""):
        return ()
    if not isinstance(raw_fields, list):
        raise TrendUserFieldsError("Поля тренда настроены неверно")
    if len(raw_fields) > MAX_USER_FIELDS:
        raise TrendUserFieldsError("У тренда настроено слишком много полей")

    specs: list[TrendUserFieldSpec] = []
    seen: set[str] = set()
    for raw_field in raw_fields:
        if not isinstance(raw_field, Mapping):
            raise TrendUserFieldsError("Поля тренда настроены неверно")
        key = str(raw_field.get("key") or "").strip()
        label = str(raw_field.get("label") or key).strip()
        field_type = str(raw_field.get("type") or "text").strip().lower()
        if (
            not key
            or len(key) > MAX_FIELD_KEY_LENGTH
            or "{{" in key
            or "}}" in key
            or key in seen
        ):
            raise TrendUserFieldsError("Поля тренда настроены неверно")
        if not label or len(label) > MAX_FIELD_LABEL_LENGTH:
            raise TrendUserFieldsError("Поля тренда настроены неверно")
        if field_type not in {"text", "number"}:
            raise TrendUserFieldsError(f"Неизвестный тип поля «{label}»")

        try:
            max_length = int(raw_field.get("max_length") or DEFAULT_TEXT_MAX_LENGTH)
        except (TypeError, ValueError):
            max_length = DEFAULT_TEXT_MAX_LENGTH
        max_length = max(1, min(MAX_FIELD_VALUE_LENGTH, max_length))
        min_value = _decimal_setting(raw_field.get("min"), field_label=label)
        max_value = _decimal_setting(raw_field.get("max"), field_label=label)
        if min_value is not None and max_value is not None and min_value > max_value:
            raise TrendUserFieldsError(f"Некорректные ограничения поля «{label}»")

        specs.append(
            TrendUserFieldSpec(
                key=key,
                label=label,
                field_type=field_type,
                required=bool(raw_field.get("required", True)),
                placeholder=str(raw_field.get("placeholder") or "").strip()[:80],
                min_value=min_value,
                max_value=max_value,
                max_length=max_length,
            )
        )
        seen.add(key)
    return tuple(specs)


def _validated_field_value(spec: TrendUserFieldSpec, raw_value: str) -> str:
    value = str(raw_value or "").strip()
    if not value:
        if spec.required:
            raise TrendUserFieldsError(f"Заполните поле «{spec.label}»")
        return ""

    if spec.field_type == "number":
        if not _NUMBER_RE.fullmatch(value):
            raise TrendUserFieldsError(f"Поле «{spec.label}» должно быть числом")
        try:
            number = Decimal(value.replace(",", "."))
        except InvalidOperation:
            raise TrendUserFieldsError(f"Поле «{spec.label}» должно быть числом") from None
        if spec.min_value is not None and number < spec.min_value:
            raise TrendUserFieldsError(
                f"Поле «{spec.label}» должно быть не меньше {spec.min_value:g}"
            )
        if spec.max_value is not None and number > spec.max_value:
            raise TrendUserFieldsError(
                f"Поле «{spec.label}» должно быть не больше {spec.max_value:g}"
            )
        return value

    if len(value) > spec.max_length:
        raise TrendUserFieldsError(
            f"Поле «{spec.label}» должно быть короче {spec.max_length + 1} символов"
        )
    return value


def normalize_trend_user_fields(raw_fields: Any, *, prompt: str) -> list[dict[str, Any]]:
    specs = _field_specs({"user_fields": raw_fields})
    normalized: list[dict[str, Any]] = []
    for spec in specs:
        token = "{{" + spec.key + "}}"
        if token not in prompt:
            raise TrendUserFieldsError(f"Добавьте {token} в скрытый prompt")
        item: dict[str, Any] = {
            "key": spec.key,
            "label": spec.label,
            "type": spec.field_type,
            "required": spec.required,
            "placeholder": spec.placeholder,
        }
        if spec.field_type == "text":
            item["max_length"] = spec.max_length
        else:
            if spec.min_value is not None:
                item["min"] = float(spec.min_value) if spec.min_value % 1 else int(spec.min_value)
            if spec.max_value is not None:
                item["max"] = float(spec.max_value) if spec.max_value % 1 else int(spec.max_value)
        normalized.append(item)
    return normalized


def render_trend_prompt(
    prompt: str,
    settings: Mapping[str, Any],
    user_values: Mapping[str, str] | None = None,
) -> str:
    values = dict(user_values or {})
    specs = _field_specs(settings)
    if not specs:
        if values:
            raise TrendUserFieldsError("Этот тренд не принимает дополнительные поля")
        return prompt

    allowed = {spec.key for spec in specs}
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise TrendUserFieldsError("Переданы лишние поля тренда")

    rendered = prompt
    for spec in specs:
        token = "{{" + spec.key + "}}"
        if token not in rendered:
            raise TrendUserFieldsError(
                f"Поле «{spec.label}» не подключено к шаблону. Сообщите администратору."
            )
        value = _validated_field_value(spec, values.get(spec.key, ""))
        rendered = rendered.replace(token, value)

    unresolved = _TEMPLATE_RE.search(rendered)
    if unresolved:
        raise TrendUserFieldsError(
            f"Шаблон содержит незаполненное поле «{unresolved.group(1).strip()}»"
        )
    return rendered.strip()
