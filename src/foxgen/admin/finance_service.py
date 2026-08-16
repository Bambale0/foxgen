from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from foxgen.admin.errors import AdminConflictError, AdminNotFoundError, AdminValidationError
from foxgen.admin.policy import (
    OPERATIONS_WRITE,
    PAYMENTS_WRITE,
    TARIFFS_WRITE,
    AdminContext,
)
from foxgen.admin.repository import AdminCommandExecutor, CommandResult
from foxgen.domain.models import GenerationStatus, LedgerEntryType
from foxgen.infra.admin_models import AdminOutbox, OperationEvent, PaymentEvent, TariffVersion
from foxgen.infra.billing import ensure_wallet_locked, settle_generation_charge
from foxgen.infra.billing_models import LedgerEntry, ModelPrice
from foxgen.infra.database import Database, Generation
from foxgen.infra.payment_models import UserPaymentOrder
from foxgen.infra.payment_refund_models import PaymentRefundAttempt
from foxgen.infra.payment_refunds import (
    ACTIVE_REFUND_STATUSES,
    TELEGRAM_STARS_PROVIDER,
    refund_debit_ledger_key,
    restore_refund_hold,
)


class AdminPaymentService:
    def __init__(self, database: Database, executor: AdminCommandExecutor) -> None:
        self._database = database
        self._executor = executor

    async def recheck_payment(
        self,
        *,
        context: AdminContext,
        payment_id: UUID,
        idempotency_key: str,
    ) -> CommandResult:
        context.require(PAYMENTS_WRITE)

        async def operation(session: AsyncSession) -> dict[str, object]:
            payment = await session.get(PaymentEvent, payment_id)
            if payment is None:
                raise AdminNotFoundError("payment", str(payment_id))
            dedupe = f"payment.recheck:{payment.id}:{idempotency_key}"
            await session.execute(
                pg_insert(AdminOutbox)
                .values(
                    event_type="payment.recheck",
                    target_id=str(payment.id),
                    deduplication_key=dedupe,
                    payload={"payment_id": str(payment.id)},
                )
                .on_conflict_do_nothing(index_elements=[AdminOutbox.deduplication_key])
            )
            return {"payment_id": str(payment.id), "queued": True, "action": "recheck"}

        return await self._executor.execute(
            context=context,
            action="payment.recheck",
            target_id=str(payment_id),
            idempotency_key=idempotency_key,
            request_payload={"payment_id": str(payment_id)},
            operation=operation,
        )

    async def reprocess_payment(
        self,
        *,
        context: AdminContext,
        payment_id: UUID,
        idempotency_key: str,
    ) -> CommandResult:
        context.require(PAYMENTS_WRITE)

        async def operation(session: AsyncSession) -> dict[str, object]:
            payment = await session.get(PaymentEvent, payment_id)
            if payment is None:
                raise AdminNotFoundError("payment", str(payment_id))
            if payment.status not in {"completed", "paid", "succeeded"}:
                raise AdminConflictError(
                    "Only a completed payment can be reprocessed",
                    details={"status": payment.status},
                )
            if payment.credited_ledger_key:
                return {
                    "payment_id": str(payment.id),
                    "queued": False,
                    "already_credited": True,
                    "ledger_key": payment.credited_ledger_key,
                }
            dedupe = f"payment.reprocess:{payment.id}"
            await session.execute(
                pg_insert(AdminOutbox)
                .values(
                    event_type="payment.reprocess",
                    target_id=str(payment.id),
                    deduplication_key=dedupe,
                    payload={"payment_id": str(payment.id)},
                )
                .on_conflict_do_nothing(index_elements=[AdminOutbox.deduplication_key])
            )
            return {
                "payment_id": str(payment.id),
                "queued": True,
                "already_credited": False,
            }

        return await self._executor.execute(
            context=context,
            action="payment.reprocess",
            target_id=str(payment_id),
            idempotency_key=idempotency_key,
            request_payload={"payment_id": str(payment_id)},
            operation=operation,
        )

    async def refund_payment(
        self,
        *,
        context: AdminContext,
        payment_id: UUID,
        reason: str,
        idempotency_key: str,
    ) -> CommandResult:
        context.require(PAYMENTS_WRITE)
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise AdminValidationError("Refund reason is required")

        async def operation(session: AsyncSession) -> dict[str, object]:
            payment = await session.scalar(
                select(PaymentEvent).where(PaymentEvent.id == payment_id).with_for_update()
            )
            if payment is None:
                raise AdminNotFoundError("payment", str(payment_id))
            if payment.provider != TELEGRAM_STARS_PROVIDER:
                raise AdminConflictError(
                    "Only Telegram Stars payments can use native Stars refund",
                    details={"provider": payment.provider},
                )
            if not payment.credited_ledger_key:
                raise AdminConflictError("Payment has not been credited and cannot be refunded")

            order = await session.scalar(
                select(UserPaymentOrder)
                .where(
                    UserPaymentOrder.user_id == payment.user_id,
                    UserPaymentOrder.provider == TELEGRAM_STARS_PROVIDER,
                    UserPaymentOrder.telegram_payment_charge_id == payment.external_id,
                )
                .with_for_update()
            )
            if order is None:
                raise AdminNotFoundError("payment_order", payment.external_id)
            if order.status == "refunded" or payment.status == "refunded":
                raise AdminConflictError("Payment is already refunded")
            if order.status in {"refund_pending", "refund_unknown"}:
                raise AdminConflictError(
                    "A refund attempt is already active",
                    details={"order_status": order.status},
                )
            if order.status != "credited":
                raise AdminConflictError(
                    "Only a credited Stars order can be refunded",
                    details={"order_status": order.status},
                )

            active_attempt = await session.scalar(
                select(PaymentRefundAttempt)
                .where(
                    PaymentRefundAttempt.payment_id == payment.id,
                    PaymentRefundAttempt.status.in_(ACTIVE_REFUND_STATUSES),
                )
                .limit(1)
                .with_for_update()
            )
            if active_attempt is not None:
                raise AdminConflictError(
                    "A refund attempt is already active",
                    details={"refund_attempt_id": str(active_attempt.id)},
                )

            account = await ensure_wallet_locked(
                session,
                user_id=payment.user_id,
                currency=payment.currency,
            )
            if account.available_units < payment.amount_units:
                raise AdminConflictError(
                    "User does not have enough available CREDIT to reverse this payment",
                    details={
                        "available_units": account.available_units,
                        "required_units": payment.amount_units,
                    },
                )

            attempt_id = uuid4()
            debit_key = refund_debit_ledger_key(
                charge_id=payment.external_id,
                attempt_id=attempt_id,
            )
            account.available_units -= payment.amount_units
            account.version += 1
            session.add(
                LedgerEntry(
                    user_id=payment.user_id,
                    generation_id=None,
                    reservation_id=None,
                    entry_type=LedgerEntryType.DEBIT,
                    currency=payment.currency,
                    available_delta=-payment.amount_units,
                    reserved_delta=0,
                    idempotency_key=debit_key,
                    actor=f"admin:{context.user_id}",
                    reason=f"Hold CREDIT for Telegram Stars refund: {normalized_reason}",
                    metadata_json={
                        "payment_id": str(payment.id),
                        "refund_attempt_id": str(attempt_id),
                        "telegram_payment_charge_id": payment.external_id,
                    },
                )
            )
            attempt = PaymentRefundAttempt(
                id=attempt_id,
                payment_id=payment.id,
                order_id=order.id,
                user_id=payment.user_id,
                provider=payment.provider,
                external_charge_id=payment.external_id,
                amount_units=payment.amount_units,
                currency=payment.currency,
                reason=normalized_reason,
                requested_by=context.user_id,
                status="pending",
                debit_ledger_key=debit_key,
            )
            session.add(attempt)
            order.status = "refund_pending"
            payment.status = "refund_pending"
            await session.execute(
                pg_insert(AdminOutbox)
                .values(
                    event_type="payment.refund",
                    target_id=str(payment.id),
                    deduplication_key=f"payment.refund:{attempt.id}",
                    payload={
                        "payment_id": str(payment.id),
                        "refund_attempt_id": str(attempt.id),
                    },
                )
                .on_conflict_do_nothing(index_elements=[AdminOutbox.deduplication_key])
            )
            return {
                "payment_id": str(payment.id),
                "refund_attempt_id": str(attempt.id),
                "queued": True,
                "held_units": payment.amount_units,
                "status": "refund_pending",
            }

        return await self._executor.execute(
            context=context,
            action="payment.refund",
            target_id=str(payment_id),
            idempotency_key=idempotency_key,
            request_payload={"payment_id": str(payment_id), "reason": normalized_reason},
            operation=operation,
        )

    async def resolve_refund(
        self,
        *,
        context: AdminContext,
        payment_id: UUID,
        outcome: str,
        evidence: str,
        idempotency_key: str,
    ) -> CommandResult:
        context.require(PAYMENTS_WRITE)
        normalized_outcome = outcome.strip().lower()
        normalized_evidence = evidence.strip()
        if normalized_outcome not in {"refunded", "not_refunded"}:
            raise AdminValidationError("Refund resolution outcome must be refunded or not_refunded")
        if not normalized_evidence:
            raise AdminValidationError("Refund resolution evidence is required")

        async def operation(session: AsyncSession) -> dict[str, object]:
            payment = await session.scalar(
                select(PaymentEvent).where(PaymentEvent.id == payment_id).with_for_update()
            )
            if payment is None:
                raise AdminNotFoundError("payment", str(payment_id))
            order = await session.scalar(
                select(UserPaymentOrder)
                .where(
                    UserPaymentOrder.user_id == payment.user_id,
                    UserPaymentOrder.provider == TELEGRAM_STARS_PROVIDER,
                    UserPaymentOrder.telegram_payment_charge_id == payment.external_id,
                )
                .with_for_update()
            )
            if order is None:
                raise AdminNotFoundError("payment_order", payment.external_id)
            attempt = await session.scalar(
                select(PaymentRefundAttempt)
                .where(
                    PaymentRefundAttempt.payment_id == payment.id,
                    PaymentRefundAttempt.status == "unknown",
                )
                .order_by(PaymentRefundAttempt.created_at.desc())
                .limit(1)
                .with_for_update()
            )
            if attempt is None or order.status != "refund_unknown":
                raise AdminConflictError("Payment has no unresolved ambiguous refund")

            now = datetime.now(timezone.utc)
            if normalized_outcome == "refunded":
                attempt.status = "resolved_refunded"
                order.status = "refunded"
                payment.status = "refunded"
            else:
                restore_key = await restore_refund_hold(
                    session,
                    attempt=attempt,
                    actor=f"admin:{context.user_id}",
                    reason=f"Restore CREDIT after refund evidence: {normalized_evidence}",
                )
                attempt.status = "resolved_not_refunded"
                order.status = "credited"
                payment.status = "completed"
                attempt.provider_payload = {
                    **attempt.provider_payload,
                    "restore_ledger_key": restore_key,
                }
            attempt.resolution_note = normalized_evidence
            attempt.resolved_at = now
            attempt.last_error = None
            return {
                "payment_id": str(payment.id),
                "refund_attempt_id": str(attempt.id),
                "outcome": normalized_outcome,
                "status": order.status,
                "restore_ledger_key": attempt.restore_ledger_key,
            }

        return await self._executor.execute(
            context=context,
            action="payment.refund.resolve",
            target_id=str(payment_id),
            idempotency_key=idempotency_key,
            request_payload={
                "payment_id": str(payment_id),
                "outcome": normalized_outcome,
                "evidence": normalized_evidence,
            },
            operation=operation,
        )


