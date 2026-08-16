from __future__ import annotations

from collections.abc import Mapping

from foxgen.core.errors import ErrorCode, ProviderError
from foxgen.providers.kie.client import KieClient, TaskCreated, TaskRecord
from foxgen.providers.kie.suno import SUNO_API_FAMILY, SunoClient


MARKET_API_FAMILY = "market"


class RoutedKieClient:
    """Route durable provider tasks by the reviewed ModelSpec API family."""

    def __init__(self, market: KieClient) -> None:
        self._market = market
        self._suno = SunoClient(market)

    async def aclose(self) -> None:
        await self._market.aclose()

    async def create_task(
        self,
        *,
        model: str,
        input_data: Mapping[str, object],
        callback_url: str | None = None,
        api_family: str = MARKET_API_FAMILY,
    ) -> TaskCreated:
        if api_family == MARKET_API_FAMILY:
            return await self._market.create_task(
                model=model,
                input_data=input_data,
                callback_url=callback_url,
            )
        if api_family == SUNO_API_FAMILY:
            return await self._suno.create_task(
                model=model,
                input_data=input_data,
                callback_url=callback_url,
            )
        raise ProviderError(
            ErrorCode.PROVIDER_PROTOCOL,
            f"Неподдерживаемое семейство API провайдера: {api_family}",
            retryable=False,
        )

    async def get_task(
        self,
        task_id: str,
        *,
        api_family: str = MARKET_API_FAMILY,
    ) -> TaskRecord:
        if api_family == MARKET_API_FAMILY:
            return await self._market.get_task(task_id)
        if api_family == SUNO_API_FAMILY:
            return await self._suno.get_task(task_id)
        raise ProviderError(
            ErrorCode.PROVIDER_PROTOCOL,
            f"Неподдерживаемое семейство API провайдера: {api_family}",
            retryable=False,
        )
