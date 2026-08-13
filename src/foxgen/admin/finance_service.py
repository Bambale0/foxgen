from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

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
from foxgen.infra.admin_models import AdminOutbox, OperationEvent, PaymentEvent, TariffVersion
from foxgen.infra.billing import settle_generation_charge
from foxgen.infra.billing_models import ModelPrice
from foxgen.infra.database import Database, Generation
from foxgen.domain.models import GenerationStatus


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
            await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('foxgen:tariffs', 0))"))
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
                if not isinstance(raw_amount, int) or isinstance(raw_amount, bool) or raw_amount <= 0:
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
