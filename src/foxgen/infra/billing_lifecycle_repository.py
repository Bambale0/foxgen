from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from foxgen.application.lifecycle import GenerationWorkItem
from foxgen.application.reconciliation import ReconciliationFinding
from foxgen.core.errors import ErrorCode, SubmissionError
from foxgen.domain.models import (
    DeliveryStatus,
    GenerationStatus,
    MediaAssetStatus,
    OutboxStatus,
    ReservationStatus,
)
from foxgen.infra.billing import settle_generation_charge
from foxgen.infra.billing_models import BalanceReservation
from foxgen.infra.database import (
    Database,
    Generation,
    GenerationDelivery,
    MediaAsset,
    OutboxEvent,
)
from foxgen.infra.lifecycle_repository import (
    SqlAlchemyLifecycleRepository,
    _generation_item,
    generation_transition_values,
    validate_transition_set,
)


_ACCEPTED_OR_LATER: tuple[str, ...] = (
    GenerationStatus.SUBMITTED.value,
    GenerationStatus.PROCESSING.value,
    GenerationStatus.RESULT_READY.value,
    GenerationStatus.STORING_MEDIA.value,
    GenerationStatus.DELIVERY_PENDING.value,
    GenerationStatus.SUCCEEDED.value,
)
_TERMINAL_FAILURES: tuple[str, ...] = (
    GenerationStatus.FAILED.value,
    GenerationStatus.CANCELLED.value,
)


