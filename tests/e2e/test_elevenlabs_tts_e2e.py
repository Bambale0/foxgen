import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, update

from foxgen.api.app import create_app
from foxgen.api.miniapp_security import TelegramMiniAppUser, issue_miniapp_token
from foxgen.application.delivery import MediaPipeline
from foxgen.application.lifecycle import GenerationWorker
from foxgen.application.media import DownloadedMedia, StoredMedia
from foxgen.application.submissions import NoopSubmissionRateLimiter, SubmissionService
from foxgen.core.config import Settings
from foxgen.domain.models import (
    DeliveryStatus,
    GenerationStatus,
    LedgerEntryType,
    MediaAssetStatus,
    ReservationStatus,
)
from foxgen.infra.billing import SqlAlchemyBillingRepository
from foxgen.infra.billing_lifecycle_repository import BillingAwareLifecycleRepository
from foxgen.infra.billing_models import BalanceReservation, LedgerEntry, ModelPrice, WalletAccount
from foxgen.infra.database import (
    Database,
    Generation,
    GenerationDelivery,
    MediaAsset,
    OutboxEvent,
)
from foxgen.infra.repositories import SqlAlchemyGenerationRepository
from foxgen.providers.kie.client import KieClient
from foxgen.providers.kie.registry import ModelRegistry

pytestmark = pytest.mark.skipif(
    os.getenv("FOXGEN_RUN_E2E") != "1",
    reason="cross-layer E2E tests run only in the CI infrastructure job",
)


MODEL_SLUG = "elevenlabs-turbo-2-5"
PROVIDER_MODEL = "elevenlabs/text-to-speech-turbo-2-5"
JWT_SECRET = "tts-e2e-miniapp-jwt-secret-long-enough"
RESULT_URL = "https://kie.example.test/results/tts.mp3"


def tts_payload() -> dict[str, object]:
    return {
        "text": "Привет из полного Happy Fox E2E.",
        "voice": "Rachel",
        "stability": 0.5,
        "similarity_boost": 0.75,
        "style": 0.0,
        "speed": 1.0,
        "timestamps": False,
        "previous_text": "",
        "next_text": "",
        "language_code": "ru",
    }


class FakeAudioDownloader:
    def __init__(self) -> None:
        self.urls: list[str] = []

    async def download(self, url: str) -> DownloadedMedia:
        self.urls.append(url)
        body = b"ID3-e2e-elevenlabs-audio"
        handle = tempfile.NamedTemporaryFile(
            prefix="foxgen-tts-result-", suffix=".mp3", delete=False
        )
        try:
            handle.write(body)
            path = Path(handle.name)
        finally:
            handle.close()
        return DownloadedMedia(
            path=path,
            filename="tts.mp3",
            content_type="audio/mpeg",
            size_bytes=len(body),
            checksum_sha256=hashlib.sha256(body).hexdigest(),
        )


class FakeAudioStorage:
    def __init__(self) -> None:
        self.objects: dict[str, StoredMedia] = {}

    async def store(self, *, key: str, media: DownloadedMedia) -> StoredMedia:
        result = StoredMedia(
            storage_key=key,
            content_type=media.content_type,
            size_bytes=media.size_bytes,
            checksum_sha256=media.checksum_sha256,
        )
        self.objects[key] = result
        return result

    async def delete(self, storage_key: str) -> None:
        self.objects.pop(storage_key, None)

    async def presigned_url(self, storage_key: str) -> str:
        return f"https://results.example.test/{storage_key}"


class FakeTelegramAudioSender:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def send(self, *, recipient_id: int, urls: list[str], caption: str) -> list[int]:
        self.calls.append({"recipient_id": recipient_id, "urls": list(urls), "caption": caption})
        return [7001]


def _settings() -> Settings:
    return Settings(
        env="test",
        miniapp_enabled=True,
        miniapp_jwt_secret=JWT_SECRET,
        task_submission_enabled=True,
    )


