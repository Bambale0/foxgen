import hashlib
import json
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
from foxgen.application.lifecycle import GenerationWorker
from foxgen.application.media import DownloadedMedia, StoredMedia
from foxgen.application.submissions import NoopSubmissionRateLimiter, SubmissionService
from foxgen.core.config import Settings
from foxgen.domain.models import (
    DeliveryStatus,
    GenerationStatus,
    LedgerEntryType,
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
from foxgen.providers.kie.router import RoutedKieClient

pytestmark = pytest.mark.skipif(
    os.getenv("FOXGEN_RUN_E2E") != "1",
    reason="cross-layer E2E tests run only in the CI infrastructure job",
)


JWT_SECRET = "suno-extend-e2e-miniapp-jwt-secret-long-enough"
CORE_MODEL = "suno-v5"
EXTEND_MODEL = "suno-v5-extend"
CORE_TRACK_A = "https://cdn.example.test/core-a.mp3"
CORE_TRACK_B = "https://cdn.example.test/core-b.mp3"
EXT_TRACK_A = "https://cdn.example.test/extend-a.mp3"
EXT_TRACK_B = "https://cdn.example.test/extend-b.mp3"


class FakeAudioDownloader:
    def __init__(self) -> None:
        self.urls: list[str] = []

    async def download(self, url: str) -> DownloadedMedia:
        self.urls.append(url)
        body = f"ID3-{url.rsplit('/', 1)[-1]}".encode()
        handle = tempfile.NamedTemporaryFile(
            prefix="foxgen-suno-extend-", suffix=".mp3", delete=False
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


class FakeAudioStorage:
    def __init__(self) -> None:
        self.objects: dict[str, StoredMedia] = {}

    async def store(self, *, key: str, media: DownloadedMedia) -> StoredMedia:
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
        return f"https://fake-storage.example.test/{storage_key}"


class FakeTelegramSender:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def send(self, *, recipient_id: int, urls: list[str], caption: str) -> list[int]:
        offset = len(self.calls) * 10
        self.calls.append({"recipient_id": recipient_id, "urls": list(urls), "caption": caption})
        return [9001 + offset + index for index in range(len(urls))]


def settings() -> Settings:
    return Settings(
        env="test",
        miniapp_enabled=True,
        miniapp_jwt_secret=JWT_SECRET,
        task_submission_enabled=True,
        s3_bucket="foxgen-e2e",
        s3_region="us-east-1",
        s3_endpoint_url="http://127.0.0.1:9000",
        s3_access_key_id="e2e-access",
        s3_secret_access_key="e2e-secret",
        s3_force_path_style=True,
    )


def auth(user_id: int, username: str) -> str:
    return issue_miniapp_token(
        TelegramMiniAppUser(id=user_id, first_name="Suno", username=username),
        secret=JWT_SECRET,
        ttl_seconds=3600,
    )


def core_payload() -> dict[str, object]:
    return {
        "custom_mode": True,
        "instrumental": False,
        "prompt": "[Verse] City lights and empty roads",
        "style": "indie pop, warm female vocal",
        "title": "Last Train",
        "negative_tags": "metal",
    }


@pytest.mark.asyncio
async def test_owner_can_extend_stored_suno_track_and_foreign_user_cannot() -> None:
    database = Database(os.environ["FOXGEN_DATABASE_URL"])
    billing = SqlAlchemyBillingRepository(database)
    lifecycle = BillingAwareLifecycleRepository(database)
    submission = SubmissionService(
        repository=SqlAlchemyGenerationRepository(database),
        rate_limiter=NoopSubmissionRateLimiter(),
    )
    owner_id = 996_000_000 + uuid4().int % 500_000
    foreign_id = owner_id + 500_000
    core_price = await billing.set_model_price(
        model_slug=CORE_MODEL,
        amount_units=20,
        currency="CREDIT",
        active_from=datetime.now(timezone.utc),
        active_until=None,
        metadata={"test": "suno-extend-core"},
    )
    extend_price = await billing.set_model_price(
        model_slug=EXTEND_MODEL,
        amount_units=30,
        currency="CREDIT",
        active_from=datetime.now(timezone.utc),
        active_until=None,
        metadata={"test": "suno-extend"},
    )
    await billing.adjust_balance(
        user_id=owner_id,
        username="extend_owner",
        amount_units=100,
        idempotency_key=f"suno-extend-credit-{owner_id}",
        actor="test:e2e",
        reason="Suno Extend E2E starting balance",
    )

    requests: list[tuple[str, str, dict[str, object] | None]] = []

    async def provider_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode()) if request.content else None
        requests.append((request.method, request.url.path, body))
        if request.method == "POST" and request.url.path == "/api/v1/generate":
            assert body is not None
            assert body["model"] == "V5"
            return httpx.Response(200, json={"code": 200, "data": {"taskId": "core-source-task"}})
        if request.method == "POST" and request.url.path == "/api/v1/generate/extend":
            assert body is not None
            assert body == {
                "defaultParamFlag": True,
                "audioId": "core-track-a",
                "model": "V5",
                "prompt": "Continue into a bigger final chorus",
                "style": "indie pop, warm female vocal",
                "title": "Last Train Extended",
                "continueAt": 92.5,
            }
            assert "source_generation_id" not in body
            return httpx.Response(200, json={"code": 200, "data": {"taskId": "extend-task"}})
        if request.method == "GET" and request.url.path == "/api/v1/generate/record-info":
            task_id = request.url.params["taskId"]
            if task_id == "core-source-task":
                return httpx.Response(
                    200,
                    json={
                        "code": 200,
                        "data": {
                            "taskId": task_id,
                            "status": "SUCCESS",
                            "type": "generate",
                            "response": {
                                "sunoData": [
                                    {
                                        "id": "core-track-a",
                                        "audioUrl": CORE_TRACK_A,
                                        "title": "Last Train A",
                                        "duration": 120.0,
                                    },
                                    {
                                        "id": "core-track-b",
                                        "audioUrl": CORE_TRACK_B,
                                        "title": "Last Train B",
                                        "duration": 118.0,
                                    },
                                ]
                            },
                        },
                    },
                )
            assert task_id == "extend-task"
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "data": {
                        "taskId": task_id,
                        "status": "SUCCESS",
                        "type": "extend",
                        "response": {
                            "sunoData": [
                                {
                                    "id": "extended-track-a",
                                    "audioUrl": EXT_TRACK_A,
                                    "title": "Extended A",
                                    "duration": 182.0,
                                },
                                {
                                    "id": "extended-track-b",
                                    "audioUrl": EXT_TRACK_B,
                                    "title": "Extended B",
                                    "duration": 179.0,
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
    routed = RoutedKieClient(KieClient(api_key="e2e-key", client=provider_http))
    downloader = FakeAudioDownloader()
    media_storage = FakeAudioStorage()
    sender = FakeTelegramSender()
    media = MediaPipeline(
        repository=lifecycle,
        downloader=downloader,
        storage=media_storage,
        sender=sender,
    )
    worker = GenerationWorker(
        repository=lifecycle,
        client=routed,
        registry=ModelRegistry(),
        callback_url="https://foxgen.example.test/webhooks/kie",
        media_pipeline=media,
        worker_id="suno-extend-e2e-worker",
        batch_size=10,
        max_attempts=3,
    )
    app = create_app(
        settings(),
        manage_resources=False,
        submission_service=submission,
        billing_service=billing,
    )
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 36123))
    core_generation_id: UUID | None = None
    extend_generation_id: UUID | None = None

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            owner_token = auth(owner_id, "extend_owner")
            foreign_token = auth(foreign_id, "foreign_user")
            core = await client.post(
                "/v1/miniapp/tasks",
                headers={
                    "Authorization": f"Bearer {owner_token}",
                    "Idempotency-Key": f"core-source-{uuid4()}",
                },
                json={"model_slug": CORE_MODEL, "input": core_payload()},
            )
            assert core.status_code == 202
            core_generation_id = UUID(core.json()["generation_id"])

        assert await worker.run_once() == 1
        assert await worker.poll_once() == 1
        assert await worker.run_once() == 1
        assert await worker.run_once() == 1

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            owner_sources = await client.get(
                "/v1/miniapp/music/suno/sources",
                headers={"Authorization": f"Bearer {owner_token}"},
            )
            assert owner_sources.status_code == 200
            sources = owner_sources.json()["items"]
            assert [item["audio_id"] for item in sources] == ["core-track-a", "core-track-b"]
            assert all(item["generation_id"] == str(core_generation_id) for item in sources)
            assert all(item["preview_url"].startswith("http") for item in sources)

            foreign_sources = await client.get(
                "/v1/miniapp/music/suno/sources",
                headers={"Authorization": f"Bearer {foreign_token}"},
            )
            assert foreign_sources.status_code == 200
            assert foreign_sources.json()["items"] == []

            foreign_extend = await client.post(
                "/v1/miniapp/music/suno/extend",
                headers={
                    "Authorization": f"Bearer {foreign_token}",
                    "Idempotency-Key": "foreign-extend-attempt",
                },
                json={
                    "source_generation_id": str(core_generation_id),
                    "audio_id": "core-track-a",
                    "default_param_flag": False,
                },
            )
            assert foreign_extend.status_code == 404

            extend = await client.post(
                "/v1/miniapp/music/suno/extend",
                headers={
                    "Authorization": f"Bearer {owner_token}",
                    "Idempotency-Key": "owned-extend-001",
                },
                json={
                    "source_generation_id": str(core_generation_id),
                    "audio_id": "core-track-a",
                    "default_param_flag": True,
                    "prompt": "Continue into a bigger final chorus",
                    "style": "indie pop, warm female vocal",
                    "title": "Last Train Extended",
                    "continue_at": 92.5,
                },
            )
            assert extend.status_code == 202
            extend_generation_id = UUID(extend.json()["generation_id"])
            assert extend.json()["model"] == EXTEND_MODEL

        assert await worker.run_once() == 1
        assert await worker.poll_once() == 1
        assert await worker.run_once() == 1
        assert await worker.run_once() == 1

        async with database.session() as session:
            core_generation = await session.get(Generation, core_generation_id)
            extended = await session.get(Generation, extend_generation_id)
            wallet = await session.get(WalletAccount, owner_id)
            reservations = (
                await session.scalars(
                    select(BalanceReservation)
                    .where(BalanceReservation.user_id == owner_id)
                    .order_by(BalanceReservation.created_at)
                )
            ).all()
            extended_assets = (
                await session.scalars(
                    select(MediaAsset).where(MediaAsset.generation_id == extend_generation_id)
                )
            ).all()
            extended_delivery = await session.scalar(
                select(GenerationDelivery).where(
                    GenerationDelivery.generation_id == extend_generation_id
                )
            )
            ledger = (
                await session.scalars(select(LedgerEntry).where(LedgerEntry.user_id == owner_id))
            ).all()
            outbox = (
                await session.scalars(
                    select(OutboxEvent).where(
                        OutboxEvent.aggregate_id.in_([core_generation_id, extend_generation_id])
                    )
                )
            ).all()

            assert core_generation is not None
            assert core_generation.status == GenerationStatus.SUCCEEDED
            assert extended is not None
            assert extended.status == GenerationStatus.SUCCEEDED
            assert extended.input_payload["source_generation_id"] == str(core_generation_id)
            assert extended.input_payload["audio_id"] == "core-track-a"
            assert extended.result_payload["audioUrls"] == [EXT_TRACK_A, EXT_TRACK_B]
            assert wallet is not None
            assert wallet.available_units == 50
            assert wallet.reserved_units == 0
            assert [item.amount_units for item in reservations] == [20, 30]
            assert all(item.status == ReservationStatus.CAPTURED for item in reservations)
            assert {asset.source_url for asset in extended_assets} == {EXT_TRACK_A, EXT_TRACK_B}
            assert extended_delivery is not None
            assert extended_delivery.status == DeliveryStatus.SENT
            types = [LedgerEntryType(str(item.entry_type)) for item in ledger]
            assert types.count(LedgerEntryType.CREDIT) == 1
            assert types.count(LedgerEntryType.RESERVE) == 2
            assert types.count(LedgerEntryType.CAPTURE) == 2
            assert all(str(item.status) == "completed" for item in outbox)

        extend_posts = [item for item in requests if item[1] == "/api/v1/generate/extend"]
        assert len(extend_posts) == 1
        assert "source_generation_id" not in extend_posts[0][2]
        assert len(sender.calls) == 2
        assert len(sender.calls[0]["urls"]) == 2
        assert len(sender.calls[1]["urls"]) == 2
    finally:
        await provider_http.aclose()
        # Keep immutable audit rows and only disable the test price fixtures.
        async with database.session() as session:
            async with session.begin():
                await session.execute(
                    update(ModelPrice)
                    .where(ModelPrice.id.in_([core_price.id, extend_price.id]))
                    .values(enabled=False)
                )
        await database.close()
