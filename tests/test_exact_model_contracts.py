from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from foxgen.api.app import create_app
from foxgen.application.submissions import GenerationSnapshot, SubmissionService
from foxgen.core.config import Settings
from foxgen.core.errors import ErrorCode, SubmissionError
from foxgen.domain.models import GenerationStatus, MediaKind, ModelSpec
from foxgen.providers.kie.contracts import InputContract, validate_input
from foxgen.providers.kie.registry import ModelRegistry


class RejectTrackingRepository:
    def __init__(self) -> None:
        self.find_calls = 0
        self.admit_calls = 0

    async def find_by_idempotency(
        self,
        *,
        user_id: int,
        idempotency_key: str,
    ) -> GenerationSnapshot | None:
        del user_id, idempotency_key
        self.find_calls += 1
        return None

    async def admit(
        self,
        *,
        user_id: int,
        username: str | None,
        idempotency_key: str,
        request_hash: str,
        model_slug: str,
        media_kind: MediaKind,
        prompt: str | None,
        input_payload: dict[str, object],
        user_concurrency_limit: int,
        global_concurrency_limit: int,
    ) -> tuple[GenerationSnapshot, bool]:
        del (
            username,
            media_kind,
            prompt,
            input_payload,
            user_concurrency_limit,
            global_concurrency_limit,
        )
        self.admit_calls += 1
        return (
            GenerationSnapshot(
                id=UUID("11111111-1111-1111-1111-111111111111"),
                user_id=user_id,
                model_slug=model_slug,
                status=GenerationStatus.QUEUED,
                request_hash=request_hash,
            ),
            True,
        )


class RejectTrackingLimiter:
    def __init__(self) -> None:
        self.calls = 0

    async def check(self, user_id: int) -> None:
        del user_id
        self.calls += 1


def test_registry_separates_catalog_models_from_submission_models() -> None:
    registry = ModelRegistry()
    enabled = registry.submission_models()

    assert {item.slug for item in enabled} == {
        "seedream-5-pro",
        "seedream-5-pro-edit",
        "nano-banana-2",
        "nano-banana-pro",
        "seedance-2",
        "seedance-2-mini",
    }
    assert all(item.provider_id_verified for item in enabled)
    assert all(item.schema_verified for item in enabled)
    assert all(item.enabled_for_submission for item in enabled)
    assert all(item.contract != InputContract.PASSTHROUGH for item in enabled)
    assert all(item.tested_live is False for item in enabled)

    catalog_only = registry.get("gpt-image-2")
    assert catalog_only.provider_id_verified is True
    assert catalog_only.schema_verified is False
    assert catalog_only.enabled_for_submission is False
    assert catalog_only.production_ready is False


def test_registry_rejects_passthrough_model_marked_for_submission() -> None:
    unsafe = ModelSpec(
        slug="unsafe",
        provider_model="unsafe/model",
        title="Unsafe",
        family="Unsafe",
        media_kind=MediaKind.IMAGE,
        capabilities=frozenset(),
        verified=True,
        contract=InputContract.PASSTHROUGH,
        provider_id_verified=True,
        schema_verified=True,
        enabled_for_submission=True,
    )

    with pytest.raises(ValueError, match="passthrough"):
        ModelRegistry((unsafe,))


@pytest.mark.asyncio
async def test_catalog_only_submission_is_rejected_before_persistence_and_rate_limit() -> None:
    repository = RejectTrackingRepository()
    limiter = RejectTrackingLimiter()
    service = SubmissionService(repository=repository, rate_limiter=limiter)

    with pytest.raises(SubmissionError) as error:
        await service.submit(
            user_id=42,
            username="fox",
            model_slug="gpt-image-2",
            input_data={"prompt": "A fox"},
            idempotency_key="request-0001",
        )

    assert error.value.code == ErrorCode.AUTHORIZATION
    assert repository.find_calls == 0
    assert repository.admit_calls == 0
    assert limiter.calls == 0


