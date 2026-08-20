"""HappyFox YooKassa payment lifecycle helpers.

Keeps provider handling isolated from the balance domain. The caller is
responsible for persistence; these helpers only normalize YooKassa events.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any


SUCCESS_EVENTS = {"payment.succeeded"}
FAILED_EVENTS = {"payment.canceled"}


def normalize_yookassa_event(payload: dict[str, Any]) -> dict[str, Any]:
    obj = payload.get("object") or {}
    amount = (obj.get("amount") or {}).get("value")

    return {
        "event_id": payload.get("id"),
        "event_type": payload.get("event"),
        "payment_id": obj.get("id"),
        "status": obj.get("status"),
        "amount_rub": Decimal(amount) if amount else Decimal("0"),
        "metadata": obj.get("metadata") or {},
    }


def credits_from_metadata(metadata: dict[str, Any]) -> int:
    return max(0, int(metadata.get("credits", 0)))


def is_successful_payment(event_type: str | None) -> bool:
    return event_type in SUCCESS_EVENTS


def is_failed_payment(event_type: str | None) -> bool:
    return event_type in FAILED_EVENTS
