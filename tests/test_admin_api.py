import json
import time
from typing import Any

import httpx
import pytest

from foxgen.admin.errors import AdminAuthorizationError
from foxgen.admin.policy import ALL_SCOPES, AdminContext
from foxgen.admin.repository import CommandResult
from foxgen.admin.security import request_signature
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


class FakeQueries:
    async def summary(self, context: AdminContext) -> dict[str, object]:
        return {"users": 10, "admin": context.user_id}


class FakeUsers:
    def __init__(self) -> None:
        self.calls = 0

    async def adjust_balance(
        self,
        *,
        context: AdminContext,
        user_id: int,
        amount_units: int,
        reason: str,
        idempotency_key: str,
    ) -> CommandResult:
        self.calls += 1
        return CommandResult(
            payload={
                "admin_user_id": context.user_id,
                "user_id": user_id,
                "amount_units": amount_units,
                "reason": reason,
                "idempotency_key": idempotency_key,
            },
            replayed=False,
        )


class FakeAdminServices:
    def __init__(self) -> None:
        self.policy = FakePolicy()
        self.queries = FakeQueries()
        self.users = FakeUsers()


def _settings() -> Settings:
    return Settings(
        env="test",
        admin_api_enabled=True,
        admin_web_enabled=True,
        admin_hmac_key="admin-secret",
        admin_network_allowlist="127.0.0.1/32",
    )


def _signed_headers(
    *,
    method: str,
    path: str,
    body: bytes,
    user_id: int = 100,
    request_id: str = "request-1",
    signature_override: str | None = None,
) -> dict[str, str]:
    timestamp = str(int(time.time()))
    signature = request_signature(
        secret="admin-secret",
        timestamp=timestamp,
        method=method,
        path=path,
        request_id=request_id,
        raw_body=body,
    )
    return {
        "X-Admin-User-Id": str(user_id),
        "X-Request-Id": request_id,
        "X-Admin-Timestamp": timestamp,
        "X-Admin-Signature": signature_override or signature,
    }


@pytest.mark.asyncio
async def test_signed_admin_health_and_summary() -> None:
    services = FakeAdminServices()
    app = create_app(
        _settings(),
        manage_resources=False,
        admin_services=services,  # type: ignore[arg-type]
    )
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        health = await client.get(
            "/internal/admin/health",
            headers=_signed_headers(method="GET", path="/internal/admin/health", body=b""),
        )
        summary = await client.get(
            "/internal/admin/summary",
            headers=_signed_headers(
                method="GET",
                path="/internal/admin/summary",
                body=b"",
                request_id="request-2",
            ),
        )

    assert health.status_code == 200
    assert health.json()["admin_user_id"] == 100
    assert summary.status_code == 200
    assert summary.json() == {"users": 10, "admin": 100}


@pytest.mark.asyncio
async def test_admin_api_rejects_invalid_signature_and_regular_user() -> None:
    app = create_app(
        _settings(),
        manage_resources=False,
        admin_services=FakeAdminServices(),  # type: ignore[arg-type]
    )
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        bad_signature = await client.get(
            "/internal/admin/health",
            headers=_signed_headers(
                method="GET",
                path="/internal/admin/health",
                body=b"",
                signature_override="0" * 64,
            ),
        )
        regular_user = await client.get(
            "/internal/admin/health",
            headers=_signed_headers(
                method="GET",
                path="/internal/admin/health",
                body=b"",
                user_id=101,
                request_id="regular-user",
            ),
        )

    assert bad_signature.status_code == 401
    assert regular_user.status_code == 403


@pytest.mark.asyncio
async def test_admin_balance_write_requires_idempotency_and_confirmation() -> None:
    services = FakeAdminServices()
    app = create_app(
        _settings(),
        manage_resources=False,
        admin_services=services,  # type: ignore[arg-type]
    )
    path = "/internal/admin/users/42/balance-adjustments"
    raw = json.dumps(
        {"amount_units": 100, "reason": "manual correction"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        base_headers = _signed_headers(method="POST", path=path, body=raw)
        missing_controls = await client.post(
            path, content=raw, headers={**base_headers, "Content-Type": "application/json"}
        )
        allowed = await client.post(
            path,
            content=raw,
            headers={
                **_signed_headers(
                    method="POST",
                    path=path,
                    body=raw,
                    request_id="write-2",
                ),
                "Content-Type": "application/json",
                "Idempotency-Key": "adjust-1",
                "X-Admin-Confirm": "CONFIRM",
            },
        )

    assert missing_controls.status_code == 422
    assert allowed.status_code == 200
    assert allowed.json()["user_id"] == 42
    assert services.users.calls == 1


@pytest.mark.asyncio
async def test_admin_api_is_not_exposed_when_disabled() -> None:
    app = create_app(
        Settings(env="test", admin_api_enabled=False),
        manage_resources=False,
        admin_services=FakeAdminServices(),  # type: ignore[arg-type]
    )
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/internal/admin/health")
    assert response.status_code == 404
