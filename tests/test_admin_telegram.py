from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from foxgen.bot.admin import _authorize_callback, _authorize_message, admin_balance_confirm
from foxgen.bot.admin_api_client import AdminApiClientError


@pytest.mark.asyncio
async def test_non_admin_cannot_open_admin_from_message() -> None:
    client = SimpleNamespace(
        health=AsyncMock(
            side_effect=AdminApiClientError(
                "forbidden",
                status_code=403,
                code="admin_authorization",
            )
        )
    )
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=1001),
        answer=AsyncMock(),
    )
    state = SimpleNamespace(clear=AsyncMock())

    user_id = await _authorize_message(message, client, state=state)  # type: ignore[arg-type]

    assert user_id is None
    state.clear.assert_awaited_once()
    message.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_non_admin_cannot_execute_callback_or_continue_admin_fsm() -> None:
    client = SimpleNamespace(
        health=AsyncMock(
            side_effect=AdminApiClientError(
                "forbidden",
                status_code=403,
                code="admin_authorization",
            )
        )
    )
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=1002),
        answer=AsyncMock(),
    )
    state = SimpleNamespace(clear=AsyncMock(), get_data=AsyncMock())

    user_id = await _authorize_callback(callback, client, state=state)  # type: ignore[arg-type]
    await admin_balance_confirm(  # type: ignore[arg-type]
        callback,
        state,
        admin_api_client=client,
    )

    assert user_id is None
    assert state.clear.await_count >= 2
    state.get_data.assert_not_awaited()
    assert callback.answer.await_count >= 2


@pytest.mark.asyncio
async def test_admin_authorization_is_revalidated_for_each_event() -> None:
    client = SimpleNamespace(health=AsyncMock(return_value={"status": "ok"}))
    message = SimpleNamespace(from_user=SimpleNamespace(id=2001), answer=AsyncMock())
    callback = SimpleNamespace(from_user=SimpleNamespace(id=2001), answer=AsyncMock())

    assert await _authorize_message(message, client) == 2001  # type: ignore[arg-type]
    assert await _authorize_callback(callback, client) == 2001  # type: ignore[arg-type]
    assert client.health.await_count == 2
