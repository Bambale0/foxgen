import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from foxgen.api.miniapp_security import (
    decode_miniapp_token,
    issue_miniapp_token,
    validate_telegram_init_data,
)


BOT_TOKEN = "123456:test-miniapp-bot-token"
JWT_SECRET = "miniapp-jwt-test-secret-that-is-long-enough"


def signed_init_data(
    *,
    user_id: int = 424242,
    auth_date: int | None = None,
    first_name: str = "Алексей",
    username: str = "alex_fox",
) -> str:
    values = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAE-test-query-id",
        "user": json.dumps(
            {
                "id": user_id,
                "first_name": first_name,
                "username": username,
                "language_code": "ru",
                "is_premium": True,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }
    data_check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def test_valid_telegram_init_data_and_jwt_round_trip() -> None:
    init_data = signed_init_data()

    user = validate_telegram_init_data(
        init_data,
        bot_token=BOT_TOKEN,
        max_age_seconds=3600,
    )
    token = issue_miniapp_token(user, secret=JWT_SECRET, ttl_seconds=3600)
    principal = decode_miniapp_token(token, secret=JWT_SECRET)

    assert user.id == 424242
    assert user.display_name == "Алексей"
    assert user.is_premium is True
    assert principal.user_id == 424242
    assert principal.username == "alex_fox"
    assert principal.display_name == "Алексей"
    assert principal.is_premium is True


def test_telegram_init_data_rejects_tampering() -> None:
    init_data = signed_init_data().replace("alex_fox", "mallory")

    with pytest.raises(ValueError, match="signature is invalid"):
        validate_telegram_init_data(
            init_data,
            bot_token=BOT_TOKEN,
            max_age_seconds=3600,
        )


def test_telegram_init_data_rejects_expired_payload() -> None:
    now = int(time.time())
    init_data = signed_init_data(auth_date=now - 3601)

    with pytest.raises(ValueError, match="expired"):
        validate_telegram_init_data(
            init_data,
            bot_token=BOT_TOKEN,
            max_age_seconds=3600,
            now=now,
        )


def test_telegram_init_data_rejects_duplicate_fields() -> None:
    init_data = signed_init_data() + "&auth_date=1"

    with pytest.raises(ValueError, match="duplicate fields"):
        validate_telegram_init_data(
            init_data,
            bot_token=BOT_TOKEN,
            max_age_seconds=3600,
        )
