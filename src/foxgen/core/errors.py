from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    VALIDATION = "validation_error"
    AUTHENTICATION = "authentication_error"
    INSUFFICIENT_CREDITS = "insufficient_credits"
    RATE_LIMITED = "rate_limited"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_REJECTED = "provider_rejected"
    PROVIDER_PROTOCOL = "provider_protocol_error"
    TASK_NOT_FOUND = "task_not_found"
    WEBHOOK_INVALID = "webhook_invalid"


@dataclass(slots=True)
class FoxGenError(Exception):
    code: ErrorCode
    public_message: str
    retryable: bool = False
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.public_message


class ProviderError(FoxGenError):
    pass


class WebhookVerificationError(FoxGenError):
    pass
