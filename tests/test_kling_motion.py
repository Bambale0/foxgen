import json
import struct
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from foxgen.api.app import create_app
from foxgen.application.kling_motion import KLING_MOTION_MODEL_SLUG, KlingMotionService
from foxgen.application.media import DownloadedMedia
from foxgen.application.submissions import SubmissionReceipt, _validate_private_storage_ownership
from foxgen.core.config import Settings
from foxgen.core.errors import ErrorCode, ProviderError, SubmissionError
from foxgen.domain.models import GenerationStatus
from foxgen.providers.kie.client import KieClient
from foxgen.providers.kie.contracts import InputContract, validate_input
from foxgen.providers.kie.motion import KlingMotionClient
from foxgen.providers.kie.registry import ModelRegistry


def _box(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(payload), kind) + payload


def _motion_mp4(*, width: int = 720, height: int = 1280, duration: int = 5) -> bytes:
    mvhd = _box(
        b"mvhd",
        b"\x00\x00\x00\x00" + struct.pack(">IIII", 0, 0, 1000, duration * 1000),
    )
    tkhd = _box(
        b"tkhd",
        b"\x00\x00\x00\x00" + struct.pack(">II", width << 16, height << 16),
    )
    trak = _box(b"trak", tkhd)
    return _box(b"ftyp", b"isom") + _box(b"moov", mvhd + trak)


def _png(*, width: int = 768, height: int = 768) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I4sII", 13, b"IHDR", width, height)


def _media(path: Path, content_type: str) -> DownloadedMedia:
    return DownloadedMedia(
        path=path,
        filename=path.name,
        content_type=content_type,
        size_bytes=path.stat().st_size,
        checksum_sha256="test",
    )


@dataclass
class FakeInputMedia:
    image: DownloadedMedia
    video: DownloadedMedia

    async def describe(self, storage_key: str) -> DownloadedMedia:
        return self.video if storage_key.endswith(".mp4") else self.image

    async def presigned_url(self, storage_key: str) -> str:
        return f"https://inputs.example.test/{storage_key}?sig=fresh"


class FakeSubmission:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def submit(self, **kwargs: object) -> SubmissionReceipt:
        self.calls.append(dict(kwargs))
        return SubmissionReceipt(
            generation_id=uuid4(),
            model_slug=KLING_MOTION_MODEL_SLUG,
            provider_model="kling-3.0/motion-control",
            status=GenerationStatus.QUEUED,
            provider_task_id=None,
            replayed=False,
        )


def payload(user_id: int = 42) -> dict[str, object]:
    return {
        "prompt": "Transfer the dancer motion to the character",
        "image_storage_key": f"inputs/miniapp/{user_id}/character.png",
        "video_storage_key": f"inputs/miniapp/{user_id}/motion.mp4",
        "mode": "720p",
        "character_orientation": "image",
        "background_source": "input_video",
    }


def test_motion_contract_is_strict_and_fail_closed() -> None:
    normalized = validate_input(InputContract.KLING_3_MOTION_CONTROL, payload())
    assert normalized["mode"] == "720p"

    with pytest.raises(ValidationError):
        validate_input(
            InputContract.KLING_3_MOTION_CONTROL,
            {**payload(), "mode": "1080p"},
        )
    with pytest.raises(ValidationError):
        validate_input(
            InputContract.KLING_3_MOTION_CONTROL,
            {**payload(), "input_urls": ["https://evil.example/image.png"]},
        )


def test_registry_exposes_production_motion_model() -> None:
    item = ModelRegistry().get(KLING_MOTION_MODEL_SLUG)
    assert item.production_ready is True
    assert item.provider_model == "kling-3.0/motion-control"
    assert item.api_family == "kling_motion"


def test_private_storage_guard_rejects_foreign_owner() -> None:
    with pytest.raises(SubmissionError) as error:
        _validate_private_storage_ownership(42, payload(99))
    assert error.value.code == ErrorCode.TASK_NOT_FOUND


