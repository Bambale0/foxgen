"""
Read-only DB helpers for internal API.
Separate from database.py to avoid touching the main bot code.
"""

from __future__ import annotations

import logging

from bot import db as db_backend
from bot.database import DATABASE_PATH

logger = logging.getLogger(__name__)


async def simple_db_query_ok() -> bool:
    """Проверяет, что база данных отвечает (SELECT 1)."""
    async with db_backend.connect(DATABASE_PATH) as db:
        cursor = await db.execute("SELECT 1")
        row = await cursor.fetchone()
        return row is not None and row[0] == 1


async def get_db_aggregates() -> dict:
    """Агрегированная read-only статистика для internal API."""
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row

        # Пользователи
        cursor = await db.execute("""
            SELECT
                COUNT(*) AS total_users,
                COALESCE(SUM(CASE WHEN has_paid = 1 THEN 1 ELSE 0 END), 0) AS paid_users,
                COALESCE(SUM(CASE WHEN is_banned = 1 THEN 1 ELSE 0 END), 0) AS banned_users,
                COALESCE(SUM(credits), 0) AS total_credits
            FROM users
        """)
        users_row = await cursor.fetchone()

        # Генерации
        cursor = await db.execute("""
            SELECT
                COUNT(*) AS total_tasks,
                COALESCE(SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END), 0) AS completed_tasks,
                COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0) AS failed_tasks,
                COALESCE(SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END), 0) AS pending_tasks
            FROM generation_tasks
        """)
        tasks_row = await cursor.fetchone()

        # Транзакции
        cursor = await db.execute("""
            SELECT
                COUNT(*) AS total_transactions,
                COALESCE(SUM(CASE WHEN status = 'completed' THEN amount_rub ELSE 0 END), 0) AS completed_revenue_rub,
                COALESCE(SUM(CASE WHEN status = 'completed' THEN credits ELSE 0 END), 0) AS completed_credits,
                COALESCE(SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END), 0) AS pending_transactions
            FROM transactions
        """)
        tx_row = await cursor.fetchone()

    return {
        "users": {
            "total": users_row["total_users"] if users_row else 0,
            "paid": users_row["paid_users"] if users_row else 0,
            "banned": users_row["banned_users"] if users_row else 0,
            "total_credits": users_row["total_credits"] if users_row else 0,
        },
        "generations": {
            "total": tasks_row["total_tasks"] if tasks_row else 0,
            "completed": tasks_row["completed_tasks"] if tasks_row else 0,
            "failed": tasks_row["failed_tasks"] if tasks_row else 0,
            "pending": tasks_row["pending_tasks"] if tasks_row else 0,
        },
        "finance": {
            "total_transactions": tx_row["total_transactions"] if tx_row else 0,
            "completed_revenue_rub": float(tx_row["completed_revenue_rub"]) if tx_row else 0.0,
            "completed_credits": tx_row["completed_credits"] if tx_row else 0,
            "pending_transactions": tx_row["pending_transactions"] if tx_row else 0,
        },
    }