from __future__ import annotations

from datetime import datetime
from uuid import UUID as UUIDValue

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from foxgen.infra.database import Base


class PromoRedemption(Base):
    __tablename__ = "promo_redemptions"
    __table_args__ = (
        UniqueConstraint(
            "promo_code",
            "user_id",
            name="uq_promo_redemptions_code_user",
        ),
        UniqueConstraint("ledger_key", name="uq_promo_redemptions_ledger_key"),
        CheckConstraint("reward_units > 0", name="ck_promo_redemptions_reward_positive"),
    )

    id: Mapped[UUIDValue] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    promo_code: Mapped[str] = mapped_column(
        ForeignKey("promo_codes.code", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    reward_units: Mapped[int] = mapped_column(BigInteger)
    ledger_key: Mapped[str] = mapped_column(String(255))
    redeemed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
