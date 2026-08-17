import os

import pytest
from sqlalchemy import text

from foxgen.infra.database import Database

pytestmark = pytest.mark.skipif(
    os.getenv("FOXGEN_RUN_INTEGRATION") != "1",
    reason="real infrastructure tests are enabled only in CI",
)


@pytest.mark.asyncio
async def test_upload_cover_owner_guard_trigger_and_function_exist() -> None:
    database = Database(os.environ["FOXGEN_DATABASE_URL"])
    try:
        async with database.session() as session:
            trigger = await session.scalar(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM pg_trigger
                        WHERE tgname = 'trg_generations_suno_upload_cover_input'
                          AND NOT tgisinternal
                    )
                    """
                )
            )
            function = await session.scalar(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM pg_proc
                        WHERE proname = 'foxgen_validate_suno_upload_cover_input'
                    )
                    """
                )
            )
        assert trigger is True
        assert function is True
    finally:
        await database.close()
