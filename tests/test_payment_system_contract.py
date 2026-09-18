import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import database, db
from bot.business_rules import (
    DEFAULT_RULES,
    get_business_rules,
    validate_business_rules,
)
from bot.max_payments import MaxYooKassaService, get_max_payment_order
from bot.max_store import get_max_balance
from bot.payment_checkout import save_checkout_intent, record_reconciliation_attempt
from bot.services.preset_manager import preset_manager
from bot.yookassa_webhook import handle_webhook, yookassa_service


@pytest.mark.asyncio
async def test_telegram_webhook_routes_and_credits_once(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "tg.db"))
    await database.init_db()
    user = await database.get_or_create_user(902)
    await database.create_transaction(
        order_id="tg-order",
        user_id=user.id,
        credits=25,
        amount_rub=250,
        provider="yookassa",
        payment_id="tg-payment",
    )
    remote = {
        "id": "tg-payment",
        "status": "succeeded",
        "paid": True,
        "amount": {"value": "250.00", "currency": "RUB"},
        "metadata": {"order_id": "tg-order"},
    }
    monkeypatch.setattr(yookassa_service, "enabled", True)
    monkeypatch.setattr(yookassa_service, "_request", AsyncMock(return_value=remote))
    before = user.credits
    app = web.Application()
    app.router.add_post("/yookassa/webhook", handle_webhook)
    async with TestClient(TestServer(app)) as client:
        responses = await asyncio.gather(
            *(
                client.post(
                    "/yookassa/webhook",
                    json={"event": "payment.succeeded", "object": {"id": "tg-payment"}},
                )
                for _ in range(8)
            )
        )
        assert all(response.status == 200 for response in responses)
    assert (await database.get_or_create_user(902)).credits - before == 25
    async with db.connect() as connection:
        row = await (
            await connection.execute(
                "SELECT channel,recipient_id FROM payment_notification_outbox"
            )
        ).fetchone()
        assert tuple(row) == ("telegram", 902)


@pytest.mark.asyncio
async def test_telegram_referral_inviter_gift_is_awarded_after_first_purchase_once(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "referral-gift.db"))
    await database.init_db()
    from bot.services import referral_service

    referrer = await database.get_or_create_user(930)
    referred = await database.get_or_create_user(931)
    async with db.connect() as connection:
        await connection.execute(
            "UPDATE users SET partner_agreed_at=CURRENT_TIMESTAMP WHERE id=?",
            (referrer.id,),
        )
        await connection.commit()
    before_referrer = await database.get_or_create_user(930)

    async with db.connect() as connection:
        connection.row_factory = db.Row
        result = await referral_service.attach_referral_in_transaction(
            connection,
            931,
            referred.id,
            referrer.referral_code,
            source="test",
        )
        assert result.attached is True
        await connection.commit()

    after_attach = await database.get_or_create_user(930)
    assert after_attach.credits == before_referrer.credits
    assert after_attach.referral_earned == before_referrer.referral_earned

    async with db.connect() as connection:
        connection.row_factory = db.Row
        referral = await (await connection.execute(
            "SELECT bonus_credits FROM referrals WHERE referrer_id=? AND referred_id=?",
            (referrer.id, referred.id),
        )).fetchone()
        assert referral is not None
        assert int(referral["bonus_credits"] or 0) == 0

    await database.create_transaction(
        order_id="ref-first-order",
        user_id=referred.id,
        credits=25,
        amount_rub=250,
        provider="yookassa",
        payment_id="ref-first-payment",
    )

    completion = await database.complete_payment_atomic("ref-first-order")
    assert completion["ok"] is True
    assert completion["already_completed"] is False
    assert completion["referral_bonus"]["invite_bonus_credits"] == get_business_rules()["inviter_bonus_credits"]

    after_first_purchase = await database.get_or_create_user(930)
    assert after_first_purchase.credits == before_referrer.credits + get_business_rules()["inviter_bonus_credits"]
    assert after_first_purchase.referral_earned == before_referrer.referral_earned + get_business_rules()["inviter_bonus_credits"]

    duplicate = await database.complete_payment_atomic("ref-first-order")
    assert duplicate["ok"] is True
    assert duplicate["already_completed"] is True
    after_duplicate = await database.get_or_create_user(930)
    assert after_duplicate.credits == after_first_purchase.credits
    assert after_duplicate.referral_earned == after_first_purchase.referral_earned

    async with db.connect() as connection:
        connection.row_factory = db.Row
        referral = await (await connection.execute(
            "SELECT bonus_credits FROM referrals WHERE referrer_id=? AND referred_id=?",
            (referrer.id, referred.id),
        )).fetchone()
        assert int(referral["bonus_credits"] or 0) == get_business_rules()["inviter_bonus_credits"]


@pytest.mark.asyncio
async def test_max_referral_failure_rolls_back_credit_and_status(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "max.db"))
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
    order = await service.create_checkout(903, "start")
    original = service._award_purchase_referrals
    monkeypatch.setattr(
        service,
        "_award_purchase_referrals",
        AsyncMock(side_effect=RuntimeError("database")),
    )
    with pytest.raises(RuntimeError):
        await service.complete_order(order.order_id)
    assert await get_max_balance(903) == 5
    assert (await get_max_payment_order(order.order_id)).status == "pending"
    monkeypatch.setattr(service, "_award_purchase_referrals", original)
    assert (await service.complete_order(order.order_id))["ok"]
    assert await get_max_balance(903) == 30


