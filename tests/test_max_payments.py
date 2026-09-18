import asyncio

from bot import database
from bot.max_payments import (
    MaxYooKassaService,
    get_max_payment_order,
    get_max_referral_stats,
    register_max_referral,
)
from bot.max_store import ensure_max_user, get_max_balance


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
    assert asyncio.run(get_max_balance(300)) == 30

    duplicate = asyncio.run(service.complete_order(order.order_id))
    assert duplicate["already_completed"] is True
    assert asyncio.run(get_max_balance(300)) == 30

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


def test_max_referrals_award_signup_and_first_purchase_rewards_in_max_credits(tmp_path, monkeypatch) -> None:
    _prepare_database(tmp_path / "max-referrals.db", monkeypatch)

    assert asyncio.run(register_max_referral(20, 10)) is True
    assert asyncio.run(register_max_referral(30, 20)) is True
    assert asyncio.run(register_max_referral(30, 10)) is False

    before_l1 = asyncio.run(get_max_balance(20))
    before_l2 = asyncio.run(get_max_balance(10))
    # Every new MAX user gets the signup gift. The inviter gift is deferred until
    # the invited user's first purchase.
    assert before_l1 == 5
    assert before_l2 == 5

    service, _ = _payment_service(monkeypatch)
    order = asyncio.run(service.create_checkout(30, "start"))
    result = asyncio.run(service.complete_order(order.order_id))
    assert result["ok"] is True

    # First purchase gift (3 paws) + 250 RUB * 30% / 10 RUB per paw = 7.5 paws.
    assert asyncio.run(get_max_balance(20)) == before_l1 + 10.5
    # 250 RUB * 7% / 10 RUB per paw = 1.75 paws for level 2.
    assert asyncio.run(get_max_balance(10)) == before_l2 + 1.75

    duplicate = asyncio.run(service.complete_order(order.order_id))
    assert duplicate["already_completed"] is True
    assert asyncio.run(get_max_balance(20)) == before_l1 + 10.5

    second_order = asyncio.run(service.create_checkout(30, "start"))
    second_result = asyncio.run(service.complete_order(second_order.order_id))
    assert second_result["ok"] is True
    # A second distinct purchase pays only percentage commissions, not the one-time gift.
    assert asyncio.run(get_max_balance(20)) == before_l1 + 18.0
    assert asyncio.run(get_max_balance(10)) == before_l2 + 3.5

    async def _gift_notifications() -> int:
        from bot import db as db_backend

        async with db_backend.connect() as db:
            cursor = await db.execute(
                """
                SELECT COUNT(*)
                FROM payment_notification_outbox
                WHERE channel = 'max' AND order_id LIKE '%:referrer:gift'
                """
            )
            row = await cursor.fetchone()
            return int(row[0])

    assert asyncio.run(_gift_notifications()) == 1

    stats = asyncio.run(get_max_referral_stats(20))
    assert stats["referrals"] == 1
    assert stats["earned_credits"] >= 18.0


def test_max_new_user_bonus_is_awarded_once_without_referral(tmp_path, monkeypatch) -> None:
    _prepare_database(tmp_path / "max-new-user.db", monkeypatch)

    user = asyncio.run(ensure_max_user(777))
    assert user.balance_credits == 5
    assert asyncio.run(get_max_balance(777)) == 5

    same_user = asyncio.run(ensure_max_user(777, username="fox"))
    assert same_user.balance_credits == 5
    assert asyncio.run(get_max_balance(777)) == 5


def test_max_legacy_inviter_bonus_key_prevents_first_purchase_gift_replay(tmp_path, monkeypatch) -> None:
    _prepare_database(tmp_path / "max-legacy-referral.db", monkeypatch)

    assert asyncio.run(register_max_referral(30, 20)) is True

    async def _insert_legacy_bonus() -> None:
        from bot import db as db_backend
        from bot.max_store import apply_max_balance_delta

        async with db_backend.connect() as db:
            await apply_max_balance_delta(
                20,
                3,
                tx_type="referral_signup_inviter",
                idempotency_key="maxref:30:inviter:20",
                connection=db,
                metadata={"buyer_max_user_id": 30},
            )
            await db.commit()

    asyncio.run(_insert_legacy_bonus())
    before_l1 = asyncio.run(get_max_balance(20))

    service, _ = _payment_service(monkeypatch)
    order = asyncio.run(service.create_checkout(30, "start"))
    result = asyncio.run(service.complete_order(order.order_id))
    assert result["ok"] is True

    assert asyncio.run(get_max_balance(20)) == before_l1 + 7.5
    stats = asyncio.run(get_max_referral_stats(20))
    assert stats["earned_credits"] >= 10.5

    async def _gift_notifications() -> int:
        from bot import db as db_backend

        async with db_backend.connect() as db:
            cursor = await db.execute(
                """
                SELECT COUNT(*)
                FROM payment_notification_outbox
                WHERE channel = 'max' AND order_id LIKE '%:referrer:gift'
                """
            )
            row = await cursor.fetchone()
            return int(row[0])

    assert asyncio.run(_gift_notifications()) == 0


def test_max_yookassa_refuses_amount_mismatch_without_credit(tmp_path, monkeypatch) -> None:
    _prepare_database(tmp_path / "max-payment-mismatch.db", monkeypatch)
    service, _ = _payment_service(monkeypatch, remote_amount="251.00")

    order = asyncio.run(service.create_checkout(777, "start"))
    result = asyncio.run(service.complete_order(order.order_id))

    assert result["ok"] is False
    assert result["status"] == "verification_failed"
    assert result["reason"] == "amount_mismatch"
    assert asyncio.run(get_max_balance(777)) == 5
    persisted = asyncio.run(get_max_payment_order(order.order_id))
    assert persisted is not None
    assert persisted.status == "pending"
