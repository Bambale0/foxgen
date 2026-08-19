"""Обработка webhook-уведомлений от Т-Банка"""

import json
import logging
from typing import Any, Callable, Dict, Optional, Union

from .exceptions import TBankValidationError
from .models import Notification
from .utils import generate_token

logger = logging.getLogger(__name__)


class WebhookHandler:
    """Обработчик webhook-уведомлений"""

    def __init__(self, password: str):
        self.password = password
        self._handlers: Dict[str, Callable] = {}

    def on(self, status: str, handler: Callable[[Notification], None]):
        """
        Регистрация обработчика для статуса

        Args:
            status: Статус платежа (например, "CONFIRMED", "CANCELED", "AUTHORIZED")
            handler: Функция-обработчик

        Returns:
            handler (для использования как декоратор)
        """
        self._handlers[status] = handler
        return handler

    def validate_notification(self, data: Dict[str, Any]) -> bool:
        """
        Валидация подписи уведомления

        Важно: в уведомлении вложенные объекты не участвуют в подписи!

        Args:
            data: Данные уведомления

        Returns:
            True если подпись валидна
        """
        if "Token" not in data:
            return False

        received_token = data["Token"]
        calculated_token = generate_token(data, self.password)

        return received_token == calculated_token

    def parse_notification(self, body: Union[str, Dict[str, Any]]) -> Notification:
        """
        Парсинг и валидация уведомления

        Args:
            body: JSON-строка или dict с данными

        Returns:
            Notification объект

        Raises:
            TBankValidationError: если подпись невалидна
        """
        if isinstance(body, str):
            data = json.loads(body)
        else:
            data = body

        if not self.validate_notification(data):
            raise TBankValidationError("Invalid notification signature")

        return Notification.model_validate(data)

    def handle(self, body: Union[str, Dict[str, Any]]) -> Notification:
        """
        Обработка уведомления с вызовом зарегистрированных хендлеров

        Args:
            body: Данные уведомления

        Returns:
            Notification объект
        """
        notification = self.parse_notification(body)

        # Вызываем специфичный обработчик
        handler = self._handlers.get(notification.status.value)
        if handler:
            try:
                handler(notification)
            except Exception as e:
                logger.error(f"Error in webhook handler for {notification.status}: {e}")

        # Вызываем универсальный обработчик, если есть
        universal_handler = self._handlers.get("*")
        if universal_handler:
            try:
                universal_handler(notification)
            except Exception as e:
                logger.error(f"Error in universal webhook handler: {e}")

        return notification

    def get_success_response(self) -> str:
        """Возвращает успешный ответ для Т-Банка"""
        return json.dumps({"Success": True})

    def get_error_response(self, message: str = "Error") -> str:
        """Возвращает ответ об ошибке"""
        return json.dumps({"Success": False, "Message": message})