@pytest.mark.asyncio
async def test_reconciliation_placeholder_does_not_erase_checkout_snapshot(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "intent.db"))
    await record_reconciliation_attempt("telegram", "new")
    await save_checkout_intent("telegram", "new", {"order_id": "new"})
    from bot.payment_checkout import get_checkout_intent

    assert await get_checkout_intent("telegram", "new") == {"order_id": "new"}


def test_business_policy_reads_live_shared_control_plane(monkeypatch):
    policy = copy.deepcopy(DEFAULT_RULES)
    policy["level1_percent"] = 22
    monkeypatch.setattr(
        preset_manager, "get_price_config", lambda: {"business_rules": policy}
    )
    assert get_business_rules()["level1_percent"] == 22
    assert database.get_partner_percent_by_tier("basic") == 22
    policy["level2_percent"] = 90
    with pytest.raises(ValueError, match="100%"):
        validate_business_rules(policy)


@pytest.mark.asyncio
async def test_readiness_reports_dependency_failure(monkeypatch):
    from bot import payment_readiness

    monkeypatch.setattr(
        payment_readiness.db_backend,
        "connect",
        lambda: (_ for _ in ()).throw(RuntimeError("db")),
    )
    monkeypatch.setattr(
        payment_readiness.redis_service, "get_client", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(payment_readiness, "TASKS", {})
    report = await payment_readiness.readiness_report()
    assert report["status"] == "degraded"
    assert not report["checks"]["database"]
    assert not report["checks"]["payment_workers"]


@pytest.mark.asyncio
async def test_provider_identity_is_authoritative_over_foreign_metadata(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "identity.db"))
    await database.init_db()
    user = await database.get_or_create_user(905)
    for order, amount, payment in [
        ("owner", 100, "provider-payment"),
        ("foreign", 200, ""),
    ]:
        await database.create_transaction(
            order_id=order,
            user_id=user.id,
            credits=25,
            amount_rub=amount,
            provider="yookassa",
            payment_id=payment,
        )
    monkeypatch.setattr(yookassa_service, "enabled", True)
    monkeypatch.setattr(
        yookassa_service,
        "_request",
        AsyncMock(
            return_value={
                "id": "provider-payment",
                "status": "succeeded",
                "paid": True,
                "amount": {"value": "200.00", "currency": "RUB"},
                "metadata": {"order_id": "foreign"},
            }
        ),
    )
    result = await yookassa_service.get_payment("provider-payment")
    assert result["paid"] is False
    assert result["verification_error"] == "order_id_mismatch"


@pytest.mark.asyncio
async def test_disabled_channel_does_not_starve_notification_delivery(
    tmp_path, monkeypatch
):
    from bot.payment_delivery import (
        ensure_sqlite_outbox,
        enqueue_payment_notification,
        deliver_payment_notifications,
    )

    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "delivery.db"))
    async with db.connect() as connection:
        await ensure_sqlite_outbox(connection)
        for index in range(55):
            await enqueue_payment_notification(
                connection,
                channel="max",
                order_id=f"a{index}",
                recipient_id=1,
                message="MAX",
            )
        await enqueue_payment_notification(
            connection, channel="telegram", order_id="z", recipient_id=906, message="TG"
        )
        await connection.commit()
    bot = SimpleNamespace(send_message=AsyncMock())
    await deliver_payment_notifications({"bot": bot})
    bot.send_message.assert_awaited_once_with(906, "TG", parse_mode="HTML")


@pytest.mark.asyncio
async def test_max_promocode_bonus_is_accounted_once(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "promo.db"))
    await database.init_db()
    promo = await database.create_promo_code("SHARED")
    service = MaxYooKassaService(
        return_url="https://max.ru/test", shop_id="shop", secret_key="secret"
    )
    captured = {}

    async def provider(method, endpoint, **kwargs):
        if method == "POST":
            captured.update(kwargs["json_payload"])
            return {
                "id": "promo-payment",
                "confirmation": {"confirmation_url": "https://example.invalid/pay"},
            }
        return {
            "id": "promo-payment",
            "status": "succeeded",
            "paid": True,
            "amount": captured["amount"],
            "metadata": captured["metadata"],
        }

    monkeypatch.setattr(service, "_request", provider)
    order = await service.create_checkout(907, "start", promo_code="SHARED")
    assert order.credits == 30
    assert order.promo_bonus_credits == 5
    for _ in range(2):
        assert (await service.complete_order(order.order_id))["ok"]
    assert await get_max_balance(907) == 35
    updated = await database.get_promo_code_by_code(promo.code)
    assert updated.usage_count == 1
    assert updated.total_bonus_credits == 5


@pytest.mark.parametrize("first", ["bot.miniapp", "bot.handlers"])
def test_miniapp_and_handler_import_orders(first):
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import {first}; import bot.miniapp; import bot.handlers; assert not bot.handlers._COMPATIBILITY_INSTALLS",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
