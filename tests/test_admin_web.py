import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from foxgen.admin.errors import AdminAuthorizationError
from foxgen.admin.policy import ALL_SCOPES, AdminContext
from foxgen.admin.security import create_admin_session_token, request_signature
from foxgen.api.app import create_app
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


class FakeAdminServices:
    def __init__(self) -> None:
        self.policy = FakePolicy()
        self.users = SimpleNamespace(block_user=AsyncMock())


def _settings() -> Settings:
    return Settings(
        env="test",
        admin_api_enabled=True,
        admin_web_enabled=True,
        admin_hmac_key="admin-web-secret",
        admin_network_allowlist="127.0.0.1/32",
        admin_session_ttl_seconds=900,
    )


def _signed_headers(*, user_id: int, request_id: str, path: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    return {
        "X-Admin-User-Id": str(user_id),
        "X-Request-Id": request_id,
        "X-Admin-Timestamp": timestamp,
        "X-Admin-Signature": request_signature(
            secret="admin-web-secret",
            timestamp=timestamp,
            method="POST",
            path=path,
            request_id=request_id,
            raw_body=b"",
        ),
    }


@pytest.mark.asyncio
async def test_admin_can_mint_web_session_and_render_operator_surface() -> None:
    app = create_app(
        _settings(),
        manage_resources=False,
        admin_services=FakeAdminServices(),  # type: ignore[arg-type]
    )
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        session_response = await client.post(
            "/internal/admin/ui/session",
            headers=_signed_headers(
                user_id=100,
                request_id="admin-web-session",
                path="/internal/admin/ui/session",
            ),
        )
        assert session_response.status_code == 200
        token = session_response.json()["token"]
        dashboard = await client.get(f"/internal/admin/ui?session={token}")

    assert dashboard.status_code == 200
    assert "FoxGen Admin" in dashboard.text
    assert "Операторское действие" in dashboard.text


@pytest.mark.asyncio
async def test_regular_user_cannot_render_or_forge_admin_web_action() -> None:
    services = FakeAdminServices()
    app = create_app(
        _settings(),
        manage_resources=False,
        admin_services=services,  # type: ignore[arg-type]
    )
    regular_token = create_admin_session_token(
        secret="admin-web-secret",
        admin_user_id=101,
        ttl_seconds=900,
    )
    action_payload = json.dumps(
        {
            "action": "user.block",
            "target_id": "42",
            "payload": {"reason": "forged"},
        },
        separators=(",", ":"),
    )
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        dashboard = await client.get(f"/internal/admin/ui?session={regular_token}")
        action = await client.post(
            "/internal/admin/ui/api/action",
            content=action_payload,
            headers={
                "Content-Type": "application/json",
                "X-Admin-Session": regular_token,
                "X-Request-Id": "forged-action",
                "Idempotency-Key": "forged-key",
                "X-Admin-Confirm": "CONFIRM",
            },
        )

    assert dashboard.status_code == 403
    assert action.status_code == 403
    services.users.block_user.assert_not_awaited()
