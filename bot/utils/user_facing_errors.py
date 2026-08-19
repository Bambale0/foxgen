"""Helpers for turning backend/provider failures into friendly user text."""

from __future__ import annotations

import re


_PROVIDER_RE = re.compile(r"\b(?:kie\.ai|kie)\b", re.IGNORECASE)
_API_KEY_RE = re.compile(r"\b(api\s*key|KIE_AI_API_KEY|authorization)\b", re.IGNORECASE)
_OVERLOAD_RE = re.compile(
    r"(system load|too high|try again later|server exception|temporar|overload|busy)",
    re.IGNORECASE,
)
_MISSING_RESULT_RE = re.compile(
    r"(response did not include|task id missing|no taskId|missing task|unexpected result type)",
    re.IGNORECASE,
)
_REAL_PERSON_IMAGE_RE = re.compile(
    r"input image.*(?:may contain|contains?).*real person|real person.*input image",
    re.IGNORECASE,
)
_CONTENT_INDEX_RE = re.compile(r"content\[(\d+)]", re.IGNORECASE)


def make_user_friendly_generation_error(message: object | None) -> str | None:
    """Hide backend brand/details in errors shown to users."""
    if message is None:
        return None

    text = " ".join(str(message).split())
    if not text:
        return None

    if _API_KEY_RE.search(text):
        return "Сервис генерации временно недоступен. Мы уже видим проблему на нашей стороне."

    if _OVERLOAD_RE.search(text):
        return "Сервис генерации сейчас перегружен. Попробуйте ещё раз через минуту."

    if _MISSING_RESULT_RE.search(text):
        return "Сервис генерации не вернул готовый результат. Попробуйте ещё раз."

    if _REAL_PERSON_IMAGE_RE.search(text):
        match = _CONTENT_INDEX_RE.search(text)
        position = int(match.group(1)) + 1 if match else 1
        return (
            f"Seedance отклонил фото-референс №{position}: фильтр модели распознал "
            "на изображении возможного реального человека. Уточнение в промпте "
            "не меняет проверку самого изображения. Замените этот референс на "
            "явно вымышленного персонажа — например, иллюстрацию или 3D-рендер."
        )

    text = _PROVIDER_RE.sub("сервис генерации", text)
    text = re.sub(r"\bAPI error\b", "ошибка сервиса", text, flags=re.IGNORECASE)
    text = text.replace("API", "сервис")
    return text
