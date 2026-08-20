"""
Скрипт для проверки и обработки pending платежей Lava через API
Синхронизация статусов между Lava системой и базой данных Таня TG
"""

import asyncio
import logging
import json
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from bot.services.lava_service import lava_service
from bot import db_backend
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

async def check_lava_payment_status(payment_id: str) -> dict:
    """Проверяет статус платежа через Lava API"""
    if not lava_service.enabled:
        return {"ok": False, "error": "Lava service not enabled"}
    
    try:
        invoice = await lava_service.get_invoice(payment_id)
        if not invoice:
            return {"ok": False, "error": "Invoice not found"}
        
        # Извлекаем статус из ответа Lava
        status = str(invoice.get("status") or "").lower()
        
        # Конвертируем статусы Lava в наши статусы
        if status in {"completed", "success", "succeeded", "paid"}:
            return {"ok": True, "status": "completed", "invoice_data": invoice}
        elif status in {"cancelled", "canceled", "failed", "expired"}:
            return {"ok": True, "status": "failed", "invoice_data": invoice}
        else:
            return {"ok": True, "status": "pending", "invoice_data": invoice}
            
    except Exception as e:
        logger.error(f"Error checking Lava payment {payment_id}: {e}")
        return {"ok": False, "error": str(e)}

async def process_completed_lava_payment(order_id: str, telegram_id: int):
    """Обработка завершенного платежа Lava"""
    from bot.handlers.payments import _complete_transaction
    
    try:
        # Используем существующую логику завершения транзакций
        completion = await _complete_transaction(order_id, bot=None)
        
        if completion.get("already_completed"):
            logger.info(f"Lava payment {order_id} already processed, skipping")
            return {"ok": True, "already_completed": True}
        
        if not completion.get("ok"):
            logger.error(f"Lava payment {order_id} completion failed: {completion.get('reason')}")
            return {"ok": False, "error": completion.get("reason")}
        
        transaction = completion["transaction"]
        referral_bonus = completion.get("referral_bonus") or {}
        promo_bonus = completion.get("promo_bonus") or {}
        
        # Формируем сообщение об успешном платеже
        bonus_text = ""
        if referral_bonus:
            bonus_text = f" (реферальный бонус +{referral_bonus.get('bonus_credits', 0)}🍌)"
        if promo_bonus:
            promo_text = f" (промокод +{promo_bonus.get('bonus_credits', 0)}🍌)"
            bonus_text = promo_text + bonus_text
        
        # Отправляем уведомление пользователю
        message = (
            "✅ <b>Оплата успешно обработана</b>\n"
            f"• Начислено: <code>{transaction.credits}</code> бананов\n"
            f"• Сумма: <code>{transaction.amount_rub}</code> ₽{bonus_text}"
        )
        
        # Здесь нужно добавить отправку через notify_user_success
        # TODO: Интегрировать с существующей системой уведомлений
        
        logger.info(f"Lava payment {order_id} completed successfully")
        return {"ok": True, "completed": True}
        
    except Exception as e:
        logger.exception(f"Error processing Lava payment {order_id}: {e}")
        return {"ok": False, "error": str(e)}

async def check_all_pending_lava_payments():
    """Проверяет все pending платежи Lava в базе данных"""
    logger.info("Starting Lava pending payments check...")
    
    pending_payments = []
    
    try:
        async with db_backend.connect() as db:
            db.row_factory = db_backend.Row
            cursor = await db.execute(
                "SELECT order_id, payment_id FROM transactions "
                "WHERE provider = 'lava' AND status = 'pending' "
                "ORDER BY created_at DESC"
            )
            rows = await cursor.fetchall()
            
            for row in rows:
                pending_payments.append({
                    "order_id": row["order_id"],
                    "payment_id": row["payment_id"]
                })
    
    except Exception as e:
        logger.error(f"Error fetching pending Lava payments: {e}")
        return
    
    if not pending_payments:
        logger.info("No pending Lava payments found")
        return
    
    logger.info(f"Found {len(pending_payments)} pending Lava payments")
    
    for payment in pending_payments:
        order_id = payment["order_id"]
        payment_id = payment["payment_id"]
        
        try:
            logger.info(f"Checking Lava payment {payment_id} (order: {order_id})")
            
            # Проверяем через Lava API
            if not lava_service.enabled:
                logger.error("Lava service not enabled")
                continue
                
            invoice = await lava_service.get_invoice(payment_id)
            if not invoice:
                logger.warning(f"Invoice {payment_id} not found in Lava")
                continue
            
            status = str(invoice.get("status") or "").lower()
            logger.info(f"Lava invoice {payment_id} status: {status}")
            
            # Дополнительные данные
            if status == "completed":
                amount = invoice.get("amount")
                currency = invoice.get("currency")
                logger.info(f"  Amount: {amount} {currency}")
            
            # Просто логируем, пока не обновляем БД
            
        except Exception as e:
            logger.error(f"Error checking Lava payment {payment_id}: {e}")
    
    logger.info("Lava payment check completed")

async def main():
    """Основная функция - запускает проверку Lava платежей"""
    logger.info("=== Lava Payment Status Checker ===")
    
    try:
        await check_all_pending_lava_payments()
        logger.info("Lava payment check completed successfully")
    except Exception as e:
        logger.exception(f"Error in Lava payment checker: {e}")
    finally:
        logger.info("=== Check finished ===")

if __name__ == "__main__":
    # Запуск однократной проверки
    asyncio.run(main())