import uvicorn

from foxgen.bot.app import run_sync
from foxgen.core.config import get_settings


def run_api() -> None:
    settings = get_settings()
    uvicorn.run(
        "foxgen.api.app:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
    )


def run_bot() -> None:
    run_sync()
