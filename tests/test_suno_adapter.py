import json

import httpx
import pytest
from pydantic import ValidationError

from foxgen.application.lifecycle import normalize_provider_payload
from foxgen.application.media import extract_result_urls
from foxgen.core.errors import ProviderError
from foxgen.domain.models import GenerationStatus, MediaKind
from foxgen.providers.kie.client import KieClient
from foxgen.providers.kie.contracts import InputContract, validate_input
from foxgen.providers.kie.registry import ModelRegistry
from foxgen.providers.kie.router import RoutedKieClient
from foxgen.providers.kie.suno import SunoClient


def test_suno_v5_registry_is_reviewed_dedicated_api_family() -> None:
    item = ModelRegistry().get("suno-v5")

    assert item.provider_model == "V5"
    assert item.media_kind == MediaKind.AUDIO
    assert item.contract == InputContract.SUNO_V5_GENERATE
    assert item.api_family == "suno"
    assert item.provider_id_verified is True
    assert item.schema_verified is True
    assert item.enabled_for_submission is True
    assert item.production_ready is True
    assert item.tested_live is False
    assert item.contract_reviewed_at == "2026-08-16"


def test_suno_v5_simple_and_custom_contracts_normalize() -> None:
    simple = validate_input(
        InputContract.SUNO_V5_GENERATE,
        {
            "prompt": "Warm indie pop song about a late-night train",
            "instrumental": False,
        },
    )
    custom_vocal = validate_input(
        InputContract.SUNO_V5_GENERATE,
        {
            "custom_mode": True,
            "instrumental": False,
            "prompt": "[Verse]\nCity lights and empty roads",
            "style": "indie pop, warm female vocal",
            "title": "Last Train",
            "negative_tags": "metal, harsh noise",
            "vocal_gender": "f",
            "style_weight": 0.8,
            "weirdness_constraint": 0.25,
            "audio_weight": 0.7,
        },
    )
    custom_instrumental = validate_input(
        InputContract.SUNO_V5_GENERATE,
        {
            "custom_mode": True,
            "instrumental": True,
            "style": "cinematic synthwave, 110 bpm",
            "title": "Neon Fox",
        },
    )

    assert simple["custom_mode"] is False
    assert simple["prompt"].startswith("Warm indie")
    assert custom_vocal["title"] == "Last Train"
    assert custom_vocal["vocal_gender"] == "f"
    assert custom_instrumental["prompt"] == ""
    assert custom_instrumental["instrumental"] is True


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"prompt": "x" * 501},
        {"prompt": "simple", "style": "pop"},
        {"custom_mode": True, "instrumental": False, "style": "pop", "title": "No lyrics"},
        {"custom_mode": True, "instrumental": True, "title": "No style"},
        {
            "custom_mode": True,
            "instrumental": True,
            "style": "pop",
            "title": "Bad weight",
            "style_weight": 1.1,
        },
        {
            "custom_mode": True,
            "instrumental": False,
            "prompt": "Lyrics",
            "style": "pop",
            "title": "Bad gender",
            "vocal_gender": "x",
        },
    ],
)
def test_suno_v5_rejects_invalid_mode_combinations(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        validate_input(InputContract.SUNO_V5_GENERATE, payload)


@pytest.mark.asyncio
async def test_suno_client_uses_dedicated_endpoints_and_archives_only_canonical_audio() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer test-key"
        if request.url.path == "/api/v1/generate":
            body = json.loads(request.content.decode())
            assert body == {
                "customMode": True,
                "instrumental": False,
                "model": "V5",
                "prompt": "[Verse] Fox in the neon city",
                "style": "synth pop",
                "title": "Neon Fox",
                "negativeTags": "metal",
                "vocalGender": "f",
                "styleWeight": 0.8,
                "weirdnessConstraint": 0.2,
                "audioWeight": 0.7,
            }
            return httpx.Response(200, json={"code": 200, "data": {"taskId": "suno-task-1"}})
        assert request.url.path == "/api/v1/generate/record-info"
        assert request.url.params["taskId"] == "suno-task-1"
        return httpx.Response(
            200,
            json={
                "code": 200,
                "data": {
                    "taskId": "suno-task-1",
                    "status": "SUCCESS",
                    "type": "generate",
                    "response": {
                        "sunoData": [
                            {
                                "id": "track-a",
                                "audioUrl": "https://cdn.example/a.mp3",
                                "streamAudioUrl": "https://stream.example/a",
                                "imageUrl": "https://img.example/a.jpg",
                                "title": "Neon Fox A",
                                "duration": 121.5,
                            },
                            {
                                "id": "track-b",
                                "audioUrl": "https://cdn.example/b.mp3",
                                "streamAudioUrl": "https://stream.example/b",
                                "imageUrl": "https://img.example/b.jpg",
                                "title": "Neon Fox B",
                                "duration": 119.0,
                            },
                        ]
                    },
                },
            },
        )

    http = httpx.AsyncClient(
        base_url="https://api.kie.ai",
        transport=httpx.MockTransport(handler),
    )
    transport = KieClient(api_key="test-key", client=http)
    client = SunoClient(transport)
    try:
        created = await client.create_task(
            model="V5",
            input_data={
                "custom_mode": True,
                "instrumental": False,
                "prompt": "[Verse] Fox in the neon city",
                "style": "synth pop",
                "title": "Neon Fox",
                "negative_tags": "metal",
                "vocal_gender": "f",
                "style_weight": 0.8,
                "weirdness_constraint": 0.2,
                "audio_weight": 0.7,
            },
            callback_url="https://ignored.example/callback",
        )
        record = await client.get_task(created.task_id)
    finally:
        await http.aclose()

    assert created.task_id == "suno-task-1"
    assert record.state == "SUCCESS"
    assert record.result == {
        "audioUrls": ["https://cdn.example/a.mp3", "https://cdn.example/b.mp3"],
        "tracks": [
            {"id": "track-a", "title": "Neon Fox A", "duration": 121.5},
            {"id": "track-b", "title": "Neon Fox B", "duration": 119.0},
        ],
        "task_type": "generate",
    }
    assert extract_result_urls(record.result) == (
        "https://cdn.example/a.mp3",
        "https://cdn.example/b.mp3",
    )
    assert len(requests) == 2


def test_suno_intermediate_and_failure_statuses_map_into_shared_lifecycle() -> None:
    pending = normalize_provider_payload({"status": "TEXT_SUCCESS"})
    failed = normalize_provider_payload(
        {"status": "SENSITIVE_WORD_ERROR", "errorCode": "sensitive"}
    )

    assert pending.status == GenerationStatus.PROCESSING
    assert pending.status_reason == "provider_processing"
    assert failed.status == GenerationStatus.FAILED
    assert failed.status_reason == "provider_terminal_failure"


@pytest.mark.asyncio
async def test_routed_client_selects_market_and_suno_without_guessing_model_name() -> None:
    http = httpx.AsyncClient(
        base_url="https://api.kie.ai",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"code": 200, "data": {}})
        ),
    )
    market = KieClient(api_key="test-key", client=http)
    router = RoutedKieClient(market)
    try:
        assert router.for_family("market") is market
        assert isinstance(router.for_family("suno"), SunoClient)
        with pytest.raises(ProviderError, match="Неподдерживаемое семейство"):
            router.for_family("unknown")
    finally:
        await http.aclose()
