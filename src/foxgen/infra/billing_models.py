from datetime import datetime
from uuid import UUID as UUIDValue

from sqlalchemy import (
    BigInteger,
    Boolean,
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

from foxgen.domain.models import LedgerEntryType, ReservationStatus
from foxgen.infra.database import Base


class WalletAccount(Base):
    __tablename__ = "wallet_accounts"
    __table_args__ = (
        CheckConstraint("available_units >= 0", name="ck_wallet_accounts_available_nonnegative"),
        CheckConstraint("reserved_units >= 0", name="ck_wallet_accounts_reserved_nonnegative"),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    currency: Mapped[str] = mapped_column(String(16), default="CREDIT", server_default="CREDIT")
    available_units: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    reserved_units: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ModelPrice(Base):
    __tablename__ = "model_prices"
    __table_args__ = (
        UniqueConstraint("model_slug", "version", name="uq_model_prices_slug_version"),
        CheckConstraint("amount_units > 0", name="ck_model_prices_amount_positive"),
    )

    id: Mapped[UUIDValue] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    model_slug: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[int] = mapped_column(Integer)
    amount_units: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(16), default="CREDIT", server_default="CREDIT")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", index=True)
    active_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    active_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BalanceReservation(Base):
    __tablename__ = "balance_reservations"
    __table_args__ = (
        UniqueConstraint("generation_id", name="uq_balance_reservations_generation_id"),
        CheckConstraint("amount_units > 0", name="ck_balance_reservations_amount_positive"),
        CheckConstraint(
            "status IN ('reserved', 'captured', 'released', 'refunded')",
            name="ck_balance_reservations_status",
        ),
    )

    id: Mapped[UUIDValue] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    generation_id: Mapped[UUIDValue] = mapped_column(
        ForeignKey("generations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    price_id: Mapped[UUIDValue] = mapped_column(ForeignKey("model_prices.id"))
    amount_units: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(16))
    status: Mapped[ReservationStatus] = mapped_column(
        String(32),
        default=ReservationStatus.RESERVED,
        server_default=ReservationStatus.RESERVED,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_ledger_entries_idempotency_key"),
        CheckConstraint(
            "entry_type IN ('credit', 'debit', 'reserve', 'capture', 'release', "
            "'refund', 'adjustment')",
            name="ck_ledger_entries_type",
        ),
        CheckConstraint(
            "available_delta <> 0 OR reserved_delta <> 0",
            name="ck_ledger_entries_nonzero_delta",
        ),
    )

    id: Mapped[UUIDValue] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    generation_id: Mapped[UUIDValue | None] = mapped_column(
        ForeignKey("generations.id", ondelete="SET NULL"), index=True
    )
    reservation_id: Mapped[UUIDValue | None] = mapped_column(
        ForeignKey("balance_reservations.id", ondelete="SET NULL"), index=True
    )
    entry_type: Mapped[LedgerEntryType] = mapped_column(String(32), index=True)
    currency: Mapped[str] = mapped_column(String(16))
    available_delta: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    reserved_delta: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    idempotency_key: Mapped[str] = mapped_column(String(255))
    actor: Mapped[str] = mapped_column(String(128))
    reason: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
