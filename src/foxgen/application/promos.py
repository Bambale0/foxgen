from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PromoRedemptionResult:
    code: str
    reward_units: int
    available_units: int
    replayed: bool


class PromoRedemptionServiceProtocol(Protocol):
    async def redeem(
        self,
        *,
        user_id: int,
        username: str | None,
        code: str,
    ) -> PromoRedemptionResult: ...
