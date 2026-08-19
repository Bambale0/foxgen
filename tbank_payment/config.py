"""Конфигурация для T-Bank клиента"""

import os
from typing import Optional

from pydantic import BaseModel, Field


class TBankConfig(BaseModel):
    terminal_key: str = Field(..., description="TerminalKey")
    password: str = Field(..., description="Password (secret key)")
    base_url: str = Field(
        default="https://securepay.tinkoff.ru/v2/", description="API base URL"
    )
    notification_url: Optional[str] = Field(None, description="NotificationURL")
    success_url: Optional[str] = Field(None, description="SuccessURL")
    fail_url: Optional[str] = Field(None, description="FailURL")

    @classmethod
    def from_env(cls) -> "TBankConfig":
        return cls(
            terminal_key=os.getenv("TBANK_TERMINAL_KEY", ""),
            password=os.getenv("TBANK_SECRET_KEY", ""),
            base_url=os.getenv("TBANK_API_URL", "https://securepay.tinkoff.ru/v2/"),
            notification_url=os.getenv("TBANK_NOTIFICATION_URL"),
            success_url=os.getenv("TBANK_SUCCESS_URL"),
            fail_url=os.getenv("TBANK_FAIL_URL"),
        )
