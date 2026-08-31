import asyncio

from bot import database
from bot.max_payments import (
    MaxYooKassaService,
    get_max_payment_order,
    get_max_referral_stats,
    register_max_referral,
)
from bot.max_store import get_max_balance


def _prepare_database(database_path, monkeypatch) -> None:
    monkeypatch.setattr(database, "DATABASE_PATH", str(database_path))
    asyncio.run(database.init_db())


def _payment_service(monkeypatch, *, remote_amount: str = "250.00"):
    service = MaxYooKassaService(
        return_url="https://max.ru/happyfox_bot?start=max_payment",
        shop_id="shop",
        secret_key="secret",
        api_base_url="https://api.example.invalid/v3",
    )
    captured = {}

    async def fake_request(method, endpoint, *, json_payload=None, idempotence_key=None):
        if method == "POST":
            captured["metadata"] = dict(json_payload["metadata"])
            captured["amount"] = dict(json_payload["amount"])
            captured["idempotence_key"] = idempotence_key
            return {
                "id": "yk-max-1",
                "status": "pending",
                "confirmation": {"confirmation_url": "https://pay.example.invalid/checkout"},
            }
        return {
            "id": "yk-max-1",
            "status": "succeeded",
            "paid": True,
            "amount": {"value": remote_amount, "currency": "RUB"},
            "metadata": captured["metadata"],
        }

    monkeypatch.setattr(service, "_request", fake_request)
    return service, captured


def test_max_yookassa_credits_only_max_ledger_and_is_idempotent(tmp_path, monkeypatch) -> None:
    _prepare_database(tmp_path / "max-payments.db", monkeypatch)
    service, captured = _payment_service(monkeypatch)

    order = asyncio.run(service.create_checkout(300, "start"))
    assert order.max_user_id == 300
    assert order.credits == 25
    assert order.amount_rub == 250
    assert order.provider_payment_id == "yk-max-1"
    assert captured["metadata"] == {
        "order_id": order.order_id,
        "product": "happyfox-max",
        "channel": "max",
        "max_user_id": "300",
    }
    assert captured["idempotence_key"]

    completed = asyncio.run(service.complete_order(order.order_id))
    assert completed["ok"] is True
    assert completed["status"] == "completed"
    assert asyncio.run(get_max_balance(300)) == 25

    duplicate = asyncio.run(service.complete_order(order.order_id))
    assert duplicate["already_completed"] is True
    assert asyncio.run(get_max_balance(300)) == 25

    async def _assert_telegram_untouched() -> None:
        from bot import db as db_backend

        async with db_backend.connect() as db:
            db.row_factory = db_backend.Row
            cursor = await db.execute(
                "SELECT order_id FROM transactions WHERE order_id = ?",
                (order.order_id,),
            )
            assert await cursor.fetchone() is None

    asyncio.run(_assert_telegram_untouched())


def test_max_referrals_award_signup_and_purchase_rewards_in_max_credits(tmp_path, monkeypatch) -> None:
    _prepare_database(tmp_path / "max-referrals.db", monkeypatch)

    assert asyncio.run(register_max_referral(20, 10)) is True
    assert asyncio.run(register_max_referral(30, 20)) is True
    assert asyncio.run(register_max_referral(30, 10)) is False

    before_l1 = asyncio.run(get_max_balance(20))
    before_l2 = asyncio.run(get_max_balance(10))
    assert before_l1 >= 3
    assert before_l2 >= 3

    service, _ = _payment_service(monkeypatch)
    order = asyncio.run(service.create_checkout(30, "start"))
    result = asyncio.run(service.complete_order(order.order_id))
    assert result["ok"] is True

    # 250 RUB * 30% / 10 RUB per paw = 7.5 paws for level 1.
    assert asyncio.run(get_max_balance(20)) == before_l1 + 7.5
    # 250 RUB * 7% / 10 RUB per paw = 1.75 paws for level 2.
    assert asyncio.run(get_max_balance(10)) == before_l2 + 1.75

    stats = asyncio.run(get_max_referral_stats(20))
    assert stats["referrals"] == 1
    assert stats["earned_credits"] >= 10.5


def test_max_yookassa_refuses_amount_mismatch_without_credit(tmp_path, monkeypatch) -> None:
    _prepare_database(tmp_path / "max-payment-mismatch.db", monkeypatch)
    service, _ = _payment_service(monkeypatch, remote_amount="251.00")

    order = asyncio.run(service.create_checkout(777, "start"))
    result = asyncio.run(service.complete_order(order.order_id))

    assert result["ok"] is False
    assert result["status"] == "verification_failed"
    assert result["reason"] == "amount_mismatch"
    assert asyncio.run(get_max_balance(777)) == 0
    persisted = asyncio.run(get_max_payment_order(order.order_id))
    assert persisted is not None
    assert persisted.status == "pending"
