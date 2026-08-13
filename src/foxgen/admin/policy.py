from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from foxgen.admin.errors import AdminAuthorizationError
from foxgen.infra.admin_models import AdminUser
from foxgen.infra.database import Database


USERS_READ = "users:read"
USERS_WRITE = "users:write"
GENERATIONS_READ = "generations:read"
FINANCE_READ = "finance:read"
FINANCE_WRITE = "finance:write"
PAYMENTS_READ = "payments:read"
PAYMENTS_WRITE = "payments:write"
TARIFFS_READ = "tariffs:read"
TARIFFS_WRITE = "tariffs:write"
OPERATIONS_READ = "operations:read"
OPERATIONS_WRITE = "operations:write"
SUPPORT_READ = "support:read"
SUPPORT_WRITE = "support:write"
CMS_READ = "cms:read"
CMS_WRITE = "cms:write"
NOTIFICATIONS_READ = "notifications:read"
NOTIFICATIONS_WRITE = "notifications:write"
MODERATION_READ = "moderation:read"
MODERATION_WRITE = "moderation:write"
PARTNERS_READ = "partners:read"
PARTNERS_WRITE = "partners:write"
PROMOS_READ = "promos:read"
PROMOS_WRITE = "promos:write"
RUNTIME_READ = "runtime:read"
RUNTIME_WRITE = "runtime:write"
AUDIT_READ = "audit:read"
AI_ADMIN = "ai_admin:use"
EXPORTS_READ = "exports:read"

ALL_SCOPES = frozenset(
    {
        USERS_READ,
        USERS_WRITE,
        GENERATIONS_READ,
        FINANCE_READ,
        FINANCE_WRITE,
        PAYMENTS_READ,
        PAYMENTS_WRITE,
        TARIFFS_READ,
        TARIFFS_WRITE,
        OPERATIONS_READ,
        OPERATIONS_WRITE,
        SUPPORT_READ,
        SUPPORT_WRITE,
        CMS_READ,
        CMS_WRITE,
        NOTIFICATIONS_READ,
        NOTIFICATIONS_WRITE,
        MODERATION_READ,
        MODERATION_WRITE,
        PARTNERS_READ,
        PARTNERS_WRITE,
        PROMOS_READ,
        PROMOS_WRITE,
        RUNTIME_READ,
        RUNTIME_WRITE,
        AUDIT_READ,
        AI_ADMIN,
        EXPORTS_READ,
    }
)

ROLE_SCOPES: dict[str, frozenset[str]] = {
    "superadmin": ALL_SCOPES,
    "operator": frozenset(
        {
            USERS_READ,
            GENERATIONS_READ,
            FINANCE_READ,
            PAYMENTS_READ,
            OPERATIONS_READ,
            SUPPORT_READ,
            SUPPORT_WRITE,
            CMS_READ,
            NOTIFICATIONS_READ,
            MODERATION_READ,
            PARTNERS_READ,
            RUNTIME_READ,
            AUDIT_READ,
            EXPORTS_READ,
        }
    ),
    "support": frozenset({USERS_READ, GENERATIONS_READ, SUPPORT_READ, SUPPORT_WRITE}),
    "moderator": frozenset({USERS_READ, MODERATION_READ, MODERATION_WRITE}),
    "finance": frozenset(
        {
            USERS_READ,
            FINANCE_READ,
            FINANCE_WRITE,
            PAYMENTS_READ,
            PAYMENTS_WRITE,
            TARIFFS_READ,
            PARTNERS_READ,
            PARTNERS_WRITE,
            EXPORTS_READ,
        }
    ),
    "marketing": frozenset(
        {
            USERS_READ,
            NOTIFICATIONS_READ,
            NOTIFICATIONS_WRITE,
            CMS_READ,
            CMS_WRITE,
            PROMOS_READ,
            PROMOS_WRITE,
            PARTNERS_READ,
            MODERATION_READ,
        }
    ),
}


@dataclass(frozen=True, slots=True)
class AdminContext:
    user_id: int
    role: str
    scopes: frozenset[str]
    request_id: str

    def require(self, scope: str) -> None:
        if scope not in self.scopes:
            raise AdminAuthorizationError(f"Missing admin scope: {scope}")


class AdminPolicy:
    def __init__(self, database: Database, *, bootstrap_superuser_ids: frozenset[int]) -> None:
        self._database = database
        self._bootstrap_superuser_ids = bootstrap_superuser_ids

    async def authorize(
        self,
        *,
        user_id: int,
        request_id: str,
        required_scope: str | None = None,
    ) -> AdminContext:
        if user_id in self._bootstrap_superuser_ids:
            context = AdminContext(
                user_id=user_id,
                role="superadmin",
                scopes=ALL_SCOPES,
                request_id=request_id,
            )
        else:
            async with self._database.session() as session:
                record = await session.scalar(
                    select(AdminUser).where(
                        AdminUser.user_id == user_id,
                        AdminUser.active.is_(True),
                    )
                )
            if record is None:
                raise AdminAuthorizationError("User is not an active administrator")
            base_scopes = ROLE_SCOPES.get(record.role, frozenset())
            custom_scopes = frozenset(
                value for value in record.scopes if isinstance(value, str) and value in ALL_SCOPES
            )
            context = AdminContext(
                user_id=user_id,
                role=record.role,
                scopes=base_scopes | custom_scopes,
                request_id=request_id,
            )

        if required_scope is not None:
            context.require(required_scope)
        return context
