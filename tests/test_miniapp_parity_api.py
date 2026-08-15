from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from foxgen.api.app import create_app
from foxgen.api.miniapp_security import TelegramMiniAppUser, issue_miniapp_token
from foxgen.application.reference_memory import (
    ReferenceMemoryItem,
    ReferenceMemoryPage,
    ReferenceSaveResult,
)
from foxgen.application.submissions import SubmissionReceipt
from foxgen.core.config import Settings
from foxgen.domain.models import GenerationStatus
from foxgen.domain.publications import (
    FeedSort,
    PublicationCommentView,
    PublicationMediaView,
    PublicationScope,
    PublicationView,
    PublicProfileView,
    RemixSourceView,
)


JWT_SECRET = "parity-test-jwt-secret-long-enough"
USER_ID = 778899
NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)
PUBLICATION_ID = UUID("11111111-2222-3333-4444-555555555555")
GENERATION_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
REFERENCE_ID = UUID("99999999-8888-7777-6666-555555555555")


def settings() -> Settings:
    return Settings(
        env="test",
        miniapp_enabled=True,
        miniapp_jwt_secret=JWT_SECRET,
        task_submission_enabled=True,
        kie_api_key="kie-parity-test",
        internal_api_token="internal-parity-test",
        s3_access_key_id="test-access",
        s3_secret_access_key="test-secret",
    )


def token() -> str:
    return issue_miniapp_token(
        TelegramMiniAppUser(
            id=USER_ID,
            first_name="Happy",
            username="happy_fox_user",
        ),
        secret=JWT_SECRET,
        ttl_seconds=3600,
    )


def headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {token()}"}


class FakePublicationService:
    def __init__(self) -> None:
        self.viewer_ids: list[int] = []
        self.profile = PublicProfileView(
            user_id=USER_ID,
            slug="happy-fox-user",
            display_name="Happy Fox User",
            bio="creator",
        )
        self.publication = PublicationView(
            id=PUBLICATION_ID,
            generation_id=GENERATION_ID,
            author=self.profile,
            scope=PublicationScope.FEED,
            active=True,
            model_slug="seedream-5-pro",
            media_kind="image",
            prompt="orange fox portrait",
            prompt_actions_allowed=True,
            media=(),
            likes_count=3,
            comments_count=1,
            remix_count=2,
            liked_by_viewer=False,
            source_publication_id=None,
            created_at=NOW,
        )

    async def get_profile(self, *, slug: str) -> PublicProfileView | None:
        return self.profile if slug == self.profile.slug else None

    async def get_own_profile(
        self, *, user_id: int, username: str | None
    ) -> PublicProfileView:
        self.viewer_ids.append(user_id)
        return self.profile

    async def update_profile(
        self,
        *,
        user_id: int,
        username: str | None,
        slug: str,
        display_name: str | None,
        bio: str | None,
    ) -> PublicProfileView:
        del username
        self.viewer_ids.append(user_id)
        self.profile = PublicProfileView(
            user_id=user_id,
            slug=slug,
            display_name=display_name,
            bio=bio,
        )
        return self.profile

    async def publish(
        self,
        *,
        user_id: int,
        username: str | None,
        generation_id: UUID,
        scope: PublicationScope,
    ) -> PublicationView:
        del username, generation_id
        self.viewer_ids.append(user_id)
        return PublicationView(**{**self.publication.__dict__, "scope": scope})

    async def unpublish(
        self,
        *,
        user_id: int,
        generation_id: UUID,
        scope: PublicationScope,
    ) -> bool:
        del generation_id, scope
        self.viewer_ids.append(user_id)
        return True

    async def get_publication(
        self,
        *,
        publication_id: UUID,
        viewer_user_id: int,
    ) -> PublicationView | None:
        self.viewer_ids.append(viewer_user_id)
        return self.publication if publication_id == PUBLICATION_ID else None

    async def list_feed(
        self,
        *,
        viewer_user_id: int,
        sort: FeedSort,
        limit: int,
        offset: int,
    ) -> list[PublicationView]:
        del sort, limit, offset
        self.viewer_ids.append(viewer_user_id)
        return [self.publication]

    async def list_profile_publications(
        self,
        *,
        slug: str,
        viewer_user_id: int,
        limit: int,
        offset: int,
    ) -> list[PublicationView]:
        del slug, limit, offset
        self.viewer_ids.append(viewer_user_id)
        return [self.publication]

    async def list_own_publications(
        self,
        *,
        user_id: int,
        scope: PublicationScope | None,
        limit: int,
        offset: int,
    ) -> list[PublicationView]:
        del scope, limit, offset
        self.viewer_ids.append(user_id)
        return [self.publication]

    async def set_like(
        self,
        *,
        publication_id: UUID,
        user_id: int,
        username: str | None,
        liked: bool,
    ) -> tuple[bool, int]:
        del publication_id, username
        self.viewer_ids.append(user_id)
        return liked, 4 if liked else 3

    async def add_comment(
        self,
        *,
        publication_id: UUID,
        surface: PublicationScope,
        user_id: int,
        username: str | None,
        body: str,
    ) -> PublicationCommentView:
        del username
        self.viewer_ids.append(user_id)
        return PublicationCommentView(
            id=uuid4(),
            publication_id=publication_id,
            surface=surface,
            author=self.profile,
            body=body,
            created_at=NOW,
        )

    async def list_comments(
        self,
        *,
        publication_id: UUID,
        surface: PublicationScope,
        limit: int,
        offset: int,
    ) -> list[PublicationCommentView]:
        del limit, offset
        return [
            PublicationCommentView(
                id=uuid4(),
                publication_id=publication_id,
                surface=surface,
                author=self.profile,
                body="great",
                created_at=NOW,
            )
        ]

    async def remix_source(self, *, publication_id: UUID) -> RemixSourceView:
        assert publication_id == PUBLICATION_ID
        return RemixSourceView(
            publication_id=PUBLICATION_ID,
            generation_id=GENERATION_ID,
            author_slug=self.profile.slug,
            model_slug="seedream-5-pro",
            media_kind="image",
            prompt="orange fox portrait",
            media=(),
        )


