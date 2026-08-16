from __future__ import annotations

from datetime import datetime
from uuid import UUID as UUIDValue

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from foxgen.infra.database import Base


class PaymentRefundAttempt(Base):
    __tablename__ = "payment_refund_attempts"
    __table_args__ = (
        UniqueConstraint("debit_ledger_key", name="uq_payment_refunds_debit_ledger_key"),
        UniqueConstraint("restore_ledger_key", name="uq_payment_refunds_restore_ledger_key"),
        CheckConstraint("amount_units > 0", name="ck_payment_refunds_amount_positive"),
        CheckConstraint("attempts >= 0", name="ck_payment_refunds_attempts_nonnegative"),
        CheckConstraint(
            "status IN ("
            "'pending', 'processing', 'succeeded', 'failed', 'unknown', "
            "'resolved_refunded', 'resolved_not_refunded'"
            ")",
            name="ck_payment_refunds_status",
        ),
    )

    id: Mapped[UUIDValue] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    payment_id: Mapped[UUIDValue] = mapped_column(
        ForeignKey("payment_events.id", ondelete="CASCADE"), index=True
    )
    order_id: Mapped[UUIDValue] = mapped_column(
        ForeignKey("user_payment_orders.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    external_charge_id: Mapped[str] = mapped_column(String(255), index=True)
    amount_units: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(16), default="CREDIT", server_default="CREDIT")
    reason: Mapped[str] = mapped_column(Text)
    requested_by: Mapped[int] = mapped_column(BigInteger, index=True)
    status: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending", index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    debit_ledger_key: Mapped[str] = mapped_column(String(255))
    restore_ledger_key: Mapped[str | None] = mapped_column(String(255))
    provider_payload: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    last_error: Mapped[str | None] = mapped_column(Text)
    resolution_note: Mapped[str | None] = mapped_column(Text)
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
