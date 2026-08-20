"""YooKassa webhook processing helpers.

Keeps provider events idempotent and separates payment confirmation from
credit granting. Application code should call apply_successful_payment only
inside its transaction layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class YooKassaEvent:
    payment_id: str
    status: str
    amount_rub: Decimal
    metadata: dict[str, str]


SUCCESS_STATUSES = {"succeeded"}


def parse_event(payload: dict) -> YooKassaEvent:
    obj = payload.get("object") or {}
    amount = obj.get("amount") or {}
    metadata = obj.get("metadata") or {}
    return YooKassaEvent(
        payment_id=str(obj.get("id", "")),
        status=str(obj.get("status", "")),
        amount_rub=Decimal(str(amount.get("value", "0"))),
        metadata={str(k): str(v) for k, v in metadata.items()},
    )


def is_success(event: YooKassaEvent) -> bool:
    return event.status in SUCCESS_STATUSES
