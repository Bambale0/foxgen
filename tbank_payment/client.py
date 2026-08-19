"""Клиент для работы с API Т-Банка"""

import datetime
import json
import logging
from typing import Any, Dict, Optional

import aiohttp
import requests

from .config import TBankConfig
from .exceptions import (
    TBankAPIError,
    TBankAuthError,
    TBankNetworkError,
    TBankValidationError,
)
from .models import (
    CancelRequest,
    CancelResponse,
    ChargeRequest,
    ChargeResponse,
    ConfirmRequest,
    ConfirmResponse,
    FinishAuthorizeRequest,
    FinishAuthorizeResponse,
    GetStateRequest,
    GetStateResponse,
    InitPaymentRequest,
    InitPaymentResponse,
    Receipt,
    SendClosingReceiptRequest,
    SendClosingReceiptResponse,
)
from .utils import amount_to_coins, format_datetime, prepare_request_data

logger = logging.getLogger(__name__)


class TBankPaymentClient:
    """Синхронный клиент для API платежей Т-Банка"""

    def __init__(
        self,
        config: Optional[TBankConfig] = None,
        terminal_key: Optional[str] = None,
        password: Optional[str] = None,
    ):
        """
        Инициализация клиента

        Args:
            config: Объект конфигурации
            terminal_key: Terminal Key (если не передан config)
            password: Пароль (если не передан config)
        """
        if config:
            self.config = config
        elif terminal_key and password:
            self.config = TBankConfig(terminal_key=terminal_key, password=password)
        else:
            self.config = TBankConfig.from_env()

        self.session = requests.Session()
        self.session.headers.update(
            {"Content-Type": "application/json", "Accept": "application/json"}
        )

    def _make_request(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Выполнение запроса к API"""
        url = f"{self.config.base_url.rstrip('/')}/{endpoint}"

        # Добавляем подпись (важно: токен генерируется до сериализации!)
        signed_data = prepare_request_data(
            data, self.config.terminal_key, self.config.password
        )

        logger.debug(
            f"Request to {endpoint}: {json.dumps(signed_data, ensure_ascii=False, default=str)}"
        )

        try:
            response = self.session.post(url, json=signed_data, timeout=30)
            response.raise_for_status()
            result = response.json()

            logger.debug(
                f"Response from {endpoint}: {json.dumps(result, ensure_ascii=False)}"
            )

            # Проверка на ошибки API
            if not result.get("Success", False):
                error_code = result.get("ErrorCode", "0")
                error_msg = result.get("Message", "Unknown error")

                if error_code == "0":
                    raise TBankAuthError(
                        f"Authentication failed: {error_msg}", error_code
                    )
                elif error_code in ["1", "2", "3"]:
                    raise TBankValidationError(
                        f"Validation error: {error_msg}", error_code
                    )
                else:
                    raise TBankAPIError(f"API error: {error_msg}", error_code)

            return result

        except requests.exceptions.RequestException as e:
            logger.error(f"Network error: {e}")
            raise TBankNetworkError(f"Network error: {str(e)}")

    def init_payment(self, request: InitPaymentRequest) -> InitPaymentResponse:
        """
        Инициализация платежа (получение PaymentURL для платежной формы Т-Банка)

        Args:
            request: Данные для инициализации платежа

        Returns:
            InitPaymentResponse с URL для оплаты
        """
        # Добавляем URL из конфига, если не указаны в запросе
        data = request.model_dump(by_alias=True, exclude_none=True)

        if not data.get("NotificationURL") and self.config.notification_url:
            data["NotificationURL"] = self.config.notification_url
        if not data.get("SuccessURL") and self.config.success_url:
            data["SuccessURL"] = self.config.success_url
        if not data.get("FailURL") and self.config.fail_url:
            data["FailURL"] = self.config.fail_url

        result = self._make_request("Init", data)
        return InitPaymentResponse.model_validate(result)

    def finish_authorize(
        self, request: FinishAuthorizeRequest
    ) -> FinishAuthorizeResponse:
        """
        Завершение авторизации (для собственной платежной формы)

        Используется для:
        - Одностадийной оплаты (сразу списывает деньги)
        - Двухстадийной оплаты (блокирует деньги)

        Args:
            request: Данные для завершения авторизации

        Returns:
            FinishAuthorizeResponse
        """
        data = request.model_dump(by_alias=True, exclude_none=True)
        result = self._make_request("FinishAuthorize", data)
        return FinishAuthorizeResponse.model_validate(result)

    def get_state(self, payment_id: str, ip: Optional[str] = None) -> GetStateResponse:
        """
        Получение состояния платежа

        Args:
            payment_id: ID платежа
            ip: IP-адрес покупателя (опционально)

        Returns:
            GetStateResponse с информацией о платеже
        """
        request = GetStateRequest(PaymentId=payment_id, IP=ip)
        data = request.model_dump(by_alias=True, exclude_none=True)
        result = self._make_request("GetState", data)
        return GetStateResponse.model_validate(result)

    def cancel_payment(
        self, payment_id: str, amount: Optional[int] = None
    ) -> CancelResponse:
        """
        Отмена платежа (возврат)

        Args:
            payment_id: ID платежа
            amount: Сумма для возврата (в копейках), если частичный возврат

        Returns:
            CancelResponse
        """
        request = CancelRequest(PaymentId=payment_id, Amount=amount)
        data = request.model_dump(by_alias=True, exclude_none=True)
        result = self._make_request("Cancel", data)
        return CancelResponse.model_validate(result)

    def confirm_payment(
        self,
        payment_id: str,
        amount: Optional[int] = None,
        receipt: Optional[Receipt] = None,
    ) -> ConfirmResponse:
        """
        Подтверждение платежа (двухстадийная оплата)

        Args:
            payment_id: ID платежа
            amount: Сумма для подтверждения (если отличается от исходной)
            receipt: Чек для отправки

        Returns:
            ConfirmResponse
        """
        request = ConfirmRequest(PaymentId=payment_id, Amount=amount, Receipt=receipt)
        data = request.model_dump(by_alias=True, exclude_none=True)
        result = self._make_request("Confirm", data)
        return ConfirmResponse.model_validate(result)

    def charge_recurrent(
        self,
        rebill_id: str,
        amount: float,
        order_id: str,
        send_email: bool = False,
        info_email: Optional[str] = None,
        description: Optional[str] = None,
    ) -> ChargeResponse:
        """
        Рекуррентный платеж (повторное списание по сохраненной карте)

        Args:
            rebill_id: ID рекуррентного платежа (получен при первой оплате)
            amount: Сумма в рублях
            order_id: ID заказа
            send_email: Отправлять ли email
            info_email: Email для уведомления
            description: Описание платежа

        Returns:
            ChargeResponse
        """
        request = ChargeRequest(
            RebillId=rebill_id,
            Amount=amount_to_coins(amount),
            OrderId=order_id,
            SendEmail=send_email,
            InfoEmail=info_email,
            Description=description,
        )
        data = request.model_dump(by_alias=True, exclude_none=True)
        result = self._make_request("Charge", data)
        return ChargeResponse.model_validate(result)

    def send_closing_receipt(
        self, payment_id: str, receipt: Receipt
    ) -> SendClosingReceiptResponse:
        """
        Отправка закрывающего чека в кассу

        Args:
            payment_id: ID платежа
            receipt: Данные чека

        Returns:
            SendClosingReceiptResponse
        """
        request = SendClosingReceiptRequest(PaymentId=payment_id, Receipt=receipt)
        data = request.model_dump(by_alias=True, exclude_none=True)

        # Отдельный endpoint для чеков
        url = f"{self.config.base_url.rstrip('/').replace('/v2', '')}/cashbox/SendClosingReceipt"

        signed_data = prepare_request_data(
            data, self.config.terminal_key, self.config.password
        )

        try:
            response = self.session.post(url, json=signed_data, timeout=30)
            response.raise_for_status()
            result = response.json()

            if not result.get("Success", False):
                error_code = result.get("ErrorCode", "0")
                error_msg = result.get("Message", "Unknown error")
                raise TBankAPIError(f"Receipt error: {error_msg}", error_code)

            return SendClosingReceiptResponse.model_validate(result)

        except requests.exceptions.RequestException as e:
            raise TBankNetworkError(f"Network error: {str(e)}")

    def resend_notifications(self) -> Dict[str, Any]:
        """
        Повторная отправка неполученных уведомлений

        Returns:
            Dict с количеством отправленных уведомлений
        """
        data = {}
        return self._make_request("Resend", data)

    def create_payment_url(
        self,
        amount: float,
        order_id: str,
        description: Optional[str] = None,
        customer_key: Optional[str] = None,
        recurrent: bool = False,
        receipt: Optional[Receipt] = None,
        redirect_due_date: Optional[datetime.datetime] = None,
    ) -> str:
        """
        Быстрое создание платежа и получение URL для оплаты

        Args:
            amount: Сумма в рублях
            order_id: Уникальный ID заказа
            description: Описание платежа
            customer_key: ID клиента (для рекуррентных)
            recurrent: Сделать платеж рекуррентным
            receipt: Данные чека
            redirect_due_date: Срок жизни ссылки

        Returns:
            URL для перехода на страницу оплаты

        Raises:
            TBankAPIError: если не удалось создать платеж
        """
        request = InitPaymentRequest(
            Amount=amount_to_coins(amount),
            OrderId=order_id,
            Description=description,
            CustomerKey=customer_key,
            Recurrent="Y" if recurrent else None,
            Receipt=receipt,
            RedirectDueDate=(
                format_datetime(redirect_due_date) if redirect_due_date else None
            ),
        )

        response = self.init_payment(request)

        if not response.success or not response.payment_url:
            raise TBankAPIError(
                f"Failed to create payment: {response.error_message}",
                response.error_code,
            )

        return response.payment_url


class TBankAsyncClient:
    """Асинхронный клиент для API платежей Т-Банка"""

    def __init__(
        self,
        config: Optional[TBankConfig] = None,
        terminal_key: Optional[str] = None,
        password: Optional[str] = None,
    ):
        if config:
            self.config = config
        elif terminal_key and password:
            self.config = TBankConfig(terminal_key=terminal_key, password=password)
        else:
            self.config = TBankConfig.from_env()

        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Получение или создание сессии"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                }
            )
        return self._session

    async def _make_request(
        self, endpoint: str, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Асинхронное выполнение запроса"""
        url = f"{self.config.base_url.rstrip('/')}/{endpoint}"

        signed_data = prepare_request_data(
            data, self.config.terminal_key, self.config.password
        )

        session = await self._get_session()

        try:
            async with session.post(url, json=signed_data, timeout=30) as response:
                response.raise_for_status()
                result = await response.json()

                if not result.get("Success", False):
                    error_code = result.get("ErrorCode", "0")
                    error_msg = result.get("Message", "Unknown error")

                    if error_code == "0":
                        raise TBankAuthError(
                            f"Authentication failed: {error_msg}", error_code
                        )
                    elif error_code in ["1", "2", "3"]:
                        raise TBankValidationError(
                            f"Validation error: {error_msg}", error_code
                        )
                    else:
                        raise TBankAPIError(f"API error: {error_msg}", error_code)

                return result

        except aiohttp.ClientError as e:
            raise TBankNetworkError(f"Network error: {str(e)}")

    async def init_payment(self, request: InitPaymentRequest) -> InitPaymentResponse:
        """Асинхронная инициализация платежа"""
        data = request.model_dump(by_alias=True, exclude_none=True)

        if not data.get("NotificationURL") and self.config.notification_url:
            data["NotificationURL"] = self.config.notification_url
        if not data.get("SuccessURL") and self.config.success_url:
            data["SuccessURL"] = self.config.success_url
        if not data.get("FailURL") and self.config.fail_url:
            data["FailURL"] = self.config.fail_url

        result = await self._make_request("Init", data)
        return InitPaymentResponse.model_validate(result)

    async def finish_authorize(
        self, request: FinishAuthorizeRequest
    ) -> FinishAuthorizeResponse:
        """Асинхронное завершение авторизации"""
        data = request.model_dump(by_alias=True, exclude_none=True)
        result = await self._make_request("FinishAuthorize", data)
        return FinishAuthorizeResponse.model_validate(result)

    async def get_state(
        self, payment_id: str, ip: Optional[str] = None
    ) -> GetStateResponse:
        """Асинхронное получение состояния платежа"""
        request = GetStateRequest(PaymentId=payment_id, IP=ip)
        data = request.model_dump(by_alias=True, exclude_none=True)
        result = await self._make_request("GetState", data)
        return GetStateResponse.model_validate(result)

    async def cancel_payment(
        self, payment_id: str, amount: Optional[int] = None
    ) -> CancelResponse:
        """Асинхронная отмена платежа"""
        request = CancelRequest(PaymentId=payment_id, Amount=amount)
        data = request.model_dump(by_alias=True, exclude_none=True)
        result = await self._make_request("Cancel", data)
        return CancelResponse.model_validate(result)

    async def confirm_payment(
        self,
        payment_id: str,
        amount: Optional[int] = None,
        receipt: Optional[Receipt] = None,
    ) -> ConfirmResponse:
        """Асинхронное подтверждение платежа"""
        request = ConfirmRequest(PaymentId=payment_id, Amount=amount, Receipt=receipt)
        data = request.model_dump(by_alias=True, exclude_none=True)
        result = await self._make_request("Confirm", data)
        return ConfirmResponse.model_validate(result)

    async def charge_recurrent(
        self,
        rebill_id: str,
        amount: float,
        order_id: str,
        send_email: bool = False,
        info_email: Optional[str] = None,
        description: Optional[str] = None,
    ) -> ChargeResponse:
        """Асинхронный рекуррентный платеж"""
        request = ChargeRequest(
            RebillId=rebill_id,
            Amount=amount_to_coins(amount),
            OrderId=order_id,
            SendEmail=send_email,
            InfoEmail=info_email,
            Description=description,
        )
        data = request.model_dump(by_alias=True, exclude_none=True)
        result = await self._make_request("Charge", data)
        return ChargeResponse.model_validate(result)

    async def send_closing_receipt(
        self, payment_id: str, receipt: Receipt
    ) -> SendClosingReceiptResponse:
        """Асинхронная отправка закрывающего чека"""
        request = SendClosingReceiptRequest(PaymentId=payment_id, Receipt=receipt)
        data = request.model_dump(by_alias=True, exclude_none=True)

        url = f"{self.config.base_url.replace('/v2', '')}/cashbox/SendClosingReceipt"
        signed_data = prepare_request_data(
            data, self.config.terminal_key, self.config.password
        )

        session = await self._get_session()

        try:
            async with session.post(url, json=signed_data, timeout=30) as response:
                response.raise_for_status()
                result = await response.json()

                if not result.get("Success", False):
                    error_code = result.get("ErrorCode", "0")
                    error_msg = result.get("Message", "Unknown error")
                    raise TBankAPIError(f"Receipt error: {error_msg}", error_code)

                return SendClosingReceiptResponse.model_validate(result)

        except aiohttp.ClientError as e:
            raise TBankNetworkError(f"Network error: {str(e)}")

    async def create_payment_url(
        self,
        amount: float,
        order_id: str,
        description: Optional[str] = None,
        customer_key: Optional[str] = None,
        recurrent: bool = False,
        receipt: Optional[Receipt] = None,
        redirect_due_date: Optional[datetime.datetime] = None,
    ) -> str:
        """Асинхронное создание платежа и получение URL"""
        request = InitPaymentRequest(
            Amount=amount_to_coins(amount),
            OrderId=order_id,
            Description=description,
            CustomerKey=customer_key,
            Recurrent="Y" if recurrent else None,
            Receipt=receipt,
            RedirectDueDate=(
                format_datetime(redirect_due_date) if redirect_due_date else None
            ),
        )

        response = await self.init_payment(request)

        if not response.success or not response.payment_url:
            raise TBankAPIError(
                f"Failed to create payment: {response.error_message}",
                response.error_code,
            )

        return response.payment_url

    async def close(self):
        """Закрытие сессии"""
        if self._session and not self._session.closed:
            await self._session.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
