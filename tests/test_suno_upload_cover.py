import json
from dataclasses import dataclass
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from foxgen.application.submissions import SubmissionReceipt
from foxgen.application.suno_upload_cover import (
    SUNO_UPLOAD_COVER_MODEL_SLUG,
    SunoUploadCoverService,
)
from foxgen.core.errors import ErrorCode, ProviderError, SubmissionError
from foxgen.domain.models import GenerationStatus
from foxgen.providers.kie.client import KieClient
from foxgen.providers.kie.contracts import InputContract, validate_input
from foxgen.providers.kie.suno import SunoUploadCoverClient


@dataclass(frozen=True)
class FakeMedia:
    content_type: str = "audio/mpeg"
    size_bytes: int = 1234


class FakeInputMedia:
    def __init__(self, *, media: FakeMedia | None = None, missing: bool = False) -> None:
        self.media = media or FakeMedia()
        self.missing = missing
        self.described: list[str] = []
        self.presigned: list[str] = []

    async def describe(self, storage_key: str) -> FakeMedia:
        self.described.append(storage_key)
        if self.missing:
            raise SubmissionError(ErrorCode.TASK_NOT_FOUND, "missing")
        return self.media

    async def presigned_url(self, storage_key: str) -> str:
        self.presigned.append(storage_key)
        return f"https://inputs.example.test/{storage_key}?sig=fresh"


class FakeSubmission:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def submit(self, **kwargs: object) -> SubmissionReceipt:
        self.calls.append(dict(kwargs))
        return SubmissionReceipt(
            generation_id=uuid4(),
            model_slug=SUNO_UPLOAD_COVER_MODEL_SLUG,
            provider_model="V5",
            status=GenerationStatus.QUEUED,
            provider_task_id=None,
            replayed=False,
        )


def simple_payload(storage_key: str = "inputs/42/source.mp3") -> dict[str, object]:
    return {
        "input_storage_key": storage_key,
        "custom_mode": False,
        "instrumental": False,
        "prompt": "Turn this melody into mellow dream pop",
    }


def custom_vocal_payload(storage_key: str = "inputs/42/source.mp3") -> dict[str, object]:
    return {
        "input_storage_key": storage_key,
        "custom_mode": True,
        "instrumental": False,
        "prompt": "[Verse] keep the melody but sing these new words",
        "style": "dream pop, warm female vocal",
        "title": "Night Cover",
        "negative_tags": "metal",
        "vocal_gender": "f",
        "style_weight": 0.7,
        "weirdness_constraint": 0.2,
        "audio_weight": 0.8,
    }


def test_upload_cover_contract_accepts_simple_and_custom_v5_modes() -> None:
    simple = validate_input(InputContract.SUNO_V5_UPLOAD_COVER, simple_payload())
    custom = validate_input(InputContract.SUNO_V5_UPLOAD_COVER, custom_vocal_payload())
    instrumental = validate_input(
        InputContract.SUNO_V5_UPLOAD_COVER,
        {
            "input_storage_key": "inputs/42/source.wav",
            "custom_mode": True,
            "instrumental": True,
            "style": "cinematic orchestral",
            "title": "Orchestral Cover",
        },
    )

    assert simple["prompt"] == "Turn this melody into mellow dream pop"
    assert custom["title"] == "Night Cover"
    assert instrumental["prompt"] == ""


