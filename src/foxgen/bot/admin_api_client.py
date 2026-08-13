from __future__ import annotations

import json
import time
from typing import Any
from uuid import uuid4

import httpx

from foxgen.admin.security import request_signature


class AdminApiClientError(Exception):
    def __init__(self, message: str, *, status_code: int, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


class AdminApiClient:
    def __init__(
        self,
        *,
        base_url: str,
        hmac_key: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not hmac_key:
            raise ValueError("Admin HMAC key is required")
        self._hmac_key = hmac_key
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds, connect=10.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health(self, admin_user_id: int) -> dict[str, object]:
        return _dict(
            await self.request("GET", "/internal/admin/health", admin_user_id=admin_user_id)
        )

    async def summary(self, admin_user_id: int) -> dict[str, object]:
        return _dict(
            await self.request("GET", "/internal/admin/summary", admin_user_id=admin_user_id)
        )

    async def request(
        self,
        method: str,
        path: str,
        *,
        admin_user_id: int,
        params: dict[str, object] | None = None,
        payload: dict[str, object] | None = None,
        idempotency_key: str | None = None,
        confirm: bool = False,
    ) -> Any:
        raw_body = b""
        headers: dict[str, str] = {}
        if payload is not None:
            raw_body = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            headers["Content-Type"] = "application/json"
        timestamp = str(int(time.time()))
        request_id = str(uuid4())
        headers.update(
            {
                "X-Admin-User-Id": str(admin_user_id),
                "X-Request-Id": request_id,
                "X-Admin-Timestamp": timestamp,
                "X-Admin-Signature": request_signature(
                    secret=self._hmac_key,
                    timestamp=timestamp,
                    method=method,
                    path=path,
                    request_id=request_id,
                    raw_body=raw_body,
                ),
            }
        )
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if confirm:
            headers["X-Admin-Confirm"] = "CONFIRM"
        try:
            response = await self._client.request(
                method,
                path,
                params=params,
                content=raw_body if payload is not None else None,
                headers=headers,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise AdminApiClientError(
                "Admin API временно недоступен.",
                status_code=503,
                code="network_error",
            ) from exc
        try:
            data: Any = response.json()
        except ValueError:
            data = response.text
        if response.is_error:
            message = "Admin API отклонил запрос."
            code: str | None = None
            if isinstance(data, dict):
                raw_message = data.get("message") or data.get("detail")
                if isinstance(raw_message, str):
                    message = raw_message
                raw_code = data.get("error")
                if isinstance(raw_code, str):
                    code = raw_code
            raise AdminApiClientError(message, status_code=response.status_code, code=code)
        return data

    async def download(
        self,
        path: str,
        *,
        admin_user_id: int,
    ) -> tuple[bytes, str]:
        timestamp = str(int(time.time()))
        request_id = str(uuid4())
        headers = {
            "X-Admin-User-Id": str(admin_user_id),
            "X-Request-Id": request_id,
            "X-Admin-Timestamp": timestamp,
            "X-Admin-Signature": request_signature(
                secret=self._hmac_key,
                timestamp=timestamp,
                method="GET",
                path=path,
                request_id=request_id,
                raw_body=b"",
            ),
        }
        try:
            response = await self._client.get(path, headers=headers)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise AdminApiClientError("Admin export недоступен.", status_code=503) from exc
        if response.is_error:
            raise AdminApiClientError(
                "Не удалось сформировать export.", status_code=response.status_code
            )
        return response.content, response.headers.get("content-type", "application/octet-stream")


def _dict(value: Any) -> dict[str, object]:
    if not isinstance(value, dict):
        raise AdminApiClientError("Admin API вернул повреждённый ответ.", status_code=502)
    return {str(key): item for key, item in value.items()}
