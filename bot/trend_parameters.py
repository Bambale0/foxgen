from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

MAX_TEMPLATE_FIELDS = 8
MAX_TEMPLATE_VALUE_LENGTH = 120

_PLACEHOLDER_RE = re.compile(
    r"{{\s*(?P<key>[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё0-9_]{0,31})\s*}}"
)
_NUMBER_RE = re.compile(r"^-?\d{1,9}(?:[.,]\d{1,4})?$")
_DATE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2}|[0-3]?\d[./-][01]?\d[./-]\d{2,4})$"
)

FieldType = Literal["text", "number", "date"]


class TrendParameterValidationError(ValueError):
    """Raised when a trend template parameter payload is invalid."""


@dataclass(frozen=True)
class TrendTemplateField:
    key: str
    label: str
    field_type: FieldType
    placeholder: str
    max_length: int = MAX_TEMPLATE_VALUE_LENGTH

    def public_payload(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "type": self.field_type,
            "required": True,
            "placeholder": self.placeholder,
            "max_length": self.max_length,
        }


_FIELD_ALIASES: dict[str, tuple[str, FieldType, str]] = {
    "age": ("Возраст", "number", "Например, 28"),
    "возраст": ("Возраст", "number", "Например, 28"),
    "name": ("Имя", "text", "Например, Анна"),
    "имя": ("Имя", "text", "Например, Анна"),
    "date": ("Дата", "date", "Выберите дату"),
    "дата": ("Дата", "date", "Выберите дату"),
    "year": ("Год", "number", "Например, 2026"),
    "год": ("Год", "number", "Например, 2026"),
    "number": ("Число", "number", "Введите число"),
    "число": ("Число", "number", "Введите число"),
    "city": ("Город", "text", "Например, Санкт-Петербург"),
    "город": ("Город", "text", "Например, Санкт-Петербург"),
    "country": ("Страна", "text", "Например, Россия"),
    "страна": ("Страна", "text", "Например, Россия"),
    "profession": ("Профессия", "text", "Например, дизайнер"),
    "профессия": ("Профессия", "text", "Например, дизайнер"),
}


def _field_metadata(key: str) -> tuple[str, FieldType, str]:
    normalized = key.casefold()
    known = _FIELD_ALIASES.get(normalized)
    if known:
        return known
    label = key.replace("_", " ").strip().capitalize() or "Значение"
    return label, "text", f"Введите {label.lower()}"


def extract_trend_template_fields(prompt: str) -> tuple[TrendTemplateField, ...]:
    """Extract unique user-editable placeholders from a hidden trend prompt."""

    clean_prompt = str(prompt or "")
    fields: list[TrendTemplateField] = []
    seen: set[str] = set()
    for match in _PLACEHOLDER_RE.finditer(clean_prompt):
        key = str(match.group("key") or "").strip()
        normalized = key.casefold()
        if not key or normalized in seen:
            continue
        seen.add(normalized)
        label, field_type, placeholder = _field_metadata(key)
        fields.append(
            TrendTemplateField(
                key=key,
                label=label,
                field_type=field_type,
                placeholder=placeholder,
            )
        )
        if len(fields) > MAX_TEMPLATE_FIELDS:
            raise TrendParameterValidationError(
                f"В одном тренде можно использовать не больше {MAX_TEMPLATE_FIELDS} полей"
            )
    return tuple(fields)


def public_trend_template_fields(prompt: str) -> list[dict[str, Any]]:
    """Return safe UI schema without allowing one bad legacy trend to break the catalog."""

    try:
        fields = extract_trend_template_fields(prompt)
    except TrendParameterValidationError:
        return []
    return [field.public_payload() for field in fields]


def _clean_value(field: TrendTemplateField, raw_value: Any) -> str:
    if isinstance(raw_value, bool) or raw_value is None:
        value = ""
    else:
        value = str(raw_value).strip()
    if not value:
        raise TrendParameterValidationError(f"Заполните поле «{field.label}»")
    if len(value) > field.max_length:
        raise TrendParameterValidationError(
            f"Поле «{field.label}» слишком длинное. Максимум {field.max_length} символов"
        )
    if any(ord(char) < 32 and char not in {"\t"} for char in value):
        raise TrendParameterValidationError(
            f"Поле «{field.label}» содержит недопустимые символы"
        )
    if "\n" in value or "\r" in value:
        raise TrendParameterValidationError(
            f"Поле «{field.label}» должно быть в одну строку"
        )

    if field.field_type == "number":
        if not _NUMBER_RE.fullmatch(value):
            raise TrendParameterValidationError(
                f"В поле «{field.label}» нужно указать число"
            )
        if field.key.casefold() in {"age", "возраст"}:
            try:
                age = int(value)
            except ValueError as exc:
                raise TrendParameterValidationError(
                    "Возраст должен быть целым числом"
                ) from exc
            if not 1 <= age <= 120:
                raise TrendParameterValidationError("Возраст должен быть от 1 до 120")
    elif field.field_type == "date" and not _DATE_RE.fullmatch(value):
        raise TrendParameterValidationError(
            f"Укажите корректную дату в поле «{field.label}»"
        )
    return value


def render_trend_prompt(prompt: str, raw_parameters: Any) -> str:
    """Render hidden prompt placeholders using validated user values only."""

    clean_prompt = str(prompt or "")
    fields = extract_trend_template_fields(clean_prompt)
    if not fields:
        if raw_parameters not in (None, {}, ""):
            if isinstance(raw_parameters, Mapping) and not raw_parameters:
                return clean_prompt
            raise TrendParameterValidationError(
                "У этого тренда нет пользовательских полей"
            )
        return clean_prompt

    if not isinstance(raw_parameters, Mapping):
        raise TrendParameterValidationError("Заполните параметры тренда")

    expected_by_key = {field.key.casefold(): field for field in fields}
    supplied: dict[str, Any] = {}
    for raw_key, raw_value in raw_parameters.items():
        key = str(raw_key or "").strip()
        normalized = key.casefold()
        if normalized not in expected_by_key:
            raise TrendParameterValidationError(
                "В запросе есть неизвестный параметр тренда"
            )
        supplied[normalized] = raw_value

    cleaned_values: dict[str, str] = {}
    for normalized, field in expected_by_key.items():
        cleaned_values[normalized] = _clean_value(field, supplied.get(normalized))

    def replace(match: re.Match[str]) -> str:
        key = str(match.group("key") or "").casefold()
        return cleaned_values[key]

    rendered = _PLACEHOLDER_RE.sub(replace, clean_prompt)
    if _PLACEHOLDER_RE.search(rendered):
        raise TrendParameterValidationError("Не все параметры тренда были заполнены")
    return rendered
