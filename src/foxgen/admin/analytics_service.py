from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from foxgen.admin.policy import FINANCE_READ, GENERATIONS_READ, SUPPORT_READ, AdminContext
from foxgen.admin.repository import AdminCommandExecutor
from foxgen.infra.admin_models import PaymentEvent, SupportTicket
from foxgen.infra.database import Database, Generation


class AdminAnalyticsService:
    def __init__(self, database: Database, executor: AdminCommandExecutor) -> None:
        self._database = database
        self._executor = executor

    async def snapshot(
        self,
        context: AdminContext,
        *,
        hours: int = 24,
    ) -> dict[str, object]:
        context.require(GENERATIONS_READ)
        context.require(FINANCE_READ)
        context.require(SUPPORT_READ)
        bounded_hours = max(1, min(hours, 24 * 90))
        since = datetime.now(timezone.utc) - timedelta(hours=bounded_hours)

        async with self._database.session() as session:
            generation_by_model = (
                await session.execute(
                    select(
                        Generation.model_slug,
                        Generation.status,
                        func.count(Generation.id),
                    )
                    .where(Generation.created_at >= since)
                    .group_by(Generation.model_slug, Generation.status)
                    .order_by(Generation.model_slug, Generation.status)
                )
            ).all()
            generation_errors = (
                await session.execute(
                    select(
                        Generation.error_code,
                        Generation.failure_stage,
                        func.count(Generation.id),
                    )
                    .where(
                        Generation.created_at >= since,
                        Generation.error_code.is_not(None),
                    )
                    .group_by(Generation.error_code, Generation.failure_stage)
                    .order_by(func.count(Generation.id).desc())
                )
            ).all()
            generation_paths = (
                await session.execute(
                    select(
                        Generation.media_kind,
                        Generation.model_slug,
                        func.count(Generation.id),
                    )
                    .where(Generation.created_at >= since)
                    .group_by(Generation.media_kind, Generation.model_slug)
                    .order_by(Generation.media_kind, func.count(Generation.id).desc())
                )
            ).all()
            payments = (
                await session.execute(
                    select(
                        PaymentEvent.provider,
                        PaymentEvent.status,
                        func.count(PaymentEvent.id),
                        func.coalesce(func.sum(PaymentEvent.amount_units), 0),
                    )
                    .where(PaymentEvent.created_at >= since)
                    .group_by(PaymentEvent.provider, PaymentEvent.status)
                    .order_by(PaymentEvent.provider, PaymentEvent.status)
                )
            ).all()
            support = (
                await session.execute(
                    select(
                        SupportTicket.status,
                        SupportTicket.priority,
                        func.count(SupportTicket.id),
                    )
                    .where(SupportTicket.created_at >= since)
                    .group_by(SupportTicket.status, SupportTicket.priority)
                    .order_by(SupportTicket.status, SupportTicket.priority)
                )
            ).all()

        payload: dict[str, object] = {
            "window_hours": bounded_hours,
            "since": since.isoformat(),
            "generations_by_model_status": [
                {
                    "model_slug": str(model_slug),
                    "status": str(status),
                    "count": int(count),
                }
                for model_slug, status, count in generation_by_model
            ],
            "generation_errors": [
                {
                    "error_code": str(error_code),
                    "failure_stage": str(failure_stage) if failure_stage is not None else None,
                    "count": int(count),
                }
                for error_code, failure_stage, count in generation_errors
            ],
            "generation_paths": [
                {
                    "media_kind": str(media_kind),
                    "model_slug": str(model_slug),
                    "count": int(count),
                }
                for media_kind, model_slug, count in generation_paths
            ],
            "payments_by_provider_status": [
                {
                    "provider": str(provider),
                    "status": str(status),
                    "count": int(count),
                    "amount_units": int(amount_units),
                }
                for provider, status, count, amount_units in payments
            ],
            "support_by_status_priority": [
                {
                    "status": str(status),
                    "priority": str(priority),
                    "count": int(count),
                }
                for status, priority, count in support
            ],
        }
        await self._executor.audit_read(
            context=context,
            action="analytics.snapshot",
            target_id=None,
            payload={"window_hours": bounded_hours},
        )
        return payload
