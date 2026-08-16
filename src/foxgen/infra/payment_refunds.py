from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foxgen.domain.models import LedgerEntryType
from foxgen.infra.billing import ensure_wallet_locked
from foxgen.infra.billing_models import LedgerEntry
from foxgen.infra.payment_refund_models import PaymentRefundAttempt


TELEGRAM_STARS_PROVIDER = "telegram_stars"
ACTIVE_REFUND_STATUSES = frozenset({"pending", "processing", "unknown"})


def refund_debit_ledger_key(*, charge_id: str, attempt_id: object) -> str:
    return f"payment-refund-debit:{TELEGRAM_STARS_PROVIDER}:{charge_id}:{attempt_id}"


def refund_restore_ledger_key(*, charge_id: str, attempt_id: object) -> str:
    return f"payment-refund-restore:{TELEGRAM_STARS_PROVIDER}:{charge_id}:{attempt_id}"


async def restore_refund_hold(
    session: AsyncSession,
    *,
    attempt: PaymentRefundAttempt,
    actor: str,
    reason: str,
) -> str:
    key = attempt.restore_ledger_key or refund_restore_ledger_key(
        charge_id=attempt.external_charge_id,
        attempt_id=attempt.id,
    )
    existing = await session.scalar(select(LedgerEntry).where(LedgerEntry.idempotency_key == key))
    if existing is None:
        account = await ensure_wallet_locked(
            session,
            user_id=attempt.user_id,
            currency=attempt.currency,
        )
        account.available_units += attempt.amount_units
        account.version += 1
        session.add(
            LedgerEntry(
                user_id=attempt.user_id,
                generation_id=None,
                reservation_id=None,
                entry_type=LedgerEntryType.CREDIT,
                currency=attempt.currency,
                available_delta=attempt.amount_units,
                reserved_delta=0,
                idempotency_key=key,
                actor=actor,
                reason=reason,
                metadata_json={
                    "payment_id": str(attempt.payment_id),
                    "refund_attempt_id": str(attempt.id),
                    "telegram_payment_charge_id": attempt.external_charge_id,
                },
            )
        )
    elif existing.user_id != attempt.user_id or existing.available_delta != attempt.amount_units:
        raise RuntimeError("refund restore ledger key is already used with different parameters")
    attempt.restore_ledger_key = key
    return key
