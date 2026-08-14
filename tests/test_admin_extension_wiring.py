import time
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import httpx
import pytest

from foxgen.admin.errors import AdminAuthorizationError
from foxgen.admin.policy import ALL_SCOPES, AdminContext
from foxgen.admin.security import create_admin_session_token, request_signature
from foxgen.api.app import create_app
from foxgen.bot.admin_extras import (
    admin_analytics,
    admin_export_xls,
    approved_withdrawals,
    mark_withdrawal_paid,
)
from foxgen.bot.app import register_runtime_routers
from foxgen.core.config import Settings


class FakePolicy:
    async def authorize(
        self,
        *,
        user_id: int,
        request_id: str,
        required_scope: str | None = None,
    ) -> AdminContext:
        if user_id != 100:
            raise AdminAuthorizationError("not an admin")
        context = AdminContext(
            user_id=user_id,
            role="superadmin",
            scopes=ALL_SCOPES,
            request_id=request_id,
        )
        if required_scope:
            context.require(required_scope)
        return context


class FakeAnalytics:
    async def snapshot(self, context: AdminContext, *, hours: int) -> dict[str, object]:
        return {"admin": context.user_id, "hours": hours}


class FakeAccess:
    async def list_admins(self, context: AdminContext) -> list[dict[str, object]]:
        return [{"user_id": context.user_id, "role": context.role}]


class FakeAdminServices:
    def __init__(self) -> None:
        self.policy = FakePolicy()
        self.analytics = FakeAnalytics()
        self.access = FakeAccess()


def _enabled_settings() -> Settings:
    return Settings(
        env="test",
        admin_api_enabled=True,
        admin_web_enabled=True,
        admin_hmac_key="admin-extension-secret",
        admin_network_allowlist="127.0.0.1/32",
        admin_session_ttl_seconds=900,
    )


