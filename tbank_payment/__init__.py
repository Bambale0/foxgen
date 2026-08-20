"""
T-Bank (Т-Банк) Payment Module
Универсальный модуль для интеграции с платежной системой Т-Касса
"""

from .client import TBankAsyncClient, TBankPaymentClient
from .config import TBankConfig
from .exceptions import (
    TBankAPIError,
    TBankAuthError,
    TBankNetworkError,
    TBankPaymentError,
    TBankValidationError,
)
from .models import (
    VAT,
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
    Notification,
    PaymentMethod,
    PaymentObject,
    PaymentStatus,
    Receipt,
    ReceiptItem,
    SendClosingReceiptRequest,
    SendClosingReceiptResponse,
    Taxation,
)
from .utils import amount_to_coins, coins_to_amount
from .webhooks import WebhookHandler

__version__ = "1.0.0"
__all__ = [
    "TBankPaymentClient",
    "TBankAsyncClient",
    "InitPaymentRequest",
    "InitPaymentResponse",
    "FinishAuthorizeRequest",
    "FinishAuthorizeResponse",
    "PaymentStatus",
    "Receipt",
    "ReceiptItem",
    "Notification",
    "CancelRequest",
    "CancelResponse",
    "ConfirmRequest",
    "ConfirmResponse",
    "GetStateRequest",
    "GetStateResponse",
    "ChargeRequest",
    "ChargeResponse",
    "SendClosingReceiptRequest",
    "SendClosingReceiptResponse",
    "Taxation",
    "VAT",
    "PaymentMethod",
    "PaymentObject",
    "TBankAPIError",
    "TBankAuthError",
    "TBankValidationError",
    "TBankPaymentError",
    "TBankNetworkError",
    "WebhookHandler",
    "TBankConfig",
    "amount_to_coins",
    "coins_to_amount",
]
