import base64
import hashlib
import hmac
import time

from foxgen.core.errors import ErrorCode, WebhookVerificationError


def verify_kie_webhook(
    *,
    task_id: str,
    timestamp: str,
    signature: str,
    secret: str,
    max_age_seconds: int = 300,
    now: int | None = None,
) -> None:
    try:
        timestamp_value = int(timestamp)
    except ValueError as exc:
        raise WebhookVerificationError(
            ErrorCode.WEBHOOK_INVALID, "Некорректная метка времени webhook."
        ) from exc

    current = int(time.time()) if now is None else now
    if abs(current - timestamp_value) > max_age_seconds:
        raise WebhookVerificationError(
            ErrorCode.WEBHOOK_INVALID, "Webhook просрочен или отправлен повторно."
        )

    signed_value = f"{task_id}.{timestamp}".encode()
    digest = hmac.new(secret.encode(), signed_value, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    if not hmac.compare_digest(expected, signature):
        raise WebhookVerificationError(
            ErrorCode.WEBHOOK_INVALID, "Подпись webhook не прошла проверку."
        )
