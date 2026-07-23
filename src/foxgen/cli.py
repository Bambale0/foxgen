import uvicorn

from foxgen.bot.app import run_sync as run_bot_sync
from foxgen.core.config import get_settings
from foxgen.worker import run_sync as run_worker_sync


def run_api() -> None:
    settings = get_settings()
    uvicorn.run(
        "foxgen.api.app:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
    )


def run_bot() -> None:
    run_bot_sync()


def run_worker() -> None:
    run_worker_sync()
