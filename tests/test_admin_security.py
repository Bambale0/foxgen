import pytest

from foxgen.admin.errors import AdminAuthenticationError, AdminAuthorizationError
from foxgen.admin.policy import AdminContext
from foxgen.admin.security import (
    create_admin_session_token,
    ip_is_allowed,
    redact_secrets,
    request_signature,
    verify_admin_session_token,
    verify_request_signature,
)


def test_admin_hmac_is_exact_body_bound_and_timestamp_limited() -> None:
    secret = "admin-test-secret"
    body = b'{"amount_units":100,"reason":"test"}'
    signature = request_signature(
        secret=secret,
        timestamp="1000",
        method="POST",
        path="/internal/admin/users/1/balance-adjustments",
        request_id="req-1",
        raw_body=body,
    )

    verify_request_signature(
        secret=secret,
        timestamp="1000",
        method="POST",
        path="/internal/admin/users/1/balance-adjustments",
        request_id="req-1",
        raw_body=body,
        signature=signature,
        max_skew_seconds=300,
        now=1100,
    )

    with pytest.raises(AdminAuthenticationError):
        verify_request_signature(
            secret=secret,
            timestamp="1000",
            method="POST",
            path="/internal/admin/users/1/balance-adjustments",
            request_id="req-1",
            raw_body=b'{"reason":"test","amount_units":100}',
            signature=signature,
            max_skew_seconds=300,
            now=1100,
        )

    with pytest.raises(AdminAuthenticationError):
        verify_request_signature(
            secret=secret,
            timestamp="1000",
            method="POST",
            path="/internal/admin/users/1/balance-adjustments",
            request_id="req-1",
            raw_body=body,
            signature=signature,
            max_skew_seconds=30,
            now=1100,
        )


def test_network_allowlist_is_cidr_based_and_fail_closed() -> None:
    allowlist = ("127.0.0.1/32", "172.16.0.0/12")
    assert ip_is_allowed("127.0.0.1", allowlist) is True
    assert ip_is_allowed("172.31.10.25", allowlist) is True
    assert ip_is_allowed("10.0.0.1", allowlist) is False
    assert ip_is_allowed("not-an-ip", allowlist) is False
    assert ip_is_allowed(None, allowlist) is False


def test_recursive_secret_redaction_covers_required_key_fragments() -> None:
    payload = {
        "token": "one",
        "nested": {
            "api_key": "two",
            "callbackUrl": "three",
            "safe": "visible",
            "items": [{"Authorization": "four", "value": 5}],
        },
    }

    assert redact_secrets(payload) == {
        "token": "[REDACTED]",
        "nested": {
            "api_key": "[REDACTED]",
            "callbackUrl": "[REDACTED]",
            "safe": "visible",
            "items": [{"Authorization": "[REDACTED]", "value": 5}],
        },
    }


def test_admin_session_token_is_signed_and_expires() -> None:
    token = create_admin_session_token(
        secret="session-secret",
        admin_user_id=42,
        ttl_seconds=60,
        now=1000,
    )
    assert verify_admin_session_token(secret="session-secret", token=token, now=1059) == 42

    with pytest.raises(AdminAuthenticationError):
        verify_admin_session_token(secret="wrong", token=token, now=1059)
    with pytest.raises(AdminAuthenticationError):
        verify_admin_session_token(secret="session-secret", token=token, now=1060)


def test_admin_context_requires_explicit_scope() -> None:
    context = AdminContext(
        user_id=1,
        role="support",
        scopes=frozenset({"users:read"}),
        request_id="req",
    )
    context.require("users:read")
    with pytest.raises(AdminAuthorizationError):
        context.require("finance:write")