class BillingAwareLifecycleRepository(SqlAlchemyLifecycleRepository):
    """Lifecycle repository that settles money in the same transaction as state changes."""

    def __init__(self, database: Database) -> None:
        super().__init__(database)
        self._billing_database = database

    async def transition_generation(
        self,
        *,
        generation_id: UUID,
        expected: frozenset[GenerationStatus],
        target: GenerationStatus,
        provider_task_id: str | None = None,
        result_payload: dict[str, object] | None = None,
        error_code: str | None = None,
        failure_stage: str | None = None,
        status_reason: str | None = None,
    ) -> GenerationWorkItem:
        validate_transition_set(expected, target)
        values = generation_transition_values(
            target=target,
            provider_task_id=provider_task_id,
            result_payload=result_payload,
            error_code=error_code,
            failure_stage=failure_stage,
            status_reason=status_reason,
        )

        async with self._billing_database.session() as session:
            async with session.begin():
                changed = await session.scalar(
                    update(Generation)
                    .where(
                        Generation.id == generation_id,
                        Generation.status.in_(tuple(status.value for status in expected)),
                    )
                    .values(**values)
                    .returning(Generation)
                )
                generation = changed
                if generation is None:
                    generation = await session.get(Generation, generation_id)
                if generation is None:
                    raise SubmissionError(
                        ErrorCode.TASK_NOT_FOUND,
                        "Локальная задача генерации не найдена.",
                    )

                if changed is not None:
                    await settle_generation_charge(
                        session,
                        generation_id=generation.id,
                        target=target,
                    )
                    if target == GenerationStatus.RESULT_READY:
                        await session.execute(
                            pg_insert(OutboxEvent)
                            .values(
                                event_type="generation.archive",
                                aggregate_id=generation.id,
                                deduplication_key=f"generation.archive:{generation.id}",
                                payload={"generation_id": str(generation.id)},
                            )
                            .on_conflict_do_nothing(
                                index_elements=[OutboxEvent.deduplication_key]
                            )
                        )
                return _generation_item(generation)

    async def _on_outbox_dead_letter(
        self,
        session: AsyncSession,
        *,
        event: OutboxEvent,
        error: str,
        failure_class: str,
    ) -> None:
        stage_by_event = {
            "generation.submit": "submission",
            "generation.archive": "storage",
            "generation.deliver": "delivery",
        }
        stage = stage_by_event.get(event.event_type)
        if stage is None:
            return

        generation = await session.scalar(
            select(Generation)
            .where(Generation.id == event.aggregate_id)
            .with_for_update()
        )
        if generation is None:
            return
        current = GenerationStatus(generation.status)
        allowed = {
            "generation.submit": {GenerationStatus.QUEUED},
            "generation.archive": {
                GenerationStatus.RESULT_READY,
                GenerationStatus.STORING_MEDIA,
            },
            "generation.deliver": {GenerationStatus.DELIVERY_PENDING},
        }[event.event_type]
        if current not in allowed:
            return

        validate_transition_set(frozenset({current}), GenerationStatus.FAILED)
        await session.execute(
            update(Generation)
            .where(
                Generation.id == generation.id,
                Generation.status == current.value,
            )
            .values(
                **generation_transition_values(
                    target=GenerationStatus.FAILED,
                    error_code=failure_class[:64],
                    failure_stage=stage,
                    status_reason=f"outbox_dead_letter:{event.event_type}"[:128],
                )
            )
        )
        if event.event_type == "generation.deliver":
            await session.execute(
                update(GenerationDelivery)
                .where(GenerationDelivery.generation_id == generation.id)
                .values(
                    status=DeliveryStatus.FAILED.value,
                    next_retry_at=None,
                    last_error=error[:10_000],
                    updated_at=func.now(),
                )
            )
        await settle_generation_charge(
            session,
            generation_id=generation.id,
            target=GenerationStatus.FAILED,
        )

    async def get_owned_generation(
        self,
        *,
        generation_id: UUID,
        user_id: int,
    ) -> GenerationWorkItem:
        async with self._billing_database.session() as session:
            generation = await session.scalar(
                select(Generation).where(
                    Generation.id == generation_id,
                    Generation.user_id == user_id,
                )
            )
            if generation is None:
                raise SubmissionError(
                    ErrorCode.TASK_NOT_FOUND,
                    "Генерация не найдена.",
                )
            return _generation_item(generation)

    async def cancel_before_submission(
        self,
        *,
        generation_id: UUID,
        user_id: int,
    ) -> GenerationWorkItem:
        async with self._billing_database.session() as session:
            async with session.begin():
                generation = await session.scalar(
                    select(Generation)
                    .where(
                        Generation.id == generation_id,
                        Generation.user_id == user_id,
                    )
                    .with_for_update()
                )
                if generation is None:
                    raise SubmissionError(
                        ErrorCode.TASK_NOT_FOUND,
                        "Генерация не найдена.",
                    )
                current = GenerationStatus(generation.status)
                if current == GenerationStatus.CANCELLED:
                    return _generation_item(generation)
                if current not in {GenerationStatus.DRAFT, GenerationStatus.QUEUED}:
                    raise SubmissionError(
                        ErrorCode.IDEMPOTENCY_CONFLICT,
                        "Отмена возможна только до начала отправки задачи провайдеру.",
                        details={"status": current.value},
                    )

                validate_transition_set(frozenset({current}), GenerationStatus.CANCELLED)
                await session.execute(
                    update(Generation)
                    .where(
                        Generation.id == generation.id,
                        Generation.status == current.value,
                    )
                    .values(
                        **generation_transition_values(
                            target=GenerationStatus.CANCELLED,
                            status_reason="cancelled_by_user_before_submission",
                        )
                    )
                )
                await settle_generation_charge(
                    session,
                    generation_id=generation.id,
                    target=GenerationStatus.CANCELLED,
                )
                await session.execute(
                    update(OutboxEvent)
                    .where(
                        OutboxEvent.aggregate_id == generation.id,
                        OutboxEvent.event_type == "generation.submit",
                        OutboxEvent.status.in_(
                            (
                                OutboxStatus.PENDING.value,
                                OutboxStatus.RETRY_WAIT.value,
                                OutboxStatus.PROCESSING.value,
                            )
                        ),
                    )
                    .values(
                        status=OutboxStatus.COMPLETED.value,
                        locked_at=None,
                        worker_id=None,
                        last_error=None,
                        failure_class=None,
                        dead_lettered_at=None,
                        updated_at=func.now(),
                    )
                )
                await session.refresh(generation)
                return _generation_item(generation)

    async def list_stuck_generations(
        self,
        *,
        statuses: frozenset[GenerationStatus],
        older_than: datetime,
        limit: int,
    ) -> tuple[GenerationWorkItem, ...]:
        if not statuses:
            return ()
        async with self._billing_database.session() as session:
            generations = tuple(
                (
                    await session.scalars(
                        select(Generation)
                        .where(
                            Generation.status.in_(tuple(status.value for status in statuses)),
                            Generation.status_changed_at < older_than,
                        )
                        .order_by(Generation.status_changed_at, Generation.id)
                        .limit(limit)
                    )
                ).all()
            )
            return tuple(_generation_item(generation) for generation in generations)

    async def resolve_delivery_unknown_sent(
        self,
        *,
        generation_id: UUID,
        message_ids: list[int],
        reason: str,
    ) -> None:
        async with self._billing_database.session() as session:
            async with session.begin():
                generation, delivery = await self._lock_unknown_delivery(
                    session,
                    generation_id=generation_id,
                )
                delivery.status = DeliveryStatus.SENT
                delivery.telegram_message_ids = message_ids
                delivery.sent_at = func.now()
                delivery.next_retry_at = None
                delivery.last_error = None
                await session.execute(
                    update(Generation)
                    .where(
                        Generation.id == generation.id,
                        Generation.status == GenerationStatus.DELIVERY_PENDING.value,
                    )
                    .values(
                        **generation_transition_values(
                            target=GenerationStatus.SUCCEEDED,
                            status_reason=f"operator_marked_sent:{reason}"[:128],
                        )
                    )
                )

    async def requeue_delivery_unknown(
        self,
        *,
        generation_id: UUID,
        idempotency_key: str,
        reason: str,
    ) -> None:
        async with self._billing_database.session() as session:
            async with session.begin():
                _, delivery = await self._lock_unknown_delivery(
                    session,
                    generation_id=generation_id,
                )
                delivery.status = DeliveryStatus.PENDING
                delivery.next_retry_at = None
                delivery.last_error = f"Operator retry approved: {reason}"[:10_000]
                await session.execute(
                    pg_insert(OutboxEvent)
                    .values(
                        event_type="generation.deliver",
                        aggregate_id=generation_id,
                        deduplication_key=(
                            f"generation.deliver.manual:{generation_id}:{idempotency_key}"
                        )[:255],
                        payload={
                            "generation_id": str(generation_id),
                            "operator_reason": reason,
                        },
                    )
                    .on_conflict_do_nothing(
                        index_elements=[OutboxEvent.deduplication_key]
                    )
                )

    async def fail_delivery_unknown(
        self,
        *,
        generation_id: UUID,
        reason: str,
    ) -> None:
        async with self._billing_database.session() as session:
            async with session.begin():
                generation, delivery = await self._lock_unknown_delivery(
                    session,
                    generation_id=generation_id,
                )
                delivery.status = DeliveryStatus.FAILED
                delivery.next_retry_at = None
                delivery.last_error = reason[:10_000]
                await session.execute(
                    update(Generation)
                    .where(
                        Generation.id == generation.id,
                        Generation.status == GenerationStatus.DELIVERY_PENDING.value,
                    )
                    .values(
                        **generation_transition_values(
                            target=GenerationStatus.FAILED,
                            error_code="delivery_operator_failed",
                            failure_stage="delivery",
                            status_reason=f"operator_delivery_failed:{reason}"[:128],
                        )
                    )
                )
                await settle_generation_charge(
                    session,
                    generation_id=generation.id,
                    target=GenerationStatus.FAILED,
                )

    async def _lock_unknown_delivery(
        self,
        session: AsyncSession,
        *,
        generation_id: UUID,
    ) -> tuple[Generation, GenerationDelivery]:
        generation = await session.scalar(
            select(Generation)
            .where(Generation.id == generation_id)
            .with_for_update()
        )
        delivery = await session.scalar(
            select(GenerationDelivery)
            .where(GenerationDelivery.generation_id == generation_id)
            .with_for_update()
        )
        if generation is None or delivery is None:
            raise SubmissionError(ErrorCode.TASK_NOT_FOUND, "Доставка не найдена.")
        if (
            GenerationStatus(generation.status) != GenerationStatus.DELIVERY_PENDING
            or DeliveryStatus(delivery.status) != DeliveryStatus.DELIVERY_UNKNOWN
        ):
            raise SubmissionError(
                ErrorCode.IDEMPOTENCY_CONFLICT,
                "Операторское решение доступно только для delivery_unknown.",
                details={
                    "generation_status": str(generation.status),
                    "delivery_status": str(delivery.status),
                },
            )
        return generation, delivery

    async def list_reconciliation_findings(
        self,
        *,
        limit: int,
    ) -> tuple[ReconciliationFinding, ...]:
        findings: list[ReconciliationFinding] = []

        def append(finding: ReconciliationFinding) -> bool:
            findings.append(finding)
            return len(findings) >= limit

        async with self._billing_database.session() as session:
            dead_letters = tuple(
                (
                    await session.scalars(
                        select(OutboxEvent)
                        .where(OutboxEvent.status == OutboxStatus.DEAD_LETTER.value)
                        .order_by(OutboxEvent.dead_lettered_at, OutboxEvent.id)
                        .limit(limit)
                    )
                ).all()
            )
            for event in dead_letters:
                if append(
                    ReconciliationFinding(
                        code="outbox_dead_letter",
                        severity="error",
                        generation_id=(
                            event.aggregate_id
                            if event.event_type.startswith("generation.")
                            else None
                        ),
                        resource_id=event.id,
                        status=str(event.status),
                        details={
                            "event_type": event.event_type,
                            "attempts": event.attempts,
                            "failure_class": event.failure_class or "unknown",
                        },
                    )
                ):
                    return tuple(findings)

            media_rows = tuple(
                (
                    await session.scalars(
                        select(MediaAsset)
                        .where(
                            MediaAsset.status.in_(
                                (
                                    MediaAssetStatus.RETRY_WAIT.value,
                                    MediaAssetStatus.FAILED.value,
                                )
                            )
                        )
                        .order_by(MediaAsset.updated_at, MediaAsset.id)
                        .limit(limit - len(findings))
                    )
                ).all()
            )
            for asset in media_rows:
                if append(
                    ReconciliationFinding(
                        code="media_storage_recovery",
                        severity=(
                            "warning"
                            if MediaAssetStatus(asset.status) == MediaAssetStatus.RETRY_WAIT
                            else "error"
                        ),
                        generation_id=asset.generation_id,
                        resource_id=asset.id,
                        status=str(asset.status),
                        details={
                            "attempts": asset.attempts,
                            "error_code": asset.error_code or "unknown",
                        },
                    )
                ):
                    return tuple(findings)

            delivery_rows = tuple(
                (
                    await session.scalars(
                        select(GenerationDelivery)
                        .where(
                            GenerationDelivery.status.in_(
                                (
                                    DeliveryStatus.RETRY_WAIT.value,
                                    DeliveryStatus.DELIVERY_UNKNOWN.value,
                                    DeliveryStatus.FAILED.value,
                                )
                            )
                        )
                        .order_by(GenerationDelivery.updated_at, GenerationDelivery.id)
                        .limit(limit - len(findings))
                    )
                ).all()
            )
            for delivery in delivery_rows:
                if append(
                    ReconciliationFinding(
                        code=(
                            "delivery_unknown"
                            if DeliveryStatus(delivery.status)
                            == DeliveryStatus.DELIVERY_UNKNOWN
                            else "delivery_recovery"
                        ),
                        severity=(
                            "critical"
                            if DeliveryStatus(delivery.status)
                            == DeliveryStatus.DELIVERY_UNKNOWN
                            else "warning"
                        ),
                        generation_id=delivery.generation_id,
                        resource_id=delivery.id,
                        status=str(delivery.status),
                        details={"attempts": delivery.attempts},
                    )
                ):
                    return tuple(findings)

            missing_deliveries = tuple(
                (
                    await session.scalars(
                        select(Generation)
                        .outerjoin(
                            GenerationDelivery,
                            GenerationDelivery.generation_id == Generation.id,
                        )
                        .where(
                            Generation.status == GenerationStatus.DELIVERY_PENDING.value,
                            GenerationDelivery.id.is_(None),
                        )
                        .limit(limit - len(findings))
                    )
                ).all()
            )
            for generation in missing_deliveries:
                if append(
                    ReconciliationFinding(
                        code="delivery_missing",
                        severity="error",
                        generation_id=generation.id,
                        resource_id=None,
                        status=str(generation.status),
                        details={},
                    )
                ):
                    return tuple(findings)

            succeeded_rows = tuple(
                (
                    await session.execute(
                        select(Generation, GenerationDelivery)
                        .outerjoin(
                            GenerationDelivery,
                            GenerationDelivery.generation_id == Generation.id,
                        )
                        .where(
                            Generation.status == GenerationStatus.SUCCEEDED.value,
                            or_(
                                GenerationDelivery.id.is_(None),
                                GenerationDelivery.status != DeliveryStatus.SENT.value,
                            ),
                        )
                        .limit(limit - len(findings))
                    )
                ).all()
            )
            for generation, delivery in succeeded_rows:
                if append(
                    ReconciliationFinding(
                        code="succeeded_without_sent_delivery",
                        severity="critical",
                        generation_id=generation.id,
                        resource_id=(delivery.id if delivery is not None else None),
                        status=(str(delivery.status) if delivery is not None else None),
                        details={},
                    )
                ):
                    return tuple(findings)

            sent_rows = tuple(
                (
                    await session.execute(
                        select(GenerationDelivery, Generation)
                        .join(Generation, Generation.id == GenerationDelivery.generation_id)
                        .where(
                            GenerationDelivery.status == DeliveryStatus.SENT.value,
                            Generation.status != GenerationStatus.SUCCEEDED.value,
                        )
                        .limit(limit - len(findings))
                    )
                ).all()
            )
            for delivery, generation in sent_rows:
                if append(
                    ReconciliationFinding(
                        code="sent_delivery_generation_not_succeeded",
                        severity="error",
                        generation_id=generation.id,
                        resource_id=delivery.id,
                        status=str(generation.status),
                        details={},
                    )
                ):
                    return tuple(findings)

            reservation_rows = tuple(
                (
                    await session.execute(
                        select(BalanceReservation, Generation)
                        .join(Generation, Generation.id == BalanceReservation.generation_id)
                        .where(
                            or_(
                                and_(
                                    BalanceReservation.status
                                    == ReservationStatus.RESERVED.value,
                                    Generation.status.in_(
                                        _ACCEPTED_OR_LATER + _TERMINAL_FAILURES
                                    ),
                                ),
                                and_(
                                    BalanceReservation.status
                                    == ReservationStatus.CAPTURED.value,
                                    Generation.status.in_(_TERMINAL_FAILURES),
                                ),
                            )
                        )
                        .limit(limit - len(findings))
                    )
                ).all()
            )
            for reservation, generation in reservation_rows:
                append(
                    ReconciliationFinding(
                        code="reservation_generation_mismatch",
                        severity="critical",
                        generation_id=generation.id,
                        resource_id=reservation.id,
                        status=str(reservation.status),
                        details={"generation_status": str(generation.status)},
                    )
                )

        return tuple(findings)

    async def apply_safe_reconciliation(
        self,
        *,
        limit: int,
    ) -> tuple[str, ...]:
        fixed: list[str] = []
        async with self._billing_database.session() as session:
            async with session.begin():
                reservation_rows = tuple(
                    (
                        await session.execute(
                            select(BalanceReservation, Generation)
                            .join(Generation, Generation.id == BalanceReservation.generation_id)
                            .where(
                                or_(
                                    and_(
                                        BalanceReservation.status
                                        == ReservationStatus.RESERVED.value,
                                        Generation.status.in_(
                                            _ACCEPTED_OR_LATER + _TERMINAL_FAILURES
                                        ),
                                    ),
                                    and_(
                                        BalanceReservation.status
                                        == ReservationStatus.CAPTURED.value,
                                        Generation.status.in_(_TERMINAL_FAILURES),
                                    ),
                                )
                            )
                            .with_for_update()
                            .limit(limit)
                        )
                    ).all()
                )
                for _, generation in reservation_rows:
                    generation_status = GenerationStatus(generation.status)
                    target = (
                        generation_status
                        if generation_status in {
                            GenerationStatus.FAILED,
                            GenerationStatus.CANCELLED,
                        }
                        else GenerationStatus.SUBMITTED
                    )
                    await settle_generation_charge(
                        session,
                        generation_id=generation.id,
                        target=target,
                    )
                    fixed.append(f"settle_reservation:{generation.id}")
                    if len(fixed) >= limit:
                        return tuple(fixed)

                sent_rows = tuple(
                    (
                        await session.execute(
                            select(GenerationDelivery, Generation)
                            .join(Generation, Generation.id == GenerationDelivery.generation_id)
                            .where(
                                GenerationDelivery.status == DeliveryStatus.SENT.value,
                                Generation.status == GenerationStatus.DELIVERY_PENDING.value,
                            )
                            .with_for_update()
                            .limit(limit - len(fixed))
                        )
                    ).all()
                )
                for _, generation in sent_rows:
                    await session.execute(
                        update(Generation)
                        .where(
                            Generation.id == generation.id,
                            Generation.status
                            == GenerationStatus.DELIVERY_PENDING.value,
                        )
                        .values(
                            **generation_transition_values(
                                target=GenerationStatus.SUCCEEDED,
                                status_reason="reconciled_sent_delivery",
                            )
                        )
                    )
                    fixed.append(f"finalize_sent_delivery:{generation.id}")
        return tuple(fixed)
