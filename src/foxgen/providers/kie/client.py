from collections.abc import Mapping
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from foxgen.core.errors import ErrorCode, ProviderError


class TaskCreated(BaseModel):
    model_config = ConfigDict(frozen=True)
    task_id: str


class TaskRecord(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)
    task_id: str
    state: str | None = None
    result: Any = None


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, ProviderError) and exc.retryable


class KieClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.kie.ai",
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("KIE API key is required")
        self._authorization = f"Bearer {api_key}"
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds, connect=10.0),
        )
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=0.5, max=5),
        reraise=True,
    )
    async def create_task(
        self,
        *,
        model: str,
        input_data: Mapping[str, object],
        callback_url: str | None = None,
    ) -> TaskCreated:
        payload: dict[str, object] = {"model": model, "input": dict(input_data)}
        if callback_url:
            payload["callBackUrl"] = callback_url
        data = await self._request("POST", "/api/v1/jobs/createTask", json=payload)
        task_id = data.get("taskId")
        if not isinstance(task_id, str) or not task_id:
            raise ProviderError(
                ErrorCode.PROVIDER_PROTOCOL,
                "Провайдер вернул некорректный идентификатор задачи.",
                retryable=False,
                details={"data": data},
            )
        return TaskCreated(task_id=task_id)

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=0.5, max=5),
        reraise=True,
    )
    async def get_task(self, task_id: str) -> TaskRecord:
        data = await self._request(
            "GET", "/api/v1/jobs/recordInfo", params={"taskId": task_id}
        )
        normalized_id = data.get("taskId", task_id)
        if not isinstance(normalized_id, str):
            normalized_id = task_id
        state = data.get("state") or data.get("status")
        return TaskRecord(
            task_id=normalized_id,
            state=state if isinstance(state, str) else None,
            result=data.get("resultJson") or data.get("result"),
            **{
                key: value
                for key, value in data.items()
                if key not in {"taskId", "state", "status", "resultJson", "result"}
            },
        )

    async def get_credits(self) -> int:
        data = await self._request("GET", "/api/v1/chat/credit")
        value: object = data
        if isinstance(data, dict) and "credits" in data:
            value = data["credits"]
        if not isinstance(value, int):
            raise ProviderError(
                ErrorCode.PROVIDER_PROTOCOL,
                "Провайдер вернул некорректный баланс.",
                details={"data": data},
            )
        return value

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        supplied_headers = kwargs.pop("headers", None)
        headers = dict(supplied_headers or {})
        headers["Authorization"] = self._authorization
        try:
            response = await self._client.request(method, path, headers=headers, **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "Сервис генерации временно недоступен. Повторим попытку.",
                retryable=True,
            ) from exc

        payload: Any
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError(
                ErrorCode.PROVIDER_PROTOCOL,
                "Сервис генерации вернул повреждённый ответ.",
                retryable=response.status_code >= 500,
            ) from exc

        if response.status_code == 401:
            raise ProviderError(ErrorCode.AUTHENTICATION, "Ошибка авторизации KIE.ai.")
        if response.status_code == 402:
            raise ProviderError(
                ErrorCode.INSUFFICIENT_CREDITS,
                "На аккаунте KIE.ai недостаточно кредитов.",
            )
        if response.status_code == 429:
            raise ProviderError(
                ErrorCode.RATE_LIMITED,
                "KIE.ai ограничил частоту запросов. Повторим попытку.",
                retryable=True,
            )
        if response.status_code in {455, 500, 502, 503, 504}:
            raise ProviderError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "KIE.ai временно недоступен. Повторим попытку.",
                retryable=True,
                details={"status": response.status_code},
            )
        if response.is_error:
            raise ProviderError(
                ErrorCode.PROVIDER_REJECTED,
                "KIE.ai отклонил запрос. Проверьте параметры и медиа.",
                details={"status": response.status_code, "payload": payload},
            )

        if not isinstance(payload, dict):
            raise ProviderError(
                ErrorCode.PROVIDER_PROTOCOL,
                "KIE.ai вернул ответ неизвестного формата.",
            )
        code = payload.get("code")
        if code not in {None, 200}:
            raise ProviderError(
                ErrorCode.PROVIDER_REJECTED,
                str(payload.get("msg") or "KIE.ai отклонил запрос."),
                retryable=code in {429, 455, 500, 502, 503, 504},
                details={"code": code},
            )
        data = payload.get("data", {})
        if isinstance(data, dict):
            return data
        if isinstance(data, int):
            return {"credits": data}
        raise ProviderError(
            ErrorCode.PROVIDER_PROTOCOL,
            "KIE.ai вернул некорректное поле data.",
            details={"payload": payload},
        )
