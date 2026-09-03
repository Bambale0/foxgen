import asyncio

import pytest
from aiohttp import web

from bot.max_api import MAX_UPDATE_TYPES, MaxSettings
from bot.max_runtime import (
    MaxRuntimeSettings,
    _ensure_max_subscription,
    setup_max_runtime,
)


class FakeSubscriptionClient:
    def __init__(self, subscriptions=None) -> None:
        self.subscriptions = subscriptions or []
        self.created = []

    async def get_subscriptions(self):
        return {"subscriptions": self.subscriptions}

    async def create_subscription(self, webhook_url):
        self.created.append(webhook_url)
        return {"success": True}


def test_max_runtime_is_dark_by_default(monkeypatch) -> None:
    monkeypatch.delenv("MAX_ENABLED", raising=False)
    app = web.Application()
    setup_max_runtime(app)
    assert "max_client" not in app
    assert all(
        getattr(route.resource, "canonical", "") != "/max/webhook"
        for route in app.router.routes()
    )


def test_enabled_max_runtime_requires_explicit_public_contract(monkeypatch) -> None:
    monkeypatch.setenv("MAX_WEBHOOK_URL", "https://api.example.invalid/max/webhook")
    monkeypatch.delenv("MAX_BOT_NAME", raising=False)
    monkeypatch.setenv(
        "MAX_PAYMENT_RETURN_URL",
        "https://api.example.invalid/mini-app/",
    )
    runtime = MaxRuntimeSettings.from_env()
    settings = MaxSettings(
        enabled=True,
        access_token="token",
        webhook_secret="valid_secret",
        webhook_path="/max/webhook",
    )
    # A missing bot username may hide referral deep links, but it must not take
    # down callbacks/generation/payment for the whole MAX channel.
    runtime.validate_enabled(settings)

    bad = MaxRuntimeSettings(
        webhook_url="https://api.example.invalid/wrong",
        bot_name="",
        payment_return_url="https://api.example.invalid/mini-app/",
        support_contact="",
    )
    with pytest.raises(RuntimeError, match="MAX_WEBHOOK_URL path"):
        bad.validate_enabled(settings)


def test_max_subscription_is_created_or_refreshed_with_event_parity() -> None:
    client = FakeSubscriptionClient()
    asyncio.run(
        _ensure_max_subscription(
            client,
            webhook_url="https://api.example.invalid/max/webhook",
        )
    )
    assert client.created == ["https://api.example.invalid/max/webhook"]

    existing = FakeSubscriptionClient(
        [
            {
                "url": "https://api.example.invalid/max/webhook",
                "update_types": list(MAX_UPDATE_TYPES),
            }
        ]
    )
    asyncio.run(
        _ensure_max_subscription(
            existing,
            webhook_url="https://api.example.invalid/max/webhook",
        )
    )
    # POST /subscriptions is also MAX's update operation. Refreshing the same
    # URL repairs a rotated/recovered webhook secret that GET cannot reveal.
    assert existing.created == ["https://api.example.invalid/max/webhook"]

    incomplete = FakeSubscriptionClient(
        [
            {
                "url": "https://api.example.invalid/max/webhook",
                "update_types": ["message_created"],
            }
        ]
    )
    asyncio.run(
        _ensure_max_subscription(
            incomplete,
            webhook_url="https://api.example.invalid/max/webhook",
        )
    )
    assert incomplete.created == ["https://api.example.invalid/max/webhook"]
