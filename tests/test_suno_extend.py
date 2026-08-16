from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
import pytest

from foxgen.application.submissions import SubmissionReceipt
from foxgen.application.suno_extend import SunoExtendService, SunoTrackRecord
from foxgen.core.errors import ErrorCode, ProviderError, SubmissionError
from foxgen.domain.models import GenerationStatus
from foxgen.providers.kie.client import KieClient
from foxgen.providers.kie.contracts import InputContract, validate_input
from foxgen.providers.kie.router import RoutedKieClient
from foxgen.providers.kie.suno import SunoExtendClient


SOURCE_GENERATION_ID = UUID("11111111-2222-3333-4444-555555555555")


class FakeSourceRepository:
    def __init__(self, source: SunoTrackRecord | None) -> None:
        self.source = source
        self.lookups: list[tuple[int, UUID, str]] = []

    async def list_sources(self, *, user_id: int, limit: int = 40) -> tuple[SunoTrackRecord, ...]:
        del user_id, limit
        return (self.source,) if self.source is not None else ()

    async def get_source(
        self,
        *,
        user_id: int,
        generation_id: UUID,
        audio_id: str,
    ) -> SunoTrackRecord | None:
        self.lookups.append((user_id, generation_id, audio_id))
        if (
            self.source is not None
            and generation_id == self.source.generation_id
            and audio_id == self.source.audio_id
        ):
            return self.source
        return None


class FakeSigner:
    async def presigned_url(self, storage_key: str) -> str:
        return f"https://storage.example.test/{storage_key}"


class FakeSubmission:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def submit(
        self,
        *,
        user_id: int,
        username: str | None,
        model_slug: str,
        input_data: dict[str, object],
        idempotency_key: str,
        source_publication_id: UUID | None = None,
    ) -> SubmissionReceipt:
        del source_publication_id
        self.calls.append(
            {
                "user_id": user_id,
                "username": username,
                "model_slug": model_slug,
                "input_data": dict(input_data),
                "idempotency_key": idempotency_key,
            }
        )
        return SubmissionReceipt(
            generation_id=uuid4(),
            model_slug=model_slug,
            provider_model="V5",
            status=GenerationStatus.QUEUED,
            provider_task_id=None,
            replayed=False,
        )


def source(*, duration: float | None = 120.0) -> SunoTrackRecord:
    return SunoTrackRecord(
        generation_id=SOURCE_GENERATION_ID,
        model_slug="suno-v5",
        audio_id="source-audio-id",
        title="Last Train",
        duration_seconds=duration,
        storage_key="generations/source/track.mp3",
        created_at=datetime.now(timezone.utc),
    )


def test_suno_extend_contract_supports_inherited_and_custom_v5_modes() -> None:
    inherited = validate_input(
        InputContract.SUNO_V5_EXTEND,
        {
            "source_generation_id": str(SOURCE_GENERATION_ID),
            "audio_id": "source-audio-id",
        },
    )
    custom = validate_input(
        InputContract.SUNO_V5_EXTEND,
        {
            "source_generation_id": str(SOURCE_GENERATION_ID),
            "audio_id": "source-audio-id",
            "default_param_flag": True,
            "prompt": "[Verse] Keep the city lights burning",
            "style": "indie pop, warm female vocal",
            "title": "Last Train Extended",
            "continue_at": 92.5,
            "negative_tags": "metal",
            "vocal_gender": "f",
            "style_weight": 0.8,
        },
    )

    assert inherited["default_param_flag"] is False
    assert custom["continue_at"] == 92.5
    assert custom["title"] == "Last Train Extended"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "source_generation_id": str(SOURCE_GENERATION_ID),
            "audio_id": "source-audio-id",
            "prompt": "custom field without custom flag",
        },
        {
            "source_generation_id": str(SOURCE_GENERATION_ID),
            "audio_id": "source-audio-id",
            "default_param_flag": True,
            "style": "pop",
            "title": "Missing prompt",
            "continue_at": 50,
        },
        {
            "source_generation_id": str(SOURCE_GENERATION_ID),
            "audio_id": "source-audio-id",
            "default_param_flag": True,
            "prompt": "lyrics",
            "title": "Missing style",
            "continue_at": 50,
        },
        {
            "source_generation_id": str(SOURCE_GENERATION_ID),
            "audio_id": "source-audio-id",
            "default_param_flag": True,
            "prompt": "lyrics",
            "style": "pop",
            "title": "Missing continue",
        },
    ],
)
def test_suno_extend_contract_rejects_invalid_mode(payload: dict[str, object]) -> None:
    with pytest.raises(Exception):
        validate_input(InputContract.SUNO_V5_EXTEND, payload)


