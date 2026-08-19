import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

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
from foxgen.domain.models import DeliveryStatus, GenerationStatus, ReservationStatus
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
from foxgen.infra.input_media import LocalInputMediaStorage
from foxgen.infra.repositories import SqlAlchemyGenerationRepository
from foxgen.providers.kie.client import KieClient
from foxgen.providers.kie.registry import ModelRegistry
from foxgen.providers.kie.router import RoutedKieClient

pytestmark = pytest.mark.skipif(
    os.getenv("FOXGEN_RUN_E2E") != "1",
    reason="cross-layer E2E tests run only in the CI infrastructure job",
)


MODEL = "suno-v5-upload-cover"
JWT_SECRET = "cover-e2e-miniapp-jwt-secret-long-enough"
RESULT_A = "https://cdn.example.test/cover-a.mp3"
RESULT_B = "https://cdn.example.test/cover-b.mp3"


class FakeResultDownloader:
    async def download(self, url: str) -> DownloadedMedia:
        body = f"ID3-{url.rsplit('/', 1)[-1]}".encode()
        handle = tempfile.NamedTemporaryFile(
            prefix="foxgen-cover-result-", suffix=".mp3", delete=False
        )
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

    async def aclose(self) -> None:
        return None


class FakeResultStorage:
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


class FakeTelegramSender:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def send(self, *, recipient_id: int, urls: list[str], caption: str) -> list[int]:
        self.calls.append({"recipient_id": recipient_id, "urls": list(urls), "caption": caption})
        return [5001 + index for index in range(len(urls))]


def auth(user_id: int, username: str) -> str:
    return issue_miniapp_token(
        TelegramMiniAppUser(id=user_id, first_name="Cover", username=username),
        secret=JWT_SECRET,
        ttl_seconds=3600,
    )


