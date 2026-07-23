from collections.abc import Mapping
from typing import Protocol

from foxgen.providers.kie.client import TaskCreated
from foxgen.providers.kie.contracts import validate_input
from foxgen.providers.kie.registry import ModelRegistry


class TaskClient(Protocol):
    async def create_task(
        self,
        *,
        model: str,
        input_data: Mapping[str, object],
        callback_url: str | None = None,
    ) -> TaskCreated: ...


class KieModelService:
    def __init__(self, client: TaskClient, registry: ModelRegistry | None = None) -> None:
        self._client = client
        self._registry = registry or ModelRegistry()

    async def submit(
        self,
        *,
        model_slug: str,
        input_data: dict[str, object],
        callback_url: str | None = None,
    ) -> TaskCreated:
        model = self._registry.get(model_slug)
        normalized = validate_input(model.contract, input_data)
        return await self._client.create_task(
            model=model.provider_model,
            input_data=normalized,
            callback_url=callback_url,
        )
