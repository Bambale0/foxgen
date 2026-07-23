import base64
import hashlib
import hmac

import pytest

from foxgen.core.errors import WebhookVerificationError
from foxgen.providers.kie.webhooks import verify_kie_webhook


def sign(task_id: str, timestamp: str, secret: str) -> str:
    digest = hmac.new(
        secret.encode(),
        f"{task_id}.{timestamp}".encode(),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode()


def test_valid_webhook_signature() -> None:
    verify_kie_webhook(
        task_id="task-1",
        timestamp="1000",
        signature=sign("task-1", "1000", "secret"),
        secret="secret",
        max_age_seconds=300,
        now=1000,
    )


def test_rejects_expired_webhook() -> None:
    with pytest.raises(WebhookVerificationError):
        verify_kie_webhook(
            task_id="task-1",
            timestamp="1000",
            signature=sign("task-1", "1000", "secret"),
            secret="secret",
            max_age_seconds=300,
            now=1400,
        )
