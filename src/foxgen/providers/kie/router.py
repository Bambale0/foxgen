from __future__ import annotations

from foxgen.core.errors import ErrorCode, ProviderError
from foxgen.providers.kie.client import KieClient
from foxgen.providers.kie.suno import SUNO_API_FAMILY, SunoClient


MARKET_API_FAMILY = "market"


class RoutedKieClient:
    """Select the reviewed KIE API-family client for a ModelSpec."""

    def __init__(self, market: KieClient) -> None:
        self._market = market
        self._suno = SunoClient(market)

    def for_family(self, api_family: str) -> KieClient | SunoClient:
        if api_family == MARKET_API_FAMILY:
            return self._market
        if api_family == SUNO_API_FAMILY:
            return self._suno
        raise ProviderError(
            ErrorCode.PROVIDER_PROTOCOL,
            f"Неподдерживаемое семейство API провайдера: {api_family}",
            retryable=False,
        )

    async def aclose(self) -> None:
        await self._market.aclose()
