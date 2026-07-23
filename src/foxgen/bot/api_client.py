from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True, slots=True)
class PriceQuote:
    model_slug: str
    amount_units: int
    currency: str
    version: int


@dataclass(frozen=True, slots=True)
class BalanceView:
    available_units: int
    reserved_units: int
    currency: str


@dataclass(frozen=True, slots=True)
class QueuedGeneration:
    generation_id: str
    status: str
    replayed: bool


class FoxGenApiError(Exception):
    def __init__(self, message: str, *, status_code: int, retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.retryable = retryable


class FoxGenApiClient:
    def __init__(
        self,
        *,
        base_url: str,
        internal_token: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not internal_token:
            raise ValueError("Internal API token is required")
        self._token = internal_token
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds, connect=10.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def prices(self) -> dict[str, PriceQuote]:
        payload = await self._request("GET", "/v1/prices", authenticated=False)
        if not isinstance(payload, list):
            raise FoxGenApiError("Каталог цен временно недоступен.", status_code=502)
        quotes: dict[str, PriceQuote] = {}
        for item in payload:
            if not isinstance(item, dict):
                continue
            slug = item.get("model_slug")
            amount = item.get("amount_units")
            currency = item.get("currency")
            version = item.get("version")
            if (
                isinstance(slug, str)
                and isinstance(amount, int)
                and isinstance(currency, str)
                and isinstance(version, int)
            ):
                quotes[slug] = PriceQuote(slug, amount, currency, version)
        return quotes

    async def balance(self, user_id: int) -> BalanceView:
        payload = await self._request("GET", f"/v1/users/{user_id}/balance")
        if not isinstance(payload, dict):
            raise FoxGenApiError("Баланс временно недоступен.", status_code=502)
        return BalanceView(
            available_units=int(payload.get("available_units", 0)),
            reserved_units=int(payload.get("reserved_units", 0)),
            currency=str(payload.get("currency", "CREDIT")),
        )

    async def submit(
        self,
        *,
        user_id: int,
        username: str | None,
        model_slug: str,
        input_data: dict[str, object],
        idempotency_key: str,
    ) -> QueuedGeneration:
        headers = {
            "X-FoxGen-User-Id": str(user_id),
            "Idempotency-Key": idempotency_key,
        }
        if username:
            headers["X-FoxGen-Username"] = username
        payload = await self._request(
            "POST",
            f"/v1/models/{model_slug}/tasks",
            headers=headers,
            json={"input": input_data},
        )
        if not isinstance(payload, dict):
            raise FoxGenApiError("Не удалось поставить генерацию в очередь.", status_code=502)
        generation_id = payload.get("generation_id")
        status = payload.get("status")
        if not isinstance(generation_id, str) or not isinstance(status, str):
            raise FoxGenApiError("Сервер вернул повреждённый ответ.", status_code=502)
        return QueuedGeneration(
            generation_id=generation_id,
            status=status,
            replayed=bool(payload.get("replayed", False)),
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        authenticated: bool = True,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> Any:
        request_headers = dict(headers or {})
        if authenticated:
            request_headers["Authorization"] = f"Bearer {self._token}"
        try:
            response = await self._client.request(
                method,
                path,
                headers=request_headers,
                **kwargs,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise FoxGenApiError(
                "FoxGen временно недоступен. Попробуйте ещё раз.",
                status_code=503,
                retryable=True,
            ) from exc

        try:
            payload: Any = response.json()
        except ValueError:
            payload = None
        if response.is_error:
            message = "Не удалось выполнить запрос."
            retryable = response.status_code >= 500
            if isinstance(payload, dict):
                detail = payload.get("message") or payload.get("detail")
                if isinstance(detail, str):
                    message = detail
                retryable = bool(payload.get("retryable", retryable))
            raise FoxGenApiError(
                message,
                status_code=response.status_code,
                retryable=retryable,
            )
        return payload
