import os

import pytest
from sqlalchemy import text

from foxgen.infra.database import Database

pytestmark = pytest.mark.skipif(
    os.getenv("FOXGEN_RUN_INTEGRATION") != "1",
    reason="real infrastructure tests are enabled only in the CI infrastructure job",
)


@pytest.mark.asyncio
async def test_suno_extend_owner_guard_trigger_is_installed() -> None:
    database = Database(os.environ["FOXGEN_DATABASE_URL"])
    try:
        async with database.session() as session:
            trigger_count = int(
                await session.scalar(
                    text(
                        """
                        SELECT count(*)
                        FROM pg_trigger
                        WHERE tgname = 'trg_generations_suno_extend_source'
                          AND NOT tgisinternal
                        """
                    )
                )
                or 0
            )
            function_count = int(
                await session.scalar(
                    text(
                        """
                        SELECT count(*)
                        FROM pg_proc
                        WHERE proname = 'foxgen_validate_suno_extend_source'
                        """
                    )
                )
                or 0
            )
            assert trigger_count == 1
            assert function_count == 1
    finally:
        await database.close()
