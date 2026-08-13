from __future__ import annotations

from foxgen.admin.errors import AdminNotFoundError, AdminValidationError
from foxgen.admin.policy import GENERATIONS_READ, AdminContext
from foxgen.admin.repository import AdminCommandExecutor
from foxgen.providers.kie.contracts import validate_input
from foxgen.providers.kie.registry import ModelRegistry


class AdminPreviewService:
    def __init__(
        self,
        executor: AdminCommandExecutor,
        *,
        registry: ModelRegistry | None = None,
    ) -> None:
        self._executor = executor
        self._registry = registry or ModelRegistry()

    async def generation_preview(
        self,
        *,
        context: AdminContext,
        model_slug: str,
        input_payload: dict[str, object],
    ) -> dict[str, object]:
        context.require(GENERATIONS_READ)
        try:
            model = self._registry.get(model_slug)
        except KeyError as exc:
            raise AdminNotFoundError("model", model_slug) from exc
        try:
            normalized = validate_input(model.contract, input_payload)
        except Exception as exc:
            raise AdminValidationError(
                "Generation preview input is invalid",
                details={"model_slug": model_slug, "validation_error": str(exc)},
            ) from exc
        result: dict[str, object] = {
            "model_slug": model.slug,
            "provider_model": model.provider_model,
            "media_kind": str(model.media_kind),
            "production_ready": model.production_ready,
            "normalized_input": normalized,
            "would_submit": False,
            "would_reserve_balance": False,
        }
        await self._executor.audit_read(
            context=context,
            action="generation.preview",
            target_id=model_slug,
            payload={"model_slug": model_slug},
        )
        return result
