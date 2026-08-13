from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from foxgen.admin.errors import AdminConflictError, AdminNotFoundError, AdminValidationError
from foxgen.admin.policy import (
    MODERATION_WRITE,
    PARTNERS_WRITE,
    PROMOS_WRITE,
    RUNTIME_WRITE,
    AdminContext,
)
from foxgen.admin.repository import AdminCommandExecutor, CommandResult
from foxgen.infra.admin_models import (
    FeedModerationAction,
    ModelAvailability,
    PartnerProfile,
    PartnerWithdrawal,
    PromoCode,
    PromptLibraryItem,
    RuntimeFlag,
    TrendItem,
)
from foxgen.infra.database import Database


class AdminPartnerService:
    def __init__(self, database: Database, executor: AdminCommandExecutor) -> None:
        self._database = database
        self._executor = executor

    async def act_on_withdrawal(
        self,
        *,
        context: AdminContext,
        withdrawal_id: UUID,
        action: str,
        idempotency_key: str,
    ) -> CommandResult:
        context.require(PARTNERS_WRITE)
        if action not in {"approve", "reject", "mark_paid"}:
            raise AdminValidationError("Unsupported withdrawal action")

        async def operation(session: AsyncSession) -> dict[str, object]:
            withdrawal = await session.get(PartnerWithdrawal, withdrawal_id, with_for_update=True)
            if withdrawal is None:
                raise AdminNotFoundError("partner withdrawal", str(withdrawal_id))
            transitions = {
                "approve": ({"pending"}, "approved"),
                "reject": ({"pending", "approved"}, "rejected"),
                "mark_paid": ({"approved"}, "paid"),
            }
            allowed, target = transitions[action]
            if withdrawal.status == target:
                return {"withdrawal_id": str(withdrawal.id), "status": target}
            if withdrawal.status not in allowed:
                raise AdminConflictError(
                    "Withdrawal transition is not allowed",
                    details={"status": withdrawal.status, "action": action},
                )
            withdrawal.status = target
            withdrawal.reviewed_by = context.user_id
            withdrawal.reviewed_at = func.now()
            if target == "paid":
                partner = await session.get(PartnerProfile, withdrawal.user_id, with_for_update=True)
                if partner is not None:
                    partner.withdrawn_units += withdrawal.amount_units
            return {"withdrawal_id": str(withdrawal.id), "status": target}

        return await self._executor.execute(
            context=context,
            action=f"partner_withdrawal.{action}",
            target_id=str(withdrawal_id),
            idempotency_key=idempotency_key,
            request_payload={"withdrawal_id": str(withdrawal_id), "action": action},
            operation=operation,
        )


class AdminPromoService:
    def __init__(self, database: Database, executor: AdminCommandExecutor) -> None:
        self._database = database
        self._executor = executor

    async def create(
        self,
        *,
        context: AdminContext,
        code: str,
        reward_units: int,
        max_uses: int | None,
        metadata: dict[str, object],
        idempotency_key: str,
    ) -> CommandResult:
        context.require(PROMOS_WRITE)
        normalized = code.strip().upper()
        if not normalized or len(normalized) > 64:
            raise AdminValidationError("Promo code must contain 1-64 characters")
        if reward_units < 0:
            raise AdminValidationError("Promo reward cannot be negative")
        if max_uses is not None and max_uses <= 0:
            raise AdminValidationError("Promo max_uses must be positive")

        async def operation(session: AsyncSession) -> dict[str, object]:
            existing = await session.get(PromoCode, normalized)
            if existing is not None:
                raise AdminConflictError("Promo code already exists")
            promo = PromoCode(
                code=normalized,
                active=True,
                reward_units=reward_units,
                max_uses=max_uses,
                metadata_json=metadata,
                created_by=context.user_id,
            )
            session.add(promo)
            return {
                "code": promo.code,
                "active": promo.active,
                "reward_units": promo.reward_units,
                "max_uses": promo.max_uses,
            }

        return await self._executor.execute(
            context=context,
            action="promo.create",
            target_id=normalized,
            idempotency_key=idempotency_key,
            request_payload={
                "code": normalized,
                "reward_units": reward_units,
                "max_uses": max_uses,
                "metadata": metadata,
            },
            operation=operation,
        )

    async def set_active(
        self,
        *,
        context: AdminContext,
        code: str,
        active: bool,
        idempotency_key: str,
    ) -> CommandResult:
        context.require(PROMOS_WRITE)
        normalized = code.strip().upper()

        async def operation(session: AsyncSession) -> dict[str, object]:
            promo = await session.get(PromoCode, normalized, with_for_update=True)
            if promo is None:
                raise AdminNotFoundError("promo code", normalized)
            promo.active = active
            return {"code": promo.code, "active": promo.active}

        return await self._executor.execute(
            context=context,
            action="promo.activate" if active else "promo.deactivate",
            target_id=normalized,
            idempotency_key=idempotency_key,
            request_payload={"code": normalized, "active": active},
            operation=operation,
        )


