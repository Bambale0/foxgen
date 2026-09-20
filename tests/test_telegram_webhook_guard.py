from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.services.telegram_webhook_guard import (
    inspect_and_reconcile_telegram_webhook,
    webhook_drift_reasons,
)


class _FakeBot:
    def __init__(self, infos):
        self.infos = list(infos)
        self.set_calls = []

    async def get_webhook_info(self):
        if len(self.infos) > 1:
            return self.infos.pop(0)
        return self.infos[0]

    async def set_webhook(self, **kwargs):
        self.set_calls.append(kwargs)
        return True


def _info(
    *,
    url="https://api.happy-fox.online/webhook",
    ip="2.27.160.11",
    allowed=None,
    pending=0,
    error=None,
):
    return SimpleNamespace(
        url=url,
        ip_address=ip,
        allowed_updates=allowed
        if allowed is not None
        else ["message", "callback_query", "pre_checkout_query"],
        pending_update_count=pending,
        last_error_message=error,
    )


def test_drift_reasons_cover_url_ip_and_allowed_updates() -> None:
    reasons = webhook_drift_reasons(
        _info(
            url="https://legacy.example/webhook",
            ip="203.0.113.9",
            allowed=["message"],
        ),
        expected_url="https://api.happy-fox.online/webhook",
        expected_ip="2.27.160.11",
        expected_allowed_updates=["message", "callback_query", "pre_checkout_query"],
    )

    assert reasons == ("url", "ip_address", "allowed_updates")


@pytest.mark.asyncio
async def test_drift_is_repaired_without_dropping_pending_updates() -> None:
    expected_updates = ["message", "callback_query", "pre_checkout_query"]
    bot = _FakeBot(
        [
            _info(url="https://legacy.example/webhook", allowed=["message"], pending=7),
            _info(allowed=expected_updates, pending=7),
        ]
    )

    check = await inspect_and_reconcile_telegram_webhook(
        bot,
        expected_url="https://api.happy-fox.online/webhook",
        expected_ip="2.27.160.11",
        secret="secret",
        expected_allowed_updates=expected_updates,
        silence_seconds=300,
        last_update_age_seconds=10,
    )

    assert check.repaired is True
    assert check.remaining_drift_reasons == ()
    assert len(bot.set_calls) == 1
    assert bot.set_calls[0]["drop_pending_updates"] is False
    assert bot.set_calls[0]["allowed_updates"] == expected_updates
    assert bot.set_calls[0]["secret_token"] == "secret"
    assert bot.set_calls[0]["ip_address"] == "2.27.160.11"


@pytest.mark.asyncio
async def test_healthy_registration_is_not_rewritten() -> None:
    expected_updates = ["message", "callback_query", "pre_checkout_query"]
    bot = _FakeBot([_info(allowed=expected_updates)])

    check = await inspect_and_reconcile_telegram_webhook(
        bot,
        expected_url="https://api.happy-fox.online/webhook",
        expected_ip="2.27.160.11",
        secret="secret",
        expected_allowed_updates=expected_updates,
        silence_seconds=300,
        last_update_age_seconds=5,
    )

    assert check.drift_reasons == ()
    assert check.silence_detected is False
    assert bot.set_calls == []


@pytest.mark.asyncio
async def test_historical_error_alone_does_not_trigger_re_registration() -> None:
    expected_updates = ["message", "callback_query", "pre_checkout_query"]
    bot = _FakeBot(
        [_info(allowed=expected_updates, pending=0, error="Wrong response 504")]
    )

    check = await inspect_and_reconcile_telegram_webhook(
        bot,
        expected_url="https://api.happy-fox.online/webhook",
        expected_ip="2.27.160.11",
        secret="secret",
        expected_allowed_updates=expected_updates,
        silence_seconds=300,
        last_update_age_seconds=600,
    )

    assert check.drift_reasons == ()
    assert check.silence_detected is False
    assert bot.set_calls == []


@pytest.mark.asyncio
async def test_pending_queue_plus_update_silence_alerts_without_mutating_registration() -> None:
    expected_updates = ["message", "callback_query", "pre_checkout_query"]
    bot = _FakeBot([_info(allowed=expected_updates, pending=3)])

    check = await inspect_and_reconcile_telegram_webhook(
        bot,
        expected_url="https://api.happy-fox.online/webhook",
        expected_ip="2.27.160.11",
        secret="secret",
        expected_allowed_updates=expected_updates,
        silence_seconds=300,
        last_update_age_seconds=301,
    )

    assert check.silence_detected is True
    assert check.incident_key == "silence"
    assert bot.set_calls == []
