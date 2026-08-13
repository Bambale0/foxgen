from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from foxgen.admin.errors import AdminConflictError, AdminNotFoundError, AdminValidationError
from foxgen.admin.policy import (
    CMS_WRITE,
    NOTIFICATIONS_WRITE,
    SUPPORT_WRITE,
    AdminContext,
)
from foxgen.admin.repository import AdminCommandExecutor, CommandResult
from foxgen.infra.admin_models import (
    AdminOutbox,
    CmsDocument,
    CmsDocumentVersion,
    NotificationCampaign,
    NotificationDelivery,
    SupportMessage,
    SupportOutbox,
    SupportTicket,
)
from foxgen.infra.database import Database, User


_ALLOWED_TICKET_STATUSES = frozenset({"open", "pending", "resolved", "closed"})
_ALLOWED_PRIORITIES = frozenset({"low", "normal", "high", "urgent"})


class AdminSupportService:
    def __init__(self, database: Database, executor: AdminCommandExecutor) -> None:
        self._database = database
        self._executor = executor

    async def assign_ticket(
        self,
        *,
        context: AdminContext,
        ticket_id: UUID,
        assignee_id: int,
        idempotency_key: str,
    ) -> CommandResult:
        context.require(SUPPORT_WRITE)

        async def operation(session: AsyncSession) -> dict[str, object]:
            ticket = await session.get(SupportTicket, ticket_id)
            if ticket is None:
                raise AdminNotFoundError("support ticket", str(ticket_id))
            ticket.assigned_admin_id = assignee_id
            ticket.updated_at = func.now()
            return {
                "ticket_id": str(ticket.id),
                "assigned_admin_id": assignee_id,
                "status": ticket.status,
            }

        return await self._executor.execute(
            context=context,
            action="support.assign",
            target_id=str(ticket_id),
            idempotency_key=idempotency_key,
            request_payload={"ticket_id": str(ticket_id), "assignee_id": assignee_id},
            operation=operation,
        )

    async def update_ticket(
        self,
        *,
        context: AdminContext,
        ticket_id: UUID,
        status: str | None,
        priority: str | None,
        operator_note: str | None,
        idempotency_key: str,
    ) -> CommandResult:
        context.require(SUPPORT_WRITE)
        if status is not None and status not in _ALLOWED_TICKET_STATUSES:
            raise AdminValidationError("Unsupported ticket status")
        if priority is not None and priority not in _ALLOWED_PRIORITIES:
            raise AdminValidationError("Unsupported ticket priority")

        async def operation(session: AsyncSession) -> dict[str, object]:
            ticket = await session.get(SupportTicket, ticket_id)
            if ticket is None:
                raise AdminNotFoundError("support ticket", str(ticket_id))
            if status is not None:
                ticket.status = status
            if priority is not None:
                ticket.priority = priority
            if operator_note is not None:
                ticket.operator_note = operator_note
            ticket.updated_at = func.now()
            return {
                "ticket_id": str(ticket.id),
                "status": ticket.status,
                "priority": ticket.priority,
                "operator_note": ticket.operator_note,
            }

        return await self._executor.execute(
            context=context,
            action="support.update",
            target_id=str(ticket_id),
            idempotency_key=idempotency_key,
            request_payload={
                "ticket_id": str(ticket_id),
                "status": status,
                "priority": priority,
                "operator_note": operator_note,
            },
            operation=operation,
        )

    async def reply_ticket(
        self,
        *,
        context: AdminContext,
        ticket_id: UUID,
        body: str,
        idempotency_key: str,
    ) -> CommandResult:
        context.require(SUPPORT_WRITE)
        clean_body = body.strip()
        if not clean_body:
            raise AdminValidationError("Support reply cannot be empty")
        if len(clean_body) > 4096:
            raise AdminValidationError("Support reply exceeds Telegram message limit")

        async def operation(session: AsyncSession) -> dict[str, object]:
            ticket = await session.get(SupportTicket, ticket_id)
            if ticket is None:
                raise AdminNotFoundError("support ticket", str(ticket_id))
            message = SupportMessage(
                ticket_id=ticket.id,
                sender_kind="admin",
                sender_id=context.user_id,
                body=clean_body,
                status="queued",
            )
            session.add(message)
            await session.flush()
            session.add(
                SupportOutbox(
                    message_id=message.id,
                    recipient_id=ticket.user_id,
                    deduplication_key=f"support.reply:{message.id}",
                    payload={
                        "ticket_id": str(ticket.id),
                        "message_id": str(message.id),
                        "text": clean_body,
                    },
                )
            )
            if ticket.status == "resolved":
                ticket.status = "pending"
            ticket.updated_at = func.now()
            return {
                "ticket_id": str(ticket.id),
                "message_id": str(message.id),
                "delivery_status": "queued",
            }

        return await self._executor.execute(
            context=context,
            action="support.reply",
            target_id=str(ticket_id),
            idempotency_key=idempotency_key,
            request_payload={"ticket_id": str(ticket_id), "body": clean_body},
            operation=operation,
        )