class AdminPromptService:
    def __init__(self, database: Database, executor: AdminCommandExecutor) -> None:
        self._database = database
        self._executor = executor

    async def moderate(
        self,
        *,
        context: AdminContext,
        item_id: UUID,
        action: str,
        reason: str | None,
        idempotency_key: str,
    ) -> CommandResult:
        context.require(MODERATION_WRITE)
        targets = {"approve": "approved", "reject": "rejected", "deactivate": "inactive"}
        if action not in targets:
            raise AdminValidationError("Unsupported prompt moderation action")
        if action == "reject" and not (reason or "").strip():
            raise AdminValidationError("Reject reason is required")

        async def operation(session: AsyncSession) -> dict[str, object]:
            item = await session.get(PromptLibraryItem, item_id, with_for_update=True)
            if item is None:
                raise AdminNotFoundError("prompt library item", str(item_id))
            target = targets[action]
            if target == "inactive" and item.status != "approved":
                raise AdminConflictError("Only approved prompts can be deactivated")
            if target in {"approved", "rejected"} and item.status != "pending":
                raise AdminConflictError("Only pending prompts can be moderated")
            item.status = target
            item.moderation_reason = (reason or "").strip() or None
            item.moderated_by = context.user_id
            item.moderated_at = func.now()
            return {"item_id": str(item.id), "status": item.status}

        return await self._executor.execute(
            context=context,
            action=f"prompt.{action}",
            target_id=str(item_id),
            idempotency_key=idempotency_key,
            request_payload={"item_id": str(item_id), "action": action, "reason": reason},
            operation=operation,
        )


class AdminRuntimeService:
    def __init__(self, database: Database, executor: AdminCommandExecutor) -> None:
        self._database = database
        self._executor = executor

    async def set_flag(
        self,
        *,
        context: AdminContext,
        key: str,
        enabled: bool,
        value: dict[str, object],
        idempotency_key: str,
    ) -> CommandResult:
        context.require(RUNTIME_WRITE)
        normalized = key.strip().lower()
        if not normalized or len(normalized) > 128:
            raise AdminValidationError("Runtime flag key is invalid")

        async def operation(session: AsyncSession) -> dict[str, object]:
            await session.execute(
                pg_insert(RuntimeFlag)
                .values(
                    key=normalized,
                    enabled=enabled,
                    value=value,
                    updated_by=context.user_id,
                )
                .on_conflict_do_update(
                    index_elements=[RuntimeFlag.key],
                    set_={
                        "enabled": enabled,
                        "value": value,
                        "updated_by": context.user_id,
                        "updated_at": func.now(),
                    },
                )
            )
            return {"key": normalized, "enabled": enabled, "value": value}

        return await self._executor.execute(
            context=context,
            action="runtime.flag.set",
            target_id=normalized,
            idempotency_key=idempotency_key,
            request_payload={"key": normalized, "enabled": enabled, "value": value},
            operation=operation,
        )

    async def set_model_availability(
        self,
        *,
        context: AdminContext,
        model_slug: str,
        enabled: bool,
        reason: str | None,
        idempotency_key: str,
    ) -> CommandResult:
        context.require(RUNTIME_WRITE)
        normalized = model_slug.strip()
        if not normalized:
            raise AdminValidationError("Model slug is required")

        async def operation(session: AsyncSession) -> dict[str, object]:
            await session.execute(
                pg_insert(ModelAvailability)
                .values(
                    model_slug=normalized,
                    enabled=enabled,
                    reason=(reason or "").strip() or None,
                    updated_by=context.user_id,
                )
                .on_conflict_do_update(
                    index_elements=[ModelAvailability.model_slug],
                    set_={
                        "enabled": enabled,
                        "reason": (reason or "").strip() or None,
                        "updated_by": context.user_id,
                        "updated_at": func.now(),
                    },
                )
            )
            return {
                "model_slug": normalized,
                "enabled": enabled,
                "reason": (reason or "").strip() or None,
            }

        return await self._executor.execute(
            context=context,
            action="runtime.model_availability",
            target_id=normalized,
            idempotency_key=idempotency_key,
            request_payload={"model_slug": normalized, "enabled": enabled, "reason": reason},
            operation=operation,
        )


