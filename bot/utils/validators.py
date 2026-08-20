"""
Validators for user input and data
"""

import re
from html import escape
from typing import Optional, Tuple


def validate_prompt(prompt: str, max_length: int = 1000) -> Tuple[bool, Optional[str]]:
    """
    Валидирует текстовый промпт

    Returns:
        Tuple[bool, Optional[str]]: (is_valid, error_message)
    """
    if not prompt or not prompt.strip():
        return False, "Промпт не может быть пустым"

    prompt = prompt.strip()

    if len(prompt) < 3:
        return False, "Промпт слишком короткий (минимум 3 символа)"

    if len(prompt) > max_length:
        return False, f"Промпт слишком длинный (максимум {max_length} символов)"

    # Проверка на потенциально вредный контент (базовая)
    forbidden_patterns = [
        r"<script",
        r"javascript:",
        r"on\w+\s*=",
    ]

    for pattern in forbidden_patterns:
        if re.search(pattern, prompt, re.IGNORECASE):
            return False, "Промпт содержит недопустимый контент"

    return True, None


def validate_image_size(
    size_bytes: int, max_mb: float = 10.0
) -> Tuple[bool, Optional[str]]:
    """
    Валидирует размер изображения

    Args:
        size_bytes: Размер в байтах
        max_mb: Максимальный размер в мегабайтах

    Returns:
        Tuple[bool, Optional[str]]: (is_valid, error_message)
    """
    max_bytes = int(max_mb * 1024 * 1024)

    if size_bytes == 0:
        return False, "Изображение пустое"

    if size_bytes > max_bytes:
        return False, f"Изображение слишком большое (максимум {max_mb} МБ)"

    if size_bytes < 100:
        return False, "Изображение слишком маленькое"

    return True, None


def sanitize_input(text: str, max_length: int = 500) -> str:
    """
    Очищает пользовательский ввод от потенциально опасного контента

    Args:
        text: Входной текст
        max_length: Максимальная длина

    Returns:
        Очищенная строка
    """
    if not text:
        return ""

    # Удаляем лишние пробелы
    text = " ".join(text.split())

    # Обрезаем до максимальной длины
    text = text[:max_length]

    # Экранируем HTML-теги
    text = escape(text)

    return text


def validate_telegram_id(user_id: int) -> bool:
    """
    Валидирует Telegram ID пользователя
    """
    return isinstance(user_id, int) and user_id > 0


def validate_credits_amount(amount: int) -> Tuple[bool, Optional[str]]:
    """
    Валидирует количество кредитов
    """
    if not isinstance(amount, int):
        return False, "Количество должно быть целым числом"

    if amount < 0:
        return False, "Количество не может быть отрицательным"

    if amount > 100000:
        return False, "Превышен лимит кредитов"

    return True, None


def validate_aspect_ratio(ratio: str) -> bool:
    """
    Валидирует соотношение сторон
    """
    valid_ratios = ["1:1", "16:9", "9:16", "3:4", "4:3", "21:9", "9:21", "3:2"]
    return ratio in valid_ratios


def validate_duration(duration: int) -> bool:
    """
    Валидирует длительность видео
    """
    return isinstance(duration, int) and 1 <= duration <= 60


_EXPLICIT_PROMPT_PATTERNS = [
    r"\b(nude|nudity|naked|nsfw|explicit|sexual|sex|porn|erotic|fetish)\b",
    r"\b(topless|see[- ]?through|cameltoe|nipples?|areola|genitals?|vagina|penis|boobs?|tits?|ass|butt)\b",
    r"\b(lingerie|underwear|thong|g[- ]?string)\b",
    r"\b(раздвин\w*\s+ног\w*|показыва\w*\s+(свои\s+)?трусик\w*|покажи\w*\s+(свои\s+)?трусик\w*|демонстриру\w*\s+(реалистичн\w*\s+)?вагин\w*|откровенн\w*\s+(сним\w*|фотограф\w*|фото|portrait|shot))\b",
    r"\b(эрот\w*|эротичн\w*|порно\w*|секс\w*|обнажен\w*|обнажён\w*|гол(?:ая|ые|ый|ое)|нага(?:я|яя|я)|наг(?:ой|ие|их)|откровенн\w*|гол\w*\s+груд\w*|сос(?:ок|ки|ков)|ягодиц\w*|вагин\w*|генитал\w*|полов\w*\s+орган\w*|трусик\w*|стринг\w*|нижн\w*\s+бель\w*)\b",
]


def detect_explicit_prompt_policy_violation(prompt: str) -> Optional[str]:
    """Detect clearly sexual/explicit prompts that should be rejected before provider calls."""
    normalized = " ".join((prompt or "").lower().split())
    if not normalized:
        return None
    for pattern in _EXPLICIT_PROMPT_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            return pattern
    return None
