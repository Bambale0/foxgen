from __future__ import annotations

from datetime import datetime
from uuid import UUID as UUIDValue

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from foxgen.infra.database import Base


class UserPaymentOrder(Base):
    __tablename__ = "user_payment_orders"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_user_payment_orders_user_idempotency",
        ),
        UniqueConstraint("invoice_payload", name="uq_user_payment_orders_invoice_payload"),
        UniqueConstraint(
            "telegram_payment_charge_id",
            name="uq_user_payment_orders_telegram_charge",
        ),
        CheckConstraint("credits_units > 0", name="ck_user_payment_orders_credits_positive"),
        CheckConstraint("provider_amount > 0", name="ck_user_payment_orders_amount_positive"),
        CheckConstraint(
            "status IN ('created', 'invoice_ready', 'paid', 'credited', 'failed', 'refunded')",
            name="ck_user_payment_orders_status",
        ),
    )

    id: Mapped[UUIDValue] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(
        String(64), default="telegram_stars", server_default="telegram_stars", index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    package_code: Mapped[str] = mapped_column(String(128))
    package_title: Mapped[str] = mapped_column(String(255))
    package_description: Mapped[str] = mapped_column(String(512), default="", server_default="")
    credits_units: Mapped[int] = mapped_column(BigInteger)
    provider_amount: Mapped[int] = mapped_column(BigInteger)
    provider_currency: Mapped[str] = mapped_column(String(16), default="XTR", server_default="XTR")
    invoice_payload: Mapped[str] = mapped_column(String(128))
    invoice_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(32), default="created", server_default="created", index=True
    )
    telegram_payment_charge_id: Mapped[str | None] = mapped_column(String(255), index=True)
    provider_payment_charge_id: Mapped[str | None] = mapped_column(String(255))
    raw_payment: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    credited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
