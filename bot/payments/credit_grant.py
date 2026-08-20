"""Application contract for successful payment credit grants.

The database transaction implementation belongs to the existing balance
service. This module defines the provider-neutral boundary.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CreditGrant:
    user_id: int
    credits: int
    payment_id: str
    provider: str = "yookassa"


def credits_from_rub(amount_rub: float, rate: int = 10) -> int:
    if amount_rub <= 0:
        return 0
    return int(amount_rub // rate)