class AdminCmsService:
    def __init__(self, database: Database, executor: AdminCommandExecutor) -> None:
        self._database = database
        self._executor = executor

    async def save_document(
        self,
        *,
        context: AdminContext,
        slug: str,
        title: str,
        body: str,
        metadata: dict[str, object],
        idempotency_key: str,
    ) -> CommandResult:
        context.require(CMS_WRITE)
        clean_slug = slug.strip().lower()
        clean_title = title.strip()
        clean_body = body.strip()
        if not clean_slug or not clean_title or not clean_body:
            raise AdminValidationError("CMS slug, title and body are required")
        if any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for char in clean_slug):
            raise AdminValidationError("CMS slug may contain only lowercase letters, digits, '-' and '_'")

        async def operation(session: AsyncSession) -> dict[str, object]:
            document = await session.scalar(select(CmsDocument).where(CmsDocument.slug == clean_slug))
            if document is None:
                document = CmsDocument(slug=clean_slug, title=clean_title)
                session.add(document)
                await session.flush()
            else:
                document.title = clean_title
            latest = await session.scalar(
                select(func.max(CmsDocumentVersion.version)).where(
                    CmsDocumentVersion.document_id == document.id
                )
            )
            version = CmsDocumentVersion(
                document_id=document.id,
                version=int(latest or 0) + 1,
                body=clean_body,
                metadata_json=metadata,
                created_by=context.user_id,
            )
            session.add(version)
            await session.flush()
            return {
                "document_id": str(document.id),
                "version_id": str(version.id),
                "version": version.version,
                "slug": document.slug,
                "published": False,
            }

        return await self._executor.execute(
            context=context,
            action="cms.save",
            target_id=clean_slug,
            idempotency_key=idempotency_key,
            request_payload={
                "slug": clean_slug,
                "title": clean_title,
                "body": clean_body,
                "metadata": metadata,
            },
            operation=operation,
        )

    async def publish_document(
        self,
        *,
        context: AdminContext,
        document_id: UUID,
        version_id: UUID | None,
        idempotency_key: str,
    ) -> CommandResult:
        context.require(CMS_WRITE)

        async def operation(session: AsyncSession) -> dict[str, object]:
            document = await session.get(CmsDocument, document_id)
            if document is None:
                raise AdminNotFoundError("CMS document", str(document_id))
            if version_id is None:
                version = await session.scalar(
                    select(CmsDocumentVersion)
                    .where(CmsDocumentVersion.document_id == document.id)
                    .order_by(CmsDocumentVersion.version.desc())
                    .limit(1)
                )
            else:
                version = await session.get(CmsDocumentVersion, version_id)
            if version is None or version.document_id != document.id:
                raise AdminNotFoundError("CMS document version", str(version_id or "latest"))
            if version.published_at is None:
                version.published_at = func.now()
            document.published_version_id = version.id
            document.updated_at = func.now()
            return {
                "document_id": str(document.id),
                "version_id": str(version.id),
                "version": version.version,
                "published": True,
            }

        return await self._executor.execute(
            context=context,
            action="cms.publish",
            target_id=str(document_id),
            idempotency_key=idempotency_key,
            request_payload={
                "document_id": str(document_id),
                "version_id": str(version_id) if version_id else None,
            },
            operation=operation,
        )


