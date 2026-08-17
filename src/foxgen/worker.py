import asyncio
import os
import socket
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from foxgen.admin.payment_refund_worker import PaymentRefundWorker, TelegramStarsRefundSender
from foxgen.admin.rate_limit import RateLimitedAdminSender
from foxgen.admin.worker import AdminWorker, TelegramAdminDeliverySender
from foxgen.application.delivery import MediaPipeline
from foxgen.application.lifecycle import GenerationWorker
from foxgen.application.reference_memory import ReferenceDeleteProcessor
from foxgen.core.config import Settings, get_settings
from foxgen.infra.billing_lifecycle_repository import BillingAwareLifecycleRepository
from foxgen.infra.database import Database
from foxgen.infra.input_media import LocalInputMediaStorage
from foxgen.infra.media import SecureMediaDownloader, S3MediaStorage, TelegramMediaSender
from foxgen.infra.reference_memory import SqlAlchemyReferenceMemoryRepository
from foxgen.providers.kie.client import KieClient
from foxgen.providers.kie.registry import ModelRegistry
from foxgen.providers.kie.router import RoutedKieClient


async def run(settings: Settings | None = None) -> None:
    resolved = settings or get_settings()
    api_key = resolved.kie_api_key
    telegram_token = resolved.telegram_bot_token
    internal_token = resolved.internal_api_token
    if api_key is None:
        raise RuntimeError("FOXGEN_KIE_API_KEY is required for the generation worker")
    if telegram_token is None:
        raise RuntimeError("FOXGEN_TELEGRAM_BOT_TOKEN is required for result delivery")
    if internal_token is None:
        raise RuntimeError("FOXGEN_INTERNAL_API_TOKEN is required for private generation inputs")

    database = Database(resolved.database_url)
    repository = BillingAwareLifecycleRepository(database)
    input_storage = LocalInputMediaStorage(
        root=resolved.telegram_input_storage_root,
        public_base_url=resolved.telegram_input_public_base_url,
        signing_secret=internal_token.get_secret_value(),
        presigned_url_ttl_seconds=resolved.telegram_input_presigned_url_ttl_seconds,
        retention_seconds=resolved.telegram_input_retention_seconds,
    )
    client = RoutedKieClient(
        KieClient(
            api_key=api_key.get_secret_value(),
            base_url=str(resolved.kie_base_url),
        ),
        input_media=input_storage,
    )
    downloader = SecureMediaDownloader(
        timeout_seconds=resolved.media_download_timeout_seconds,
        max_bytes=resolved.media_max_bytes,
    )
    storage = S3MediaStorage(
        bucket=resolved.s3_bucket,
        region=resolved.s3_region,
        endpoint_url=str(resolved.s3_endpoint_url) if resolved.s3_endpoint_url else None,
        access_key_id=(
            resolved.s3_access_key_id.get_secret_value()
            if resolved.s3_access_key_id is not None
            else None
        ),
        secret_access_key=(
            resolved.s3_secret_access_key.get_secret_value()
            if resolved.s3_secret_access_key is not None
            else None
        ),
        force_path_style=resolved.s3_force_path_style,
        presigned_url_ttl_seconds=resolved.media_presigned_url_ttl_seconds,
    )
    reference_storage = S3MediaStorage(
        bucket=resolved.s3_bucket,
        region=resolved.s3_region,
        endpoint_url=str(resolved.s3_endpoint_url) if resolved.s3_endpoint_url else None,
        access_key_id=(
            resolved.s3_access_key_id.get_secret_value()
            if resolved.s3_access_key_id is not None
            else None
        ),
        secret_access_key=(
            resolved.s3_secret_access_key.get_secret_value()
            if resolved.s3_secret_access_key is not None
            else None
        ),
        force_path_style=resolved.s3_force_path_style,
        presigned_url_ttl_seconds=resolved.reference_memory_presigned_url_ttl_seconds,
    )
    bot = Bot(
        token=telegram_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    media_pipeline = MediaPipeline(
        repository=repository,
        downloader=downloader,
        storage=storage,
        sender=TelegramMediaSender(bot),
    )
    reference_delete_processor = ReferenceDeleteProcessor(
        repository=SqlAlchemyReferenceMemoryRepository(database),
        storage=reference_storage,
    )

    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    worker = GenerationWorker(
        repository=repository,
        client=client,
        registry=ModelRegistry(),
        callback_url=resolved.kie_callback_url,
        media_pipeline=media_pipeline,
        reference_delete_processor=reference_delete_processor,
        worker_id=worker_id,
        batch_size=resolved.worker_outbox_batch_size,
        lease_seconds=resolved.worker_outbox_lease_seconds,
        max_attempts=resolved.worker_outbox_max_attempts,
        poll_interval=timedelta(seconds=resolved.provider_poll_interval_seconds),
        stale_submitting_after=timedelta(seconds=resolved.stale_submitting_seconds),
    )
    admin_sender = RateLimitedAdminSender(
        TelegramAdminDeliverySender(bot),
        rate_per_second=resolved.admin_notification_rate_per_second,
    )
    admin_worker = AdminWorker(
        database=database,
        sender=admin_sender,
        worker_id=f"{worker_id}:admin",
        batch_size=resolved.admin_worker_batch_size,
        lease_seconds=resolved.admin_worker_lease_seconds,
        max_attempts=resolved.admin_worker_max_attempts,
        notification_rate_per_second=resolved.admin_notification_rate_per_second,
    )
    refund_worker = PaymentRefundWorker(
        database=database,
        sender=TelegramStarsRefundSender(bot),
        worker_id=f"{worker_id}:stars-refund",
        batch_size=resolved.admin_worker_batch_size,
        lease_seconds=resolved.admin_worker_lease_seconds,
        max_attempts=resolved.admin_worker_max_attempts,
    )

    try:
        while True:
            processed = await worker.run_once()
            polled = await worker.poll_once()
            reconciled = await worker.reconcile_once(datetime.now(timezone.utc))
            refund_processed = await refund_worker.run_once()
            admin_processed = await admin_worker.run_once()
            if (
                processed == 0
                and polled == 0
                and reconciled == 0
                and refund_processed == 0
                and admin_processed == 0
            ):
                await asyncio.sleep(resolved.worker_loop_interval_seconds)
    finally:
        await bot.session.close()
        await downloader.aclose()
        await client.aclose()
        await database.close()


def run_sync() -> None:
    asyncio.run(run())
