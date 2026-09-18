from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from bot import database
from bot.max_payments import MaxYooKassaService
from bot.max_store import get_max_balance
from bot.payment_delivery import deliver_payment_notifications
from bot.yookassa_webhook import handle_webhook


@pytest.mark.asyncio
async def test_shared_webhook_credits_max_once_and_retries_buyer_notification(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "payments.db"))
    await database.init_db()
    service = MaxYooKassaService(
        return_url="https://max.ru/test", shop_id="shop", secret_key="secret"
    )
    captured = {}

    async def provider(method, endpoint, **kwargs):
        if method == "POST":
            captured.update(kwargs["json_payload"])
            return {
                "id": "max-payment",
                "confirmation": {"confirmation_url": "https://example.invalid/pay"},
            }
        return {
            "id": "max-payment",
            "status": "succeeded",
            "paid": True,
            "amount": captured["amount"],
            "metadata": captured["metadata"],
        }

    monkeypatch.setattr(service, "_request", provider)
    order = await service.create_checkout(300, "start")
    max_client = SimpleNamespace(
        send_message=AsyncMock(side_effect=RuntimeError("network"))
    )
    telegram = SimpleNamespace(send_message=AsyncMock())
    app = web.Application()
    app["max_channel"] = SimpleNamespace(payments=service)
    app["max_client"] = max_client
    app["bot"] = telegram
    app.router.add_post("/yookassa/webhook", handle_webhook)
    app.router.add_post("/webhook/yookassa", handle_webhook)
    async with TestClient(TestServer(app)) as client:
        for path in ["/yookassa/webhook", "/webhook/yookassa"]:
            r = await client.post(
                path,
                json={"event": "payment.succeeded", "object": {"id": "max-payment"}},
            )
            assert r.status == 200
    assert await get_max_balance(300) == order.credits + 5
    await deliver_payment_notifications(app)
    max_client.send_message.assert_awaited_once()
    telegram.send_message.assert_not_awaited()
    max_client.send_message.side_effect = None
    from bot import db

    async with db.connect() as connection:
        await connection.execute(
            "UPDATE payment_notification_outbox SET next_attempt_at=0"
        )
        await connection.commit()
    await deliver_payment_notifications(app)
    assert max_client.send_message.await_count == 2
    assert max_client.send_message.call_args.args[0] == 300
    await deliver_payment_notifications(app)
    assert max_client.send_message.await_count == 2


@pytest.mark.asyncio
async def test_webhook_returns_retryable_error_on_provider_outage(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "payments.db"))
    await database.init_db()
    from bot.yookassa_webhook import yookassa_service

    monkeypatch.setattr(yookassa_service, "get_payment", AsyncMock(return_value=None))
    app = web.Application()
    app.router.add_post("/yookassa/webhook", handle_webhook)
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/yookassa/webhook",
            json={"event": "payment.succeeded", "object": {"id": "p"}},
        )
        assert response.status == 503