class FakeReferenceService:
    def __init__(self) -> None:
        self.user_ids: list[int] = []
        self.item = ReferenceMemoryItem(
            id=REFERENCE_ID,
            content_type="image/png",
            size_bytes=123,
            created_at=NOW,
            preview_url="https://fox.example/v1/reference-media/signed",
        )

    async def save_from_temporary_input(
        self, *, user_id: int, username: str | None, storage_key: str
    ) -> ReferenceSaveResult:
        del username
        self.user_ids.append(user_id)
        assert storage_key.startswith(f"inputs/miniapp/{user_id}/")
        return ReferenceSaveResult(item=self.item, duplicate=False)

    async def list(
        self, *, user_id: int, offset: int = 0, limit: int = 20
    ) -> ReferenceMemoryPage:
        del offset, limit
        self.user_ids.append(user_id)
        return ReferenceMemoryPage(
            items=(self.item,),
            total=1,
            used_bytes=123,
            max_items=50,
            max_bytes=1024,
        )

    async def resolve(
        self, *, user_id: int, asset_ids: tuple[UUID, ...]
    ) -> tuple[ReferenceMemoryItem, ...]:
        self.user_ids.append(user_id)
        assert asset_ids == (REFERENCE_ID,)
        return (self.item,)

    async def delete(self, *, user_id: int, asset_id: UUID) -> None:
        self.user_ids.append(user_id)
        assert asset_id == REFERENCE_ID


class FakeSubmissionService:
    def __init__(self) -> None:
        self.source_publication_id: UUID | None = None

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
        del username, input_data, idempotency_key
        assert user_id == USER_ID
        self.source_publication_id = source_publication_id
        return SubmissionReceipt(
            generation_id=uuid4(),
            model_slug=model_slug,
            provider_model=model_slug,
            status=GenerationStatus.QUEUED,
            provider_task_id=None,
            replayed=False,
        )


def app_with_services() -> tuple[TestClient, FakePublicationService, FakeReferenceService, FakeSubmissionService]:
    publications = FakePublicationService()
    references = FakeReferenceService()
    submissions = FakeSubmissionService()
    app = create_app(
        settings(),
        manage_resources=False,
        publication_service=publications,
        reference_memory_service=references,
        submission_service=submissions,
    )
    return TestClient(app), publications, references, submissions


def test_social_and_reference_routes_require_telegram_derived_jwt() -> None:
    client, _publications, _references, _submissions = app_with_services()
    with client:
        assert client.get("/v1/miniapp/feed").status_code == 401
        assert client.get("/v1/miniapp/reference-memory").status_code == 401


def test_feed_like_comment_profile_and_publish_use_jwt_owner() -> None:
    client, publications, _references, _submissions = app_with_services()
    with client:
        feed = client.get("/v1/miniapp/feed", headers=headers())
        liked = client.put(
            f"/v1/miniapp/publications/{PUBLICATION_ID}/like",
            headers=headers(),
            json={"liked": True},
        )
        comment = client.post(
            f"/v1/miniapp/publications/{PUBLICATION_ID}/comments",
            headers=headers(),
            json={"surface": "feed", "body": "Класс!"},
        )
        profile = client.put(
            "/v1/miniapp/me/profile",
            headers=headers(),
            json={"slug": "happy_fox", "display_name": "Happy", "bio": "AI creator"},
        )
        published = client.post(
            f"/v1/miniapp/generations/{GENERATION_ID}/publications",
            headers=headers(),
            json={"scope": "profile"},
        )

    assert feed.status_code == 200
    assert feed.json()["items"][0]["id"] == str(PUBLICATION_ID)
    assert liked.json() == {"liked": True, "likes_count": 4}
    assert comment.status_code == 201
    assert profile.json()["slug"] == "happy_fox"
    assert published.json()["scope"] == "profile"
    assert publications.viewer_ids and set(publications.viewer_ids) == {USER_ID}


def test_reference_memory_list_resolve_delete_are_owner_scoped() -> None:
    client, _publications, references, _submissions = app_with_services()
    with client:
        listed = client.get("/v1/miniapp/reference-memory", headers=headers())
        resolved = client.post(
            "/v1/miniapp/reference-memory/resolve",
            headers=headers(),
            json={"reference_ids": [str(REFERENCE_ID)]},
        )
        deleted = client.delete(
            f"/v1/miniapp/reference-memory/{REFERENCE_ID}", headers=headers()
        )

    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == str(REFERENCE_ID)
    assert resolved.status_code == 200
    assert deleted.status_code == 202
    assert references.user_ids and set(references.user_ids) == {USER_ID}


def test_miniapp_remix_lineage_reaches_shared_submission_service() -> None:
    client, _publications, _references, submissions = app_with_services()
    with client:
        response = client.post(
            "/v1/miniapp/tasks",
            headers={**headers(), "Idempotency-Key": "remix-contract-001"},
            json={
                "model_slug": "seedream-5-pro",
                "source_publication_id": str(PUBLICATION_ID),
                "input": {
                    "prompt": "orange fox portrait remix",
                    "aspect_ratio": "1:1",
                    "quality": "basic",
                    "output_format": "png",
                    "nsfw_checker": False,
                },
            },
        )

    assert response.status_code == 202
    assert submissions.source_publication_id == PUBLICATION_ID
