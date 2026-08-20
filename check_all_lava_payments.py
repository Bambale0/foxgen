#!/usr/bin/env python3
"""
Скрипт для проверки ВСЕХ Lava платежей через API
Проверяет статусы и обновляет транзакции в БД
"""

import asyncio
import json
import logging
import sys
import os

# Добавляем путь к проекту
sys.path.append('/root/tanya/banano_kling')

# Импортируем после добавления пути
from bot.services.lava_service import lava_service
from bot import db_backend
from bot.config import config

# Настраиваем логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/lava_checker.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

async def check_invoice_status(payment_id: str):
    """Проверяет статус инвойса через Lava API"""
    if not lava_service.enabled:
        logger.error(f"Lava service is not enabled!")
        return None
    
    try:
        logger.info(f"Checking Lava invoice: {payment_id}")
        
        # Проверяем через Lava API
        invoice = await lava_service.get_invoice(payment_id)
        if invoice is None:
            logger.warning(f"Invoice {payment_id} not found in Lava")
            return None
        
        logger.info(f"Lava response: {json.dumps(invoice)[:500]}")
        
        # Получаем статус из инвойса
        status = str(invoice.get("status", "")).lower()
        order_id = invoice.get("order_id")
        amount = invoice.get("amount")
        currency = invoice.get("currency")
        
        return {
            "payment_id": payment_id,
            "order_id": order_id,
            "status": status,
            "amount": amount,
            "currency": currency,
            "invoice_data": invoice
        }
        
    except Exception as e:
        logger.error(f"Error checking invoice {payment_id}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None

async def get_all_pending_lava_transactions():
    """Получает все pending транзакции Lava из БД"""
    pending_transactions = []
    
    try:
        async with db_backend.connect() as db:
            db.row_factory = db_backend.Row
            cursor = await db.execute(
                "SELECT order_id, payment_id, user_id, amount_rub, credits, created_at "
                "FROM transactions "
                "WHERE provider = 'lava' AND status = 'pending' "
                "ORDER BY created_at DESC"
            )
            rows = await cursor.fetchall()
            
            for row in rows:
                pending_transactions.append({
                    "order_id": row["order_id"],
                    "payment_id": row["payment_id"],
                    "user_id": row["user_id"],
                    "amount_rub": row["amount_rub"],
                    "credits": row["credits"],
                    "created_at": row["created_at"]
                })
        
        logger.info(f"Found {len(pending_transactions)} pending Lava transactions")
        
    except Exception as e:
        logger.error(f"Error fetching pending transactions: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    return pending_transactions

async def update_transaction_status(order_id: str, new_status: str):
    """Обновляет статус транзакции в БД"""
    try:
        async with db_backend.connect() as db:
            await db.execute(
                "UPDATE transactions SET status = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE order_id = ?",
                (new_status, order_id)
            )
            await db.commit()
        
        logger.info(f"Updated transaction {order_id} to status: {new_status}")
        return True
    
    except Exception as e:
        logger.error(f"Error updating transaction {order_id}: {e}")
        return False

async def process_invoice(invoice_info: dict):
    """Обрабатывает инвойс и обновляет статус транзакции"""
    if not invoice_info:
        return False
    
    payment_id = invoice_info["payment_id"]
    status = invoice_info["status"]
    order_id = invoice_info["order_id"] or "unknown"
    
    logger.info(f"Processing invoice {payment_id}: status={status}, order={order_id}")
    
    if status in {"completed", "success", "succeeded", "paid"}:
        logger.info(f"✅ Invoice {payment_id} completed! Amount: {invoice_info.get('amount')} {invoice_info.get('currency')}")
        
        # Обновляем статус в БД
        updated = await update_transaction_status(order_id, "completed")
        if updated:
            logger.info(f"✅ Transaction {order_id} marked as completed")
            return True
        else:
            logger.error(f"❌ Failed to update transaction {order_id}")
            return False
    
    elif status in {"cancelled", "canceled", "failed", "expired"}:
        logger.info(f"❌ Invoice {payment_id} failed: {status}")
        
        # Обновляем статус в БД
        await update_transaction_status(order_id, "failed")
        logger.info(f"Transaction {order_id} marked as failed")
        return True
    
    else:
        logger.info(f"⏳ Invoice {payment_id} still pending: {status}")
        return False

async def main():
    """Основная функция проверки"""
    logger.info("=" * 60)
    logger.info("STARTING LAVA PAYMENTS CHECK")
    logger.info("=" * 60)
    
    # Проверяем Lava service
    if not lava_service.enabled:
        logger.error("Lava service is DISABLED! Check LAVA_API_KEY in .env")
        return
    
    logger.info(f"Lava service enabled: {lava_service.enabled}")
    logger.info(f"Using LAVA_API_KEY: {'*' * 10}{config.LAVA_API_KEY[-4:] if config.LAVA_API_KEY else 'N/A'}")
    
    # Получаем все pending транзакции
    pending_transactions = await get_all_pending_lava_transactions()
    
    if not pending_transactions:
        logger.info("No pending Lava transactions found")
        return
    
    logger.info(f"Checking {len(pending_transactions)} pending Lava transactions...")
    
    results = {
        "total": len(pending_transactions),
        "completed": 0,
        "failed": 0,
        "pending": 0,
        "not_found": 0,
        "errors": 0
    }
    
    # Проверяем каждую транзакцию
    for i, trans in enumerate(pending_transactions, 1):
        payment_id = trans["payment_id"]
        order_id = trans["order_id"]
        amount = trans["amount_rub"]
        user_id = trans["user_id"]
        
        logger.info(f"\n[{i}/{len(pending_transactions)}] Checking: payment_id={payment_id}, order={order_id}, amount={amount}₽, user={user_id}")
        
        # Проверяем статус через Lava API
        invoice_info = await check_invoice_status(payment_id)
        
        if invoice_info is None:
            logger.warning(f"  Invoice {payment_id} NOT FOUND in Lava system")
            results["not_found"] += 1
            continue
        
        status = invoice_info["status"]
        
        if status in {"completed", "success", "succeeded", "paid"}:
            results["completed"] += 1
        elif status in {"cancelled", "canceled", "failed", "expired"}:
            results["failed"] += 1
        else:
            results["pending"] += 1
        
        # Обрабатываем инвойс
        try:
            await process_invoice(invoice_info)
        except Exception as e:
            logger.error(f"Error processing invoice {payment_id}: {e}")
            results["errors"] += 1
    
    # Итоговый отчет
    logger.info("\n" + "=" * 60)
    logger.info("LAVA PAYMENTS CHECK COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Total checked: {results['total']}")
    logger.info(f"✅ Completed: {results['completed']}")
    logger.info(f"❌ Failed: {results['failed']}")
    logger.info(f"⏳ Still pending: {results['pending']}")
    logger.info(f"⚠️ Not found in Lava: {results['not_found']}")
    logger.info(f"🚫 Errors: {results['errors']}")
    
    # Если есть completed транзакции - показываем детали
    if results["completed"] > 0:
        logger.info("\n🔔 **ВНИМАНИЕ**: Completed транзакции нужно обработать!")
        logger.info("Нужно вызвать _complete_transaction для начисления кредитов")
    
    logger.info("=" * 60)

if __name__ == "__main__":
    # Запускаем асинхронную проверку
    asyncio.run(main())