class AdminTariffService:
    def __init__(self, database: Database, executor: AdminCommandExecutor) -> None:
        self._database = database
        self._executor = executor

    async def publish(
        self,
        *,
        context: AdminContext,
        payload: dict[str, object],
        idempotency_key: str,
    ) -> CommandResult:
        context.require(TARIFFS_WRITE)
        model_prices = self._validated_model_prices(payload)
        self._validate_payload(payload)

        async def operation(session: AsyncSession) -> dict[str, object]:
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended('foxgen:tariffs', 0))")
            )
            latest = await session.scalar(select(func.max(TariffVersion.version)))
            next_version = int(latest or 0) + 1
            published_at = datetime.now(timezone.utc)
            tariff = TariffVersion(
                version=next_version,
                payload=payload,
                created_by=context.user_id,
                published_at=published_at,
            )
            session.add(tariff)
            await session.flush()

            for model_slug, amount_units in model_prices.items():
                latest_model_version = await session.scalar(
                    select(func.max(ModelPrice.version)).where(ModelPrice.model_slug == model_slug)
                )
                await session.execute(
                    update(ModelPrice)
                    .where(ModelPrice.model_slug == model_slug, ModelPrice.enabled.is_(True))
                    .values(enabled=False, active_until=published_at)
                )
                session.add(
                    ModelPrice(
                        model_slug=model_slug,
                        version=int(latest_model_version or 0) + 1,
                        amount_units=amount_units,
                        currency="CREDIT",
                        enabled=True,
                        active_from=published_at,
                        active_until=None,
                        metadata_json={
                            "tariff_version": next_version,
                            "admin_user_id": context.user_id,
                        },
                    )
                )

            return {
                "version_id": str(tariff.id),
                "version": next_version,
                "published_at": published_at.isoformat(),
                "model_prices_updated": len(model_prices),
            }

        return await self._executor.execute(
            context=context,
            action="tariffs.publish",
            target_id=None,
            idempotency_key=idempotency_key,
            request_payload=payload,
            operation=operation,
        )

    @staticmethod
    def _validate_payload(payload: dict[str, object]) -> None:
        allowed = {
            "packages",
            "model_prices",
            "image_prices",
            "video_prices",
            "partner_exchange",
            "prompt_costs",
            "video_prompt_costs",
            "metadata",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise AdminValidationError(
                "Tariff payload contains unsupported sections",
                details={"unknown": unknown},
            )
        if not payload:
            raise AdminValidationError("Tariff payload cannot be empty")
        _validate_nonnegative_numbers(payload)

    @staticmethod
    def _validated_model_prices(payload: dict[str, object]) -> dict[str, int]:
        merged: dict[str, int] = {}
        for section_name in ("model_prices", "image_prices", "video_prices"):
            section = payload.get(section_name)
            if section is None:
                continue
            if not isinstance(section, dict):
                raise AdminValidationError(f"{section_name} must be an object")
            for raw_slug, raw_amount in section.items():
                if not isinstance(raw_slug, str) or not raw_slug.strip():
                    raise AdminValidationError(f"{section_name} contains an invalid model slug")
                if (
                    not isinstance(raw_amount, int)
                    or isinstance(raw_amount, bool)
                    or raw_amount <= 0
                ):
                    raise AdminValidationError(
                        f"{section_name}.{raw_slug} must be a positive integer credit amount"
                    )
                merged[raw_slug] = raw_amount
        return merged


class AdminOperationService:
    def __init__(self, database: Database, executor: AdminCommandExecutor) -> None:
        self._database = database
        self._executor = executor

    async def replay(
        self,
        *,
        context: AdminContext,
        operation_id: UUID,
        idempotency_key: str,
    ) -> CommandResult:
        context.require(OPERATIONS_WRITE)

        async def operation(session: AsyncSession) -> dict[str, object]:
            parent = await session.get(OperationEvent, operation_id)
            if parent is None:
                raise AdminNotFoundError("operation", str(operation_id))
            child = OperationEvent(
                generation_id=parent.generation_id,
                parent_operation_id=parent.id,
                operation_type=f"replay:{parent.operation_type}",
                status="queued",
                payload={"source_operation_id": str(parent.id), "source_payload": parent.payload},
                created_by=context.user_id,
            )
            session.add(child)
            await session.flush()
            await session.execute(
                pg_insert(AdminOutbox)
                .values(
                    event_type="operation.replay",
                    target_id=str(child.id),
                    deduplication_key=f"operation.replay:{parent.id}:{idempotency_key}",
                    payload={"operation_id": str(child.id)},
                )
                .on_conflict_do_nothing(index_elements=[AdminOutbox.deduplication_key])
            )
            return {
                "operation_id": str(child.id),
                "parent_operation_id": str(parent.id),
                "status": "queued",
                "charged": False,
            }

        return await self._executor.execute(
            context=context,
            action="operation.replay",
            target_id=str(operation_id),
            idempotency_key=idempotency_key,
            request_payload={"operation_id": str(operation_id)},
            operation=operation,
        )

    async def refund(
        self,
        *,
        context: AdminContext,
        operation_id: UUID,
        reason: str,
        idempotency_key: str,
    ) -> CommandResult:
        context.require(OPERATIONS_WRITE)
        if not reason.strip():
            raise AdminValidationError("Refund reason is required")

        async def operation(session: AsyncSession) -> dict[str, object]:
            source = await session.get(OperationEvent, operation_id)
            if source is None:
                raise AdminNotFoundError("operation", str(operation_id))
            if source.generation_id is None:
                raise AdminConflictError("Operation is not linked to a billable generation")
            generation = await session.get(Generation, source.generation_id)
            if generation is None:
                raise AdminNotFoundError("generation", str(source.generation_id))
            await settle_generation_charge(
                session,
                generation_id=generation.id,
                target=GenerationStatus.FAILED,
            )
            refund_event = OperationEvent(
                generation_id=generation.id,
                parent_operation_id=source.id,
                operation_type="admin.refund",
                status="completed",
                payload={"reason": reason.strip(), "source_operation_id": str(source.id)},
                created_by=context.user_id,
            )
            session.add(refund_event)
            await session.flush()
            return {
                "operation_id": str(refund_event.id),
                "generation_id": str(generation.id),
                "status": "completed",
                "reason": reason.strip(),
            }

        return await self._executor.execute(
            context=context,
            action="operation.refund",
            target_id=str(operation_id),
            idempotency_key=idempotency_key,
            request_payload={"operation_id": str(operation_id), "reason": reason.strip()},
            operation=operation,
        )


def _validate_nonnegative_numbers(value: object, path: str = "tariff") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _validate_nonnegative_numbers(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_nonnegative_numbers(item, f"{path}[{index}]")
    elif isinstance(value, (int, float)) and not isinstance(value, bool) and value < 0:
        raise AdminValidationError(f"{path} cannot contain negative numeric values")
