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
class FeedProfileView:
    user_id: int
    public_slug: str
    display_name: str
    username: str | None
    avatar_url: str | None
    bio: str | None
    deep_link: str


@dataclass(frozen=True, slots=True)
class FeedPublicationView:
    id: str
    generation_id: str
    author_user_id: int
    scope: str
    media_kind: str
    model_slug: str
    media_urls: tuple[str, ...]
    prompt: str | None
    prompt_actions_allowed: bool
    is_derivative: bool
    source_publication_id: str | None
    likes_count: int
    comments_count: int
    shares_count: int
    remixes_count: int
    viewer_liked: bool
    is_mine: bool
    author_slug: str
    author_display_name: str
    author_username: str | None
    author_avatar_url: str | None
    post_deep_link: str
    remix_deep_link: str


@dataclass(frozen=True, slots=True)
class FeedCommentView:
    id: str
    publication_id: str
    user_id: int
    surface: str
    text: str
    author_display_name: str
    author_slug: str
    is_mine: bool


@dataclass(frozen=True, slots=True)
class FeedProfilePage:
    profile: FeedProfileView
    items: tuple[FeedPublicationView, ...]


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
            headers=self._user_headers(user_id),
        )
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
        source_publication_id: str | None = None,
    ) -> QueuedGeneration:
        headers = self._user_headers(user_id)
        headers["Idempotency-Key"] = idempotency_key
        if username:
            headers["X-FoxGen-Username"] = username
        body: dict[str, object] = {"input": input_data}
        if source_publication_id is not None:
            body["source_publication_id"] = source_publication_id
        payload = await self._request(
            "POST",
            f"/v1/models/{model_slug}/tasks",
            headers=headers,
            json=body,
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

    async def feed(
        self,
        *,
        user_id: int,
        source: str = "recent",
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[FeedPublicationView, ...]:
        payload = await self._request(
            "GET",
            "/v1/feed",
            headers=self._user_headers(user_id),
            params={"source": source, "limit": limit, "offset": offset},
        )
        if not isinstance(payload, dict):
            raise FoxGenApiError("Лента временно недоступна.", status_code=502)
        return self._publication_list(payload.get("items"))

    async def feed_publication(
        self,
        *,
        user_id: int,
        publication_id: str,
    ) -> FeedPublicationView:
        payload = await self._request(
            "GET",
            f"/v1/feed/publications/{publication_id}",
            headers=self._user_headers(user_id),
        )
        return self._publication(payload)

    async def own_feed_profile(
        self,
        *,
        user_id: int,
        username: str | None = None,
        display_name: str | None = None,
    ) -> FeedProfileView:
        headers = self._user_headers(user_id)
        if username:
            headers["X-FoxGen-Username"] = username
        if display_name:
            headers["X-FoxGen-Display-Name"] = display_name
        payload = await self._request("GET", "/v1/feed/profile/me", headers=headers)
        return self._profile(payload)

    async def feed_profile(
        self,
        *,
        user_id: int,
        public_slug: str,
        limit: int = 30,
        offset: int = 0,
    ) -> FeedProfilePage:
        payload = await self._request(
            "GET",
            f"/v1/feed/profile/{public_slug}",
            headers=self._user_headers(user_id),
            params={"limit": limit, "offset": offset},
        )
        if not isinstance(payload, dict):
            raise FoxGenApiError("Профиль временно недоступен.", status_code=502)
        return FeedProfilePage(
            profile=self._profile(payload.get("profile")),
            items=self._publication_list(payload.get("items")),
        )

    async def own_publications(
        self,
        *,
        user_id: int,
        scope: str | None = None,
        include_unpublished: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[FeedPublicationView, ...]:
        params: dict[str, object] = {
            "include_unpublished": str(include_unpublished).lower(),
            "limit": limit,
            "offset": offset,
        }
        if scope is not None:
            params["scope"] = scope
        payload = await self._request(
            "GET",
            "/v1/feed/me",
            headers=self._user_headers(user_id),
            params=params,
        )
        if not isinstance(payload, dict):
            raise FoxGenApiError("Публикации временно недоступны.", status_code=502)
        return self._publication_list(payload.get("items"))

    async def publish(
        self,
        *,
        user_id: int,
        generation_id: str,
        scope: str,
        prompt_visible: bool = False,
    ) -> FeedPublicationView:
        payload = await self._request(
            "PUT",
            "/v1/feed/publications",
            headers=self._user_headers(user_id),
            json={
                "generation_id": generation_id,
                "scope": scope,
                "prompt_visible": prompt_visible,
            },
        )
        return self._publication(payload)

    async def unpublish(self, *, user_id: int, publication_id: str) -> None:
        await self._request(
            "DELETE",
            f"/v1/feed/publications/{publication_id}",
            headers=self._user_headers(user_id),
        )

    async def set_feed_like(
        self,
        *,
        user_id: int,
        publication_id: str,
        liked: bool,
    ) -> FeedPublicationView:
        payload = await self._request(
            "PUT" if liked else "DELETE",
            f"/v1/feed/publications/{publication_id}/like",
            headers=self._user_headers(user_id),
        )
        return self._publication(payload)

    async def feed_comments(
        self,
        *,
        user_id: int,
        publication_id: str,
        surface: str,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[FeedCommentView, ...]:
        payload = await self._request(
            "GET",
            f"/v1/feed/publications/{publication_id}/comments",
            headers=self._user_headers(user_id),
            params={"surface": surface, "limit": limit, "offset": offset},
        )
        if not isinstance(payload, dict):
            raise FoxGenApiError("Комментарии временно недоступны.", status_code=502)
        return self._comment_list(payload.get("items"))

    async def add_feed_comment(
        self,
        *,
        user_id: int,
        publication_id: str,
        surface: str,
        text: str,
    ) -> FeedCommentView:
        payload = await self._request(
            "POST",
            f"/v1/feed/publications/{publication_id}/comments",
            headers=self._user_headers(user_id),
            json={"surface": surface, "text": text},
        )
        return self._comment(payload)

    async def share_feed_publication(
        self,
        *,
        user_id: int,
        publication_id: str,
        surface: str,
    ) -> str:
        payload = await self._request(
            "POST",
            f"/v1/feed/publications/{publication_id}/share",
            headers=self._user_headers(user_id),
            json={"surface": surface},
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("start_param"), str):
            raise FoxGenApiError("Не удалось подготовить ссылку.", status_code=502)
        return str(payload["start_param"])

    async def remix_source(
        self,
        *,
        user_id: int,
        publication_id: str,
    ) -> FeedPublicationView:
        payload = await self._request(
            "GET",
            f"/v1/feed/publications/{publication_id}/remix",
            headers=self._user_headers(user_id),
        )
        if not isinstance(payload, dict):
            raise FoxGenApiError("Remix временно недоступен.", status_code=502)
        return self._publication(payload.get("source"))

    @staticmethod
    def _user_headers(user_id: int) -> dict[str, str]:
        return {"X-FoxGen-User-Id": str(user_id)}

    @classmethod
    def _publication_list(cls, value: object) -> tuple[FeedPublicationView, ...]:
        if not isinstance(value, list):
            return ()
        return tuple(cls._publication(item) for item in value if isinstance(item, dict))

    @staticmethod
    def _publication(value: object) -> FeedPublicationView:
        if not isinstance(value, dict):
            raise FoxGenApiError("Сервер вернул повреждённую публикацию.", status_code=502)
        author = value.get("author")
        if not isinstance(author, dict):
            author = {}
        media_urls_raw = value.get("media_urls")
        media_urls = (
            tuple(str(item) for item in media_urls_raw if isinstance(item, str))
            if isinstance(media_urls_raw, list)
            else ()
        )
        publication_id = value.get("id")
        generation_id = value.get("generation_id")
        if not isinstance(publication_id, str) or not isinstance(generation_id, str):
            raise FoxGenApiError("Сервер вернул повреждённую публикацию.", status_code=502)
        return FeedPublicationView(
            id=publication_id,
            generation_id=generation_id,
            author_user_id=int(value.get("author_user_id", 0)),
            scope=str(value.get("scope", "feed")),
            media_kind=str(value.get("media_kind", "image")),
            model_slug=str(value.get("model_slug", "")),
            media_urls=media_urls,
            prompt=value.get("prompt") if isinstance(value.get("prompt"), str) else None,
            prompt_actions_allowed=bool(value.get("prompt_actions_allowed", False)),
            is_derivative=bool(value.get("is_derivative", False)),
            source_publication_id=(
                value.get("source_publication_id")
                if isinstance(value.get("source_publication_id"), str)
                else None
            ),
            likes_count=int(value.get("likes_count", 0)),
            comments_count=int(value.get("comments_count", 0)),
            shares_count=int(value.get("shares_count", 0)),
            remixes_count=int(value.get("remixes_count", 0)),
            viewer_liked=bool(value.get("viewer_liked", False)),
            is_mine=bool(value.get("is_mine", False)),
            author_slug=str(author.get("public_slug", "")),
            author_display_name=str(author.get("display_name", "Автор")),
            author_username=(
                author.get("username") if isinstance(author.get("username"), str) else None
            ),
            author_avatar_url=(
                author.get("avatar_url") if isinstance(author.get("avatar_url"), str) else None
            ),
            post_deep_link=str(value.get("post_deep_link", f"post_{publication_id}")),
            remix_deep_link=str(value.get("remix_deep_link", f"remix_{publication_id}")),
        )

    @classmethod
    def _comment_list(cls, value: object) -> tuple[FeedCommentView, ...]:
        if not isinstance(value, list):
            return ()
        return tuple(cls._comment(item) for item in value if isinstance(item, dict))

    @staticmethod
    def _comment(value: object) -> FeedCommentView:
        if not isinstance(value, dict):
            raise FoxGenApiError("Сервер вернул повреждённый комментарий.", status_code=502)
        author = value.get("author")
        if not isinstance(author, dict):
            author = {}
        return FeedCommentView(
            id=str(value.get("id", "")),
            publication_id=str(value.get("publication_id", "")),
            user_id=int(value.get("user_id", 0)),
            surface=str(value.get("surface", "feed")),
            text=str(value.get("text", "")),
            author_display_name=str(author.get("display_name", "Автор")),
            author_slug=str(author.get("public_slug", "")),
            is_mine=bool(value.get("is_mine", False)),
        )

    @staticmethod
    def _profile(value: object) -> FeedProfileView:
        if not isinstance(value, dict):
            raise FoxGenApiError("Сервер вернул повреждённый профиль.", status_code=502)
        public_slug = value.get("public_slug")
        display_name = value.get("display_name")
        if not isinstance(public_slug, str) or not isinstance(display_name, str):
            raise FoxGenApiError("Сервер вернул повреждённый профиль.", status_code=502)
        return FeedProfileView(
            user_id=int(value.get("user_id", 0)),
            public_slug=public_slug,
            display_name=display_name,
            username=value.get("username") if isinstance(value.get("username"), str) else None,
            avatar_url=value.get("avatar_url") if isinstance(value.get("avatar_url"), str) else None,
            bio=value.get("bio") if isinstance(value.get("bio"), str) else None,
            deep_link=str(value.get("deep_link", f"profile_{public_slug}")),
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
