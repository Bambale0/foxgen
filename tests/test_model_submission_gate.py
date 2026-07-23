from collections.abc import Mapping

import pytest

from foxgen.core.errors import ErrorCode, SubmissionError
from foxgen.domain.models import Capability, MediaKind, ModelSpec
from foxgen.providers.kie.client import TaskCreated
from foxgen.providers.kie.contracts import InputContract
from foxgen.providers.kie.service import KieModelService


class TrackingClient:
    def __init__(self) -> None:
        self.calls = 0

    async def create_task(
        self,
        *,
        model: str,
        input_data: Mapping[str, object],
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


def test_reviewed_schema_can_remain_explicitly_disabled() -> None:
    model = ModelSpec(
        slug="disabled-reviewed-model",
        provider_model="provider/disabled-reviewed-model",
        title="Disabled reviewed model",
        family="Test",
        media_kind=MediaKind.IMAGE,
        capabilities=frozenset({Capability.TEXT_TO_IMAGE}),
        verified=True,
        docs_url="https://docs.example/model",
        contract=InputContract.SEEDREAM_5_TEXT,
        enabled_for_submission=False,
    )

    assert model.provider_id_verified is True
    assert model.schema_verified is True
    assert model.enabled_for_submission is False
    assert model.production_ready is False
