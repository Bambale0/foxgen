import pytest

from foxgen.core.errors import ErrorCode, SubmissionError
from foxgen.providers.kie.client import TaskCreated
from foxgen.providers.kie.service import KieModelService


class TrackingClient:
    def __init__(self) -> None:
        self.calls = 0

    async def create_task(
        self,
        *,
        model: str,
        input_data: dict[str, object],
        callback_url: str | None = None,
    ) -> TaskCreated:
        del model, input_data, callback_url
        self.calls += 1
        return TaskCreated(task_id="provider-task-1")


@pytest.mark.asyncio
async def test_direct_kie_service_cannot_submit_catalog_only_model() -> None:
    client = TrackingClient()
    service = KieModelService(client)

    with pytest.raises(SubmissionError) as error:
        await service.submit(
            model_slug="gpt-image-2",
            input_data={"prompt": "A fox"},
        )

    assert error.value.code == ErrorCode.AUTHORIZATION
    assert client.calls == 0