@pytest.mark.asyncio
async def test_happy_fox_owner_audio_cover_reaches_two_track_delivery() -> None:
    database = Database(os.environ["FOXGEN_DATABASE_URL"])
    billing = SqlAlchemyBillingRepository(database)
    lifecycle = BillingAwareLifecycleRepository(database)
    submission = SubmissionService(
        repository=SqlAlchemyGenerationRepository(database),
        rate_limiter=NoopSubmissionRateLimiter(),
    )
    owner_id = 995_000_000 + uuid4().int % 200_000
    foreign_id = owner_id + 300_000
    price = await billing.set_model_price(
        model_slug=MODEL,
        amount_units=25,
        currency="CREDIT",
        active_from=datetime.now(timezone.utc),
        active_until=None,
        metadata={"test": "suno-upload-cover-e2e"},
    )
    await billing.adjust_balance(
        user_id=owner_id,
        username="cover_owner",
        amount_units=100,
        idempotency_key=f"cover-e2e-credit-{owner_id}",
        actor="test:e2e",
        reason="Cover E2E starting balance",
    )

    with tempfile.TemporaryDirectory(prefix="foxgen-cover-inputs-") as input_root:
        settings = Settings(
            env="test",
            miniapp_enabled=True,
            miniapp_jwt_secret=JWT_SECRET,
            task_submission_enabled=True,
            internal_api_token="cover-e2e-internal-token",
            telegram_input_storage_root=input_root,
            telegram_input_public_base_url="https://foxgen.example.test",
            telegram_input_presigned_url_ttl_seconds=600,
            telegram_input_retention_seconds=3600,
            telegram_input_max_bytes=10 * 1024 * 1024,
        )
        app = create_app(
            settings,
            manage_resources=False,
            submission_service=submission,
            billing_service=billing,
        )
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 37123))
        owner_token = auth(owner_id, "cover_owner")
        foreign_token = auth(foreign_id, "cover_foreign")
        provider_posts: list[dict[str, object]] = []

        async def provider_handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path == "/api/v1/generate/upload-cover":
                body = json.loads(request.content.decode())
                provider_posts.append(body)
                assert body["model"] == "V5"
                assert body["customMode"] is True
                assert body["instrumental"] is False
                assert body["title"] == "Neon Cover"
                assert str(body["uploadUrl"]).startswith(
                    "https://foxgen.example.test/v1/input-media/"
                )
                assert "input_storage_key" not in body
                return httpx.Response(200, json={"code": 200, "data": {"taskId": "cover-e2e-task"}})
            if request.method == "GET" and request.url.path == "/api/v1/generate/record-info":
                assert request.url.params["taskId"] == "cover-e2e-task"
                return httpx.Response(
                    200,
                    json={
                        "code": 200,
                        "data": {
                            "taskId": "cover-e2e-task",
                            "status": "SUCCESS",
                            "type": "upload_cover",
                            "response": {
                                "sunoData": [
                                    {
                                        "id": "cover-track-a",
                                        "audioUrl": RESULT_A,
                                        "title": "Neon Cover A",
                                        "duration": 150.0,
                                        "sourceAudioUrl": "https://provider-helper.example/source.mp3",
                                    },
                                    {
                                        "id": "cover-track-b",
                                        "audioUrl": RESULT_B,
                                        "title": "Neon Cover B",
                                        "duration": 148.0,
                                    },
                                ]
                            },
                        },
                    },
                )
            raise AssertionError(f"Unexpected provider request: {request.method} {request.url}")

        provider_http = httpx.AsyncClient(
            base_url="https://api.kie.ai",
            transport=httpx.MockTransport(provider_handler),
        )
        input_storage = LocalInputMediaStorage(
            root=Path(input_root),
            public_base_url=settings.telegram_input_public_base_url,
            signing_secret=settings.internal_api_token.get_secret_value(),
            presigned_url_ttl_seconds=settings.telegram_input_presigned_url_ttl_seconds,
            retention_seconds=settings.telegram_input_retention_seconds,
        )
        routed = RoutedKieClient(
            KieClient(api_key="e2e-key", client=provider_http),
            input_media=input_storage,
        )
        result_storage = FakeResultStorage()
        sender = FakeTelegramSender()
        media = MediaPipeline(
            repository=lifecycle,
            downloader=FakeResultDownloader(),
            storage=result_storage,
            sender=sender,
        )
        worker = GenerationWorker(
            repository=lifecycle,
            client=routed,
            registry=ModelRegistry(),
            callback_url="https://foxgen.example.test/webhooks/kie",
            media_pipeline=media,
            worker_id="cover-e2e-worker",
            batch_size=10,
            max_attempts=3,
        )
        generation_id: UUID | None = None

        try:
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                upload = await client.post(
                    "/v1/miniapp/input-media",
                    headers={
                        "Authorization": f"Bearer {owner_token}",
                        "Content-Type": "audio/mpeg",
                    },
                    content=b"ID3-owner-cover-source",
                )
                assert upload.status_code == 201
                storage_key = upload.json()["storage_key"]
                assert storage_key.startswith(f"inputs/miniapp/{owner_id}/")
                assert "http" not in storage_key

                foreign = await client.post(
                    "/v1/miniapp/music/suno/upload-cover",
                    headers={
                        "Authorization": f"Bearer {foreign_token}",
                        "Idempotency-Key": "foreign-cover",
                    },
                    json={
                        "input_storage_key": storage_key,
                        "custom_mode": False,
                        "instrumental": False,
                        "prompt": "steal this source",
                    },
                )
                assert foreign.status_code == 404

                cover = await client.post(
                    "/v1/miniapp/music/suno/upload-cover",
                    headers={
                        "Authorization": f"Bearer {owner_token}",
                        "Idempotency-Key": "owner-cover-001",
                    },
                    json={
                        "input_storage_key": storage_key,
                        "custom_mode": True,
                        "instrumental": False,
                        "prompt": "[Verse] new lyrics over the same melodic idea",
                        "style": "synthwave, warm female vocal",
                        "title": "Neon Cover",
                    },
                )
                assert cover.status_code == 202
                generation_id = UUID(cover.json()["generation_id"])

            assert await worker.run_once() == 1
            assert len(provider_posts) == 1
            async with database.session() as session:
                submitted = await session.get(Generation, generation_id)
                assert submitted is not None
                assert submitted.status == GenerationStatus.SUBMITTED
                assert submitted.provider_task_id == "cover-e2e-task"
            await lifecycle.schedule_next_poll(generation_id=generation_id, delay=timedelta())
            assert await worker.poll_once() == 1
            assert await worker.run_once() == 1
            assert await worker.run_once() == 1

            async with database.session() as session:
                generation = await session.get(Generation, generation_id)
                wallet = await session.get(WalletAccount, owner_id)
                reservation = await session.scalar(
                    select(BalanceReservation).where(
                        BalanceReservation.generation_id == generation_id
                    )
                )
                assets = (
                    await session.scalars(
                        select(MediaAsset).where(MediaAsset.generation_id == generation_id)
                    )
                ).all()
                delivery = await session.scalar(
                    select(GenerationDelivery).where(
                        GenerationDelivery.generation_id == generation_id
                    )
                )
                ledger = (
                    await session.scalars(
                        select(LedgerEntry).where(LedgerEntry.user_id == owner_id)
                    )
                ).all()
                outbox = (
                    await session.scalars(
                        select(OutboxEvent).where(OutboxEvent.aggregate_id == generation_id)
                    )
                ).all()

                assert generation is not None
                assert generation.status == GenerationStatus.SUCCEEDED
                assert generation.input_payload["input_storage_key"] == storage_key
                assert "uploadUrl" not in generation.input_payload
                assert "upload_url" not in generation.input_payload
                assert generation.result_payload["audioUrls"] == [RESULT_A, RESULT_B]
                assert all(
                    "sourceAudioUrl" not in item for item in generation.result_payload["tracks"]
                )
                assert wallet is not None
                assert wallet.available_units == 75
                assert wallet.reserved_units == 0
                assert reservation is not None
                assert reservation.amount_units == 25
                assert reservation.status == ReservationStatus.CAPTURED
                assert {asset.source_url for asset in assets} == {RESULT_A, RESULT_B}
                assert delivery is not None
                assert delivery.status == DeliveryStatus.SENT
                assert len(sender.calls) == 1
                assert len(sender.calls[0]["urls"]) == 2
                assert sum(item.available_delta for item in ledger) == 75
                assert sum(item.reserved_delta for item in ledger) == 0
                assert {item.event_type for item in outbox} == {
                    "generation.submit",
                    "generation.archive",
                    "generation.deliver",
                }
                assert all(str(item.status) == "completed" for item in outbox)
        finally:
            await provider_http.aclose()

    try:
        # Preserve immutable owner audit history and disable only the test price fixture.
        async with database.session() as session:
            async with session.begin():
                await session.execute(
                    update(ModelPrice).where(ModelPrice.id == price.id).values(enabled=False)
                )
    finally:
        await database.close()
