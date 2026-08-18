import hashlib
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, update

from foxgen.api.app import create_app
from foxgen.api.miniapp_security import TelegramMiniAppUser, issue_miniapp_token
from foxgen.application.delivery import MediaPipeline
from foxgen.application.lifecycle import GenerationWorker, LifecycleTaskClient
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
from foxgen.providers.kie.client import TaskCreated, TaskRecord
from foxgen.providers.kie.registry import ModelRegistry

pytestmark = pytest.mark.skipif(
    os.getenv("FOXGEN_RUN_E2E") != "1",
    reason="cross-layer E2E tests run only in the CI infrastructure job",
)


MODEL_SLUG = "suno-v5"
JWT_SECRET = "suno-e2e-miniapp-jwt-secret-long-enough"
TRACK_A = "https://cdn.example.test/suno/track-a.mp3"
TRACK_B = "https://cdn.example.test/suno/track-b.mp3"


def suno_payload() -> dict[str, object]:
    return {
        "custom_mode": True,
        "instrumental": False,
        "prompt": "[Verse] City lights and empty roads",
        "style": "indie pop, warm female vocal",
        "title": "Last Train",
        "negative_tags": "metal",
    }


class FakeSunoClient:
    def __init__(self) -> None:
        self.create_calls: list[dict[str, object]] = []
        self.poll_calls = 0

    async def create_task(
        self,
        *,
        model: str,
        input_data: dict[str, object],
        callback_url: str | None = None,
    ) -> TaskCreated:
        self.create_calls.append(
            {
                "model": model,
                "input_data": dict(input_data),
                "callback_url": callback_url,
            }
        )
        return TaskCreated(task_id="suno-e2e-task")

    async def get_task(self, task_id: str) -> TaskRecord:
        assert task_id == "suno-e2e-task"
        self.poll_calls += 1
        if self.poll_calls == 1:
            return TaskRecord(
                task_id=task_id,
                state="TEXT_SUCCESS",
                result={"audioUrls": [], "tracks": [], "task_type": "generate"},
            )
        return TaskRecord(
            task_id=task_id,
            state="SUCCESS",
            result={
                "audioUrls": [TRACK_A, TRACK_B],
                "tracks": [
                    {"id": "track-a", "title": "Last Train A"},
                    {"id": "track-b", "title": "Last Train B"},
                ],
                "task_type": "generate",
            },
        )


class FakeProviderRouter:
    def __init__(self, suno: FakeSunoClient) -> None:
        self.suno = suno
        self.families: list[str] = []

    def for_family(self, api_family: str) -> LifecycleTaskClient:
        self.families.append(api_family)
        assert api_family == "suno"
        return self.suno  # type: ignore[return-value]


class FakeAudioDownloader:
    def __init__(self) -> None:
        self.urls: list[str] = []

    async def download(self, url: str) -> DownloadedMedia:
        self.urls.append(url)
        body = f"ID3-{url.rsplit('/', 1)[-1]}".encode()
        handle = tempfile.NamedTemporaryFile(prefix="foxgen-suno-e2e-", suffix=".mp3", delete=False)
        try:
            handle.write(body)
            path = Path(handle.name)
        finally:
            handle.close()
        return DownloadedMedia(
            path=path,
            filename=url.rsplit("/", 1)[-1],
            content_type="audio/mpeg",
            size_bytes=len(body),
            checksum_sha256=hashlib.sha256(body).hexdigest(),
        )


class FakeAudioStorage:
    def __init__(self) -> None:
        self.objects: dict[str, StoredMedia] = {}

    async def store(self, *, key: str, media: DownloadedMedia) -> StoredMedia:
        assert media.content_type == "audio/mpeg"
        stored = StoredMedia(
            storage_key=key,
            content_type=media.content_type,
            size_bytes=media.size_bytes,
            checksum_sha256=media.checksum_sha256,
        )
        self.objects[key] = stored
        return stored

    async def delete(self, storage_key: str) -> None:
        self.objects.pop(storage_key, None)

    async def presigned_url(self, storage_key: str) -> str:
        assert storage_key in self.objects
        return f"https://storage.example.test/{storage_key}"


class FakeTelegramSender:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def send(
        self,
        *,
        recipient_id: int,
        urls: list[str],
        caption: str,
    ) -> list[int]:
        self.calls.append({"recipient_id": recipient_id, "urls": list(urls), "caption": caption})
        return [8101, 8102]


def settings() -> Settings:
    return Settings(
        env="test",
        miniapp_enabled=True,
        miniapp_jwt_secret=JWT_SECRET,
        task_submission_enabled=True,
        kie_api_key="e2e-key",
    )


def auth_headers(user_id: int, idempotency_key: str) -> dict[str, str]:
    token = issue_miniapp_token(
        TelegramMiniAppUser(id=user_id, first_name="Suno", username="suno_e2e"),
        secret=JWT_SECRET,
        ttl_seconds=3600,
    )
    return {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": idempotency_key,
    }


