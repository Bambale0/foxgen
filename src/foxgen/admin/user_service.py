from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from foxgen.admin.errors import AdminNotFoundError, AdminValidationError
from foxgen.admin.policy import FINANCE_WRITE, USERS_WRITE, AdminContext
from foxgen.admin.repository import AdminCommandExecutor, CommandResult
from foxgen.infra.admin_user_models import UserRestriction
from foxgen.infra.billing import ensure_wallet_locked
from foxgen.infra.billing_models import LedgerEntry
from foxgen.infra.database import Database, User
from foxgen.domain.models import LedgerEntryType


class AdminUserService:
    def __init__(self, database: Database, executor: AdminCommandExecutor) -> None:
        self._database = database
        self._executor = executor

    async def block_user(
        self,
        *,
        context: AdminContext,
        user_id: int,
        reason: str,
        idempotency_key: str,
    ) -> CommandResult:
        context.require(USERS_WRITE)
        if not reason.strip():
            raise AdminValidationError("Block reason is required")

        async def operation(session: AsyncSession) -> dict[str, object]:
            user = await session.get(User, user_id)
            if user is None:
                raise AdminNotFoundError("user", str(user_id))
            await session.execute(
                pg_insert(UserRestriction)
                .values(
                    user_id=user_id,
                    blocked=True,
                    reason=reason.strip(),
                    source="admin",
                    updated_by=context.user_id,
                    blocked_at=func.now(),
                )
                .on_conflict_do_update(
                    index_elements=[UserRestriction.user_id],
                    set_={
                        "blocked": True,
                        "reason": reason.strip(),
                        "source": "admin",
                        "updated_by": context.user_id,
                        "blocked_at": func.now(),
                        "updated_at": func.now(),
                    },
                )
            )
            return {"user_id": user_id, "blocked": True, "reason": reason.strip()}

        return await self._executor.execute(
            context=context,
            action="user.block",
            target_id=str(user_id),
            idempotency_key=idempotency_key,
            request_payload={"user_id": user_id, "reason": reason.strip()},
            operation=operation,
        )

    async def unblock_user(
        self,
        *,
        context: AdminContext,
        user_id: int,
        idempotency_key: str,
    ) -> CommandResult:
        context.require(USERS_WRITE)

        async def operation(session: AsyncSession) -> dict[str, object]:
            user = await session.get(User, user_id)
            if user is None:
                raise AdminNotFoundError("user", str(user_id))
            await session.execute(
                pg_insert(UserRestriction)
                .values(
                    user_id=user_id,
                    blocked=False,
                    reason=None,
                    source="admin",
                    updated_by=context.user_id,
                )
                .on_conflict_do_update(
                    index_elements=[UserRestriction.user_id],
                    set_={
                        "blocked": False,
                        "reason": None,
                        "updated_by": context.user_id,
                        "blocked_at": None,
                        "updated_at": func.now(),
                    },
                )
            )
            return {"user_id": user_id, "blocked": False}

        return await self._executor.execute(
            context=context,
            action="user.unblock",
            target_id=str(user_id),
            idempotency_key=idempotency_key,
            request_payload={"user_id": user_id},
            operation=operation,
        )

    async def adjust_balance(
        self,
        *,
        context: AdminContext,
        user_id: int,
        amount_units: int,
        reason: str,
        idempotency_key: str,
    ) -> CommandResult:
        context.require(FINANCE_WRITE)
        if amount_units == 0:
            raise AdminValidationError("Balance adjustment must be non-zero")
        if abs(amount_units) > 10_000_000_000:
            raise AdminValidationError("Balance adjustment exceeds the safety limit")
        if not reason.strip():
            raise AdminValidationError("Adjustment reason is required")

        async def operation(session: AsyncSession) -> dict[str, object]:
            await session.execute(
                pg_insert(User)
                .values(id=user_id, username=None)
                .on_conflict_do_nothing(index_elements=[User.id])
            )
            account = await ensure_wallet_locked(session, user_id=user_id, currency="CREDIT")
            if account.available_units + amount_units < 0:
                raise AdminValidationError(
                    "Adjustment would make the available balance negative",
                    details={"available_units": account.available_units},
                )
            ledger_key = f"admin-adjust:{context.user_id}:{idempotency_key}"
            existing = await session.scalar(
                select(LedgerEntry).where(LedgerEntry.idempotency_key == ledger_key)
            )
            if existing is None:
                account.available_units += amount_units
                account.version += 1
                session.add(
                    LedgerEntry(
                        user_id=user_id,
                        generation_id=None,
                        reservation_id=None,
                        entry_type=(
                            LedgerEntryType.CREDIT if amount_units > 0 else LedgerEntryType.DEBIT
                        ),
                        currency="CREDIT",
                        available_delta=amount_units,
                        reserved_delta=0,
                        idempotency_key=ledger_key,
                        actor=f"admin:{context.user_id}",
                        reason=reason.strip(),
                        metadata_json={
                            "admin_request_id": context.request_id,
                            "admin_idempotency_key": idempotency_key,
                        },
                    )
                )
                await session.flush()
            return {
                "user_id": user_id,
                "currency": account.currency,
                "available_units": account.available_units,
                "reserved_units": account.reserved_units,
                "version": account.version,
                "amount_units": amount_units,
            }

        return await self._executor.execute(
            context=context,
            action="user.balance_adjustment",
            target_id=str(user_id),
            idempotency_key=idempotency_key,
            request_payload={
                "user_id": user_id,
                "amount_units": amount_units,
                "reason": reason.strip(),
            },
            operation=operation,
        )