@pytest.mark.asyncio
async def test_motion_service_probes_media_before_submission(tmp_path: Path) -> None:
    image_path = tmp_path / "character.png"
    image_path.write_bytes(_png())
    video_path = tmp_path / "motion.mp4"
    video_path.write_bytes(_motion_mp4(duration=5))
    submission = FakeSubmission()
    service = KlingMotionService(
        input_media=FakeInputMedia(
            image=_media(image_path, "image/png"),
            video=_media(video_path, "video/mp4"),
        ),
        submission=submission,
    )

    receipt = await service.submit(
        user_id=42,
        username="owner",
        input_data=payload(),
        idempotency_key="motion-owner-001",
    )

    assert receipt.model_slug == KLING_MOTION_MODEL_SLUG
    assert len(submission.calls) == 1
    assert submission.calls[0]["input_data"] == validate_input(
        InputContract.KLING_3_MOTION_CONTROL,
        payload(),
    )


@pytest.mark.asyncio
async def test_motion_service_rejects_invalid_duration_before_submission(tmp_path: Path) -> None:
    image_path = tmp_path / "character.png"
    image_path.write_bytes(_png())
    video_path = tmp_path / "motion.mp4"
    video_path.write_bytes(_motion_mp4(duration=31))
    submission = FakeSubmission()
    service = KlingMotionService(
        input_media=FakeInputMedia(
            image=_media(image_path, "image/png"),
            video=_media(video_path, "video/mp4"),
        ),
        submission=submission,
    )

    with pytest.raises(SubmissionError) as error:
        await service.submit(
            user_id=42,
            username="owner",
            input_data=payload(),
            idempotency_key="motion-duration",
        )

    assert error.value.code == ErrorCode.VALIDATION
    assert submission.calls == []


@pytest.mark.asyncio
async def test_provider_resolves_fresh_urls_without_leaking_storage_keys(tmp_path: Path) -> None:
    image_path = tmp_path / "character.png"
    image_path.write_bytes(_png())
    video_path = tmp_path / "motion.mp4"
    video_path.write_bytes(_motion_mp4())
    resolver = FakeInputMedia(
        image=_media(image_path, "image/png"),
        video=_media(video_path, "video/mp4"),
    )
    seen: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/jobs/createTask"
        body = json.loads(request.content.decode())
        seen.append(body)
        return httpx.Response(200, json={"code": 200, "data": {"taskId": "motion-task"}})

    http = httpx.AsyncClient(
        base_url="https://api.kie.ai",
        transport=httpx.MockTransport(handler),
    )
    client = KlingMotionClient(KieClient(api_key="test-key", client=http), resolver)
    try:
        created = await client.create_task(
            model="kling-3.0/motion-control",
            input_data=payload(),
            callback_url="https://fox.example/webhooks/kie?generation_id=1",
        )
    finally:
        await http.aclose()

    assert created.task_id == "motion-task"
    assert len(seen) == 1
    body = seen[0]
    assert body["model"] == "kling-3.0/motion-control"
    provider_input = body["input"]
    assert provider_input["input_urls"][0].startswith("https://inputs.example.test/")
    assert provider_input["video_urls"][0].startswith("https://inputs.example.test/")
    assert "image_storage_key" not in provider_input
    assert "video_storage_key" not in provider_input
    assert body["callBackUrl"].startswith("https://fox.example/")


def test_product_routes_are_mounted_in_application() -> None:
    app = create_app(Settings(env="test"), manage_resources=False)
    paths = {route.path for route in app.routes}

    assert "/v1/miniapp/motion/kling" in paths
    assert "/v1/miniapp/motion/kling/inputs/image" in paths
    assert "/v1/miniapp/motion/kling/inputs/video" in paths
    assert "/v1/miniapp/music/suno/extend" in paths
    assert "/v1/miniapp/music/suno/upload-cover" in paths
