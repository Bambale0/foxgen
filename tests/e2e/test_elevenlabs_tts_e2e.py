import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select

from foxgen.application.delivery import DeliveryResult, MediaBlob, MediaPipeline, StoredMedia
from foxgen.application.lifecycle import GenerationWorker
from foxgen.application.submissions import NoopSubmissionRateLimiter, SubmissionService
from foxgen.api.app import create_app
from foxgen.api.miniapp_security import TelegramMiniAppUser, issue_miniapp_token
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
    ProviderEvent,
    User,
)
from foxgen.infra.repositories import SqlAlchemyGenerationRepository
from foxgen.providers.kie.client import CreateTaskResponse, KieTaskState, TaskResult
from foxgen.providers.kie.registry import ModelRegistry

pytestmark = pytest.mark.skipif(
    os.getenv("FOXGEN_RUN_E2E") != "1",
    reason="cross-layer E2E tests run only in the CI infrastructure job",
)


MODEL_SLUG = "elevenlabs-turbo-2-5"
PROVIDER_MODEL = "elevenlabs/text-to-speech-turbo-2-5"
JWT_SECRET = "tts-e2e-miniapp-jwt-secret-long-enough"


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


class FakeKieClient:
    def __init__(self) -> None:
        self.create_calls: list[dict[str, object]] = []
        self.check_calls: list[str] = []

    async def create(
        self,
        *,
        provider_model: str,
        input_payload: dict[str, object],
        callback_url: str | None,
    ) -> CreateTaskResponse:
        self.create_calls.append(
            {
                "provider_model": provider_model,
                "input_payload": dict(input_payload),
                "callback_url": callback_url,
            }
        )
        return CreateTaskResponse(task_id="kie-tts-e2e-task")

    async def check(self, task_id: str) -> TaskResult:
        self.check_calls.append(task_id)
        return TaskResult(
            state=KieTaskState.SUCCESS,
            result_urls=("https://kie.example.test/results/tts.mp3",),
            raw_payload={
                "taskId": task_id,
                "state": "success",
                "resultJson": {"resultUrls": ["https://kie.example.test/results/tts.mp3"]},
            },
        )


class FakeAudioDownloader:
    def __init__(self) -> None:
        self.urls: list[str] = []

    async def download(self, url: str) -> MediaBlob:
        self.urls.append(url)
        body = b"ID3-e2e-elevenlabs-audio"
        return MediaBlob(
            body=body,
            content_type="audio/mpeg",
            extension="mp3",
            checksum_sha256=hashlib.sha256(body).hexdigest(),
        )


class FakeAudioStorage:
    def __init__(self) -> None:
        self.keys: list[str] = []

    async def put(self, *, object_key: str, media: MediaBlob) -> StoredMedia:
        assert media.content_type == "audio/mpeg"
        assert media.extension == "mp3"
        self.keys.append(object_key)
        return StoredMedia(
            object_key=object_key,
            storage_url=f"s3://foxgen-e2e/{object_key}",
            checksum_sha256=media.checksum_sha256,
        )


class FakeTelegramAudioSender:
    def __init__(self) -> None:
        self.calls: list[tuple[int, tuple[str, ...]]] = []

    async def send(self, *, user_id: int, storage_urls: tuple[str, ...]) -> DeliveryResult:
        self.calls.append((user_id, storage_urls))
        return DeliveryResult(message_ids=(7001,), uncertain=False)


@dataclass(frozen=True)
class E2EResources:
    generation_id: object
    price_id: object
    user_id: int


def _settings() -> Settings:
    return Settings(
        env="test",
        miniapp_enabled=True,
        miniapp_jwt_secret=JWT_SECRET,
        task_submission_enabled=True,
    )


def _miniapp_headers(user_id: int) -> dict[str, str]:
    token = issue_miniapp_token(
        TelegramMiniAppUser(id=user_id, first_name="TTS", username="tts_e2e"),
        secret=JWT_SECRET,
        ttl_seconds=3600,
    )
    return {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": f"tts-e2e-{uuid4()}",
    }


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
    generation_id = None
    fake_kie = FakeKieClient()
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
        client=fake_kie,  # type: ignore[arg-type]
        registry=ModelRegistry(),
        callback_url="https://foxgen.example.test/webhooks/kie",
        media_pipeline=media,
        worker_id="tts-e2e-worker",
        batch_size=10,
        max_attempts=3,
    )

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            payload = tts_payload()
            validation = await client.post(
                f"/v1/miniapp/models/{MODEL_SLUG}/validate",
                headers={"Authorization": _miniapp_headers(user_id)["Authorization"]},
                json={"input": payload},
            )
            assert validation.status_code == 200
            assert validation.json()["input"] == payload

            task = await client.post(
                "/v1/miniapp/tasks",
                headers=_miniapp_headers(user_id),
                json={"model_slug": MODEL_SLUG, "input": payload},
            )
            assert task.status_code == 202
            assert task.json()["model_slug"] == MODEL_SLUG
            assert task.json()["status"] == "queued"
            generation_id = task.json()["generation_id"]

        assert await worker.run_once() == 1
        assert fake_kie.create_calls == [
            {
                "provider_model": PROVIDER_MODEL,
                "input_payload": tts_payload(),
                "callback_url": "https://foxgen.example.test/webhooks/kie",
            }
        ]

        completed = await worker.process_callback("kie-tts-e2e-task")
        assert completed is not None
        assert completed.status == GenerationStatus.RESULT_READY
        assert fake_kie.check_calls == ["kie-tts-e2e-task"]

        assert await worker.run_once() == 1
        assert downloader.urls == ["https://kie.example.test/results/tts.mp3"]
        assert len(storage.keys) == 1
        assert storage.keys[0].endswith(".mp3")

        assert await worker.run_once() == 1
        assert sender.calls == [
            (
                user_id,
                (f"s3://foxgen-e2e/{storage.keys[0]}",),
            )
        ]

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
            assert asset.storage_key == storage.keys[0]
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
        async with database.session() as session:
            async with session.begin():
                if generation_id is not None:
                    await session.execute(
                        delete(OutboxEvent).where(OutboxEvent.aggregate_id == generation_id)
                    )
                await session.execute(
                    delete(ProviderEvent).where(
                        ProviderEvent.provider_task_id == "kie-tts-e2e-task"
                    )
                )
                await session.execute(delete(User).where(User.id == user_id))
                await session.execute(delete(ModelPrice).where(ModelPrice.id == price.id))
        await database.close()