@pytest.mark.parametrize(
    "payload",
    [
        {"input_storage_key": "inputs/42/source.mp3", "custom_mode": False},
        {
            "input_storage_key": "inputs/42/source.mp3",
            "custom_mode": False,
            "prompt": "ok",
            "style": "must not be accepted",
        },
        {
            "input_storage_key": "inputs/42/source.mp3",
            "custom_mode": True,
            "instrumental": False,
            "style": "pop",
            "title": "Missing lyrics",
        },
        {
            "input_storage_key": "https://evil.example/source.mp3",
            "custom_mode": False,
            "prompt": "cover",
        },
    ],
)
def test_upload_cover_contract_rejects_unsafe_or_incomplete_payloads(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        validate_input(InputContract.SUNO_V5_UPLOAD_COVER, payload)


@pytest.mark.asyncio
async def test_owner_service_rejects_foreign_storage_before_paid_submission() -> None:
    storage = FakeInputMedia()
    submission = FakeSubmission()
    service = SunoUploadCoverService(
        input_media=storage,  # type: ignore[arg-type]
        submission=submission,
        max_bytes=10_000,
    )

    with pytest.raises(SubmissionError) as error:
        await service.submit(
            user_id=42,
            username="owner",
            input_data=simple_payload("inputs/99/source.mp3"),
            idempotency_key="cover-foreign",
        )

    assert error.value.code == ErrorCode.TASK_NOT_FOUND
    assert storage.described == []
    assert submission.calls == []


@pytest.mark.asyncio
async def test_owner_service_rejects_non_audio_before_paid_submission() -> None:
    storage = FakeInputMedia(media=FakeMedia(content_type="image/png"))
    submission = FakeSubmission()
    service = SunoUploadCoverService(
        input_media=storage,  # type: ignore[arg-type]
        submission=submission,
        max_bytes=10_000,
    )

    with pytest.raises(SubmissionError) as error:
        await service.submit(
            user_id=42,
            username="owner",
            input_data=simple_payload(),
            idempotency_key="cover-image",
        )

    assert error.value.code == ErrorCode.VALIDATION
    assert submission.calls == []


@pytest.mark.asyncio
async def test_owner_service_submits_only_normalized_owner_audio() -> None:
    storage = FakeInputMedia()
    submission = FakeSubmission()
    service = SunoUploadCoverService(
        input_media=storage,  # type: ignore[arg-type]
        submission=submission,
        max_bytes=10_000,
    )

    receipt = await service.submit(
        user_id=42,
        username="owner",
        input_data=custom_vocal_payload(),
        idempotency_key="cover-owner-001",
    )

    assert receipt.model_slug == SUNO_UPLOAD_COVER_MODEL_SLUG
    assert storage.described == ["inputs/42/source.mp3"]
    assert len(submission.calls) == 1
    assert submission.calls[0]["user_id"] == 42
    assert submission.calls[0]["model_slug"] == SUNO_UPLOAD_COVER_MODEL_SLUG
    assert submission.calls[0]["input_data"] == validate_input(
        InputContract.SUNO_V5_UPLOAD_COVER,
        custom_vocal_payload(),
    )


@pytest.mark.asyncio
async def test_provider_resolves_fresh_upload_url_and_never_sends_storage_key() -> None:
    requests: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/generate/upload-cover"
        body = json.loads(request.content.decode())
        requests.append(body)
        return httpx.Response(200, json={"code": 200, "data": {"taskId": "cover-task"}})

    http = httpx.AsyncClient(
        base_url="https://api.kie.ai",
        transport=httpx.MockTransport(handler),
    )
    storage = FakeInputMedia()
    client = SunoUploadCoverClient(
        KieClient(api_key="test-key", client=http),
        storage,  # type: ignore[arg-type]
    )
    try:
        created = await client.create_task(
            model="V5",
            input_data=custom_vocal_payload(),
        )
    finally:
        await http.aclose()

    assert created.task_id == "cover-task"
    assert storage.described == ["inputs/42/source.mp3"]
    assert storage.presigned == ["inputs/42/source.mp3"]
    assert len(requests) == 1
    body = requests[0]
    assert body["uploadUrl"] == "https://inputs.example.test/inputs/42/source.mp3?sig=fresh"
    assert body["customMode"] is True
    assert body["instrumental"] is False
    assert body["model"] == "V5"
    assert body["title"] == "Night Cover"
    assert "input_storage_key" not in body


@pytest.mark.asyncio
async def test_provider_missing_input_fails_before_external_post() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    http = httpx.AsyncClient(
        base_url="https://api.kie.ai",
        transport=httpx.MockTransport(handler),
    )
    client = SunoUploadCoverClient(
        KieClient(api_key="test-key", client=http),
        FakeInputMedia(missing=True),  # type: ignore[arg-type]
    )
    try:
        with pytest.raises(ProviderError) as error:
            await client.create_task(model="V5", input_data=simple_payload())
    finally:
        await http.aclose()

    assert error.value.retryable is False
    assert calls == 0
