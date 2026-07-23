from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from foxgen import __version__
from foxgen.api.security import authenticate_submission, validate_idempotency_key
from foxgen.application.submissions import SubmissionReceipt, SubmissionService
from foxgen.core.config import Settings, get_settings
from foxgen.core.errors import ErrorCode, FoxGenError, WebhookVerificationError
from foxgen.infra.database import Database
from foxgen.infra.rate_limit import RedisSubmissionRateLimiter
from foxgen.infra.redis import RedisPool
from foxgen.infra.repositories import SqlAlchemyGenerationRepository
from foxgen.providers.kie.client import KieClient
from foxgen.providers.kie.contracts import contract_schema, validate_input
from foxgen.providers.kie.registry import ModelRegistry
from foxgen.providers.kie.webhooks import verify_kie_webhook


class HealthResponse(BaseModel):
    status: str
    version: str
    dependencies: dict[str, str] | None = None


class ModelInputRequest(BaseModel):
    input: dict[str, Any]


class SubmissionServiceProtocol(Protocol):
    async def submit(
        self,
        *,
        user_id: int,
        username: str | None,
        model_slug: str,
        input_data: dict[str, object],
        idempotency_key: str,
    ) -> SubmissionReceipt: ...


class KieWebhookTaskData(BaseModel):
    model_config = ConfigDict(extra="allow")

    taskId: str | None = None
    task_id: str | None = None


class KieWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    taskId: str | None = None
    task_id: str | None = None
    data: KieWebhookTaskData | None = None

    @property
    def resolved_task_id(self) -> str:
        value = self.taskId or self.task_id
        if not value and self.data is not None:
            value = self.data.taskId or self.data.task_id
        if not value:
            raise ValueError("task id is missing")
        return value


def model_payload(item: Any, *, include_schema: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "slug": item.slug,
        "provider_model": item.provider_model,
        "title": item.title,
        "family": item.family,
        "media_kind": item.media_kind,
        "capabilities": sorted(item.capabilities),
        "verified": item.verified,
        "tier": item.tier,
        "rank": item.rank,
        "contract": item.contract,
        "defaults": dict(item.defaults),
        "recommended_for": list(item.recommended_for),
        "docs_url": item.docs_url,
        "api_family": item.api_family,
    }
    if include_schema:
        payload["input_schema"] = contract_schema(item.contract)
    return payload


def model_or_404(registry: ModelRegistry, slug: str) -> Any:
    try:
        return registry.get(slug)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def validated_input_or_422(contract: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return validate_input(contract, payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_url=False)) from exc


def _error_status(code: ErrorCode) -> int:
    return {
        ErrorCode.AUTHENTICATION: 401,
        ErrorCode.AUTHORIZATION: 403,
        ErrorCode.INSUFFICIENT_CREDITS: 402,
        ErrorCode.IDEMPOTENCY_CONFLICT: 409,
        ErrorCode.RATE_LIMITED: 429,
        ErrorCode.CONCURRENCY_LIMITED: 429,
        ErrorCode.SUBMISSION_DISABLED: 503,
        ErrorCode.PROVIDER_UNAVAILABLE: 503,
        ErrorCode.PROVIDER_PROTOCOL: 502,
        ErrorCode.PROVIDER_REJECTED: 422,
        ErrorCode.TASK_NOT_FOUND: 404,
        ErrorCode.WEBHOOK_INVALID: 401,
    }.get(code, 500)


def receipt_payload(receipt: SubmissionReceipt) -> dict[str, Any]:
    return {
        "generation_id": str(receipt.generation_id),
        "model": receipt.model_slug,
        "provider_model": receipt.provider_model,
        "status": receipt.status,
        "provider_task_id": receipt.provider_task_id,
        "replayed": receipt.replayed,
    }


def create_app(
    settings: Settings | None = None,
    *,
    manage_resources: bool = True,
    submission_service: SubmissionServiceProtocol | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    registry = ModelRegistry()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if not manage_resources:
            yield
            return

        database = Database(resolved_settings.database_url)
        redis = RedisPool(resolved_settings.redis_url)
        kie_client: KieClient | None = None
        app.state.database = database
        app.state.redis = redis

        api_key = resolved_settings.kie_api_key
        if app.state.submission_service is None and api_key is not None:
            kie_client = KieClient(
                api_key=api_key.get_secret_value(),
                base_url=str(resolved_settings.kie_base_url),
            )
            app.state.submission_service = SubmissionService(
                repository=SqlAlchemyGenerationRepository(database),
                client=kie_client,
                rate_limiter=RedisSubmissionRateLimiter(
                    redis.client,
                    user_limit_per_minute=(
                        resolved_settings.submission_user_rate_limit_per_minute
                    ),
                    global_limit_per_minute=(
                        resolved_settings.submission_global_rate_limit_per_minute
                    ),
                ),
                registry=registry,
                callback_url=resolved_settings.kie_callback_url,
                user_concurrency_limit=resolved_settings.submission_user_concurrency_limit,
                global_concurrency_limit=resolved_settings.submission_global_concurrency_limit,
            )

        try:
            yield
        finally:
            if kie_client is not None:
                await kie_client.aclose()
            await redis.close()
            await database.close()

    app = FastAPI(
        title="FoxGen API",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.registry = registry
    app.state.submission_service = submission_service

    @app.exception_handler(FoxGenError)
    async def foxgen_error_handler(request: Request, exc: FoxGenError) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=_error_status(exc.code),
            content={
                "error": exc.code,
                "message": exc.public_message,
                "retryable": exc.retryable,
            },
        )

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
        return [model_payload(item) for item in registry.list()]

    @app.get("/v1/models/{slug}")
    async def model_detail(slug: str) -> dict[str, Any]:
        return model_payload(model_or_404(registry, slug), include_schema=True)

    @app.post("/v1/models/{slug}/validate")
    async def validate_model_input(slug: str, request: ModelInputRequest) -> dict[str, Any]:
        item = model_or_404(registry, slug)
        normalized = validated_input_or_422(item.contract, request.input)
        return {"model": item.provider_model, "input": normalized}

    @app.post("/v1/models/{slug}/tasks", status_code=202)
    async def create_model_task(
        slug: str,
        body: ModelInputRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
        user_id_header: str | None = Header(default=None, alias="X-FoxGen-User-Id"),
        username: str | None = Header(default=None, alias="X-FoxGen-Username"),
    ) -> dict[str, Any]:
        principal = authenticate_submission(
            settings=resolved_settings,
            authorization=authorization,
            user_id_header=user_id_header,
        )
        idempotency_key = validate_idempotency_key(idempotency_key_header)
        item = model_or_404(registry, slug)
        validated_input_or_422(item.contract, body.input)

        service: SubmissionServiceProtocol | None = request.app.state.submission_service
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Task submission service is not configured",
            )
        receipt = await service.submit(
            user_id=principal.user_id,
            username=username,
            model_slug=slug,
            input_data=body.input,
            idempotency_key=idempotency_key,
        )
        return receipt_payload(receipt)

    @app.post("/webhooks/kie")
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
            task_id = payload.resolved_task_id
            verify_kie_webhook(
                task_id=task_id,
                timestamp=x_webhook_timestamp,
                signature=x_webhook_signature,
                secret=secret_value.get_secret_value(),
                max_age_seconds=resolved_settings.webhook_max_age_seconds,
            )
        except (WebhookVerificationError, ValueError) as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

        # Durable, idempotent result processing is implemented in the next lifecycle PR.
        return {"status": "accepted", "task_id": task_id}

    return app


app = create_app()
