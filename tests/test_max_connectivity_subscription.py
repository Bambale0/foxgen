from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.max_commands import MAX_QUICK_COMMANDS
from scripts import check_max_connectivity as checker

CANONICAL = "https://api.happy-fox.online/max/webhook"


def configure(monkeypatch, subscriptions):
    settings = SimpleNamespace(enabled=True, validate_enabled=lambda: None)
    monkeypatch.setattr(checker.MaxSettings, "from_env", lambda: settings)
    client = SimpleNamespace(
        get_subscriptions=AsyncMock(return_value={"subscriptions": subscriptions}),
        get_bot_info=AsyncMock(
            return_value={
                "commands": [
                    {"name": name, "description": description}
                    for name, description in MAX_QUICK_COMMANDS
                ]
            }
        ),
        close=AsyncMock(),
    )
    monkeypatch.setattr(checker, "MaxClient", lambda _: client)
    monkeypatch.setenv("MAX_WEBHOOK_URL", CANONICAL)
    return client


@pytest.mark.parametrize(
    "subscriptions",
    [
        [{"url": CANONICAL}, {"url": "https://legacy.example.invalid/max/webhook"}],
        [{"url": CANONICAL}, {"url": CANONICAL}],
        [{"url": "https://legacy.example.invalid/max/webhook"}],
        [],
        None,
        [{}],
    ],
)
@pytest.mark.asyncio
async def test_rejects_anything_except_one_canonical_subscription(
    monkeypatch, subscriptions
):
    client = configure(monkeypatch, subscriptions)
    with pytest.raises(RuntimeError, match="exactly one canonical"):
        await checker.check()
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_accepts_single_canonical_subscription(monkeypatch, capsys):
    client = configure(monkeypatch, [{"url": CANONICAL}])
    await checker.check()
    assert "subscriptions=1" in capsys.readouterr().out
    client.close.assert_awaited_once()
