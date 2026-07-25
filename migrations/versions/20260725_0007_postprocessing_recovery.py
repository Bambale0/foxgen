"""Add retry/dead-letter state for outbox, media and delivery.

Revision ID: 20260725_0007
Revises: 20260725_0006
Create Date: 2026-07-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260725_0007"
down_revision: str | None = "20260725_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_OUTBOX_NEW = (
    "status IN ('pending', 'retry_wait', 'processing', 'completed', "
    "'dead_letter', 'failed')"
)
_OUTBOX_OLD = "status IN ('pending', 'processing', 'completed', 'failed')"
_MEDIA_NEW = "status IN ('pending', 'retry_wait', 'stored', 'failed')"
_MEDIA_OLD = "status IN ('pending', 'stored', 'failed')"
_DELIVERY_NEW = (
    "status IN ('pending', 'retry_wait', 'sending', 'sent', "
    "'delivery_unknown', 'failed')"
)
_DELIVERY_OLD = "status IN ('pending', 'sending', 'sent', 'delivery_unknown', 'failed')"


def upgrade() -> None:
    op.drop_constraint("ck_outbox_events_status", "outbox_events", type_="check")
    op.create_check_constraint("ck_outbox_events_status", "outbox_events", _OUTBOX_NEW)
    op.add_column("outbox_events", sa.Column("failure_class", sa.String(64), nullable=True))
    op.add_column(
        "outbox_events",
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE outbox_events SET status = 'dead_letter', dead_lettered_at = updated_at "
        "WHERE status = 'failed'"
    )
    op.create_index(
        "ix_outbox_events_recovery",
        "outbox_events",
        ["status", "available_at"],
        unique=False,
    )

    op.drop_constraint("ck_media_assets_status", "media_assets", type_="check")
    op.create_check_constraint("ck_media_assets_status", "media_assets", _MEDIA_NEW)
    op.add_column(
        "media_assets",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "media_assets",
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("media_assets", sa.Column("last_error", sa.Text(), nullable=True))
    op.create_index(
        "ix_media_assets_recovery",
        "media_assets",
        ["status", "next_retry_at"],
        unique=False,
    )

    op.drop_constraint(
        "ck_generation_deliveries_status",
        "generation_deliveries",
        type_="check",
    )
    op.create_check_constraint(
        "ck_generation_deliveries_status",
        "generation_deliveries",
        _DELIVERY_NEW,
    )
    op.add_column(
        "generation_deliveries",
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_generation_deliveries_recovery",
        "generation_deliveries",
        ["status", "next_retry_at"],
        unique=False,
    )


def downgrade() -> None:
    op.execute(
        "UPDATE generation_deliveries SET status = 'pending' WHERE status = 'retry_wait'"
    )
    op.drop_index(
        "ix_generation_deliveries_recovery",
        table_name="generation_deliveries",
    )
    op.drop_column("generation_deliveries", "next_retry_at")
    op.drop_constraint(
        "ck_generation_deliveries_status",
        "generation_deliveries",
        type_="check",
    )
    op.create_check_constraint(
        "ck_generation_deliveries_status",
        "generation_deliveries",
        _DELIVERY_OLD,
    )

    op.execute("UPDATE media_assets SET status = 'failed' WHERE status = 'retry_wait'")
    op.drop_index("ix_media_assets_recovery", table_name="media_assets")
    op.drop_column("media_assets", "last_error")
    op.drop_column("media_assets", "next_retry_at")
    op.drop_column("media_assets", "attempts")
    op.drop_constraint("ck_media_assets_status", "media_assets", type_="check")
    op.create_check_constraint("ck_media_assets_status", "media_assets", _MEDIA_OLD)

    op.execute("UPDATE outbox_events SET status = 'failed' WHERE status = 'dead_letter'")
    op.execute("UPDATE outbox_events SET status = 'pending' WHERE status = 'retry_wait'")
    op.drop_index("ix_outbox_events_recovery", table_name="outbox_events")
    op.drop_column("outbox_events", "dead_lettered_at")
    op.drop_column("outbox_events", "failure_class")
    op.drop_constraint("ck_outbox_events_status", "outbox_events", type_="check")
    op.create_check_constraint("ck_outbox_events_status", "outbox_events", _OUTBOX_OLD)
