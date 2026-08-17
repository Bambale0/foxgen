from __future__ import annotations

from foxgen.core.errors import ErrorCode, ProviderError
from foxgen.providers.kie.client import KieClient
from foxgen.providers.kie.suno import (
    SUNO_API_FAMILY,
    SUNO_EXTEND_API_FAMILY,
    SUNO_UPLOAD_COVER_API_FAMILY,
    InputMediaResolver,
    SunoClient,
    SunoExtendClient,
    SunoUploadCoverClient,
)


MARKET_API_FAMILY = "market"


class RoutedKieClient:
    """Select the reviewed KIE API-family client for a ModelSpec."""

    def __init__(self, market: KieClient, *, input_media: InputMediaResolver | None = None) -> None:
        self._market = market
        self._suno = SunoClient(market)
        self._suno_extend = SunoExtendClient(market)
        self._suno_upload_cover = (
            SunoUploadCoverClient(market, input_media) if input_media is not None else None
        )

    def for_family(
        self,
        api_family: str,
    ) -> KieClient | SunoClient | SunoExtendClient | SunoUploadCoverClient:
        if api_family == MARKET_API_FAMILY:
            return self._market
        if api_family == SUNO_API_FAMILY:
            return self._suno
        if api_family == SUNO_EXTEND_API_FAMILY:
            return self._suno_extend
        if api_family == SUNO_UPLOAD_COVER_API_FAMILY:
            if self._suno_upload_cover is None:
                raise ProviderError(
                    ErrorCode.PROVIDER_UNAVAILABLE,
                    "Suno Upload & Cover input storage is not configured.",
                    retryable=False,
                )
            return self._suno_upload_cover
        raise ProviderError(
            ErrorCode.PROVIDER_PROTOCOL,
            f"Неподдерживаемое семейство API провайдера: {api_family}",
            retryable=False,
        )

    async def aclose(self) -> None:
        await self._market.aclose()