class AdminNotificationService:
    def __init__(self, database: Database, executor: AdminCommandExecutor) -> None:
        self._database = database
        self._executor = executor

    async def preview(
        self,
        *,
        context: AdminContext,
        message: str,
        segment: dict[str, object],
    ) -> dict[str, object]:
        context.require(NOTIFICATIONS_WRITE)
        clean_message = self._validate_message(message)
        async with self._database.session() as session:
            recipients = await self._recipient_ids(session, segment)
        await self._executor.audit_read(
            context=context,
            action="notification.preview",
            target_id=None,
            payload={"recipient_count": len(recipients), "segment": segment},
        )
        return {
            "message": clean_message,
            "segment": segment,
            "recipient_count": len(recipients),
            "sample_recipient_ids": recipients[:20],
        }

    async def create_campaign(
        self,
        *,
        context: AdminContext,
        name: str,
        message: str,
        segment: dict[str, object],
        idempotency_key: str,
    ) -> CommandResult:
        context.require(NOTIFICATIONS_WRITE)
        clean_name = name.strip()
        clean_message = self._validate_message(message)
        if not clean_name:
            raise AdminValidationError("Campaign name is required")
        self._validate_segment(segment)

        async def operation(session: AsyncSession) -> dict[str, object]:
            campaign = NotificationCampaign(
                name=clean_name,
                message=clean_message,
                segment=segment,
                status="ready",
                created_by=context.user_id,
            )
            session.add(campaign)
            await session.flush()
            return {
                "campaign_id": str(campaign.id),
                "status": campaign.status,
                "name": campaign.name,
            }

        return await self._executor.execute(
            context=context,
            action="notification.create",
            target_id=None,
            idempotency_key=idempotency_key,
            request_payload={"name": clean_name, "message": clean_message, "segment": segment},
            operation=operation,
        )

    async def test_campaign(
        self,
        *,
        context: AdminContext,
        campaign_id: UUID,
        recipient_id: int,
        idempotency_key: str,
    ) -> CommandResult:
        context.require(NOTIFICATIONS_WRITE)

        async def operation(session: AsyncSession) -> dict[str, object]:
            campaign = await session.get(NotificationCampaign, campaign_id)
            if campaign is None:
                raise AdminNotFoundError("notification campaign", str(campaign_id))
            await session.execute(
                pg_insert(AdminOutbox)
                .values(
                    event_type="notification.test",
                    target_id=str(campaign.id),
                    deduplication_key=f"notification.test:{campaign.id}:{recipient_id}:{idempotency_key}",
                    payload={
                        "campaign_id": str(campaign.id),
                        "recipient_id": recipient_id,
                        "text": f"[TEST] {campaign.message}",
                    },
                )
                .on_conflict_do_nothing(index_elements=[AdminOutbox.deduplication_key])
            )
            return {"campaign_id": str(campaign.id), "recipient_id": recipient_id, "queued": True}

        return await self._executor.execute(
            context=context,
            action="notification.test",
            target_id=str(campaign_id),
            idempotency_key=idempotency_key,
            request_payload={"campaign_id": str(campaign_id), "recipient_id": recipient_id},
            operation=operation,
        )

    async def start_campaign(
        self,
        *,
        context: AdminContext,
        campaign_id: UUID,
        idempotency_key: str,
    ) -> CommandResult:
        context.require(NOTIFICATIONS_WRITE)

        async def operation(session: AsyncSession) -> dict[str, object]:
            campaign = await session.get(NotificationCampaign, campaign_id, with_for_update=True)
            if campaign is None:
                raise AdminNotFoundError("notification campaign", str(campaign_id))
            if campaign.status == "cancelled":
                raise AdminConflictError("Cancelled campaign cannot be started")
            recipients = await self._recipient_ids(session, campaign.segment)
            for recipient_id in recipients:
                await session.execute(
                    pg_insert(NotificationDelivery)
                    .values(campaign_id=campaign.id, recipient_id=recipient_id)
                    .on_conflict_do_nothing(
                        index_elements=[
                            NotificationDelivery.campaign_id,
                            NotificationDelivery.recipient_id,
                        ]
                    )
                )
            campaign.status = "running" if recipients else "completed"
            campaign.started_at = campaign.started_at or datetime.now(timezone.utc)
            if not recipients:
                campaign.completed_at = datetime.now(timezone.utc)
            return {
                "campaign_id": str(campaign.id),
                "status": campaign.status,
                "delivery_count": len(recipients),
            }

        return await self._executor.execute(
            context=context,
            action="notification.start",
            target_id=str(campaign_id),
            idempotency_key=idempotency_key,
            request_payload={"campaign_id": str(campaign_id)},
            operation=operation,
        )

    async def cancel_campaign(
        self,
        *,
        context: AdminContext,
        campaign_id: UUID,
        idempotency_key: str,
    ) -> CommandResult:
        context.require(NOTIFICATIONS_WRITE)

        async def operation(session: AsyncSession) -> dict[str, object]:
            campaign = await session.get(NotificationCampaign, campaign_id, with_for_update=True)
            if campaign is None:
                raise AdminNotFoundError("notification campaign", str(campaign_id))
            if campaign.status == "completed":
                raise AdminConflictError("Completed campaign cannot be cancelled")
            campaign.status = "cancelled"
            campaign.cancelled_at = datetime.now(timezone.utc)
            await session.execute(
                update(NotificationDelivery)
                .where(
                    NotificationDelivery.campaign_id == campaign.id,
                    NotificationDelivery.status.in_(("pending", "retry_wait")),
                )
                .values(status="failed", last_error="campaign_cancelled")
            )
            return {"campaign_id": str(campaign.id), "status": "cancelled"}

        return await self._executor.execute(
            context=context,
            action="notification.cancel",
            target_id=str(campaign_id),
            idempotency_key=idempotency_key,
            request_payload={"campaign_id": str(campaign_id)},
            operation=operation,
        )

    @staticmethod
    def _validate_message(message: str) -> str:
        clean = message.strip()
        if not clean:
            raise AdminValidationError("Campaign message is required")
        if len(clean) > 4096:
            raise AdminValidationError("Campaign message exceeds Telegram message limit")
        return clean

    @staticmethod
    def _validate_segment(segment: dict[str, object]) -> None:
        allowed = {"user_ids", "created_after", "created_before"}
        unknown = set(segment) - allowed
        if unknown:
            raise AdminValidationError(
                "Unsupported campaign segment keys",
                details={"unknown": sorted(unknown)},
            )
        user_ids = segment.get("user_ids")
        if user_ids is not None and (
            not isinstance(user_ids, list)
            or any(not isinstance(value, int) for value in user_ids)
            or len(user_ids) > 100_000
        ):
            raise AdminValidationError("segment.user_ids must be a list of integer Telegram IDs")
        for key in ("created_after", "created_before"):
            value = segment.get(key)
            if value is not None and not isinstance(value, str):
                raise AdminValidationError(f"segment.{key} must be an ISO datetime string")

    async def _recipient_ids(
        self,
        session: AsyncSession,
        segment: dict[str, object],
    ) -> list[int]:
        self._validate_segment(segment)
        statement = select(User.id)
        user_ids = segment.get("user_ids")
        if isinstance(user_ids, list):
            statement = statement.where(User.id.in_(tuple(int(value) for value in user_ids)))
        created_after = _parse_datetime(segment.get("created_after"), "created_after")
        created_before = _parse_datetime(segment.get("created_before"), "created_before")
        if created_after is not None:
            statement = statement.where(User.created_at >= created_after)
        if created_before is not None:
            statement = statement.where(User.created_at < created_before)
        return [int(value) for value in (await session.scalars(statement.order_by(User.id))).all()]


def _parse_datetime(value: object, name: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AdminValidationError(f"segment.{name} must be a string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AdminValidationError(f"segment.{name} must be a valid ISO datetime") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
