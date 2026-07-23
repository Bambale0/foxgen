import asyncio
import os
import socket
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from foxgen.application.delivery import MediaPipeline
from foxgen.application.lifecycle import GenerationWorker
from foxgen.core.config import Settings, get_settings
from foxgen.infra.database import Database
from foxgen.infra.lifecycle_repository import SqlAlchemyLifecycleRepository
from foxgen.infra.media import SecureMediaDownloader, S3MediaStorage, TelegramMediaSender
from foxgen.providers.kie.client import KieClient
from foxgen.providers.kie.registry import ModelRegistry


async def run(settings: Settings | None = None) -> None:
    resolved = settings or get_settings()
    api_key = resolved.kie_api_key
    telegram_token = resolved.telegram_bot_token
    if api_key is None:
        raise RuntimeError("FOXGEN_KIE_API_KEY is required for the generation worker")
    if telegram_token is None:
        raise RuntimeError("FOXGEN_TELEGRAM_BOT_TOKEN is required for result delivery")

    database = Database(resolved.database_url)
    repository = SqlAlchemyLifecycleRepository(database)
    client = KieClient(
        api_key=api_key.get_secret_value(),
        base_url=str(resolved.kie_base_url),
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

    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    worker = GenerationWorker(
        repository=repository,
        client=client,
        registry=ModelRegistry(),
        callback_url=resolved.kie_callback_url,
        media_pipeline=media_pipeline,
        worker_id=worker_id,
        batch_size=resolved.worker_outbox_batch_size,
        lease_seconds=resolved.worker_outbox_lease_seconds,
        max_attempts=resolved.worker_outbox_max_attempts,
        poll_interval=timedelta(seconds=resolved.provider_poll_interval_seconds),
        stale_submitting_after=timedelta(seconds=resolved.stale_submitting_seconds),
    )

    try:
        while True:
            processed = await worker.run_once()
            polled = await worker.poll_once()
            reconciled = await worker.reconcile_once(datetime.now(timezone.utc))
            if processed == 0 and polled == 0 and reconciled == 0:
                await asyncio.sleep(resolved.worker_loop_interval_seconds)
    finally:
        await bot.session.close()
        await downloader.aclose()
        await client.aclose()
        await database.close()


def run_sync() -> None:
    asyncio.run(run())
