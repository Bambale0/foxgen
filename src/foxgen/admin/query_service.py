from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, or_, select

from foxgen.admin.errors import AdminNotFoundError
from foxgen.admin.policy import (
    AUDIT_READ,
    CMS_READ,
    FINANCE_READ,
    GENERATIONS_READ,
    MODERATION_READ,
    NOTIFICATIONS_READ,
    OPERATIONS_READ,
    PARTNERS_READ,
    PAYMENTS_READ,
    PROMOS_READ,
    RUNTIME_READ,
    SUPPORT_READ,
    TARIFFS_READ,
    USERS_READ,
    AdminContext,
)
from foxgen.admin.repository import AdminCommandExecutor
from foxgen.admin.security import redact_secrets
from foxgen.infra.admin_models import (
    AdminAuditEvent,
    AdminCommand,
    CmsDocument,
    CmsDocumentVersion,
    FeedModerationAction,
    ModelAvailability,
    NotificationCampaign,
    NotificationDelivery,
    OperationEvent,
    PartnerProfile,
    PartnerWithdrawal,
    PaymentEvent,
    PromoCode,
    PromptLibraryItem,
    RuntimeFlag,
    SupportMessage,
    SupportTicket,
    TariffVersion,
    TrendItem,
)
from foxgen.infra.admin_user_models import UserRestriction
from foxgen.infra.billing_models import LedgerEntry, ModelPrice, WalletAccount
from foxgen.infra.database import Database, Generation, User


