import os

import pytest
from sqlalchemy import delete

from foxgen.core.errors import ErrorCode, SubmissionError
from foxgen.domain.models import GenerationStatus, MediaAssetStatus, MediaKind
from foxgen.domain.publications import PublicationScope
from foxgen.infra.database import Database, Generation, MediaAsset, User
from foxgen.infra.publication_models import GenerationLineage
from foxgen.infra.publications import SqlAlchemyPublicationRepository

pytestmark = pytest.mark.skipif(
    os.getenv("FOXGEN_RUN_INTEGRATION") != "1",
    reason="real infrastructure tests are enabled only in the CI infrastructure job",
)


async def _stored_generation(
    database: Database,
    *,
    user_id: int,
    key: str,
    prompt: str,
) -> Generation:
    async with database.session() as session:
        async with session.begin():
            generation = Generation(
                user_id=user_id,
                idempotency_key=key,
                request_hash=(key.encode().hex() + "0" * 64)[:64],
                media_kind=MediaKind.IMAGE,
                model_slug="seedream-5-pro",
                prompt=prompt,
                status=GenerationStatus.SUCCEEDED.value,
                input_payload={"prompt": prompt},
            )
            session.add(generation)
            await session.flush()
            session.add(
                MediaAsset(
                    generation_id=generation.id,
                    source_url=f"https://provider.example/{generation.id}.png",
                    storage_key=f"generations/{generation.id}/result.png",
                    content_type="image/png",
                    size_bytes=1234,
                    checksum_sha256="a" * 64,
                    status=MediaAssetStatus.STORED.value,
                )
            )
            await session.flush()
            return generation


@pytest.mark.asyncio
async def test_publication_derivative_like_and_comment_invariants() -> None:
    database = Database(os.environ["FOXGEN_DATABASE_URL"])
    repository = SqlAlchemyPublicationRepository(database)
    user_id = 910_000_058

    try:
        async with database.session() as session:
            async with session.begin():
                session.add(User(id=user_id, username="feed-integration"))

        source_generation = await _stored_generation(
            database,
            user_id=user_id,
            key="feed-source-0001",
            prompt="Original public fox prompt",
        )
        source_feed = await repository.publish(
            user_id=user_id,
            username="feed-integration",
            generation_id=source_generation.id,
            scope=PublicationScope.FEED,
        )
        source_profile = await repository.publish(
            user_id=user_id,
            username="feed-integration",
            generation_id=source_generation.id,
            scope=PublicationScope.PROFILE,
        )
        assert source_feed.generation_id == source_profile.generation_id
        assert source_feed.prompt == "Original public fox prompt"
        assert source_feed.prompt_actions_allowed is True

        liked, count = await repository.set_like(
            publication_id=source_feed.id,
            user_id=user_id,
            username="feed-integration",
            liked=True,
        )
        assert liked is True and count == 1
        liked, count = await repository.set_like(
            publication_id=source_feed.id,
            user_id=user_id,
            username="feed-integration",
            liked=True,
        )
        assert liked is True and count == 1
        liked, count = await repository.set_like(
            publication_id=source_feed.id,
            user_id=user_id,
            username="feed-integration",
            liked=False,
        )
        assert liked is False and count == 0
        liked, count = await repository.set_like(
            publication_id=source_feed.id,
            user_id=user_id,
            username="feed-integration",
            liked=False,
        )
        assert liked is False and count == 0

        comment = await repository.add_comment(
            publication_id=source_feed.id,
            surface=PublicationScope.FEED,
            user_id=user_id,
            username="feed-integration",
            body="Great fox",
        )
        assert comment.surface == PublicationScope.FEED
        comments = await repository.list_comments(
            publication_id=source_feed.id,
            surface=PublicationScope.FEED,
            limit=10,
            offset=0,
        )
        assert [item.body for item in comments] == ["Great fox"]
        with pytest.raises(SubmissionError) as wrong_surface:
            await repository.list_comments(
                publication_id=source_feed.id,
                surface=PublicationScope.PROFILE,
                limit=10,
                offset=0,
            )
        assert wrong_surface.value.code == ErrorCode.VALIDATION

        derivative = await _stored_generation(
            database,
            user_id=user_id,
            key="feed-derivative-0001",
            prompt="Private derivative prompt",
        )
        async with database.session() as session:
            async with session.begin():
                session.add(
                    GenerationLineage(
                        generation_id=derivative.id,
                        source_publication_id=source_feed.id,
                    )
                )

        with pytest.raises(SubmissionError) as feed_block:
            await repository.publish(
                user_id=user_id,
                username="feed-integration",
                generation_id=derivative.id,
                scope=PublicationScope.FEED,
            )
        assert feed_block.value.code == ErrorCode.VALIDATION

        derivative_profile = await repository.publish(
            user_id=user_id,
            username="feed-integration",
            generation_id=derivative.id,
            scope=PublicationScope.PROFILE,
        )
        assert derivative_profile.prompt is None
        assert derivative_profile.prompt_actions_allowed is False
        assert derivative_profile.source_publication_id == source_feed.id

        detail = await repository.get_publication(
            publication_id=derivative_profile.id,
            viewer_user_id=user_id,
        )
        assert detail is not None
        assert detail.prompt is None
        assert detail.prompt_actions_allowed is False
        with pytest.raises(SubmissionError) as derivative_remix:
            await repository.remix_source(publication_id=derivative_profile.id)
        assert derivative_remix.value.code == ErrorCode.VALIDATION
    finally:
        async with database.session() as session:
            async with session.begin():
                await session.execute(delete(User).where(User.id == user_id))
        await database.close()
