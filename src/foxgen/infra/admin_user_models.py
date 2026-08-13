from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from foxgen.infra.database import Base


class UserRestriction(Base):
    __tablename__ = "user_restrictions"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), default="admin", server_default="admin")
    updated_by: Mapped[int | None] = mapped_column(BigInteger)
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
