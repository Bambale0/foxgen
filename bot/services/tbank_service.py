import logging
from typing import Any, Dict, Optional

from bot.config import config
from tbank_payment.client import TBankAsyncClient
from tbank_payment.config import TBankConfig
from tbank_payment.models import GetStateRequest, InitPaymentRequest
from tbank_payment.webhooks import WebhookHandler

logger = logging.getLogger(__name__)


class TBankService:
    """Обертка над TBankAsyncClient для совместимости с текущим кодом бота"""

    def __init__(self, terminal_key: str, secret_key: str, api_url: str = None):
        self.terminal_key = terminal_key
        self.secret_key = secret_key
        self.api_url = api_url or config.TBANK_API_URL
        self.client = TBankAsyncClient(
            config=TBankConfig(
                terminal_key=terminal_key,
                password=secret_key,
                base_url=self.api_url,
            ),
        )
        self.webhook_handler = WebhookHandler(secret_key)

    async def init_payment(
        self,
        amount: int,  # в копейках
        order_id: str,
        description: str,
        customer_key: str,
        success_url: str,
        fail_url: str,
        notification_url: str,
        data: Optional[Dict] = None,
    ) -> Optional[Dict]:
        """Инициализация платежа (совместимый интерфейс)"""
        request = InitPaymentRequest(
            Amount=amount,
            OrderId=order_id,
            Description=description,
            CustomerKey=customer_key,
            SuccessURL=success_url,
            FailURL=fail_url,
            NotificationURL=notification_url,
            DATA=data,
            PayType="O",  # Одностадийная
            Language="ru",
        )
        result = await self.client.init_payment(request)
        return result.model_dump() if hasattr(result, "model_dump") else result

    async def get_state(self, payment_id: str) -> Optional[Dict]:
        """Проверка статуса платежа"""
        result = await self.client.get_state(payment_id)
        return result.model_dump() if hasattr(result, "model_dump") else result

    async def cancel(self, payment_id: str) -> Optional[Dict]:
        """Отмена платежа"""
        result = await self.client.cancel_payment(payment_id)
        return result.model_dump() if hasattr(result, "model_dump") else result

    def verify_notification(self, data: Dict[str, Any]) -> bool:
        """Проверка подписи уведомления"""
        return self.webhook_handler.validate_notification(data)


# Создаём сервис (совместимость с текущим кодом)
tbank_service = TBankService(
    terminal_key=config.TBANK_TERMINAL_KEY,
    secret_key=config.TBANK_SECRET_KEY,
)
