from unittest.mock import AsyncMock
import pytest
from bot import database
from bot.payment_checkout import create_telegram_checkout, recover_telegram_checkout
from bot.services.yookassa_service import yookassa_service


@pytest.mark.asyncio
async def test_checkout_persists_owner_before_provider_and_recovers_ambiguous_response(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "checkout.db"))
    await database.init_db()
    user = await database.get_or_create_user(100)
    remote = AsyncMock(
        side_effect=[
            None,
            {
                "Success": True,
                "PaymentId": "p",
                "PaymentURL": "https://example.invalid/pay",
            },
        ]
    )
    monkeypatch.setattr(yookassa_service, "create_payment", remote)
    result = await create_telegram_checkout(
        user_id=user.id,
        credits=25,
        amount_rub=250,
        order_id="order",
        description="HappyFox",
        return_url="https://example.invalid",
    )
    assert result is None
    transaction = await database.get_transaction_by_order("order")
    assert transaction and transaction.user_id == user.id and not transaction.payment_id
    recovered = await recover_telegram_checkout("order")
    assert recovered["PaymentId"] == "p"
    assert (await database.get_transaction_by_order("order")).payment_id == "p"
    assert remote.call_args_list[0] == remote.call_args_list[1]


@pytest.mark.asyncio
async def test_expired_creation_key_is_never_replayed(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "checkout.db"))
    await database.init_db()
    from bot.payment_checkout import save_checkout_intent
    from bot import db

    await save_checkout_intent("telegram", "expired", {"order_id": "expired"})
    async with db.connect() as connection:
        await connection.execute("UPDATE payment_checkout_intents SET created_at=0")
        await connection.commit()
    provider = AsyncMock()
    monkeypatch.setattr(yookassa_service, "create_payment", provider)
    assert await recover_telegram_checkout("expired") is None
    provider.assert_not_awaited()
