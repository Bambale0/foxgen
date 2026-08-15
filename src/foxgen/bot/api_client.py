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


@dataclass(frozen=True, slots=True)
class SavedReference:
    id: str
    content_type: str
    size_bytes: int
    created_at: str
    preview_url: str


@dataclass(frozen=True, slots=True)
class SavedReferencePage:
    items: tuple[SavedReference, ...]
    total: int
    used_bytes: int
    max_items: int
    max_bytes: int


@dataclass(frozen=True, slots=True)
class SavedReferenceResult:
    item: SavedReference
    duplicate: bool


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
        payload = await self._request(
            "GET",
            f"/v1/users/{user_id}/balance",
            headers={"X-FoxGen-User-Id": str(user_id)},
        )
        if not isinstance(payload, dict):
            raise FoxGenApiError("Баланс временно недоступен.", status_code=502)
        return BalanceView(
            available_units=int(payload.get("available_units", 0)),
            reserved_units=int(payload.get("reserved_units", 0)),
            currency=str(payload.get("currency", "CREDIT")),
        )

    async def list_references(
        self,
        *,
        user_id: int,
        offset: int = 0,
        limit: int = 20,
    ) -> SavedReferencePage:
        payload = await self._request(
            "GET",
            "/v1/reference-memory",
            headers={"X-FoxGen-User-Id": str(user_id)},
            params={"offset": offset, "limit": limit},
        )
        if not isinstance(payload, dict):
            raise FoxGenApiError("Память референсов временно недоступна.", status_code=502)
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            raise FoxGenApiError("Сервер вернул повреждённую память референсов.", status_code=502)
        items = tuple(self._saved_reference(item) for item in raw_items if isinstance(item, dict))
        return SavedReferencePage(
            items=items,
            total=int(payload.get("total", 0)),
            used_bytes=int(payload.get("used_bytes", 0)),
            max_items=int(payload.get("max_items", 0)),
            max_bytes=int(payload.get("max_bytes", 0)),
        )

    async def save_reference(
        self,
        *,
        user_id: int,
        username: str | None,
        storage_key: str,
    ) -> SavedReferenceResult:
        headers = {"X-FoxGen-User-Id": str(user_id)}
        if username:
            headers["X-FoxGen-Username"] = username
        payload = await self._request(
            "POST",
            "/v1/reference-memory",
            headers=headers,
            json={"storage_key": storage_key},
        )
        if not isinstance(payload, dict):
            raise FoxGenApiError("Не удалось сохранить референс.", status_code=502)
        return SavedReferenceResult(
            item=self._saved_reference(payload),
            duplicate=bool(payload.get("duplicate", False)),
        )

    async def resolve_references(
        self,
        *,
        user_id: int,
        reference_ids: tuple[str, ...],
    ) -> tuple[SavedReference, ...]:
        payload = await self._request(
            "POST",
            "/v1/reference-memory/resolve",
            headers={"X-FoxGen-User-Id": str(user_id)},
            json={"reference_ids": list(reference_ids)},
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise FoxGenApiError("Не удалось подготовить сохранённые референсы.", status_code=502)
        return tuple(
            self._saved_reference(item) for item in payload["items"] if isinstance(item, dict)
        )

    async def delete_reference(self, *, user_id: int, reference_id: str) -> None:
        await self._request(
            "DELETE",
            f"/v1/reference-memory/{reference_id}",
            headers={"X-FoxGen-User-Id": str(user_id)},
        )

    async def feed(
        self,
        *,
        user_id: int,
        sort: str = "recent",
        limit: int = 10,
        offset: int = 0,
    ) -> dict[str, object]:
        payload = await self._user_request(
            "GET",
            "/v1/feed",
            user_id=user_id,
            params={"sort": sort, "limit": limit, "offset": offset},
        )
        return _dict_payload(payload, "Лента временно недоступна.")

    async def publication(self, *, user_id: int, publication_id: str) -> dict[str, object]:
        payload = await self._user_request(
            "GET",
            f"/v1/publications/{publication_id}",
            user_id=user_id,
        )
        return _dict_payload(payload, "Публикация временно недоступна.")

    async def publication_media(
        self,
        *,
        user_id: int,
        publication_id: str,
    ) -> dict[str, object]:
        payload = await self._user_request(
            "GET",
            f"/v1/publications/{publication_id}/media",
            user_id=user_id,
        )
        return _dict_payload(payload, "Медиа публикации временно недоступно.")

    async def profile(self, *, user_id: int, slug: str) -> dict[str, object]:
        payload = await self._user_request(
            "GET",
            f"/v1/profiles/{slug}",
            user_id=user_id,
        )
        return _dict_payload(payload, "Профиль временно недоступен.")

    async def own_profile(
        self,
        *,
        user_id: int,
        username: str | None,
    ) -> dict[str, object]:
        payload = await self._user_request(
            "GET",
            "/v1/me/profile",
            user_id=user_id,
            username=username,
        )
        return _dict_payload(payload, "Профиль временно недоступен.")

    async def update_profile(
        self,
        *,
        user_id: int,
        username: str | None,
        slug: str,
        display_name: str | None,
        bio: str | None,
    ) -> dict[str, object]:
        payload = await self._user_request(
            "PUT",
            "/v1/me/profile",
            user_id=user_id,
            username=username,
            json={"slug": slug, "display_name": display_name, "bio": bio},
        )
        return _dict_payload(payload, "Не удалось обновить профиль.")

    async def profile_publications(
        self,
        *,
        user_id: int,
        slug: str,
        limit: int = 10,
        offset: int = 0,
    ) -> dict[str, object]:
        payload = await self._user_request(
            "GET",
            f"/v1/profiles/{slug}/publications",
            user_id=user_id,
            params={"limit": limit, "offset": offset},
        )
        return _dict_payload(payload, "Публикации профиля временно недоступны.")

    async def own_publications(
        self,
        *,
        user_id: int,
        scope: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, object]:
        params: dict[str, object] = {"limit": limit, "offset": offset}
        if scope:
            params["scope"] = scope
        payload = await self._user_request(
            "GET",
            "/v1/me/publications",
            user_id=user_id,
            params=params,
        )
        return _dict_payload(payload, "Ваши публикации временно недоступны.")

    async def publish_generation(
        self,
        *,
        user_id: int,
        username: str | None,
        generation_id: str,
        scope: str,
    ) -> dict[str, object]:
        payload = await self._user_request(
            "POST",
            f"/v1/generations/{generation_id}/publications",
            user_id=user_id,
            username=username,
            json={"scope": scope},
        )
        return _dict_payload(payload, "Не удалось опубликовать генерацию.")

    async def unpublish_generation(
        self,
        *,
        user_id: int,
        generation_id: str,
        scope: str,
    ) -> dict[str, object]:
        payload = await self._user_request(
            "DELETE",
            f"/v1/generations/{generation_id}/publications/{scope}",
            user_id=user_id,
        )
        return _dict_payload(payload, "Не удалось снять публикацию.")

    async def set_like(
        self,
        *,
        user_id: int,
        username: str | None,
        publication_id: str,
        liked: bool,
    ) -> dict[str, object]:
        payload = await self._user_request(
            "PUT",
            f"/v1/publications/{publication_id}/like",
            user_id=user_id,
            username=username,
            json={"liked": liked},
        )
        return _dict_payload(payload, "Не удалось обновить отметку нравится.")

    async def comments(
        self,
        *,
        user_id: int,
        publication_id: str,
        surface: str,
        limit: int = 30,
        offset: int = 0,
    ) -> dict[str, object]:
        payload = await self._user_request(
            "GET",
            f"/v1/publications/{publication_id}/comments",
            user_id=user_id,
            params={"surface": surface, "limit": limit, "offset": offset},
        )
        return _dict_payload(payload, "Комментарии временно недоступны.")

    async def add_comment(
        self,
        *,
        user_id: int,
        username: str | None,
        publication_id: str,
        surface: str,
        body: str,
    ) -> dict[str, object]:
        payload = await self._user_request(
            "POST",
            f"/v1/publications/{publication_id}/comments",
            user_id=user_id,
            username=username,
            json={"surface": surface, "body": body},
        )
        return _dict_payload(payload, "Не удалось добавить комментарий.")

    async def remix_source(
        self,
        *,
        user_id: int,
        publication_id: str,
    ) -> dict[str, object]:
        payload = await self._user_request(
            "GET",
            f"/v1/publications/{publication_id}/remix",
            user_id=user_id,
        )
        return _dict_payload(payload, "Этот ремикс сейчас недоступен.")

    async def submit(
        self,
        *,
        user_id: int,
        username: str | None,
        model_slug: str,
        input_data: dict[str, object],
        idempotency_key: str,
        source_publication_id: str | None = None,
    ) -> QueuedGeneration:
        headers = {
            "X-FoxGen-User-Id": str(user_id),
            "Idempotency-Key": idempotency_key,
        }
        if username:
            headers["X-FoxGen-Username"] = username
        if source_publication_id:
            headers["X-FoxGen-Source-Publication-Id"] = source_publication_id
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

    @staticmethod
    def _saved_reference(payload: dict[str, Any]) -> SavedReference:
        reference_id = payload.get("id")
        content_type = payload.get("content_type")
        created_at = payload.get("created_at")
        preview_url = payload.get("preview_url")
        if not all(
            isinstance(value, str)
            for value in (reference_id, content_type, created_at, preview_url)
        ):
            raise FoxGenApiError("Сервер вернул повреждённый референс.", status_code=502)
        try:
            size_bytes = int(payload.get("size_bytes", 0))
        except (TypeError, ValueError) as exc:
            raise FoxGenApiError("Сервер вернул повреждённый референс.", status_code=502) from exc
        return SavedReference(
            id=reference_id,
            content_type=content_type,
            size_bytes=size_bytes,
            created_at=created_at,
            preview_url=preview_url,
        )

    async def _user_request(
        self,
        method: str,
        path: str,
        *,
        user_id: int,
        username: str | None = None,
        **kwargs: Any,
    ) -> Any:
        headers = {"X-FoxGen-User-Id": str(user_id)}
        if username:
            headers["X-FoxGen-Username"] = username
        return await self._request(method, path, headers=headers, **kwargs)

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


def _dict_payload(payload: Any, message: str) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise FoxGenApiError(message, status_code=502)
    return payload
