"""Exercise the production SQL adapter against an isolated PostgreSQL database."""

import asyncio
import os
import subprocess
import time
from pathlib import Path

import psycopg
import pytest

from bot import database, db
from bot.max_payments import MaxYooKassaService
from bot.max_store import get_max_balance
from bot.schema_migrations import run_schema_migrations


@pytest.fixture
def payment_database_url():
    explicit = os.getenv("TEST_PAYMENT_DATABASE_URL")
    if explicit:
        yield explicit
        return
    if os.getenv("CI", "").lower() != "true":
        pytest.skip("isolated PostgreSQL not configured")
    # Existing backend CI runs the full suite on a Docker-capable Ubuntu runner.
    # Own the container lifecycle here; never borrow the production data plane.
    container = subprocess.check_output(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "-e",
            "POSTGRES_PASSWORD=ci-only",
            "-e",
            "POSTGRES_DB=happyfox_payment_test",
            "-p",
            "127.0.0.1::5432",
            "postgres:16-alpine",
        ],
        text=True,
    ).strip()
    try:
        # The image first starts a temporary socket-only server during initdb.
        # TCP readiness waits for the final server, avoiding its shutdown race.
        for _ in range(60):
            ready = subprocess.run(
                [
                    "docker",
                    "exec",
                    container,
                    "pg_isready",
                    "-h",
                    "127.0.0.1",
                    "-U",
                    "postgres",
                ],
                capture_output=True,
                check=False,
            )
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            pytest.fail("isolated PostgreSQL did not become ready")
        port = (
            subprocess.check_output(
                ["docker", "port", container, "5432/tcp"], text=True
            )
            .strip()
            .rsplit(":", 1)[1]
        )
        yield f"postgresql://postgres:ci-only@127.0.0.1:{port}/happyfox_payment_test"
    finally:
        subprocess.run(["docker", "stop", container], capture_output=True, check=False)


@pytest.mark.asyncio
async def test_concurrent_channel_completions_are_atomic(
    monkeypatch, payment_database_url
):
    monkeypatch.setenv("DATABASE_URL", payment_database_url)
    async with await psycopg.AsyncConnection.connect(
        os.environ["DATABASE_URL"]
    ) as connection:
        await connection.execute(Path("schema_postgres.sql").read_text())
    try:
        await database.init_db()
        await run_schema_migrations()
        user = await database.get_or_create_user(99401)
        await database.create_transaction(
            order_id="pg-concurrent-tg",
            user_id=user.id,
            credits=25,
            amount_rub=250,
            provider="yookassa",
            payment_id="pg-tg-payment",
        )
        before = user.credits
        results = await asyncio.gather(
            *(database.complete_payment_atomic("pg-concurrent-tg") for _ in range(16))
        )
        assert sum(r.get("ok") and not r.get("already_completed") for r in results) == 1
        assert (await database.get_or_create_user(99401)).credits - before == 25
        service = MaxYooKassaService(
            return_url="https://max.ru/test", shop_id="shop", secret_key="secret"
        )
        captured = {}

        async def provider(method, endpoint, **kwargs):
            if method == "POST":
                captured.update(kwargs["json_payload"])
                return {
                    "id": "pg-max-payment",
                    "confirmation": {"confirmation_url": "https://example.invalid/pay"},
                }
            return {
                "id": "pg-max-payment",
                "status": "succeeded",
                "paid": True,
                "amount": captured["amount"],
                "metadata": captured["metadata"],
            }

        monkeypatch.setattr(service, "_request", provider)
        order = await service.create_checkout(99402, "start")
        results = await asyncio.gather(
            *(service.complete_order(order.order_id) for _ in range(16))
        )
        assert sum(r.get("ok") and not r.get("already_completed") for r in results) == 1
        assert await get_max_balance(99402) == 30
        async with db.connect() as connection:
            row = await (
                await connection.execute(
                    "SELECT COUNT(*) FROM payment_notification_outbox"
                )
            ).fetchone()
            assert row[0] == 2
    finally:
        await db.close()