class AdminQueryService:
    def __init__(self, database: Database, executor: AdminCommandExecutor) -> None:
        self._database = database
        self._executor = executor

    async def summary(self, context: AdminContext) -> dict[str, object]:
        context.require(USERS_READ)
        now = datetime.now(timezone.utc)
        since = now - timedelta(hours=24)
        async with self._database.session() as session:
            total_users = int(await session.scalar(select(func.count(User.id))) or 0)
            total_generations = int(await session.scalar(select(func.count(Generation.id))) or 0)
            active_generations = int(
                await session.scalar(
                    select(func.count(Generation.id)).where(
                        Generation.status.in_(
                            (
                                "queued",
                                "submitting",
                                "submitted",
                                "processing",
                                "submission_unknown",
                                "result_ready",
                                "storing_media",
                                "delivery_pending",
                            )
                        )
                    )
                )
                or 0
            )
            failed_24h = int(
                await session.scalar(
                    select(func.count(Generation.id)).where(
                        Generation.status == "failed",
                        Generation.created_at >= since,
                    )
                )
                or 0
            )
            open_tickets = int(
                await session.scalar(
                    select(func.count(SupportTicket.id)).where(
                        SupportTicket.status.in_(("open", "pending"))
                    )
                )
                or 0
            )
            running_campaigns = int(
                await session.scalar(
                    select(func.count(NotificationCampaign.id)).where(
                        NotificationCampaign.status == "running"
                    )
                )
                or 0
            )
            pending_withdrawals = int(
                await session.scalar(
                    select(func.count(PartnerWithdrawal.id)).where(
                        PartnerWithdrawal.status == "pending"
                    )
                )
                or 0
            )
        payload = {
            "users": total_users,
            "generations": total_generations,
            "active_generations": active_generations,
            "failed_generations_24h": failed_24h,
            "open_support_tickets": open_tickets,
            "running_campaigns": running_campaigns,
            "pending_partner_withdrawals": pending_withdrawals,
            "generated_at": now.isoformat(),
        }
        await self._executor.audit_read(context=context, action="admin.summary", target_id=None)
        return payload

    async def users(
        self,
        context: AdminContext,
        *,
        query: str | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, object]]:
        context.require(USERS_READ)
        limit = _limit(limit)
        statement = (
            select(User, WalletAccount, UserRestriction)
            .outerjoin(WalletAccount, WalletAccount.user_id == User.id)
            .outerjoin(UserRestriction, UserRestriction.user_id == User.id)
            .order_by(User.created_at.desc(), User.id.desc())
            .offset(max(offset, 0))
            .limit(limit)
        )
        if query:
            clean = query.strip()
            if clean.lstrip("-").isdigit():
                statement = statement.where(User.id == int(clean))
            else:
                statement = statement.where(User.username.ilike(f"%{clean}%"))
        async with self._database.session() as session:
            rows = (await session.execute(statement)).all()
        result = [
            {
                "id": user.id,
                "username": user.username,
                "created_at": user.created_at.isoformat(),
                "blocked": bool(restriction.blocked) if restriction else False,
                "block_reason": restriction.reason if restriction else None,
                "balance": {
                    "currency": wallet.currency if wallet else "CREDIT",
                    "available_units": wallet.available_units if wallet else 0,
                    "reserved_units": wallet.reserved_units if wallet else 0,
                },
            }
            for user, wallet, restriction in rows
        ]
        await self._executor.audit_read(
            context=context,
            action="users.list",
            target_id=query,
            payload={"limit": limit, "offset": offset, "result_count": len(result)},
        )
        return result

    async def generations(
        self,
        context: AdminContext,
        *,
        user_id: int | None,
        status: str | None,
        limit: int,
    ) -> list[dict[str, object]]:
        context.require(GENERATIONS_READ)
        statement = select(Generation).order_by(Generation.created_at.desc()).limit(_limit(limit))
        if user_id is not None:
            statement = statement.where(Generation.user_id == user_id)
        if status:
            statement = statement.where(Generation.status == status)
        async with self._database.session() as session:
            items = tuple((await session.scalars(statement)).all())
        result = [_generation_payload(item) for item in items]
        await self._executor.audit_read(
            context=context,
            action="generations.list",
            target_id=str(user_id) if user_id is not None else None,
            payload={"status": status, "result_count": len(result)},
        )
        return result

    async def finance(self, context: AdminContext) -> dict[str, object]:
        context.require(FINANCE_READ)
        async with self._database.session() as session:
            available = int(
                await session.scalar(
                    select(func.coalesce(func.sum(WalletAccount.available_units), 0))
                )
                or 0
            )
            reserved = int(
                await session.scalar(
                    select(func.coalesce(func.sum(WalletAccount.reserved_units), 0))
                )
                or 0
            )
            ledger_entries = int(await session.scalar(select(func.count(LedgerEntry.id))) or 0)
            completed_payments = int(
                await session.scalar(
                    select(func.count(PaymentEvent.id)).where(
                        PaymentEvent.status.in_(("completed", "paid", "succeeded"))
                    )
                )
                or 0
            )
            payment_units = int(
                await session.scalar(
                    select(func.coalesce(func.sum(PaymentEvent.amount_units), 0)).where(
                        PaymentEvent.status.in_(("completed", "paid", "succeeded"))
                    )
                )
                or 0
            )
            active_prices = int(
                await session.scalar(
                    select(func.count(ModelPrice.id)).where(ModelPrice.enabled.is_(True))
                )
                or 0
            )
        payload = {
            "wallet_available_units": available,
            "wallet_reserved_units": reserved,
            "ledger_entries": ledger_entries,
            "completed_payments": completed_payments,
            "completed_payment_units": payment_units,
            "active_model_prices": active_prices,
        }
        await self._executor.audit_read(context=context, action="finance.summary", target_id=None)
        return payload

    async def payments(
        self,
        context: AdminContext,
        *,
        status: str | None,
        user_id: int | None,
        limit: int,
    ) -> list[dict[str, object]]:
        context.require(PAYMENTS_READ)
        statement = (
            select(PaymentEvent).order_by(PaymentEvent.created_at.desc()).limit(_limit(limit))
        )
        if status:
            statement = statement.where(PaymentEvent.status == status)
        if user_id is not None:
            statement = statement.where(PaymentEvent.user_id == user_id)
        async with self._database.session() as session:
            items = tuple((await session.scalars(statement)).all())
        result = [_payment_payload(item) for item in items]
        await self._executor.audit_read(
            context=context,
            action="payments.list",
            target_id=str(user_id) if user_id is not None else None,
            payload={"status": status, "result_count": len(result)},
        )
        return result

    async def payment_detail(self, context: AdminContext, payment_id: UUID) -> dict[str, object]:
        context.require(PAYMENTS_READ)
        async with self._database.session() as session:
            item = await session.get(PaymentEvent, payment_id)
        if item is None:
            raise AdminNotFoundError("payment", str(payment_id))
        await self._executor.audit_read(
            context=context,
            action="payments.detail",
            target_id=str(payment_id),
        )
        return _payment_payload(item, include_raw=True)

    async def tariffs(self, context: AdminContext) -> dict[str, object]:
        context.require(TARIFFS_READ)
        async with self._database.session() as session:
            latest = await session.scalar(
                select(TariffVersion).order_by(TariffVersion.version.desc()).limit(1)
            )
            prices = tuple(
                (
                    await session.scalars(
                        select(ModelPrice)
                        .where(ModelPrice.enabled.is_(True))
                        .order_by(ModelPrice.model_slug)
                    )
                ).all()
            )
        await self._executor.audit_read(context=context, action="tariffs.current", target_id=None)
        return {
            "version": _tariff_payload(latest) if latest else None,
            "active_model_prices": [
                {
                    "model_slug": item.model_slug,
                    "amount_units": item.amount_units,
                    "currency": item.currency,
                    "version": item.version,
                }
                for item in prices
            ],
        }

    async def tariff_versions(
        self, context: AdminContext, *, limit: int
    ) -> list[dict[str, object]]:
        context.require(TARIFFS_READ)
        async with self._database.session() as session:
            items = tuple(
                (
                    await session.scalars(
                        select(TariffVersion)
                        .order_by(TariffVersion.version.desc())
                        .limit(_limit(limit))
                    )
                ).all()
            )
        await self._executor.audit_read(context=context, action="tariffs.versions", target_id=None)
        return [_tariff_payload(item) for item in items]

    async def tariff_version(self, context: AdminContext, version_id: UUID) -> dict[str, object]:
        context.require(TARIFFS_READ)
        async with self._database.session() as session:
            item = await session.get(TariffVersion, version_id)
        if item is None:
            raise AdminNotFoundError("tariff version", str(version_id))
        await self._executor.audit_read(
            context=context,
            action="tariffs.version_detail",
            target_id=str(version_id),
        )
        return _tariff_payload(item)

    async def operations(
        self,
        context: AdminContext,
        *,
        generation_id: UUID | None,
        status: str | None,
        limit: int,
    ) -> list[dict[str, object]]:
        context.require(OPERATIONS_READ)
        statement = (
            select(OperationEvent).order_by(OperationEvent.created_at.desc()).limit(_limit(limit))
        )
        if generation_id is not None:
            statement = statement.where(OperationEvent.generation_id == generation_id)
        if status:
            statement = statement.where(OperationEvent.status == status)
        async with self._database.session() as session:
            items = tuple((await session.scalars(statement)).all())
        result = [_operation_payload(item) for item in items]
        await self._executor.audit_read(
            context=context,
            action="operations.list",
            target_id=str(generation_id) if generation_id else None,
            payload={"status": status, "result_count": len(result)},
        )
        return result

    async def operation_detail(
        self, context: AdminContext, operation_id: UUID
    ) -> dict[str, object]:
        context.require(OPERATIONS_READ)
        async with self._database.session() as session:
            item = await session.get(OperationEvent, operation_id)
        if item is None:
            raise AdminNotFoundError("operation", str(operation_id))
        await self._executor.audit_read(
            context=context,
            action="operations.detail",
            target_id=str(operation_id),
        )
        return _operation_payload(item)

    async def operation_timeline(
        self,
        context: AdminContext,
        operation_id: UUID,
    ) -> list[dict[str, object]]:
        context.require(OPERATIONS_READ)
        async with self._database.session() as session:
            root = await session.get(OperationEvent, operation_id)
            if root is None:
                raise AdminNotFoundError("operation", str(operation_id))
            conditions = [
                OperationEvent.id == root.id,
                OperationEvent.parent_operation_id == root.id,
            ]
            if root.parent_operation_id is not None:
                conditions.append(OperationEvent.id == root.parent_operation_id)
                conditions.append(OperationEvent.parent_operation_id == root.parent_operation_id)
            items = tuple(
                (
                    await session.scalars(
                        select(OperationEvent)
                        .where(or_(*conditions))
                        .order_by(OperationEvent.created_at, OperationEvent.id)
                    )
                ).all()
            )
        await self._executor.audit_read(
            context=context,
            action="operations.timeline",
            target_id=str(operation_id),
        )
        return [_operation_payload(item) for item in items]

    async def tickets(
        self,
        context: AdminContext,
        *,
        status: str | None,
        assignee_id: int | None,
        limit: int,
    ) -> list[dict[str, object]]:
        context.require(SUPPORT_READ)
        statement = (
            select(SupportTicket).order_by(SupportTicket.updated_at.desc()).limit(_limit(limit))
        )
        if status:
            statement = statement.where(SupportTicket.status == status)
        if assignee_id is not None:
            statement = statement.where(SupportTicket.assigned_admin_id == assignee_id)
        async with self._database.session() as session:
            items = tuple((await session.scalars(statement)).all())
        await self._executor.audit_read(context=context, action="support.tickets", target_id=None)
        return [_ticket_payload(item) for item in items]

    async def ticket_detail(self, context: AdminContext, ticket_id: UUID) -> dict[str, object]:
        context.require(SUPPORT_READ)
        async with self._database.session() as session:
            ticket = await session.get(SupportTicket, ticket_id)
            if ticket is None:
                raise AdminNotFoundError("support ticket", str(ticket_id))
            messages = tuple(
                (
                    await session.scalars(
                        select(SupportMessage)
                        .where(SupportMessage.ticket_id == ticket.id)
                        .order_by(SupportMessage.created_at)
                    )
                ).all()
            )
        await self._executor.audit_read(
            context=context,
            action="support.ticket_detail",
            target_id=str(ticket_id),
        )
        payload = _ticket_payload(ticket)
        payload["messages"] = [
            {
                "id": str(item.id),
                "sender_kind": item.sender_kind,
                "sender_id": item.sender_id,
                "body": item.body,
                "status": item.status,
                "created_at": item.created_at.isoformat(),
            }
            for item in messages
        ]
        return payload

    async def cms_documents(self, context: AdminContext) -> list[dict[str, object]]:
        context.require(CMS_READ)
        async with self._database.session() as session:
            items = tuple(
                (await session.scalars(select(CmsDocument).order_by(CmsDocument.slug))).all()
            )
        await self._executor.audit_read(context=context, action="cms.documents", target_id=None)
        return [_cms_document_payload(item) for item in items]

    async def cms_document(self, context: AdminContext, document_id: UUID) -> dict[str, object]:
        context.require(CMS_READ)
        async with self._database.session() as session:
            document = await session.get(CmsDocument, document_id)
            if document is None:
                raise AdminNotFoundError("CMS document", str(document_id))
            versions = tuple(
                (
                    await session.scalars(
                        select(CmsDocumentVersion)
                        .where(CmsDocumentVersion.document_id == document.id)
                        .order_by(CmsDocumentVersion.version.desc())
                    )
                ).all()
            )
        await self._executor.audit_read(
            context=context,
            action="cms.document_detail",
            target_id=str(document_id),
        )
        payload = _cms_document_payload(document)
        payload["versions"] = [
            {
                "id": str(item.id),
                "version": item.version,
                "body": item.body,
                "metadata": item.metadata_json,
                "created_by": item.created_by,
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "created_at": item.created_at.isoformat(),
            }
            for item in versions
        ]
        return payload

    async def campaigns(self, context: AdminContext, *, limit: int) -> list[dict[str, object]]:
        context.require(NOTIFICATIONS_READ)
        async with self._database.session() as session:
            items = tuple(
                (
                    await session.scalars(
                        select(NotificationCampaign)
                        .order_by(NotificationCampaign.created_at.desc())
                        .limit(_limit(limit))
                    )
                ).all()
            )
        await self._executor.audit_read(
            context=context, action="notifications.campaigns", target_id=None
        )
        return [_campaign_payload(item) for item in items]

    async def campaign_detail(self, context: AdminContext, campaign_id: UUID) -> dict[str, object]:
        context.require(NOTIFICATIONS_READ)
        async with self._database.session() as session:
            item = await session.get(NotificationCampaign, campaign_id)
            if item is None:
                raise AdminNotFoundError("notification campaign", str(campaign_id))
            rows = (
                await session.execute(
                    select(NotificationDelivery.status, func.count(NotificationDelivery.id))
                    .where(NotificationDelivery.campaign_id == campaign_id)
                    .group_by(NotificationDelivery.status)
                )
            ).all()
        payload = _campaign_payload(item)
        payload["deliveries"] = {str(status): int(count) for status, count in rows}
        await self._executor.audit_read(
            context=context,
            action="notifications.campaign_detail",
            target_id=str(campaign_id),
        )
        return payload

    async def partner_summary(self, context: AdminContext) -> dict[str, object]:
        context.require(PARTNERS_READ)
        async with self._database.session() as session:
            partners = int(await session.scalar(select(func.count(PartnerProfile.user_id))) or 0)
            earned = int(
                await session.scalar(
                    select(func.coalesce(func.sum(PartnerProfile.earned_units), 0))
                )
                or 0
            )
            withdrawn = int(
                await session.scalar(
                    select(func.coalesce(func.sum(PartnerProfile.withdrawn_units), 0))
                )
                or 0
            )
            pending = int(
                await session.scalar(
                    select(func.count(PartnerWithdrawal.id)).where(
                        PartnerWithdrawal.status == "pending"
                    )
                )
                or 0
            )
        await self._executor.audit_read(context=context, action="partners.summary", target_id=None)
        return {
            "partners": partners,
            "earned_units": earned,
            "withdrawn_units": withdrawn,
            "pending_withdrawals": pending,
        }

    async def partner_withdrawals(
        self,
        context: AdminContext,
        *,
        status: str | None,
        limit: int,
    ) -> list[dict[str, object]]:
        context.require(PARTNERS_READ)
        statement = (
            select(PartnerWithdrawal)
            .order_by(PartnerWithdrawal.created_at.desc())
            .limit(_limit(limit))
        )
        if status:
            statement = statement.where(PartnerWithdrawal.status == status)
        async with self._database.session() as session:
            items = tuple((await session.scalars(statement)).all())
        await self._executor.audit_read(
            context=context, action="partners.withdrawals", target_id=None
        )
        return [
            {
                "id": str(item.id),
                "user_id": item.user_id,
                "amount_units": item.amount_units,
                "status": item.status,
                "destination": item.destination,
                "reviewed_by": item.reviewed_by,
                "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else None,
                "created_at": item.created_at.isoformat(),
            }
            for item in items
        ]

    async def promo(self, context: AdminContext, code: str) -> dict[str, object]:
        context.require(PROMOS_READ)
        normalized = code.strip().upper()
        async with self._database.session() as session:
            item = await session.get(PromoCode, normalized)
        if item is None:
            raise AdminNotFoundError("promo code", normalized)
        await self._executor.audit_read(
            context=context, action="promo.detail", target_id=normalized
        )
        return {
            "code": item.code,
            "active": item.active,
            "reward_units": item.reward_units,
            "max_uses": item.max_uses,
            "uses": item.uses,
            "metadata": item.metadata_json,
            "created_by": item.created_by,
            "created_at": item.created_at.isoformat(),
        }

    async def prompts(
        self,
        context: AdminContext,
        *,
        status: str | None,
        limit: int,
    ) -> list[dict[str, object]]:
        context.require(MODERATION_READ)
        statement = (
            select(PromptLibraryItem)
            .order_by(PromptLibraryItem.created_at.desc())
            .limit(_limit(limit))
        )
        if status:
            statement = statement.where(PromptLibraryItem.status == status)
        async with self._database.session() as session:
            items = tuple((await session.scalars(statement)).all())
        await self._executor.audit_read(context=context, action="prompts.list", target_id=status)
        return [_prompt_payload(item) for item in items]

    async def prompt_detail(self, context: AdminContext, item_id: UUID) -> dict[str, object]:
        context.require(MODERATION_READ)
        async with self._database.session() as session:
            item = await session.get(PromptLibraryItem, item_id)
        if item is None:
            raise AdminNotFoundError("prompt library item", str(item_id))
        await self._executor.audit_read(
            context=context, action="prompts.detail", target_id=str(item_id)
        )
        return _prompt_payload(item)

    async def runtime(self, context: AdminContext) -> dict[str, object]:
        context.require(RUNTIME_READ)
        async with self._database.session() as session:
            flags = tuple(
                (await session.scalars(select(RuntimeFlag).order_by(RuntimeFlag.key))).all()
            )
            models = tuple(
                (
                    await session.scalars(
                        select(ModelAvailability).order_by(ModelAvailability.model_slug)
                    )
                ).all()
            )
        await self._executor.audit_read(context=context, action="runtime.read", target_id=None)
        return {
            "flags": [
                {
                    "key": item.key,
                    "enabled": item.enabled,
                    "value": item.value,
                    "updated_by": item.updated_by,
                    "updated_at": item.updated_at.isoformat(),
                }
                for item in flags
            ],
            "models": [
                {
                    "model_slug": item.model_slug,
                    "enabled": item.enabled,
                    "reason": item.reason,
                    "updated_by": item.updated_by,
                    "updated_at": item.updated_at.isoformat(),
                }
                for item in models
            ],
        }

    async def moderation(self, context: AdminContext) -> dict[str, object]:
        context.require(MODERATION_READ)
        async with self._database.session() as session:
            trends = tuple(
                (
                    await session.scalars(
                        select(TrendItem)
                        .where(TrendItem.active.is_(True))
                        .order_by(TrendItem.created_at.desc())
                    )
                ).all()
            )
            feed = tuple(
                (
                    await session.scalars(
                        select(FeedModerationAction)
                        .where(FeedModerationAction.active.is_(True))
                        .order_by(FeedModerationAction.created_at.desc())
                        .limit(200)
                    )
                ).all()
            )
        await self._executor.audit_read(context=context, action="moderation.read", target_id=None)
        return {
            "trends": [
                {"id": str(item.id), "title": item.title, "payload": item.payload}
                for item in trends
            ],
            "feed_actions": [
                {
                    "id": str(item.id),
                    "content_id": item.content_id,
                    "action": item.action,
                    "reason": item.reason,
                    "created_by": item.created_by,
                    "created_at": item.created_at.isoformat(),
                }
                for item in feed
            ],
        }

    async def audit(self, context: AdminContext, *, limit: int) -> list[dict[str, object]]:
        context.require(AUDIT_READ)
        async with self._database.session() as session:
            events = tuple(
                (
                    await session.scalars(
                        select(AdminAuditEvent)
                        .order_by(AdminAuditEvent.created_at.desc())
                        .limit(_limit(limit))
                    )
                ).all()
            )
        return [
            {
                "id": str(item.id),
                "admin_user_id": item.admin_user_id,
                "request_id": item.request_id,
                "action": item.action,
                "target_id": item.target_id,
                "outcome": item.outcome,
                "payload": redact_secrets(item.payload),
                "created_at": item.created_at.isoformat(),
            }
            for item in events
        ]

    async def command(self, context: AdminContext, command_id: UUID) -> dict[str, object]:
        context.require(AUDIT_READ)
        async with self._database.session() as session:
            item = await session.get(AdminCommand, command_id)
        if item is None:
            raise AdminNotFoundError("admin command", str(command_id))
        return {
            "id": str(item.id),
            "admin_user_id": item.admin_user_id,
            "request_id": item.request_id,
            "action": item.action,
            "target_id": item.target_id,
            "status": item.status,
            "request_payload": redact_secrets(item.request_payload),
            "response_payload": redact_secrets(item.response_payload or {}),
            "error_code": item.error_code,
            "created_at": item.created_at.isoformat(),
            "updated_at": item.updated_at.isoformat(),
        }


