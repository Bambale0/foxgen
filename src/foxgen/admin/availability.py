from foxgen.core.errors import ErrorCode, SubmissionError
from foxgen.infra.admin_models import ModelAvailability
from foxgen.infra.database import Database


class SqlAlchemyModelAvailabilityGuard:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def ensure_enabled(self, model_slug: str) -> None:
        async with self._database.session() as session:
            availability = await session.get(ModelAvailability, model_slug)
        if availability is not None and not availability.enabled:
            raise SubmissionError(
                ErrorCode.AUTHORIZATION,
                "Эта модель временно отключена администратором.",
                details={"model_slug": model_slug, "reason": availability.reason},
            )
