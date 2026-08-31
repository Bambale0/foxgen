import asyncio

import pytest

from bot import database
from bot.max_store import (
    MaxInsufficientBalanceError,
    apply_max_balance_delta,
    ensure_max_user,
    get_max_balance,
    get_max_session,
    list_max_history,
    record_max_generation,
    save_max_session,
)


def _prepare_database(database_path, monkeypatch) -> None:
    monkeypatch.setattr(database, "DATABASE_PATH", str(database_path))
    asyncio.run(database.init_db())


def test_max_user_balance_history_and_session_are_isolated(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "max-isolated.db"
    _prepare_database(database_path, monkeypatch)

    user = asyncio.run(
        ensure_max_user(
            4242,
            username="max_creator",
            first_name="Max",
        )
    )
    assert user.max_user_id == 4242
    assert user.balance_credits == 0

    balance = asyncio.run(
        apply_max_balance_delta(
            4242,
            50,
            tx_type="purchase",
            idempotency_key="payment:one",
            payment_provider="test",
        )
    )
    assert balance == 50

    balance = asyncio.run(
        apply_max_balance_delta(
            4242,
            -2.5,
            tx_type="generation",
            idempotency_key="generation:one",
        )
    )
    assert balance == 47.5

    asyncio.run(save_max_session(4242, "image:waiting_prompt", {"model": "banana_2"}))
    session = asyncio.run(get_max_session(4242))
    assert session.state == "image:waiting_prompt"
    assert session.data == {"model": "banana_2"}

    asyncio.run(
        record_max_generation(
            4242,
            generation_key="generation:one",
            kind="image",
            model="banana_2",
            prompt="fox portrait",
            status="completed",
            cost=2.5,
            result_url="https://example.invalid/result.jpg",
        )
    )
    history = asyncio.run(list_max_history(4242))
    assert len(history) == 1
    assert history[0]["model"] == "banana_2"
    assert history[0]["result_url"].endswith("result.jpg")

    # MAX data lives in dedicated tables. A matching external ID must not create
    # or mutate Telegram's users/transactions/generation tables.
    async def _assert_no_telegram_user() -> None:
        from bot import db as db_backend

        async with db_backend.connect() as db:
            db.row_factory = db_backend.Row
            cursor = await db.execute(
                "SELECT id FROM users WHERE telegram_id = ?",
                (4242,),
            )
            assert await cursor.fetchone() is None

    asyncio.run(_assert_no_telegram_user())


def test_max_ledger_is_idempotent_and_never_goes_negative(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "max-ledger.db"
    _prepare_database(database_path, monkeypatch)

    asyncio.run(
        apply_max_balance_delta(
            7,
            10,
            tx_type="purchase",
            idempotency_key="pay:7",
        )
    )
    same = asyncio.run(
        apply_max_balance_delta(
            7,
            10,
            tx_type="purchase",
            idempotency_key="pay:7",
        )
    )
    assert same == 10
    assert asyncio.run(get_max_balance(7)) == 10

    with pytest.raises(MaxInsufficientBalanceError):
        asyncio.run(
            apply_max_balance_delta(
                7,
                -11,
                tx_type="generation",
                idempotency_key="gen:too-expensive",
            )
        )
    assert asyncio.run(get_max_balance(7)) == 10