def _limit(value: int) -> int:
    return max(1, min(value, 200))


def _generation_payload(item: Generation) -> dict[str, object]:
    return {
        "id": str(item.id),
        "user_id": item.user_id,
        "model_slug": item.model_slug,
        "status": str(item.status),
        "provider_task_id": item.provider_task_id,
        "error_code": item.error_code,
        "failure_stage": item.failure_stage,
        "status_reason": item.status_reason,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


def _payment_payload(item: PaymentEvent, *, include_raw: bool = False) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": str(item.id),
        "provider": item.provider,
        "external_id": item.external_id,
        "user_id": item.user_id,
        "status": item.status,
        "amount_units": item.amount_units,
        "currency": item.currency,
        "credited": bool(item.credited_ledger_key),
        "last_checked_at": item.last_checked_at.isoformat() if item.last_checked_at else None,
        "processed_at": item.processed_at.isoformat() if item.processed_at else None,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }
    if include_raw:
        payload["raw_payload"] = redact_secrets(item.raw_payload)
        payload["credited_ledger_key"] = item.credited_ledger_key
    return payload


def _tariff_payload(item: TariffVersion) -> dict[str, object]:
    return {
        "id": str(item.id),
        "version": item.version,
        "payload": item.payload,
        "created_by": item.created_by,
        "published_at": item.published_at.isoformat(),
        "created_at": item.created_at.isoformat(),
    }


