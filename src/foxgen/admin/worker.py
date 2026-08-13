from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import UUID

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from foxgen.domain.models import LedgerEntryType
from foxgen.infra.admin_models import (
    AdminOutbox,
    NotificationCampaign,
    NotificationDelivery,
    OperationEvent,
    PaymentEvent,
    SupportMessage,
    SupportOutbox,
)
from foxgen.infra.billing import ensure_wallet_locked
from foxgen.infra.billing_models import LedgerEntry
from foxgen.infra.database import Database, OutboxEvent, User


class AdminDeliverySender(Protocol):
    async def send_text(self, recipient_id: int, text: str) -> int: ...


@dataclass(frozen=True, slots=True)
class PaymentRecheckResult:
    status: str
    raw_payload: dict[str, object]


class PaymentRecheckAdapter(Protocol):
    async def recheck(self, payment: PaymentEvent) -> PaymentRecheckResult: ...


class RetriableAdminJobError(Exception):
    def __init__(self, message: str, *, delay_seconds: float | None = None) -> None:
        super().__init__(message)
        self.delay_seconds = delay_seconds


class PermanentAdminJobError(Exception):
    pass


class AmbiguousAdminDeliveryError(PermanentAdminJobError):
    pass


class UnavailablePaymentRecheckAdapter:
    async def recheck(self, payment: PaymentEvent) -> PaymentRecheckResult:
        raise RetriableAdminJobError(
            f"No payment recheck adapter is registered for provider {payment.provider}"
        )


class TelegramAdminDeliverySender:
    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def send_text(self, recipient_id: int, text: str) -> int:
        try:
            message = await self._bot.send_message(recipient_id, text)
        except TelegramRetryAfter as exc:
            raise RetriableAdminJobError(
                "Telegram rate limit",
                delay_seconds=float(exc.retry_after),
            ) from exc
        except TelegramNetworkError as exc:
            # Transport ambiguity is deliberately not auto-retried: Telegram may have
            # accepted the message before the network response was lost.
            raise AmbiguousAdminDeliveryError("Telegram delivery outcome is unknown") from exc
        except TelegramBadRequest as exc:
            raise PermanentAdminJobError(f"Telegram rejected delivery: {exc}") from exc
        return message.message_id


