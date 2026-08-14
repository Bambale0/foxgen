from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl

import jwt
from pydantic import BaseModel, ConfigDict, Field, ValidationError


JWT_ALGORITHM = "HS256"
JWT_AUDIENCE = "happy-fox-miniapp"
JWT_ISSUER = "foxgen"


class TelegramMiniAppUser(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int = Field(gt=0)
    first_name: str = Field(min_length=1, max_length=256)
    last_name: str | None = Field(default=None, max_length=256)
    username: str | None = Field(default=None, max_length=64)
    language_code: str | None = Field(default=None, max_length=35)
    photo_url: str | None = Field(default=None, max_length=2048)
    is_premium: bool = False

    @property
    def display_name(self) -> str:
        full = " ".join(part for part in (self.first_name, self.last_name) if part)
        return full or self.username or str(self.id)


@dataclass(frozen=True, slots=True)
class MiniAppPrincipal:
    user_id: int
    username: str | None
    display_name: str
    photo_url: str | None
    language_code: str | None
    is_premium: bool


def validate_telegram_init_data(
    init_data: str,
    *,
    bot_token: str,
    max_age_seconds: int,
    now: int | None = None,
) -> TelegramMiniAppUser:
    if not init_data or len(init_data) > 16_384:
        raise ValueError("Telegram initData is missing or too large")
    if not bot_token:
        raise ValueError("Telegram bot token is not configured")

    pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("Telegram initData contains duplicate fields")
    values = dict(pairs)

    received_hash = values.pop("hash", None)
    if not received_hash or len(received_hash) != 64:
        raise ValueError("Telegram initData hash is missing")

    data_check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(received_hash.lower(), expected_hash):
        raise ValueError("Telegram initData signature is invalid")

    raw_auth_date = values.get("auth_date")
    try:
        auth_date = int(raw_auth_date or "")
    except ValueError as exc:
        raise ValueError("Telegram initData auth_date is invalid") from exc
    resolved_now = int(time.time()) if now is None else now
    if auth_date > resolved_now + 30:
        raise ValueError("Telegram initData auth_date is in the future")
    if resolved_now - auth_date > max_age_seconds:
        raise ValueError("Telegram initData has expired")

    raw_user = values.get("user")
    if not raw_user:
        raise ValueError("Telegram initData does not contain a user")
    try:
        payload: Any = json.loads(raw_user)
        return TelegramMiniAppUser.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise ValueError("Telegram initData user payload is invalid") from exc


def issue_miniapp_token(
    user: TelegramMiniAppUser,
    *,
    secret: str,
    ttl_seconds: int,
    now: int | None = None,
) -> str:
    if not secret:
        raise ValueError("Mini App JWT secret is not configured")
    issued_at = int(time.time()) if now is None else now
    claims: dict[str, object] = {
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "sub": str(user.id),
        "iat": issued_at,
        "nbf": issued_at - 5,
        "exp": issued_at + ttl_seconds,
        "username": user.username,
        "name": user.display_name,
        "photo_url": user.photo_url,
        "language_code": user.language_code,
        "is_premium": user.is_premium,
    }
    return jwt.encode(claims, secret, algorithm=JWT_ALGORITHM)


def decode_miniapp_token(token: str, *, secret: str) -> MiniAppPrincipal:
    if not token or not secret:
        raise ValueError("Mini App token is unavailable")
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[JWT_ALGORITHM],
            audience=JWT_AUDIENCE,
            issuer=JWT_ISSUER,
            options={"require": ["exp", "iat", "sub"]},
        )
        user_id = int(claims["sub"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("Mini App token is invalid or expired") from exc
    if user_id <= 0:
        raise ValueError("Mini App token user is invalid")

    username = claims.get("username")
    display_name = claims.get("name")
    photo_url = claims.get("photo_url")
    language_code = claims.get("language_code")
    return MiniAppPrincipal(
        user_id=user_id,
        username=username if isinstance(username, str) else None,
        display_name=display_name if isinstance(display_name, str) else str(user_id),
        photo_url=photo_url if isinstance(photo_url, str) else None,
        language_code=language_code if isinstance(language_code, str) else None,
        is_premium=bool(claims.get("is_premium")),
    )
