#!/usr/bin/env python3
"""Скрипт для поиска и исправления рассинхронизации между referrals и users.referred_by.

Проблема: В таблице referrals есть запись (referrer_id→referred_id), 
но в users.referred_by у referred_id стоит NULL или другой referrer_id.

Это приводит к тому, что пользователь не отображается в списке рефералов
партнёра (get_partner_overview считает рефералов по users.referred_by).

Использование: python scripts/repair_referral_sync.py [--dry-run]
"""

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("repair_referral_sync")


async def main(dry_run: bool = True):
    from bot import db as db_backend
    from bot.database import DATABASE_PATH

    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row

        if db_backend.is_postgres():
            # PostgreSQL: ищем рассинхроны
            cursor = await db.execute("""
                SELECT 
                    r.id AS referral_id,
                    r.referrer_id,
                    r.referred_id,
                    u.telegram_id AS referred_telegram_id,
                    u.username AS referred_username,
                    u.referred_by AS current_referred_by,
                    ru.telegram_id AS referrer_telegram_id,
                    ru.username AS referrer_username
                FROM referrals r
                JOIN users u ON u.id = r.referred_id
                JOIN users ru ON ru.id = r.referrer_id
                WHERE u.referred_by IS NULL 
                   OR u.referred_by != r.referrer_id
                ORDER BY r.created_at DESC
            """)
        else:
            cursor = await db.execute("""
                SELECT 
                    r.id AS referral_id,
                    r.referrer_id,
                    r.referred_id,
                    u.telegram_id AS referred_telegram_id,
                    u.username AS referred_username,
                    u.referred_by AS current_referred_by,
                    ru.telegram_id AS referrer_telegram_id,
                    ru.username AS referrer_username
                FROM referrals r
                JOIN users u ON u.id = r.referred_id
                JOIN users ru ON ru.id = r.referrer_id
                WHERE u.referred_by IS NULL 
                   OR u.referred_by != r.referrer_id
                ORDER BY r.created_at DESC
            """)

        rows = await cursor.fetchall()
        if not rows:
            logger.info("✅ Рассинхронов не найдено. Все рефералы корректны.")
            return

        logger.warning("⚠️ Найдено %d рассинхронизированных рефералов:", len(rows))
        for row in rows:
            logger.warning(
                "  referral_id=%s referred_id=%s (tg=%s user=%s) current_referred_by=%s → должен быть %s (tg=%s user=%s)",
                row["referral_id"],
                row["referred_id"],
                row["referred_telegram_id"],
                row["referred_username"],
                row["current_referred_by"],
                row["referrer_id"],
                row["referrer_telegram_id"],
                row["referrer_username"],
            )

            if not dry_run:
                # Исправляем referred_by
                await db.execute(
                    "UPDATE users SET referred_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (row["referrer_id"], row["referred_id"]),
                )
                logger.info("    → Исправлено!")
        
        if not dry_run:
            await db.commit()
            logger.info("✅ Все рассинхроны исправлены.")
        else:
            logger.info("ℹ️ Запустите с флагом --apply для применения исправлений.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Исправление рассинхронизации рефералов")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Применить исправления (по умолчанию dry-run)",
    )
    args = parser.parse_args()

    import asyncio
    asyncio.run(main(dry_run=not args.apply))