def test_model_api_exposes_independent_readiness_statuses() -> None:
    app = create_app(Settings(env="test"), manage_resources=False)

    with TestClient(app) as client:
        enabled = client.get("/v1/models/seedream-5-pro")
        catalog_only = client.get("/v1/models/gpt-image-2")

    assert enabled.status_code == 200
    assert enabled.json()["provider_id_verified"] is True
    assert enabled.json()["schema_verified"] is True
    assert enabled.json()["enabled_for_submission"] is True
    assert enabled.json()["production_ready"] is True
    assert enabled.json()["tested_live"] is False
    assert enabled.json()["contract_reviewed_at"] == "2026-07-23"

    assert catalog_only.status_code == 200
    assert catalog_only.json()["provider_id_verified"] is True
    assert catalog_only.json()["schema_verified"] is False
    assert catalog_only.json()["enabled_for_submission"] is False
    assert catalog_only.json()["production_ready"] is False
    assert catalog_only.json()["tested_live"] is False


@pytest.mark.parametrize(
    "payload",
    [
        {"prompt": "Fox", "aspect_ratio": "7:5"},
        {"prompt": "Fox", "quality": "ultra"},
        {"prompt": "Fox", "output_format": "jpeg"},
        {"prompt": "Fox", "unexpected": True},
    ],
)
def test_seedream_5_rejects_unsupported_values(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        validate_input(InputContract.SEEDREAM_5_TEXT, payload)


def test_seedream_5_edit_requires_and_caps_images() -> None:
    with pytest.raises(ValidationError):
        validate_input(InputContract.SEEDREAM_5_IMAGE, {"prompt": "Edit"})

    with pytest.raises(ValidationError):
        validate_input(
            InputContract.SEEDREAM_5_IMAGE,
            {
                "prompt": "Edit",
                "image_urls": [f"https://cdn.example/{index}.png" for index in range(11)],
            },
        )


def test_nano_banana_rejects_invalid_resolution_format_and_image_count() -> None:
    with pytest.raises(ValidationError):
        validate_input(
            InputContract.NANO_BANANA,
            {"prompt": "Fox", "resolution": "8K"},
        )
    with pytest.raises(ValidationError):
        validate_input(
            InputContract.NANO_BANANA,
            {"prompt": "Fox", "output_format": "webp"},
        )
    with pytest.raises(ValidationError):
        validate_input(
            InputContract.NANO_BANANA,
            {
                "prompt": "Edit",
                "image_input": [f"https://cdn.example/{index}.png" for index in range(15)],
            },
        )


def test_seedance_rejects_invalid_modes_and_boundaries() -> None:
    with pytest.raises(ValidationError, match="requires first_frame_url"):
        validate_input(
            InputContract.SEEDANCE_2,
            {"prompt": "Fox", "last_frame_url": "https://cdn.example/last.png"},
        )

    with pytest.raises(ValidationError, match="mutually exclusive"):
        validate_input(
            InputContract.SEEDANCE_2,
            {
                "prompt": "Fox",
                "first_frame_url": "https://cdn.example/first.png",
                "reference_image_urls": ["https://cdn.example/reference.png"],
            },
        )

    with pytest.raises(ValidationError, match="at most six"):
        validate_input(
            InputContract.SEEDANCE_2,
            {
                "prompt": "Fox",
                "reference_image_urls": [
                    f"https://cdn.example/image-{index}.png" for index in range(5)
                ],
                "reference_audio_urls": [
                    "https://cdn.example/audio-1.mp3",
                    "https://cdn.example/audio-2.mp3",
                ],
            },
        )

    with pytest.raises(ValidationError):
        validate_input(InputContract.SEEDANCE_2, {"prompt": "Fox", "duration": 7})

    with pytest.raises(ValidationError):
        validate_input(
            InputContract.SEEDANCE_2,
            {"prompt": "Fox", "resolution": "1080p"},
        )


def test_priority_contract_examples_normalize_to_provider_payloads() -> None:
    seedream = validate_input(
        InputContract.SEEDREAM_5_TEXT,
        {
            "prompt": "Premium product photo of a black watch",
            "aspect_ratio": "1:1",
            "quality": "high",
            "output_format": "png",
            "nsfw_checker": False,
        },
    )
    nano = validate_input(
        InputContract.NANO_BANANA,
        {
            "prompt": "Replace the background with a winter forest",
            "image_input": ["https://cdn.example/source.png"],
            "aspect_ratio": "16:9",
            "resolution": "2K",
            "output_format": "jpg",
        },
    )
    seedance = validate_input(
        InputContract.SEEDANCE_2,
        {
            "prompt": "A cinematic fox running through snow",
            "generate_audio": True,
            "resolution": "720p",
            "aspect_ratio": "16:9",
            "duration": 15,
        },
    )

    assert seedream["quality"] == "high"
    assert nano["resolution"] == "2K"
    assert seedance["duration"] == 15
