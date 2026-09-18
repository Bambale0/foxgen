"""Bounded readiness checks for the payment data plane and its workers."""

from __future__ import annotations
import asyncio
import os
from bot import db as db_backend
from bot.services.redis_service import redis_service
from bot.services.yookassa_service import yookassa_service

TASKS = {}


def register_payment_worker(name, task):
    TASKS[name] = task
    return task


async def readiness_report():
    checks = {}

    async def database_check():
        async with db_backend.connect() as connection:
            await (await connection.execute("SELECT 1")).fetchone()

    try:
        await asyncio.wait_for(database_check(), timeout=3)
        checks["database"] = True
    except Exception:
        checks["database"] = False
    try:
        client = await asyncio.wait_for(redis_service.get_client(), timeout=3)
        checks["redis"] = bool(
            client and await asyncio.wait_for(client.ping(), timeout=3)
        )
    except Exception:
        checks["redis"] = False
    required = {"delivery"}
    if yookassa_service.enabled:
        required.add("telegram_reconcile")
    if os.getenv("MAX_ENABLED", "0").lower() in {"1", "true", "yes", "on"}:
        required.add("max_reconcile")
    checks["payment_workers"] = all(
        name in TASKS and not TASKS[name].done() for name in required
    )
    return {
        "status": "ok" if all(checks.values()) else "degraded",
        "service": "happyfox",
        "revision": os.getenv("HAPPYFOX_RELEASE", "unknown"),
        "checks": checks,
    }
