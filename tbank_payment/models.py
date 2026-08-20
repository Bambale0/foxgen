"""Pydantic модели для API Т-Банка"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


POPULATE_BY_NAME_CONFIG = ConfigDict(populate_by_name=True)


class PaymentStatus(str, Enum):
    """Статусы платежа"""

    NEW = "NEW"
    FORM_SHOWED = "FORM_SHOWED"
    DEADLINE_EXPIRED = "DEADLINE_EXPIRED"
    CANCELED = "CANCELED"
    AUTHORIZING = "AUTHORIZING"
    AUTHORIZED = "AUTHORIZED"
    AUTH_FAIL = "AUTH_FAIL"
    REJECTED = "REJECTED"
    THREE_DS_CHECKING = "3DS_CHECKING"
    THREE_DS_CHECKED = "3DS_CHECKED"
    REVERSING = "REVERSING"
    PARTIAL_REVERSED = "PARTIAL_REVERSED"
    REVERSED = "REVERSED"
    CONFIRMING = "CONFIRMING"
    CONFIRMED = "CONFIRMED"
    REFUNDING = "REFUNDING"
    ASYNC_REFUNDING = "ASYNC_REFUNDING"
    PARTIAL_REFUNDED = "PARTIAL_REFUNDED"
    REFUNDED = "REFUNDED"


class Taxation(str, Enum):
    """Системы налогообложения"""

    OSN = "osn"
    USN_INCOME = "usn_income"
    USN_INCOME_OUTCOME = "usn_income_outcome"
    ENVD = "envd"
    ESN = "esn"
    PATENT = "patent"


class VAT(str, Enum):
    """Ставки НДС"""

    NONE = "none"
    VAT0 = "vat0"
    VAT10 = "vat10"
    VAT20 = "vat20"
    VAT110 = "vat110"
    VAT120 = "vat120"


class PaymentMethod(str, Enum):
    """Способы расчета"""

    FULL_PAYMENT = "full_payment"
    FULL_PREPAYMENT = "full_prepayment"
    PREPAYMENT = "prepayment"
    ADVANCE = "advance"
    PARTIAL_PAYMENT = "partial_payment"
    CREDIT = "credit"
    CREDIT_PAYMENT = "credit_payment"


class PaymentObject(str, Enum):
    """Предметы расчета"""

    COMMODITY = "commodity"
    EXCISE = "excise"
    JOB = "job"
    SERVICE = "service"
    GAMBLING_BET = "gambling_bet"
    GAMBLING_PRIZE = "gambling_prize"
    LOTTERY = "lottery"
    LOTTERY_PRIZE = "lottery_prize"
    INTELLECTUAL_ACTIVITY = "intellectual_activity"
    PAYMENT = "payment"
    AGENT_COMMISSION = "agent_commission"
    COMPOSITE = "composite"
    ANOTHER = "another"


class ReceiptItem(BaseModel):
    """Позиция чека"""

    name: str = Field(..., alias="Name", max_length=128)
    quantity: float = Field(..., alias="Quantity", gt=0)
    amount: int = Field(..., alias="Amount", description="Сумма в копейках")
    price: int = Field(..., alias="Price", description="Цена в копейках")
    tax: VAT = Field(..., alias="Tax")
    payment_method: Optional[PaymentMethod] = Field(None, alias="PaymentMethod")
    payment_object: Optional[PaymentObject] = Field(None, alias="PaymentObject")
    ean13: Optional[str] = Field(None, alias="Ean13")
    shop_code: Optional[str] = Field(None, alias="ShopCode")

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v):
        if v <= 0:
            raise ValueError("Quantity must be positive")
        return v


class Receipt(BaseModel):
    """Чек"""

    items: List[ReceiptItem] = Field(..., alias="Items")
    taxation: Taxation = Field(..., alias="Taxation")
    email: Optional[str] = Field(None, alias="Email")
    phone: Optional[str] = Field(None, alias="Phone")
    email_company: Optional[str] = Field(None, alias="EmailCompany")

    model_config = POPULATE_BY_NAME_CONFIG


class ReceiptPayments(BaseModel):
    """Платежи в чеке (для SendClosingReceipt)"""

    cash: Optional[int] = Field(None, alias="Cash")
    electronic: Optional[int] = Field(None, alias="Electronic")
    advance_payment: Optional[int] = Field(None, alias="AdvancePayment")
    credit: Optional[int] = Field(None, alias="Credit")
    provision: Optional[int] = Field(None, alias="Provision")


class InitPaymentRequest(BaseModel):
    """Запрос на инициализацию платежа"""

    amount: int = Field(..., alias="Amount", description="Сумма в копейках")
    order_id: str = Field(..., alias="OrderId", max_length=36)
    description: Optional[str] = Field(None, alias="Description", max_length=140)
    customer_key: Optional[str] = Field(None, alias="CustomerKey", max_length=36)
    recurrent: Optional[str] = Field(None, alias="Recurrent", pattern="^Y$")
    language: Optional[str] = Field("ru", alias="Language", pattern="^(ru|en)$")
    pay_type: Optional[str] = Field(None, alias="PayType", pattern="^[OT]$")
    notification_url: Optional[str] = Field(None, alias="NotificationURL")
    success_url: Optional[str] = Field(None, alias="SuccessURL")
    fail_url: Optional[str] = Field(None, alias="FailURL")
    redirect_due_date: Optional[str] = Field(None, alias="RedirectDueDate")
    data: Optional[Dict[str, str]] = Field(None, alias="DATA")
    receipt: Optional[Receipt] = Field(None, alias="Receipt")

    model_config = POPULATE_BY_NAME_CONFIG


class InitPaymentResponse(BaseModel):
    """Ответ на инициализацию платежа"""

    success: bool = Field(..., alias="Success")
    error_code: Optional[str] = Field(None, alias="ErrorCode")
    error_message: Optional[str] = Field(None, alias="Message")
    terminal_key: Optional[str] = Field(None, alias="TerminalKey")
    status: Optional[PaymentStatus] = Field(None, alias="Status")
    payment_id: Optional[str] = Field(None, alias="PaymentId")
    order_id: Optional[str] = Field(None, alias="OrderId")
    amount: Optional[int] = Field(None, alias="Amount")
    payment_url: Optional[str] = Field(None, alias="PaymentURL")
    details: Optional[str] = Field(None, alias="Details")

    model_config = POPULATE_BY_NAME_CONFIG


class FinishAuthorizeRequest(BaseModel):
    """Запрос для завершения авторизации (своя платежная форма)"""

    payment_id: str = Field(..., alias="PaymentId")
    card_data: Optional[str] = Field(None, alias="CardData")
    encrypted_payment_data: Optional[str] = Field(None, alias="EncryptedPaymentData")
    send_email: Optional[bool] = Field(None, alias="SendEmail")
    info_email: Optional[str] = Field(None, alias="InfoEmail")
    ip: Optional[str] = Field(None, alias="IP")
    route: Optional[str] = Field(None, alias="Route")
    source: Optional[str] = Field(None, alias="Source")
    data: Optional[Dict[str, str]] = Field(None, alias="DATA")
    amount: Optional[int] = Field(None, alias="Amount")
    device_channel: Optional[str] = Field("02", alias="deviceChannel")

    model_config = POPULATE_BY_NAME_CONFIG


class FinishAuthorizeResponse(BaseModel):
    """Ответ на завершение авторизации"""

    success: bool = Field(..., alias="Success")
    error_code: Optional[str] = Field(None, alias="ErrorCode")
    error_message: Optional[str] = Field(None, alias="Message")
    terminal_key: Optional[str] = Field(None, alias="TerminalKey")
    status: Optional[PaymentStatus] = Field(None, alias="Status")
    payment_id: Optional[str] = Field(None, alias="PaymentId")
    order_id: Optional[str] = Field(None, alias="OrderId")
    amount: Optional[int] = Field(None, alias="Amount")
    rebill_id: Optional[str] = Field(None, alias="RebillId")
    card_id: Optional[str] = Field(None, alias="CardId")

    # 3DS поля
    acs_url: Optional[str] = Field(None, alias="ACSUrl")
    md: Optional[str] = Field(None, alias="MD")
    pa_req: Optional[str] = Field(None, alias="PaReq")
    term_url: Optional[str] = Field(None, alias="TermUrl")

    model_config = POPULATE_BY_NAME_CONFIG


class GetStateRequest(BaseModel):
    """Запрос состояния платежа"""

    payment_id: str = Field(..., alias="PaymentId")
    ip: Optional[str] = Field(None, alias="IP")

    model_config = POPULATE_BY_NAME_CONFIG


class GetStateResponse(BaseModel):
    """Ответ с состоянием платежа"""

    success: bool = Field(..., alias="Success")
    error_code: Optional[str] = Field(None, alias="ErrorCode")
    error_message: Optional[str] = Field(None, alias="Message")
    order_id: Optional[str] = Field(None, alias="OrderId")
    status: Optional[PaymentStatus] = Field(None, alias="Status")
    payment_id: Optional[str] = Field(None, alias="PaymentId")
    amount: Optional[int] = Field(None, alias="Amount")
    rebill_id: Optional[str] = Field(None, alias="RebillId")
    params: Optional[List[Dict[str, Any]]] = Field(None, alias="Params")

    model_config = POPULATE_BY_NAME_CONFIG


class CancelRequest(BaseModel):
    """Запрос отмены платежа"""

    payment_id: str = Field(..., alias="PaymentId")
    amount: Optional[int] = Field(None, alias="Amount")

    model_config = POPULATE_BY_NAME_CONFIG


class CancelResponse(BaseModel):
    """Ответ на отмену платежа"""

    success: bool = Field(..., alias="Success")
    error_code: Optional[str] = Field(None, alias="ErrorCode")
    error_message: Optional[str] = Field(None, alias="Message")
    order_id: Optional[str] = Field(None, alias="OrderId")
    status: Optional[PaymentStatus] = Field(None, alias="Status")
    payment_id: Optional[str] = Field(None, alias="PaymentId")
    original_amount: Optional[int] = Field(None, alias="OriginalAmount")
    new_amount: Optional[int] = Field(None, alias="NewAmount")

    model_config = POPULATE_BY_NAME_CONFIG


class ConfirmRequest(BaseModel):
    """Запрос подтверждения платежа (двухстадийная)"""

    payment_id: str = Field(..., alias="PaymentId")
    amount: Optional[int] = Field(None, alias="Amount")
    receipt: Optional[Receipt] = Field(None, alias="Receipt")

    model_config = POPULATE_BY_NAME_CONFIG


class ConfirmResponse(BaseModel):
    """Ответ на подтверждение платежа"""

    success: bool = Field(..., alias="Success")
    error_code: Optional[str] = Field(None, alias="ErrorCode")
    error_message: Optional[str] = Field(None, alias="Message")
    order_id: Optional[str] = Field(None, alias="OrderId")
    status: Optional[PaymentStatus] = Field(None, alias="Status")
    payment_id: Optional[str] = Field(None, alias="PaymentId")

    model_config = POPULATE_BY_NAME_CONFIG


class ChargeRequest(BaseModel):
    """Запрос на рекуррентный платеж"""

    rebill_id: str = Field(..., alias="RebillId")
    amount: int = Field(..., alias="Amount")
    order_id: str = Field(..., alias="OrderId")
    send_email: Optional[bool] = Field(None, alias="SendEmail")
    info_email: Optional[str] = Field(None, alias="InfoEmail")
    description: Optional[str] = Field(None, alias="Description")

    model_config = POPULATE_BY_NAME_CONFIG


class ChargeResponse(BaseModel):
    """Ответ на рекуррентный платеж"""

    success: bool = Field(..., alias="Success")
    error_code: Optional[str] = Field(None, alias="ErrorCode")
    error_message: Optional[str] = Field(None, alias="Message")
    order_id: Optional[str] = Field(None, alias="OrderId")
    status: Optional[PaymentStatus] = Field(None, alias="Status")
    payment_id: Optional[str] = Field(None, alias="PaymentId")
    amount: Optional[int] = Field(None, alias="Amount")

    model_config = POPULATE_BY_NAME_CONFIG


class SendClosingReceiptRequest(BaseModel):
    """Запрос на отправку закрывающего чека"""

    payment_id: str = Field(..., alias="PaymentId")
    receipt: Receipt = Field(..., alias="Receipt")

    model_config = POPULATE_BY_NAME_CONFIG


class SendClosingReceiptResponse(BaseModel):
    """Ответ на отправку закрывающего чека"""

    success: bool = Field(..., alias="Success")
    error_code: Optional[str] = Field(None, alias="ErrorCode")
    error_message: Optional[str] = Field(None, alias="Message")

    model_config = POPULATE_BY_NAME_CONFIG


class Notification(BaseModel):
    """Webhook уведомление от Т-Банка"""

    terminal_key: str = Field(..., alias="TerminalKey")
    order_id: str = Field(..., alias="OrderId")
    success: bool = Field(..., alias="Success")
    status: PaymentStatus = Field(..., alias="Status")
    payment_id: int = Field(..., alias="PaymentId")
    error_code: Optional[str] = Field(None, alias="ErrorCode")
    amount: int = Field(..., alias="Amount")
    rebill_id: Optional[str] = Field(None, alias="RebillId")
    card_id: Optional[int] = Field(None, alias="CardId")
    pan: Optional[str] = Field(None, alias="Pan")
    data: Optional[str] = Field(None, alias="DATA")
    token: str = Field(..., alias="Token")
    expiration_date: Optional[str] = Field(None, alias="ExpDate")

    model_config = POPULATE_BY_NAME_CONFIG