class AdminModerationService:
    def __init__(self, database: Database, executor: AdminCommandExecutor) -> None:
        self._database = database
        self._executor = executor

    async def create_trend(
        self,
        *,
        context: AdminContext,
        title: str,
        payload: dict[str, object],
        idempotency_key: str,
    ) -> CommandResult:
        context.require(MODERATION_WRITE)
        clean = title.strip()
        if not clean:
            raise AdminValidationError("Trend title is required")

        async def operation(session: AsyncSession) -> dict[str, object]:
            item = TrendItem(title=clean, payload=payload, active=True, created_by=context.user_id)
            session.add(item)
            await session.flush()
            return {"trend_id": str(item.id), "title": item.title, "active": True}

        return await self._executor.execute(
            context=context,
            action="trend.create",
            target_id=None,
            idempotency_key=idempotency_key,
            request_payload={"title": clean, "payload": payload},
            operation=operation,
        )

    async def remove_trend(
        self,
        *,
        context: AdminContext,
        trend_id: UUID,
        idempotency_key: str,
    ) -> CommandResult:
        context.require(MODERATION_WRITE)

        async def operation(session: AsyncSession) -> dict[str, object]:
            item = await session.get(TrendItem, trend_id, with_for_update=True)
            if item is None:
                raise AdminNotFoundError("trend", str(trend_id))
            item.active = False
            return {"trend_id": str(item.id), "active": False}

        return await self._executor.execute(
            context=context,
            action="trend.remove",
            target_id=str(trend_id),
            idempotency_key=idempotency_key,
            request_payload={"trend_id": str(trend_id)},
            operation=operation,
        )

    async def moderate_feed(
        self,
        *,
        context: AdminContext,
        content_id: str,
        action: str,
        reason: str | None,
        idempotency_key: str,
    ) -> CommandResult:
        context.require(MODERATION_WRITE)
        if action not in {"blur", "remove", "restore"}:
            raise AdminValidationError("Unsupported feed moderation action")
        clean_content_id = content_id.strip()
        if not clean_content_id:
            raise AdminValidationError("Content id is required")

        async def operation(session: AsyncSession) -> dict[str, object]:
            moderation = FeedModerationAction(
                content_id=clean_content_id,
                action=action,
                reason=(reason or "").strip() or None,
                active=action != "restore",
                created_by=context.user_id,
            )
            session.add(moderation)
            await session.flush()
            return {
                "action_id": str(moderation.id),
                "content_id": clean_content_id,
                "action": action,
                "active": moderation.active,
            }

        return await self._executor.execute(
            context=context,
            action="feed.moderate",
            target_id=clean_content_id,
            idempotency_key=idempotency_key,
            request_payload={"content_id": clean_content_id, "action": action, "reason": reason},
            operation=operation,
        )


class SqlAlchemyModelAvailabilityGuard:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def ensure_enabled(self, model_slug: str) -> None:
        async with self._database.session() as session:
            availability = await session.get(ModelAvailability, model_slug)
        if availability is not None and not availability.enabled:
            raise AdminConflictError(
                "Model is disabled by runtime administration",
                details={"model_slug": model_slug, "reason": availability.reason},
            )