class AdminWorker:
    def __init__(
        self,
        *,
        database: Database,
        sender: AdminDeliverySender,
        payment_recheck_adapter: PaymentRecheckAdapter | None = None,
        worker_id: str,
        batch_size: int = 50,
        lease_seconds: int = 120,
        max_attempts: int = 8,
        notification_rate_per_second: float = 20.0,
    ) -> None:
        self._database = database
        self._sender = sender
        self._payment_recheck_adapter = payment_recheck_adapter or UnavailablePaymentRecheckAdapter()
        self._worker_id = worker_id
        self._batch_size = batch_size
        self._lease_seconds = lease_seconds
        self._max_attempts = max_attempts
        self._notification_delay = 1.0 / notification_rate_per_second

    async def run_once(self) -> int:
        processed = 0
        support = await self._claim_support()
        for event_id in support:
            await self._process_support(event_id)
            processed += 1

        notifications = await self._claim_notifications()
        for delivery_id in notifications:
            await self._process_notification(delivery_id)
            processed += 1

        jobs = await self._claim_admin_outbox()
        for event_id in jobs:
            await self._process_admin_outbox(event_id)
            processed += 1
        return processed

    async def _claim_support(self) -> tuple[UUID, ...]:
        now = datetime.now(timezone.utc)
        stale_before = now - timedelta(seconds=self._lease_seconds)
        async with self._database.session() as session:
            async with session.begin():
                rows = tuple(
                    (
                        await session.scalars(
                            select(SupportOutbox)
                            .where(
                                or_(
                                    (
                                        SupportOutbox.status.in_(("pending", "retry_wait"))
                                        & (SupportOutbox.available_at <= now)
                                    ),
                                    (
                                        (SupportOutbox.status == "processing")
                                        & (SupportOutbox.locked_at <= stale_before)
                                    ),
                                )
                            )
                            .order_by(SupportOutbox.available_at, SupportOutbox.created_at)
                            .with_for_update(skip_locked=True)
                            .limit(self._batch_size)
                        )
                    ).all()
                )
                for item in rows:
                    item.status = "processing"
                    item.locked_at = now
                    item.attempts += 1
                return tuple(item.id for item in rows)

    async def _claim_notifications(self) -> tuple[UUID, ...]:
        now = datetime.now(timezone.utc)
        stale_before = now - timedelta(seconds=self._lease_seconds)
        async with self._database.session() as session:
            async with session.begin():
                rows = tuple(
                    (
                        await session.scalars(
                            select(NotificationDelivery)
                            .join(
                                NotificationCampaign,
                                NotificationCampaign.id == NotificationDelivery.campaign_id,
                            )
                            .where(
                                NotificationCampaign.status == "running",
                                or_(
                                    (
                                        NotificationDelivery.status.in_(("pending", "retry_wait"))
                                        & (NotificationDelivery.available_at <= now)
                                    ),
                                    (
                                        (NotificationDelivery.status == "processing")
                                        & (NotificationDelivery.locked_at <= stale_before)
                                    ),
                                ),
                            )
                            .order_by(
                                NotificationDelivery.available_at,
                                NotificationDelivery.created_at,
                            )
                            .with_for_update(skip_locked=True)
                            .limit(self._batch_size)
                        )
                    ).all()
                )
                for item in rows:
                    item.status = "processing"
                    item.locked_at = now
                    item.attempts += 1
                return tuple(item.id for item in rows)

    async def _claim_admin_outbox(self) -> tuple[UUID, ...]:
        now = datetime.now(timezone.utc)
        stale_before = now - timedelta(seconds=self._lease_seconds)
        async with self._database.session() as session:
            async with session.begin():
                rows = tuple(
                    (
                        await session.scalars(
                            select(AdminOutbox)
                            .where(
                                or_(
                                    (
                                        AdminOutbox.status.in_(("pending", "retry_wait"))
                                        & (AdminOutbox.available_at <= now)
                                    ),
                                    (
                                        (AdminOutbox.status == "processing")
                                        & (AdminOutbox.locked_at <= stale_before)
                                    ),
                                )
                            )
                            .order_by(AdminOutbox.available_at, AdminOutbox.created_at)
                            .with_for_update(skip_locked=True)
                            .limit(self._batch_size)
                        )
                    ).all()
                )
                for item in rows:
                    item.status = "processing"
                    item.locked_at = now
                    item.attempts += 1
                return tuple(item.id for item in rows)

    async def _process_support(self, event_id: UUID) -> None:
        async with self._database.session() as session:
            event = await session.get(SupportOutbox, event_id)
            if event is None or event.status != "processing":
                return
            message = await session.get(SupportMessage, event.message_id)
            if message is None:
                await self._fail_support(event_id, PermanentAdminJobError("Support message is missing"))
                return
            recipient_id = event.recipient_id
            text = str(event.payload.get("text") or message.body)

        try:
            message_id = await self._sender.send_text(recipient_id, text)
        except Exception as exc:
            await self._fail_support(event_id, exc)
            return

        async with self._database.session() as session:
            async with session.begin():
                event = await session.get(SupportOutbox, event_id, with_for_update=True)
                if event is None or event.status != "processing":
                    return
                event.status = "sent"
                event.locked_at = None
                event.last_error = None
                message = await session.get(SupportMessage, event.message_id)
                if message is not None:
                    message.status = "sent"
                    # Store only the non-secret transport receipt in the outbox payload.
                    event.payload = {**event.payload, "telegram_message_id": message_id}

    async def _process_notification(self, delivery_id: UUID) -> None:
        async with self._database.session() as session:
            delivery = await session.get(NotificationDelivery, delivery_id)
            if delivery is None or delivery.status != "processing":
                return
            campaign = await session.get(NotificationCampaign, delivery.campaign_id)
            if campaign is None or campaign.status != "running":
                await self._fail_notification(
                    delivery_id,
                    PermanentAdminJobError("Campaign is not running"),
                )
                return
            recipient_id = delivery.recipient_id
            text = campaign.message
            campaign_id = campaign.id

        try:
            message_id = await self._sender.send_text(recipient_id, text)
        except Exception as exc:
            await self._fail_notification(delivery_id, exc)
            await self._refresh_campaign(campaign_id)
            return

        async with self._database.session() as session:
            async with session.begin():
                delivery = await session.get(NotificationDelivery, delivery_id, with_for_update=True)
                if delivery is None or delivery.status != "processing":
                    return
                delivery.status = "sent"
                delivery.telegram_message_id = message_id
                delivery.sent_at = func.now()
                delivery.locked_at = None
                delivery.last_error = None
        await self._refresh_campaign(campaign_id)

    async def _process_admin_outbox(self, event_id: UUID) -> None:
        async with self._database.session() as session:
            event = await session.get(AdminOutbox, event_id)
            if event is None or event.status != "processing":
                return
            event_type = event.event_type
            payload = dict(event.payload)

        try:
            if event_type == "notification.test":
                await self._process_test_notification(event_id, payload)
                return
            if event_type == "payment.recheck":
                await self._process_payment_recheck(event_id, payload)
                return
            if event_type == "payment.reprocess":
                await self._process_payment_reprocess(event_id, payload)
                return
            if event_type == "operation.replay":
                await self._process_operation_replay(event_id, payload)
                return
            raise PermanentAdminJobError(f"Unsupported admin outbox event: {event_type}")
        except Exception as exc:
            await self._fail_admin_outbox(event_id, exc)

    async def _process_test_notification(
        self,
        event_id: UUID,
        payload: dict[str, object],
    ) -> None:
        recipient_id = payload.get("recipient_id")
        text = payload.get("text")
        if not isinstance(recipient_id, int) or not isinstance(text, str):
            raise PermanentAdminJobError("Malformed notification test payload")
        message_id = await self._sender.send_text(recipient_id, text)
        await self._complete_admin_outbox(
            event_id,
            receipt={"telegram_message_id": message_id},
        )

    async def _process_payment_recheck(
        self,
        event_id: UUID,
        payload: dict[str, object],
    ) -> None:
        payment_id = _payload_uuid(payload, "payment_id")
        async with self._database.session() as session:
            payment = await session.get(PaymentEvent, payment_id)
            if payment is None:
                raise PermanentAdminJobError("Payment no longer exists")
            detached = PaymentEvent(
                id=payment.id,
                provider=payment.provider,
                external_id=payment.external_id,
                user_id=payment.user_id,
                status=payment.status,
                amount_units=payment.amount_units,
                currency=payment.currency,
                credited_ledger_key=payment.credited_ledger_key,
                raw_payload=dict(payment.raw_payload),
            )
        result = await self._payment_recheck_adapter.recheck(detached)
        async with self._database.session() as session:
            async with session.begin():
                event = await session.get(AdminOutbox, event_id, with_for_update=True)
                payment = await session.get(PaymentEvent, payment_id, with_for_update=True)
                if event is None or event.status != "processing" or payment is None:
                    return
                payment.status = result.status
                payment.raw_payload = result.raw_payload
                payment.last_checked_at = func.now()
                event.status = "completed"
                event.locked_at = None
                event.last_error = None
                event.payload = {**event.payload, "rechecked_status": result.status}

    async def _process_payment_reprocess(
        self,
        event_id: UUID,
        payload: dict[str, object],
    ) -> None:
        payment_id = _payload_uuid(payload, "payment_id")
        async with self._database.session() as session:
            async with session.begin():
                event = await session.get(AdminOutbox, event_id, with_for_update=True)
                payment = await session.get(PaymentEvent, payment_id, with_for_update=True)
                if event is None or event.status != "processing":
                    return
                if payment is None:
                    raise PermanentAdminJobError("Payment no longer exists")
                if payment.status not in {"completed", "paid", "succeeded"}:
                    raise PermanentAdminJobError(
                        f"Payment status {payment.status} is not creditable"
                    )
                ledger_key = payment.credited_ledger_key or (
                    f"payment-credit:{payment.provider}:{payment.external_id}"
                )
                existing = await session.scalar(
                    select(LedgerEntry).where(LedgerEntry.idempotency_key == ledger_key)
                )
                if existing is None:
                    await session.execute(
                        pg_insert(User)
                        .values(id=payment.user_id, username=None)
                        .on_conflict_do_nothing(index_elements=[User.id])
                    )
                    account = await ensure_wallet_locked(
                        session,
                        user_id=payment.user_id,
                        currency=payment.currency,
                    )
                    account.available_units += payment.amount_units
                    account.version += 1
                    session.add(
                        LedgerEntry(
                            user_id=payment.user_id,
                            generation_id=None,
                            reservation_id=None,
                            entry_type=LedgerEntryType.CREDIT,
                            currency=payment.currency,
                            available_delta=payment.amount_units,
                            reserved_delta=0,
                            idempotency_key=ledger_key,
                            actor="system:admin-payment-worker",
                            reason=(
                                f"Credit completed payment {payment.provider}/"
                                f"{payment.external_id}"
                            ),
                            metadata_json={"payment_id": str(payment.id)},
                        )
                    )
                payment.credited_ledger_key = ledger_key
                payment.processed_at = payment.processed_at or datetime.now(timezone.utc)
                event.status = "completed"
                event.locked_at = None
                event.last_error = None
                event.payload = {
                    **event.payload,
                    "credited_ledger_key": ledger_key,
                    "already_credited": existing is not None,
                }

    async def _process_operation_replay(
        self,
        event_id: UUID,
        payload: dict[str, object],
    ) -> None:
        operation_id = _payload_uuid(payload, "operation_id")
        async with self._database.session() as session:
            async with session.begin():
                event = await session.get(AdminOutbox, event_id, with_for_update=True)
                operation = await session.get(OperationEvent, operation_id, with_for_update=True)
                if event is None or event.status != "processing":
                    return
                if operation is None:
                    raise PermanentAdminJobError("Replay operation no longer exists")
                source_payload = operation.payload.get("source_payload")
                if not isinstance(source_payload, dict):
                    raise PermanentAdminJobError("Source operation has no replayable payload")
                event_type = source_payload.get("event_type")
                aggregate_id = source_payload.get("aggregate_id")
                safe_types = {"generation.archive", "generation.deliver"}
                if event_type not in safe_types or not isinstance(aggregate_id, str):
                    raise PermanentAdminJobError(
                        "Only non-billable archive/delivery operations can be replayed"
                    )
                try:
                    aggregate_uuid = UUID(aggregate_id)
                except ValueError as exc:
                    raise PermanentAdminJobError("Replay aggregate_id is invalid") from exc
                await session.execute(
                    pg_insert(OutboxEvent)
                    .values(
                        event_type=event_type,
                        aggregate_id=aggregate_uuid,
                        deduplication_key=f"admin-replay:{operation.id}:{event_type}",
                        payload={
                            "generation_id": aggregate_id,
                            "admin_replay_operation_id": str(operation.id),
                        },
                    )
                    .on_conflict_do_nothing(index_elements=[OutboxEvent.deduplication_key])
                )
                operation.status = "completed"
                operation.payload = {
                    **operation.payload,
                    "replayed_event_type": event_type,
                    "replayed_aggregate_id": aggregate_id,
                }
                event.status = "completed"
                event.locked_at = None
                event.last_error = None

    async def _complete_admin_outbox(
        self,
        event_id: UUID,
        *,
        receipt: dict[str, object],
    ) -> None:
        async with self._database.session() as session:
            async with session.begin():
                event = await session.get(AdminOutbox, event_id, with_for_update=True)
                if event is None or event.status != "processing":
                    return
                event.status = "completed"
                event.locked_at = None
                event.last_error = None
                event.payload = {**event.payload, **receipt}

    async def _fail_support(self, event_id: UUID, exc: Exception) -> None:
        async with self._database.session() as session:
            async with session.begin():
                event = await session.get(SupportOutbox, event_id, with_for_update=True)
                if event is None or event.status != "processing":
                    return
                ambiguous = isinstance(exc, AmbiguousAdminDeliveryError)
                permanent = isinstance(exc, PermanentAdminJobError)
                if ambiguous or permanent or event.attempts >= self._max_attempts:
                    event.status = "dead_letter"
                else:
                    event.status = "retry_wait"
                    event.available_at = datetime.now(timezone.utc) + _retry_delay(
                        event.attempts,
                        exc,
                    )
                event.locked_at = None
                event.last_error = _error_text(exc, ambiguous=ambiguous)
                message = await session.get(SupportMessage, event.message_id)
                if message is not None:
                    message.status = "delivery_unknown" if ambiguous else event.status

    async def _fail_notification(self, delivery_id: UUID, exc: Exception) -> None:
        async with self._database.session() as session:
            async with session.begin():
                delivery = await session.get(NotificationDelivery, delivery_id, with_for_update=True)
                if delivery is None or delivery.status != "processing":
                    return
                ambiguous = isinstance(exc, AmbiguousAdminDeliveryError)
                permanent = isinstance(exc, PermanentAdminJobError)
                if ambiguous or permanent or delivery.attempts >= self._max_attempts:
                    delivery.status = "failed"
                else:
                    delivery.status = "retry_wait"
                    delivery.available_at = datetime.now(timezone.utc) + _retry_delay(
                        delivery.attempts,
                        exc,
                    )
                delivery.locked_at = None
                delivery.last_error = _error_text(exc, ambiguous=ambiguous)

    async def _fail_admin_outbox(self, event_id: UUID, exc: Exception) -> None:
        async with self._database.session() as session:
            async with session.begin():
                event = await session.get(AdminOutbox, event_id, with_for_update=True)
                if event is None or event.status != "processing":
                    return
                permanent = isinstance(exc, PermanentAdminJobError)
                if permanent or event.attempts >= self._max_attempts:
                    event.status = "dead_letter"
                else:
                    event.status = "retry_wait"
                    event.available_at = datetime.now(timezone.utc) + _retry_delay(
                        event.attempts,
                        exc,
                    )
                event.locked_at = None
                event.last_error = _error_text(exc)
                if event.event_type == "operation.replay":
                    raw_operation_id = event.payload.get("operation_id")
                    if isinstance(raw_operation_id, str):
                        try:
                            operation = await session.get(OperationEvent, UUID(raw_operation_id))
                        except ValueError:
                            operation = None
                        if operation is not None and event.status == "dead_letter":
                            operation.status = "failed"
                            operation.payload = {
                                **operation.payload,
                                "replay_error": event.last_error,
                            }

    async def _refresh_campaign(self, campaign_id: UUID) -> None:
        async with self._database.session() as session:
            async with session.begin():
                campaign = await session.get(NotificationCampaign, campaign_id, with_for_update=True)
                if campaign is None or campaign.status != "running":
                    return
                remaining = int(
                    await session.scalar(
                        select(func.count(NotificationDelivery.id)).where(
                            NotificationDelivery.campaign_id == campaign.id,
                            NotificationDelivery.status.in_(("pending", "processing", "retry_wait")),
                        )
                    )
                    or 0
                )
                if remaining == 0:
                    campaign.status = "completed"
                    campaign.completed_at = func.now()


def _retry_delay(attempts: int, exc: Exception) -> timedelta:
    if isinstance(exc, RetriableAdminJobError) and exc.delay_seconds is not None:
        seconds = max(1.0, min(exc.delay_seconds, 3600.0))
        return timedelta(seconds=seconds)
    seconds = min(600, max(2, 2 ** min(attempts, 9)))
    return timedelta(seconds=seconds)


def _error_text(exc: Exception, *, ambiguous: bool = False) -> str:
    prefix = "delivery_unknown: " if ambiguous else ""
    return f"{prefix}{type(exc).__name__}: {exc}"[:4000]


def _payload_uuid(payload: dict[str, object], key: str) -> UUID:
    raw = payload.get(key)
    if not isinstance(raw, str):
        raise PermanentAdminJobError(f"Missing {key}")
    try:
        return UUID(raw)
    except ValueError as exc:
        raise PermanentAdminJobError(f"Invalid {key}") from exc
