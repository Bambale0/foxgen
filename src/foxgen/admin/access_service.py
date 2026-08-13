from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from foxgen.admin.errors import AdminValidationError
from foxgen.admin.policy import ADMIN_MANAGE, ALL_SCOPES, ROLE_SCOPES, AdminContext
from foxgen.admin.repository import AdminCommandExecutor, CommandResult
from foxgen.infra.admin_models import AdminUser
from foxgen.infra.database import Database


class AdminAccessService:
    def __init__(self, database: Database, executor: AdminCommandExecutor) -> None:
        self._database = database
        self._executor = executor

    async def list_admins(self, context: AdminContext) -> list[dict[str, object]]:
        context.require(ADMIN_MANAGE)
        async with self._database.session() as session:
            items = tuple(
                (await session.scalars(select(AdminUser).order_by(AdminUser.user_id))).all()
            )
        await self._executor.audit_read(context=context, action="admins.list", target_id=None)
        return [
            {
                "user_id": item.user_id,
                "role": item.role,
                "scopes": list(item.scopes),
                "active": item.active,
                "created_at": item.created_at.isoformat(),
                "updated_at": item.updated_at.isoformat(),
            }
            for item in items
        ]

    async def set_admin(
        self,
        *,
        context: AdminContext,
        user_id: int,
        role: str,
        scopes: list[str],
        active: bool,
        idempotency_key: str,
    ) -> CommandResult:
        context.require(ADMIN_MANAGE)
        normalized_role = role.strip().lower()
        if normalized_role not in ROLE_SCOPES:
            raise AdminValidationError(
                "Unknown admin role",
                details={"allowed_roles": sorted(ROLE_SCOPES)},
            )
        normalized_scopes = sorted(set(scopes))
        unknown = sorted(set(normalized_scopes) - ALL_SCOPES)
        if unknown:
            raise AdminValidationError(
                "Unknown admin scopes",
                details={"unknown_scopes": unknown},
            )
        if user_id == context.user_id and not active:
            raise AdminValidationError(
                "An administrator cannot deactivate their own current session"
            )

        async def operation(session: AsyncSession) -> dict[str, object]:
            await session.execute(
                pg_insert(AdminUser)
                .values(
                    user_id=user_id,
                    role=normalized_role,
                    scopes=normalized_scopes,
                    active=active,
                )
                .on_conflict_do_update(
                    index_elements=[AdminUser.user_id],
                    set_={
                        "role": normalized_role,
                        "scopes": normalized_scopes,
                        "active": active,
                        "updated_at": func.now(),
                    },
                )
            )
            return {
                "user_id": user_id,
                "role": normalized_role,
                "scopes": normalized_scopes,
                "active": active,
            }

        return await self._executor.execute(
            context=context,
            action="admin.set",
            target_id=str(user_id),
            idempotency_key=idempotency_key,
            request_payload={
                "user_id": user_id,
                "role": normalized_role,
                "scopes": normalized_scopes,
                "active": active,
            },
            operation=operation,
        )