def _signed_headers(*, method: str, path: str, request_id: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    return {
        "X-Admin-User-Id": "100",
        "X-Request-Id": request_id,
        "X-Admin-Timestamp": timestamp,
        "X-Admin-Signature": request_signature(
            secret="admin-extension-secret",
            timestamp=timestamp,
            method=method,
            path=path,
            request_id=request_id,
            raw_body=b"",
        ),
    }


def test_extension_routes_are_registered_with_expected_methods() -> None:
    app = create_app(
        _enabled_settings(),
        manage_resources=False,
        admin_services=cast(Any, FakeAdminServices()),
    )
    methods_by_path = {
        route.path: set(route.methods or set())
        for route in app.routes
        if hasattr(route, "methods")
    }

    expected = {
        "/internal/admin/admins": "GET",
        "/internal/admin/admins/{user_id}": "PUT",
        "/internal/admin/analytics": "GET",
        "/internal/admin/previews/generation": "POST",
        "/internal/admin/exports/users.xls": "GET",
        "/internal/admin/exports/finance.xls": "GET",
        "/internal/admin/ui/api/analytics": "GET",
        "/internal/admin/ui/api/preview-generation": "POST",
        "/internal/admin/ui/api/admins": "GET",
        "/internal/admin/ui/api/admins/{user_id}": "PUT",
    }
    for path, method in expected.items():
        assert method in methods_by_path[path]


@pytest.mark.asyncio
async def test_extension_routes_are_hidden_when_admin_surfaces_are_disabled() -> None:
    app = create_app(
        Settings(env="test", admin_api_enabled=False, admin_web_enabled=False),
        manage_resources=False,
        admin_services=cast(Any, FakeAdminServices()),
    )
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        signed = await client.get("/internal/admin/analytics")
        web = await client.get("/internal/admin/ui/api/analytics")

    assert signed.status_code == 404
    assert web.status_code == 404


@pytest.mark.asyncio
async def test_signed_and_web_analytics_extensions_are_reachable_when_enabled() -> None:
    app = create_app(
        _enabled_settings(),
        manage_resources=False,
        admin_services=cast(Any, FakeAdminServices()),
    )
    session_token = create_admin_session_token(
        secret="admin-extension-secret",
        admin_user_id=100,
        ttl_seconds=900,
    )
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        signed = await client.get(
            "/internal/admin/analytics?hours=12",
            headers=_signed_headers(
                method="GET",
                path="/internal/admin/analytics",
                request_id="extension-signed",
            ),
        )
        web = await client.get(
            "/internal/admin/ui/api/analytics?hours=6",
            headers={
                "X-Admin-Session": session_token,
                "X-Request-Id": "extension-web",
            },
        )

    assert signed.status_code == 200
    assert signed.json() == {"admin": 100, "hours": 12}
    # This also guards route ordering: the base web router has a generic
    # /api/{section} GET which would otherwise shadow this extension route.
    assert web.status_code == 200
    assert web.json() == {"admin": 100, "hours": 6}


class RecordingDispatcher:
    def __init__(self) -> None:
        self.router_names: list[str] = []

    def include_router(self, router: Any) -> None:
        self.router_names.append(router.name)


def test_telegram_extension_router_precedes_product_and_shell_fallbacks() -> None:
    dispatcher = RecordingDispatcher()
    register_runtime_routers(cast(Any, dispatcher))
    assert dispatcher.router_names == [
        "foxgen-admin-extras",
        "foxgen-admin",
        "foxgen-quick-start",
        "foxgen-generation",
        "foxgen-shell",
    ]


def _callback(data: str) -> SimpleNamespace:
    message = SimpleNamespace(edit_text=AsyncMock(), answer_document=AsyncMock())
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_telegram_analytics_extra_reauthorizes_and_uses_extension_route() -> None:
    callback = _callback("adm:analytics")
    client = SimpleNamespace(
        health=AsyncMock(return_value={"role": "superadmin"}),
        request=AsyncMock(return_value={"generations": 4}),
    )

    await admin_analytics(cast(Any, callback), cast(Any, client))

    client.health.assert_awaited_once_with(100)
    client.request.assert_awaited_once_with(
        "GET",
        "/internal/admin/analytics",
        admin_user_id=100,
        params={"hours": 24},
    )
    callback.message.edit_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_telegram_xls_extra_reauthorizes_and_delivers_file() -> None:
    callback = _callback("adm:exportxls:users")
    client = SimpleNamespace(
        health=AsyncMock(return_value={"role": "superadmin"}),
        download=AsyncMock(return_value=(b"xls-content", "application/vnd.ms-excel")),
    )

    await admin_export_xls(cast(Any, callback), cast(Any, client))

    client.health.assert_awaited_once_with(100)
    client.download.assert_awaited_once_with(
        "/internal/admin/exports/users.xls",
        admin_user_id=100,
    )
    callback.message.answer_document.assert_awaited_once()


@pytest.mark.asyncio
async def test_telegram_approved_withdrawals_extra_builds_payment_shortcut() -> None:
    callback = _callback("adm:withdrawals:approved")
    client = SimpleNamespace(
        health=AsyncMock(return_value={"role": "superadmin"}),
        request=AsyncMock(
            return_value=[
                {
                    "id": "3c61c25f-f8a7-4f99-a5b4-2027f43c77ec",
                    "user_id": 42,
                    "amount_units": 900,
                }
            ]
        ),
    )

    await approved_withdrawals(cast(Any, callback), cast(Any, client))

    client.health.assert_awaited_once_with(100)
    client.request.assert_awaited_once_with(
        "GET",
        "/internal/admin/partners/withdrawals",
        admin_user_id=100,
        params={"status": "approved", "limit": 20},
    )
    markup = callback.message.edit_text.await_args.kwargs["reply_markup"]
    callbacks = [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data is not None
    ]
    assert "adm:wdpay:3c61c25f-f8a7-4f99-a5b4-2027f43c77ec" in callbacks


@pytest.mark.asyncio
async def test_telegram_mark_paid_extra_reauthorizes_and_confirms_write() -> None:
    withdrawal_id = "3c61c25f-f8a7-4f99-a5b4-2027f43c77ec"
    callback = _callback(f"adm:wdpay:{withdrawal_id}")
    client = SimpleNamespace(
        health=AsyncMock(return_value={"role": "superadmin"}),
        request=AsyncMock(return_value={"status": "paid"}),
    )

    await mark_withdrawal_paid(cast(Any, callback), cast(Any, client))

    client.health.assert_awaited_once_with(100)
    call = client.request.await_args
    assert call.args == (
        "POST",
        f"/internal/admin/partners/withdrawals/{withdrawal_id}/actions",
    )
    assert call.kwargs["admin_user_id"] == 100
    assert call.kwargs["payload"] == {"action": "mark_paid"}
    assert call.kwargs["confirm"] is True
    assert isinstance(call.kwargs["idempotency_key"], str)
    assert call.kwargs["idempotency_key"]
