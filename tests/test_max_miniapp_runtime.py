import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import max_miniapp
from bot.max_store import MaxUser


def _signed_init_data(
    *,
    token: str = "max-test-token",
    user_id: int = 123456,
    auth_date: int | None = None,
    start_param: str = "from_max",
) -> str:
    values = {
        "auth_date": str(auth_date or int(time.time())),
        "query_id": "query-max-1",
        "start_param": start_param,
        "user": json.dumps(
            {
                "id": user_id,
                "first_name": "Max",
                "last_name": "User",
                "username": "max_user",
                "language_code": "ru",
                "photo_url": None,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(
        secret,
        check_string.encode(),
        hashlib.sha256,
    ).hexdigest()
    return urlencode(values)


def test_validate_max_init_data_accepts_official_hmac_shape() -> None:
    raw = _signed_init_data()
    payload = max_miniapp.validate_max_init_data(raw, "max-test-token")

    assert payload["user"]["id"] == 123456
    assert payload["user"]["username"] == "max_user"
    assert payload["start_param"] == "from_max"


def test_validate_max_init_data_rejects_duplicate_hash() -> None:
    raw = _signed_init_data()
    with pytest.raises(ValueError, match="Duplicate MAX init_data key"):
        max_miniapp.validate_max_init_data(
            f"{raw}&hash=second",
            "max-test-token",
        )


def test_validate_max_init_data_rejects_expired_session() -> None:
    old = int(time.time()) - max_miniapp.MAX_INIT_DATA_MAX_AGE_SECONDS - 60
    raw = _signed_init_data(auth_date=old)

    with pytest.raises(ValueError, match="Expired MAX session"):
        max_miniapp.validate_max_init_data(raw, "max-test-token")


@pytest.mark.asyncio
async def test_max_bootstrap_is_intercepted_before_telegram_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_ACCESS_TOKEN", "max-test-token")
    monkeypatch.setenv("MAX_BOT_NAME", "HappyFoxMax")

    async def fake_ensure_max_user(
        max_user_id: int,
        *,
        username: str = "",
        first_name: str = "",
        last_name: str = "",
    ) -> MaxUser:
        return MaxUser(
            max_user_id=max_user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            balance_credits=77,
        )

    async def fake_history(_user_id: int, limit: int = 24):
        assert limit == 24
        return []

    async def fake_balance(_user_id: int) -> float:
        return 77.0

    async def fake_is_admin(_user_id: int) -> bool:
        return False

    monkeypatch.setattr(max_miniapp, "ensure_max_user", fake_ensure_max_user)
    monkeypatch.setattr(max_miniapp, "list_max_history", fake_history)
    monkeypatch.setattr(max_miniapp, "get_max_balance", fake_balance)
    monkeypatch.setattr(max_miniapp, "is_max_admin", fake_is_admin)

    telegram_handler_called = False

    async def telegram_handler(_request: web.Request) -> web.Response:
        nonlocal telegram_handler_called
        telegram_handler_called = True
        return web.json_response({"ok": False, "source": "telegram"})

    app = web.Application(middlewares=[max_miniapp.max_miniapp_middleware])
    app.router.add_post("/mini-app/api/bootstrap", telegram_handler)

    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/mini-app/api/bootstrap",
            json={
                "platform": "max",
                "init_data": _signed_init_data(),
            },
        )
        payload = await response.json()

    assert response.status == 200
    assert payload["ok"] is True
    assert payload["platform"] == "max"
    assert payload["max_user_id"] == 123456
    assert payload["credits"] == 77.0
    assert telegram_handler_called is False


@pytest.mark.asyncio
async def test_telegram_request_passes_through_max_middleware() -> None:
    async def telegram_handler(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "source": "telegram"})

    app = web.Application(middlewares=[max_miniapp.max_miniapp_middleware])
    app.router.add_post("/mini-app/api/bootstrap", telegram_handler)

    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/mini-app/api/bootstrap",
            json={"platform": "telegram", "init_data": "telegram-data"},
        )
        payload = await response.json()

    assert response.status == 200
    assert payload == {"ok": True, "source": "telegram"}
