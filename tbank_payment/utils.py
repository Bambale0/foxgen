"""Утилиты для работы с API Т-Банка"""

import hashlib
import json
from typing import Any, Dict, List, Optional


def generate_token(data: Dict[str, Any], password: str) -> str:
    """
    Генерация токена для подписи запроса к API Т-Банка

    Алгоритм по документации:
    1. Собрать массив пар ключ:значение только корневых параметров
       (вложенные объекты и массивы НЕ участвуют!)
    2. Добавить {"Password": password}
    3. Отсортировать по ключу по алфавиту
    4. Конкатенировать только значения в одну строку
    5. SHA-256 хеш
    """
    # Берем только корневые параметры, исключаем вложенные объекты/массивы и Token
    filtered_data = {}
    for key, value in data.items():
        if key == "Token":
            continue
        # Пропускаем сложные объекты — они не участвуют в токене
        if isinstance(value, (dict, list)):
            continue
        if value is not None:
            filtered_data[key] = str(value)

    # Добавляем пароль
    filtered_data["Password"] = password

    # Сортируем по ключам
    sorted_items = sorted(filtered_data.items(), key=lambda x: x[0])

    # Конкатенируем только значения
    values_str = "".join([str(value) for _, value in sorted_items])

    # SHA-256
    return hashlib.sha256(values_str.encode("utf-8")).hexdigest()


def prepare_request_data(
    data: Dict[str, Any], terminal_key: str, password: str
) -> Dict[str, Any]:
    """Подготовка данных запроса с добавлением токена"""
    data = data.copy()
    data["TerminalKey"] = terminal_key
    data["Token"] = generate_token(data, password)
    return data


def amount_to_coins(amount: float) -> int:
    """Конвертация рублей в копейки"""
    return int(round(amount * 100))


def coins_to_amount(coins: int) -> float:
    """Конвертация копеек в рубли"""
    return coins / 100


def mask_pan(pan: Optional[str]) -> Optional[str]:
    """Маскировка номера карты"""
    if not pan or len(pan) < 4:
        return pan
    return "*" * (len(pan) - 4) + pan[-4:]


def format_datetime(dt) -> str:
    """Форматирование даты в формат YYYY-MM-DDTHH24:MI:SS+GMT"""
    if dt is None:
        return None
    # Формат: 2016-08-31T12:28:00+03:00
    return dt.strftime("%Y-%m-%dT%H:%M:%S%z")
