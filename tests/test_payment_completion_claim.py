import pytest
from unittest.mock import patch
from bot import database


class Cursor:
    def __init__(self, row=None, rowcount=1):
        self.row = row
        self.rowcount = rowcount

    async def fetchone(self):
        return self.row


class Connection:
    credited = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def execute(self, sql, params=()):
        if "SELECT * FROM transactions" in sql:
            return Cursor(
                dict(
                    id=1,
                    order_id="race",
                    user_id=1,
                    payment_id="payment",
                    provider="yookassa",
                    credits=25,
                    amount_rub=250,
                    status="pending",
                    created_at="2026-09-18T00:00:00",
                )
            )
        if "SET status = 'processing'" in sql:
            return Cursor(rowcount=0)  # concurrent worker already committed
        if "SELECT telegram_id, referred_by, has_paid" in sql:
            return Cursor(dict(telegram_id=100, referred_by=None, has_paid=True))
        if "SET credits = credits +" in sql:
            self.credited += params[0]
        return Cursor()

    async def rollback(self):
        pass

    async def commit(self):
        pass


@pytest.mark.asyncio
async def test_lost_payment_claim_never_credits():
    conn = Connection()
    with patch.object(database.db_backend, "connect", return_value=conn):
        result = await database.complete_payment_atomic("race")
    assert not result["ok"]
    assert conn.credited == 0
