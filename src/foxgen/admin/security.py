from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import time
from collections.abc import Mapping
from typing import Any

from foxgen.admin.errors import AdminAuthenticationError, AdminValidationError


SENSITIVE_KEYS = frozenset(
    {
        "token",
        "secret",
        "password",
        "authorization",
        "api_key",
        "apikey",
        "webhook",
        "callback",
    }
)


def _contains_sensitive_fragment(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in SENSITIVE_KEYS)


def redact_secrets(value: object) -> object:
    if isinstance(value, Mapping):
        redacted: dict[str, object] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            redacted[key] = (
                "[REDACTED]" if _contains_sensitive_fragment(key) else redact_secrets(raw_value)
            )
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return [redact_secrets(item) for item in value]
    return value


def request_signature(
    *,
    secret: str,
    timestamp: str,
    method: str,
    path: str,
    request_id: str,
    raw_body: bytes,
) -> str:
    prefix = f"{timestamp}\n{method.upper()}\n{path}\n{request_id}\n".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), prefix + raw_body, hashlib.sha256).hexdigest()


def verify_request_signature(
    *,
    secret: str,
    timestamp: str,
    method: str,
    path: str,
    request_id: str,
    raw_body: bytes,
    signature: str,
    max_skew_seconds: int,
    now: int | None = None,
) -> None:
    try:
        timestamp_int = int(timestamp)
    except ValueError as exc:
        raise AdminAuthenticationError("Invalid admin timestamp") from exc
    current = int(time.time()) if now is None else now
    if abs(current - timestamp_int) > max_skew_seconds:
        raise AdminAuthenticationError("Admin request timestamp is outside the allowed window")
    expected = request_signature(
        secret=secret,
        timestamp=timestamp,
        method=method,
        path=path,
        request_id=request_id,
        raw_body=raw_body,
    )
    if not hmac.compare_digest(expected, signature.strip().lower()):
        raise AdminAuthenticationError("Invalid admin request signature")


def ip_is_allowed(address: str | None, allowlist: tuple[str, ...]) -> bool:
    if not address:
        return False
    try:
        candidate = ipaddress.ip_address(address)
    except ValueError:
        return False
    for raw_network in allowlist:
        try:
            network = ipaddress.ip_network(raw_network, strict=False)
        except ValueError as exc:
            raise AdminValidationError(
                "Invalid admin network allowlist",
                details={"network": raw_network},
            ) from exc
        if candidate in network:
            return True
    return False


def create_admin_session_token(
    *,
    secret: str,
    admin_user_id: int,
    ttl_seconds: int,
    now: int | None = None,
) -> str:
    issued = int(time.time()) if now is None else now
    payload = {
        "admin_user_id": admin_user_id,
        "iat": issued,
        "exp": issued + ttl_seconds,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    signature = hmac.new(
        secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
    ).hexdigest()
    return f"{encoded}.{signature}"


def verify_admin_session_token(
    *,
    secret: str,
    token: str,
    now: int | None = None,
) -> int:
    try:
        encoded, supplied_signature = token.split(".", 1)
    except ValueError as exc:
        raise AdminAuthenticationError("Malformed admin session token") from exc
    expected = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, supplied_signature):
        raise AdminAuthenticationError("Invalid admin session token")
    padded = encoded + "=" * (-len(encoded) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload: Any = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdminAuthenticationError("Malformed admin session payload") from exc
    if not isinstance(payload, dict):
        raise AdminAuthenticationError("Malformed admin session payload")
    admin_user_id = payload.get("admin_user_id")
    expires_at = payload.get("exp")
    if not isinstance(admin_user_id, int) or not isinstance(expires_at, int):
        raise AdminAuthenticationError("Malformed admin session claims")
    current = int(time.time()) if now is None else now
    if current >= expires_at:
        raise AdminAuthenticationError("Admin session expired")
    return admin_user_id


def require_manual_confirmation(value: str | None) -> None:
    if value != "CONFIRM":
        raise AdminValidationError(
            "Manual confirmation is required",
            details={"required_header": "X-Admin-Confirm: CONFIRM"},
        )
