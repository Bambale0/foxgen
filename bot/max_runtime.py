from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from urllib.parse import urlparse

from aiohttp import web

from bot.max_api import MAX_UPDATE_TYPES, MaxClient, MaxSettings, setup_max_routes
from bot.max_generation import install_max_generation_worker
from bot.max_omni_audio import MaxOmniGenerationService
from bot.max_payments import MaxYooKassaService, ensure_max_payment_schema
from bot.max_suno_channel import MaxSunoChannelService
from bot.suno_jobs import install_suno_worker

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MaxRuntimeSettings:
    webhook_url: str
    bot_name: str
    payment_return_url: str
    support_contact: str
    payment_reconcile_seconds: int = 30

    @classmethod
    def from_env(cls) -> MaxRuntimeSettings:
        raw_interval = str(os.getenv("MAX_PAYMENT_RECONCILE_SECONDS", "30")).strip()
        try:
            interval = int(raw_interval)
        except ValueError:
            interval = 30
        return cls(
            webhook_url=str(os.getenv("MAX_WEBHOOK_URL", "")).strip(),
            bot_name=str(os.getenv("MAX_BOT_NAME", "")).strip().lstrip("@"),
            payment_return_url=str(os.getenv("MAX_PAYMENT_RETURN_URL", "")).strip(),
            support_contact=str(os.getenv("SUPPORT_CONTACT", "")).strip(),
            payment_reconcile_seconds=max(15, min(interval, 3600)),
        )

    def validate_enabled(self, settings: MaxSettings) -> None:
        if not settings.enabled:
            return
        if not self.webhook_url.startswith("https://"):
            raise RuntimeError("MAX_WEBHOOK_URL must be an HTTPS URL when MAX_ENABLED=1")
        parsed = urlparse(self.webhook_url)
        if parsed.path.rstrip("/") != settings.webhook_path.rstrip("/"):
            raise RuntimeError("MAX_WEBHOOK_URL path must match MAX_WEBHOOK_PATH")
        if not self.bot_name:
            raise RuntimeError("MAX_BOT_NAME is required when MAX_ENABLED=1")
        if not self.payment_return_url.startswith("https://"):
            raise RuntimeError(
                "MAX_PAYMENT_RETURN_URL must be an HTTPS URL when MAX_ENABLED=1"
            )


async def _ensure_max_subscription(
    client: MaxClient,
    *,
    webhook_url: str,
) -> None:
    payload = await client.get_subscriptions()
    subscriptions = payload.get("subscriptions") or []
    if not isinstance(subscriptions, list):
        subscriptions = []
    for subscription in subscriptions:
        if not isinstance(subscription, dict):
            continue
        if str(subscription.get("url") or "").rstrip("/") != webhook_url.rstrip("/"):
            continue
        declared = subscription.get("update_types") or []
        if isinstance(declared, list) and declared:
            missing = set(MAX_UPDATE_TYPES) - {str(item) for item in declared}
            if missing:
                raise RuntimeError(
                    "Existing MAX webhook subscription is missing update types: "
                    + ", ".join(sorted(missing))
                )
        logger.info("MAX webhook subscription already active: %s", webhook_url)
        return
    await client.create_subscription(webhook_url)
    logger.info("MAX webhook subscription created: %s", webhook_url)


async def _max_payment_reconcile_loop(
    *,
    payments: MaxYooKassaService,
    client: MaxClient,
    interval_seconds: int,
    stop_event: asyncio.Event,
) -> None:
    while not stop_event.is_set():
        try:
            completed = await payments.reconcile_pending(limit=50)
            for item in completed:
                order = item.get("order")
                if order is None:
                    continue
                balance = float(item.get("balance") or 0)
                try:
                    await client.send_message(
                        int(order.max_user_id),
                        "✅ <b>Оплата MAX подтверждена</b>\n\n"
                        f"Начислено: <b>{order.credits:g} 🐾</b>\n"
                        f"Баланс: <b>{balance:g} 🐾</b>",
                    )
                except Exception:
                    logger.exception(
                        "Failed to send MAX payment notification: order=%s",
                        order.order_id,
                    )
        except Exception:
            logger.exception("MAX payment reconciliation tick failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            pass


def setup_max_runtime(app: web.Application) -> None:
    """Composition root for MAX plus the channel-agnostic durable Suno worker."""
    # Telegram Suno also uses this worker. Internal API always calls this
    # composition root, therefore install it before the MAX feature flag check.
    install_suno_worker(app)

    settings = MaxSettings.from_env()
    if not settings.enabled:
        logger.info("MAX channel disabled")
        return

    settings.validate_enabled()
    runtime = MaxRuntimeSettings.from_env()
    runtime.validate_enabled(settings)

    client = MaxClient(settings)
    payments = MaxYooKassaService(return_url=runtime.payment_return_url)
    if not payments.enabled:
        raise RuntimeError(
            "MAX_ENABLED=1 requires YooKassa credentials and MAX_PAYMENT_RETURN_URL"
        )
    channel = MaxSunoChannelService(
        settings=settings,
        client=client,
        payments=payments,
        bot_name=runtime.bot_name,
        support_contact=runtime.support_contact,
    )
    generation = MaxOmniGenerationService(client)

    setup_max_routes(app, settings=settings, event_handler=channel.handle_update)
    app["max_client"] = client
    app["max_channel"] = channel

    async def runtime_ctx(_app: web.Application):
        await ensure_max_payment_schema()
        await _ensure_max_subscription(client, webhook_url=runtime.webhook_url)
        stop_event = asyncio.Event()
        reconcile_task = asyncio.create_task(
            _max_payment_reconcile_loop(
                payments=payments,
                client=client,
                interval_seconds=runtime.payment_reconcile_seconds,
                stop_event=stop_event,
            )
        )
        try:
            yield
        finally:
            stop_event.set()
            reconcile_task.cancel()
            try:
                await reconcile_task
            except asyncio.CancelledError:
                pass
            await payments.close()
            await client.close()

    app.cleanup_ctx.append(runtime_ctx)
    install_max_generation_worker(app, generation)

    logger.info(
        "MAX runtime registered: webhook=%s path=%s",
        runtime.webhook_url,
        settings.webhook_path,
    )