def _miniapp_headers(user_id: int, *, idempotency_key: str | None = None) -> dict[str, str]:
    token = issue_miniapp_token(
        TelegramMiniAppUser(id=user_id, first_name="TTS", username="tts_e2e"),
        secret=JWT_SECRET,
        ttl_seconds=3600,
    )
    headers = {"Authorization": f"Bearer {token}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


@pytest.mark.asyncio
async def test_happy_fox_tts_paid_generation_archives_audio_and_delivers() -> None:
    database = Database(os.environ["FOXGEN_DATABASE_URL"])
    billing = SqlAlchemyBillingRepository(database)
    lifecycle = BillingAwareLifecycleRepository(database)
    submission = SubmissionService(
        repository=SqlAlchemyGenerationRepository(database),
        rate_limiter=NoopSubmissionRateLimiter(),
    )
    user_id = 998_000_000 + uuid4().int % 1_000_000
    price = await billing.set_model_price(
        model_slug=MODEL_SLUG,
        amount_units=37,
        currency="CREDIT",
        active_from=datetime.now(timezone.utc),
        active_until=None,
        metadata={"test": "tts-e2e"},
    )
    await billing.adjust_balance(
        user_id=user_id,
        username="tts_e2e",
        amount_units=100,
        idempotency_key=f"tts-e2e-credit-{user_id}",
        actor="test:e2e",
        reason="TTS E2E starting balance",
    )

    app = create_app(
        _settings(),
        manage_resources=False,
        submission_service=submission,
        billing_service=billing,
    )
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 34123))
    provider_posts: list[dict[str, object]] = []

    async def provider_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/v1/jobs/createTask":
            body = json.loads(request.content.decode())
            provider_posts.append(body)
            assert body["model"] == PROVIDER_MODEL
            assert body["input"] == tts_payload()
            assert str(body["callBackUrl"]).startswith("https://foxgen.example.test/webhooks/kie")
            return httpx.Response(200, json={"code": 200, "data": {"taskId": "kie-tts-e2e-task"}})
        if request.method == "GET" and request.url.path == "/api/v1/jobs/recordInfo":
            assert request.url.params["taskId"] == "kie-tts-e2e-task"
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "data": {
                        "taskId": "kie-tts-e2e-task",
                        "state": "success",
                        "resultJson": {"resultUrls": [RESULT_URL]},
                    },
                },
            )
        raise AssertionError(f"Unexpected provider request: {request.method} {request.url}")

    provider_http = httpx.AsyncClient(
        base_url="https://api.kie.ai",
        transport=httpx.MockTransport(provider_handler),
    )
    downloader = FakeAudioDownloader()
    storage = FakeAudioStorage()
    sender = FakeTelegramAudioSender()
    media = MediaPipeline(
        repository=lifecycle,
        downloader=downloader,
        storage=storage,
        sender=sender,
    )
    worker = GenerationWorker(
        repository=lifecycle,
        client=KieClient(api_key="e2e-key", client=provider_http),
        registry=ModelRegistry(),
        callback_url="https://foxgen.example.test/webhooks/kie",
        media_pipeline=media,
        worker_id="tts-e2e-worker",
        batch_size=10,
        max_attempts=3,
    )
    generation_id = None

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            payload = tts_payload()
            validation = await client.post(
                f"/v1/miniapp/models/{MODEL_SLUG}/validate",
                headers=_miniapp_headers(user_id),
                json={"input": payload},
            )
            assert validation.status_code == 200
            assert validation.json()["input"] == payload

            task = await client.post(
                "/v1/miniapp/tasks",
                headers=_miniapp_headers(user_id, idempotency_key=f"tts-e2e-{uuid4()}"),
                json={"model_slug": MODEL_SLUG, "input": payload},
            )
            assert task.status_code == 202
            assert task.json()["model_slug"] == MODEL_SLUG
            assert task.json()["status"] == "queued"
            generation_id = task.json()["generation_id"]

        assert await worker.run_once() == 1
        assert len(provider_posts) == 1
        assert await worker.poll_once() == 1
        assert await worker.run_once() == 1
        assert await worker.run_once() == 1

        assert downloader.urls == [RESULT_URL]
        assert len(storage.objects) == 1
        assert sender.calls[0]["recipient_id"] == user_id
        assert len(sender.calls[0]["urls"]) == 1

        async with database.session() as session:
            generation = await session.get(Generation, generation_id)
            wallet = await session.get(WalletAccount, user_id)
            reservation = await session.scalar(
                select(BalanceReservation).where(BalanceReservation.generation_id == generation_id)
            )
            asset = await session.scalar(
                select(MediaAsset).where(MediaAsset.generation_id == generation_id)
            )
            delivery = await session.scalar(
                select(GenerationDelivery).where(GenerationDelivery.generation_id == generation_id)
            )
            ledger = (
                await session.scalars(
                    select(LedgerEntry)
                    .where(LedgerEntry.user_id == user_id)
                    .order_by(LedgerEntry.created_at, LedgerEntry.id)
                )
            ).all()
            outbox = (
                await session.scalars(
                    select(OutboxEvent).where(OutboxEvent.aggregate_id == generation_id)
                )
            ).all()

            assert generation is not None
            assert generation.status == GenerationStatus.SUCCEEDED
            assert generation.media_kind == "audio"
            assert generation.provider_task_id == "kie-tts-e2e-task"
            assert wallet is not None
            assert wallet.available_units == 63
            assert wallet.reserved_units == 0
            assert reservation is not None
            assert reservation.amount_units == 37
            assert reservation.status == ReservationStatus.CAPTURED
            assert asset is not None
            assert asset.status == MediaAssetStatus.STORED
            assert asset.content_type == "audio/mpeg"
            assert delivery is not None
            assert delivery.status == DeliveryStatus.SENT
            assert delivery.telegram_message_ids == [7001]

            financial_types = [LedgerEntryType(str(item.entry_type)) for item in ledger]
            assert financial_types.count(LedgerEntryType.CREDIT) == 1
            assert financial_types.count(LedgerEntryType.RESERVE) == 1
            assert financial_types.count(LedgerEntryType.CAPTURE) == 1
            assert sum(item.available_delta for item in ledger) == 63
            assert sum(item.reserved_delta for item in ledger) == 0
            assert {item.event_type for item in outbox} == {
                "generation.submit",
                "generation.archive",
                "generation.deliver",
            }
            assert all(str(item.status) == "completed" for item in outbox)
    finally:
        await provider_http.aclose()
        # The referenced price snapshot is part of the durable billing history. Disable
        # the fixture so later tests cannot select it, but preserve its reservation FK.
        async with database.session() as session:
            async with session.begin():
                await session.execute(
                    update(ModelPrice).where(ModelPrice.id == price.id).values(enabled=False)
                )
        await database.close()