def _operation_payload(item: OperationEvent) -> dict[str, object]:
    return {
        "id": str(item.id),
        "generation_id": str(item.generation_id) if item.generation_id else None,
        "parent_operation_id": str(item.parent_operation_id) if item.parent_operation_id else None,
        "operation_type": item.operation_type,
        "status": item.status,
        "payload": redact_secrets(item.payload),
        "created_by": item.created_by,
        "created_at": item.created_at.isoformat(),
    }


def _ticket_payload(item: SupportTicket) -> dict[str, object]:
    return {
        "id": str(item.id),
        "user_id": item.user_id,
        "subject": item.subject,
        "status": item.status,
        "assigned_admin_id": item.assigned_admin_id,
        "priority": item.priority,
        "operator_note": item.operator_note,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


def _cms_document_payload(item: CmsDocument) -> dict[str, object]:
    return {
        "id": str(item.id),
        "slug": item.slug,
        "title": item.title,
        "published_version_id": str(item.published_version_id)
        if item.published_version_id
        else None,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


def _campaign_payload(item: NotificationCampaign) -> dict[str, object]:
    return {
        "id": str(item.id),
        "name": item.name,
        "message": item.message,
        "segment": item.segment,
        "status": item.status,
        "created_by": item.created_by,
        "started_at": item.started_at.isoformat() if item.started_at else None,
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
        "cancelled_at": item.cancelled_at.isoformat() if item.cancelled_at else None,
        "created_at": item.created_at.isoformat(),
    }


def _prompt_payload(item: PromptLibraryItem) -> dict[str, object]:
    return {
        "id": str(item.id),
        "author_user_id": item.author_user_id,
        "title": item.title,
        "prompt": item.prompt,
        "status": item.status,
        "moderation_reason": item.moderation_reason,
        "moderated_by": item.moderated_by,
        "moderated_at": item.moderated_at.isoformat() if item.moderated_at else None,
        "created_at": item.created_at.isoformat(),
    }
