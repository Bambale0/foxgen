from foxgen.core.errors import ErrorCode, SubmissionError
from foxgen.infra.admin_user_models import UserRestriction
from foxgen.infra.database import Database


class SqlAlchemyUserAccessGuard:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def ensure_allowed(self, user_id: int) -> None:
        async with self._database.session() as session:
            restriction = await session.get(UserRestriction, user_id)
        if restriction is not None and restriction.blocked:
            raise SubmissionError(
                ErrorCode.AUTHORIZATION,
                "Доступ к генерациям для этого аккаунта ограничен.",
                details={"reason": restriction.reason},
            )
