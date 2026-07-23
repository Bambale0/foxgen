from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from foxgen import __version__
from foxgen.core.config import Settings, get_settings
from foxgen.core.errors import WebhookVerificationError
from foxgen.infra.database import Database
from foxgen.infra.redis import RedisPool
from foxgen.providers.kie.catalog import ModelRegistry
from foxgen.providers.kie.webhooks import verify_kie_webhook


class HealthResponse(BaseModel):
    status: str
    version: str
    dependencies: dict[str, str] | None = None


class KieWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    taskId: str | None = None
    task_id: str | None = None

    @property
    def resolved_task_id(self) -> str:
        value = self.taskId or self.task_id
        if not value:
            raise ValueError("task id is missing")
        return value


def create_app(settings: Settings | None = None, *, manage_resources: bool = True) -> FastAPI:
    resolved_settings = settings or get_settings()
    registry = ModelRegistry()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if not manage_resources:
            yield
            return
        app.state.database = Database(resolved_settings.database_url)
        app.state.redis = RedisPool(resolved_settings.redis_url)
        try:
            yield
        finally:
            await app.state.redis.close()
            await app.state.database.close()

    app = FastAPI(
        title="FoxGen API",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.registry = registry

    @app.get("/health/live", response_model=HealthResponse)
    async def live() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    @app.get("/health/ready", response_model=HealthResponse)
    async def ready(request: Request) -> HealthResponse:
        if not manage_resources:
            return HealthResponse(
                status="ok",
                version=__version__,
                dependencies={"postgres": "skipped", "redis": "skipped"},
            )
        dependencies: dict[str, str] = {}
        try:
            await request.app.state.database.ping()
            dependencies["postgres"] = "ok"
            await request.app.state.redis.ping()
            dependencies["redis"] = "ok"
        except Exception as exc:
            dependencies.setdefault("postgres", "unknown")
            dependencies.setdefault("redis", "unknown")
            raise HTTPException(status_code=503, detail=dependencies) from exc
        return HealthResponse(status="ok", version=__version__, dependencies=dependencies)

    @app.get("/v1/models")
    async def models() -> list[dict[str, Any]]:
        return [
            {
                "slug": item.slug,
                "title": item.title,
                "family": item.family,
                "media_kind": item.media_kind,
                "capabilities": sorted(item.capabilities),
                "verified": item.verified,
                "defaults": dict(item.defaults),
            }
            for item in registry.list()
        ]

    @app.post("/webhooks/kie", status_code=202)
    async def kie_webhook(
        payload: KieWebhookPayload,
        x_webhook_timestamp: str | None = Header(default=None),
        x_webhook_signature: str | None = Header(default=None),
    ) -> dict[str, str]:
        secret_value = resolved_settings.kie_webhook_hmac_key
        if secret_value is None:
            raise HTTPException(
                status_code=503,
                detail="KIE webhook verification is not configured",
            )
        if not x_webhook_timestamp or not x_webhook_signature:
            raise HTTPException(status_code=401, detail="Missing KIE webhook signature headers")
        try:
            verify_kie_webhook(
                task_id=payload.resolved_task_id,
                timestamp=x_webhook_timestamp,
                signature=x_webhook_signature,
                secret=secret_value.get_secret_value(),
                max_age_seconds=resolved_settings.webhook_max_age_seconds,
            )
        except (WebhookVerificationError, ValueError) as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

        # Durable, idempotent processing will be added by EPIC 04.
        return {"status": "accepted", "task_id": payload.resolved_task_id}

    return app


app = create_app()