@pytest.mark.asyncio
async def test_happy_fox_suno_generates_archives_and_delivers_two_tracks() -> None:
    database = Database(os.environ["FOXGEN_DATABASE_URL"])
    billing = SqlAlchemyBillingRepository(database)
    lifecycle = BillingAwareLifecycleRepository(database)
    submission = SubmissionService(
        repository=SqlAlchemyGenerationRepository(database),
        rate_limiter=NoopSubmissionRateLimiter(),
    )
    user_id = 997_000_000 + uuid4().int % 1_000_000
    price = await billing.set_model_price(
        model_slug=MODEL_SLUG,
        amount_units=55,
        currency="CREDIT",
        active_from=datetime.now(timezone.utc),
        active_until=None,
        metadata={"test": "suno-e2e"},
    )
    await billing.adjust_balance(
        user_id=user_id,
        username="suno_e2e",
        amount_units=200,
        idempotency_key=f"suno-e2e-credit-{user_id}",
        actor="test:e2e",
        reason="Suno E2E starting balance",
    )

    app = create_app(
        settings(),
        manage_resources=False,
        submission_service=submission,
        billing_service=billing,
    )
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 35123))
    fake_suno = FakeSunoClient()
    provider_router = FakeProviderRouter(fake_suno)
    downloader = FakeAudioDownloader()
    storage = FakeAudioStorage()
    sender = FakeTelegramSender()
    media = MediaPipeline(
        repository=lifecycle,
        downloader=downloader,
        storage=storage,
        sender=sender,
    )
    worker = GenerationWorker(
        repository=lifecycle,
        client=provider_router,
        registry=ModelRegistry(),
        callback_url="https://foxgen.example.test/webhooks/kie",
        media_pipeline=media,
        worker_id="suno-e2e-worker",
        batch_size=10,
        max_attempts=3,
    )
    generation_id: UUID | None = None

    try:
        payload = suno_payload()
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = auth_headers(user_id, f"suno-e2e-{uuid4()}")
            validation = await client.post(
                f"/v1/miniapp/models/{MODEL_SLUG}/validate",
                headers={"Authorization": headers["Authorization"]},
                json={"input": payload},
            )
            assert validation.status_code == 200
            assert validation.json()["input"] == payload

            task = await client.post(
                "/v1/miniapp/tasks",
                headers=headers,
                json={"model_slug": MODEL_SLUG, "input": payload},
            )
            assert task.status_code == 202
            generation_id = UUID(task.json()["generation_id"])
            assert task.json()["model"] == MODEL_SLUG
            assert task.json()["status"] == "queued"

        assert await worker.run_once() == 1
        assert fake_suno.create_calls == [
            {
                "model": "V5",
                "input_data": payload,
                "callback_url": f"https://foxgen.example.test/webhooks/kie?generation_id={generation_id}",
            }
        ]
        assert provider_router.families == ["suno"]

        assert await worker.poll_once() == 1
        async with database.session() as session:
            processing = await session.get(Generation, generation_id)
            assert processing is not None
            assert processing.status == GenerationStatus.PROCESSING
            assert processing.status_reason == "provider_processing"

        assert await worker.poll_once() == 1
        assert provider_router.families == ["suno", "suno", "suno"]

        assert await worker.run_once() == 1
        assert downloader.urls == [TRACK_A, TRACK_B]
        assert len(storage.objects) == 2
        assert all(key.endswith(".mp3") for key in storage.objects)

        assert await worker.run_once() == 1
        assert len(sender.calls) == 1
        assert sender.calls[0]["recipient_id"] == user_id
        assert len(sender.calls[0]["urls"]) == 2
        assert sender.calls[0]["caption"].startswith("✅ Генерация готова")

        async with database.session() as session:
            generation = await session.get(Generation, generation_id)
            wallet = await session.get(WalletAccount, user_id)
            reservation = await session.scalar(
                select(BalanceReservation).where(BalanceReservation.generation_id == generation_id)
            )
            assets = (
                await session.scalars(
                    select(MediaAsset)
                    .where(MediaAsset.generation_id == generation_id)
                    .order_by(MediaAsset.source_url)
                )
            ).all()
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
            assert generation.provider_task_id == "suno-e2e-task"
            assert generation.result_payload == {
                "audioUrls": [TRACK_A, TRACK_B],
                "tracks": [
                    {"id": "track-a", "title": "Last Train A"},
                    {"id": "track-b", "title": "Last Train B"},
                ],
                "task_type": "generate",
            }
            assert wallet is not None
            assert wallet.available_units == 145
            assert wallet.reserved_units == 0
            assert reservation is not None
            assert reservation.amount_units == 55
            assert reservation.status == ReservationStatus.CAPTURED
            assert len(assets) == 2
            assert {asset.source_url for asset in assets} == {TRACK_A, TRACK_B}
            assert all(asset.status == MediaAssetStatus.STORED for asset in assets)
            assert all(asset.content_type == "audio/mpeg" for asset in assets)
            assert delivery is not None
            assert delivery.status == DeliveryStatus.SENT
            assert delivery.telegram_message_ids == [8101, 8102]

            types = [LedgerEntryType(str(item.entry_type)) for item in ledger]
            assert types.count(LedgerEntryType.CREDIT) == 1
            assert types.count(LedgerEntryType.RESERVE) == 1
            assert types.count(LedgerEntryType.CAPTURE) == 1
            assert sum(item.available_delta for item in ledger) == 145
            assert sum(item.reserved_delta for item in ledger) == 0
            assert {item.event_type for item in outbox} == {
                "generation.submit",
                "generation.archive",
                "generation.deliver",
            }
            assert all(str(item.status) == "completed" for item in outbox)
    finally:
        # Keep the immutable billing/generation audit trail. Disable the price fixture
        # so it cannot affect later tests while preserving reservation FK history.
        async with database.session() as session:
            async with session.begin():
                await session.execute(
                    update(ModelPrice).where(ModelPrice.id == price.id).values(enabled=False)
                )
        await database.close()
