from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from foxgen.bot.api_client import FoxGenApiClient, FoxGenApiError
from foxgen.bot.payments import redeem_promo


@pytest.mark.asyncio
async def test_promo_command_requires_code() -> None:
    message = SimpleNamespace(
        text="/promo",
        from_user=SimpleNamespace(id=42, username="fox"),
        answer=AsyncMock(),
    )
    api_client = SimpleNamespace(_user_request=AsyncMock())

    await redeem_promo(cast(Any, message), cast(FoxGenApiClient, api_client))

    api_client._user_request.assert_not_awaited()
    rendered = message.answer.await_args.args[0]
    assert "/promo FOX500" in rendered


@pytest.mark.asyncio
async def test_promo_command_credits_through_trusted_user_api() -> None:
    message = SimpleNamespace(
        text="/promo fox500",
        from_user=SimpleNamespace(id=42, username="fox"),
        answer=AsyncMock(),
    )
    api_client = SimpleNamespace(
        _user_request=AsyncMock(
            return_value={
                "code": "FOX500",
                "reward_units": 500,
                "available_units": 1500,
                "currency": "CREDIT",
                "replayed": False,
            }
        )
    )

    await redeem_promo(cast(Any, message), cast(FoxGenApiClient, api_client))

    api_client._user_request.assert_awaited_once_with(
        "POST",
        "/v1/user-portal/promos/redeem",
        user_id=42,
        username="fox",
        json={"code": "fox500"},
    )
    rendered = message.answer.await_args.args[0]
    assert "500 CREDIT" in rendered
    assert "1500 CREDIT" in rendered


@pytest.mark.asyncio
async def test_promo_command_reports_replay_without_second_reward_message() -> None:
    message = SimpleNamespace(
        text="/promo FOX500",
        from_user=SimpleNamespace(id=42, username="fox"),
        answer=AsyncMock(),
    )
    api_client = SimpleNamespace(
        _user_request=AsyncMock(
            return_value={
                "code": "FOX500",
                "reward_units": 500,
                "available_units": 1500,
                "currency": "CREDIT",
                "replayed": True,
            }
        )
    )

    await redeem_promo(cast(Any, message), cast(FoxGenApiClient, api_client))

    rendered = message.answer.await_args.args[0]
    assert "уже был активирован" in rendered
    assert "Начислено" not in rendered
    assert "1500 CREDIT" in rendered


@pytest.mark.asyncio
async def test_promo_command_surfaces_backend_validation_error() -> None:
    message = SimpleNamespace(
        text="/promo BAD",
        from_user=SimpleNamespace(id=42, username="fox"),
        answer=AsyncMock(),
    )
    api_client = SimpleNamespace(
        _user_request=AsyncMock(
            side_effect=FoxGenApiError(
                "Промокод не найден.",
                status_code=422,
                retryable=False,
            )
        )
    )

    await redeem_promo(cast(Any, message), cast(FoxGenApiClient, api_client))

    rendered = message.answer.await_args.args[0]
    assert "Промокод не активирован" in rendered
    assert "Промокод не найден" in rendered
