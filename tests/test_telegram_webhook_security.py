import asyncio
from types import SimpleNamespace

from bot.config import config
from bot.main import handle_telegram_webhook


class _Request:
    def __init__(self, *, secret: str, body: bytes = b"") -> None:
        self.headers = {"X-Telegram-Bot-Api-Secret-Token": secret} if secret else {}
        self._body = body

    async def read(self) -> bytes:
        return self._body


def test_telegram_webhook_rejects_wrong_secret_before_parsing_body(monkeypatch) -> None:
    monkeypatch.setattr(config, "WEBHOOK_SECRET_TOKEN", "expected-secret")
    monkeypatch.setattr(config, "INTERNAL_API_SECRET", "")
    request = _Request(secret="wrong-secret", body=b'{"update_id": 1}')

    response = asyncio.run(handle_telegram_webhook(request, SimpleNamespace(), SimpleNamespace()))

    assert response.status == 401


def test_telegram_webhook_accepts_matching_secret(monkeypatch) -> None:
    monkeypatch.setattr(config, "WEBHOOK_SECRET_TOKEN", "expected-secret")
    monkeypatch.setattr(config, "INTERNAL_API_SECRET", "")
    request = _Request(secret="expected-secret", body=b"")

    response = asyncio.run(handle_telegram_webhook(request, SimpleNamespace(), SimpleNamespace()))

    assert response.status == 200
