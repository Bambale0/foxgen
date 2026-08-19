from aiogram import Bot, Router

from bot.notification_service import ensure_notification_campaign_worker
from bot.support_service import ensure_support_outbox_worker

router = Router()


async def start_delivery_workers(bot: Bot) -> None:
    """Start durable bot-owned delivery workers on dispatcher startup."""

    ensure_support_outbox_worker(bot)
    ensure_notification_campaign_worker(bot)


router.startup.register(start_delivery_workers)