@pytest.mark.asyncio
async def test_foreign_or_unknown_source_fails_before_paid_submission() -> None:
    sources = FakeSourceRepository(None)
    submission = FakeSubmission()
    service = SunoExtendService(
        sources=sources,
        submission=submission,  # type: ignore[arg-type]
        media_signer=FakeSigner(),
    )

    with pytest.raises(SubmissionError) as error:
        await service.extend(
            user_id=77,
            username="owner",
            source_generation_id=SOURCE_GENERATION_ID,
            audio_id="foreign-id",
            input_data={"default_param_flag": False},
            idempotency_key="extend-owner-check",
        )

    assert error.value.code == ErrorCode.TASK_NOT_FOUND
    assert submission.calls == []


@pytest.mark.asyncio
async def test_custom_continue_point_must_be_inside_owned_track() -> None:
    sources = FakeSourceRepository(source(duration=120.0))
    submission = FakeSubmission()
    service = SunoExtendService(
        sources=sources,
        submission=submission,  # type: ignore[arg-type]
        media_signer=FakeSigner(),
    )

    with pytest.raises(SubmissionError) as error:
        await service.extend(
            user_id=77,
            username="owner",
            source_generation_id=SOURCE_GENERATION_ID,
            audio_id="source-audio-id",
            input_data={
                "default_param_flag": True,
                "prompt": "continue",
                "style": "pop",
                "title": "Extended",
                "continue_at": 120.0,
            },
            idempotency_key="extend-duration-check",
        )

    assert error.value.code == ErrorCode.VALIDATION
    assert submission.calls == []


@pytest.mark.asyncio
async def test_owned_source_is_injected_server_side_before_shared_submission() -> None:
    sources = FakeSourceRepository(source())
    submission = FakeSubmission()
    service = SunoExtendService(
        sources=sources,
        submission=submission,  # type: ignore[arg-type]
        media_signer=FakeSigner(),
    )

    await service.extend(
        user_id=77,
        username="owner",
        source_generation_id=SOURCE_GENERATION_ID,
        audio_id="source-audio-id",
        input_data={"default_param_flag": False},
        idempotency_key="extend-owned",
    )

    assert submission.calls == [
        {
            "user_id": 77,
            "username": "owner",
            "model_slug": "suno-v5-extend",
            "input_data": {
                "default_param_flag": False,
                "source_generation_id": SOURCE_GENERATION_ID,
                "audio_id": "source-audio-id",
            },
            "idempotency_key": "extend-owned",
        }
    ]


@pytest.mark.asyncio
async def test_suno_extend_provider_body_strips_foxgen_ownership_identity() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/api/v1/generate/extend"
        body = request.read().decode()
        assert "source_generation_id" not in body
        assert "sourceGenerationId" not in body
        assert '"audioId":"source-audio-id"' in body.replace(" ", "")
        assert '"defaultParamFlag":true' in body.replace(" ", "")
        assert '"continueAt":92.5' in body.replace(" ", "")
        return httpx.Response(200, json={"code": 200, "data": {"taskId": "extend-task-1"}})

    http = httpx.AsyncClient(
        base_url="https://api.kie.ai",
        transport=httpx.MockTransport(handler),
    )
    transport = KieClient(api_key="test-key", client=http)
    client = SunoExtendClient(transport)
    try:
        created = await client.create_task(
            model="V5",
            input_data={
                "source_generation_id": SOURCE_GENERATION_ID,
                "audio_id": "source-audio-id",
                "default_param_flag": True,
                "prompt": "continue",
                "style": "pop",
                "title": "Extended",
                "continue_at": 92.5,
            },
        )
    finally:
        await http.aclose()

    assert created.task_id == "extend-task-1"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_provider_router_exposes_extend_family() -> None:
    http = httpx.AsyncClient(
        base_url="https://api.kie.ai",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"code": 200, "data": {}})
        ),
    )
    market = KieClient(api_key="test-key", client=http)
    router = RoutedKieClient(market)
    try:
        assert isinstance(router.for_family("suno_extend"), SunoExtendClient)
        with pytest.raises(ProviderError):
            router.for_family("foreign-family")
    finally:
        await http.aclose()
