from collections.abc import Mapping

import pytest

from foxgen.providers.kie.client import TaskCreated
from foxgen.providers.kie.service import KieModelService


class FakeTaskClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object], str | None]] = []

    async def create_task(
        self,
        *,
        model: str,
        input_data: Mapping[str, object],
        callback_url: str | None = None,
    ) -> TaskCreated:
        self.calls.append((model, dict(input_data), callback_url))
        return TaskCreated(task_id="task-1")


@pytest.mark.asyncio
async def test_service_submits_exact_seedance_provider_model() -> None:
    client = FakeTaskClient()
    service = KieModelService(client)

    result = await service.submit(
        model_slug="seedance-2",
        input_data={"prompt": "A cinematic fox running through snow"},
        callback_url="https://foxgen.example.com/webhooks/kie",
    )

    assert result.task_id == "task-1"
    assert client.calls[0][0] == "bytedance/seedance-2"
    assert client.calls[0][1]["resolution"] == "720p"
    assert client.calls[0][2] == "https://foxgen.example.com/webhooks/kie"


@pytest.mark.asyncio
async def test_service_submits_exact_seedream_provider_model() -> None:
    client = FakeTaskClient()
    service = KieModelService(client)

    await service.submit(
        model_slug="seedream-5-pro",
        input_data={"prompt": "Premium product shot of a watch"},
    )

    assert client.calls[0][0] == "seedream/5-pro-text-to-image"
    assert client.calls[0][1]["output_format"] == "png"
