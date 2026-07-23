import asyncio
import os
import socket
from datetime import timedelta

from foxgen.application.lifecycle import GenerationWorker
from foxgen.core.config import Settings, get_settings
from foxgen.infra.database import Database
from foxgen.infra.lifecycle_repository import SqlAlchemyLifecycleRepository
from foxgen.providers.kie.client import KieClient
from foxgen.providers.kie.registry import ModelRegistry


async def run(settings: Settings | None = None) -> None:
    resolved = settings or get_settings()
    api_key = resolved.kie_api_key
    if api_key is None:
        raise RuntimeError("FOXGEN_KIE_API_KEY is required for the generation worker")

    database = Database(resolved.database_url)
    client = KieClient(
        api_key=api_key.get_secret_value(),
        base_url=str(resolved.kie_base_url),
    )
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    worker = GenerationWorker(
        repository=SqlAlchemyLifecycleRepository(database),
        client=client,
        registry=ModelRegistry(),
        callback_url=resolved.kie_callback_url,
        worker_id=worker_id,
        batch_size=resolved.worker_outbox_batch_size,
        lease_seconds=resolved.worker_outbox_lease_seconds,
        max_attempts=resolved.worker_outbox_max_attempts,
        poll_interval=timedelta(seconds=resolved.provider_poll_interval_seconds),
    )

    try:
        while True:
            processed = await worker.run_once()
            polled = await worker.poll_once()
            if processed == 0 and polled == 0:
                await asyncio.sleep(resolved.worker_loop_interval_seconds)
    finally:
        await client.aclose()
        await database.close()


def run_sync() -> None:
    asyncio.run(run())
