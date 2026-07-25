"""Add observable generation processing stages and timestamps.

Revision ID: 20260725_0006
Revises: 20260723_0005
Create Date: 2026-07-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260725_0006"
down_revision: str | None = "20260723_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_NEW_STATUS_CHECK = (
    "status IN ('draft', 'queued', 'submitting', 'submitted', 'processing', "
    "'submission_unknown', 'result_ready', 'storing_media', 'delivery_pending', "
    "'succeeded', 'failed', 'cancelled')"
)
_OLD_STATUS_CHECK = (
    "status IN ('draft', 'queued', 'submitting', 'submitted', "
    "'submission_unknown', 'succeeded', 'failed', 'cancelled')"
)


def upgrade() -> None:
    op.drop_constraint("ck_generations_status", "generations", type_="check")
    op.create_check_constraint("ck_generations_status", "generations", _NEW_STATUS_CHECK)
    op.add_column(
        "generations",
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "generations",
        sa.Column("processing_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "generations",
        sa.Column("result_ready_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "generations",
        sa.Column("storage_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "generations",
        sa.Column("delivery_pending_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "generations",
        sa.Column("failure_stage", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "generations",
        sa.Column("status_reason", sa.String(length=128), nullable=True),
    )
    op.execute("UPDATE generations SET status_changed_at = updated_at WHERE status_changed_at IS NULL")
    op.alter_column("generations", "status_changed_at", nullable=False)
    op.create_index(
        "ix_generations_status_changed_at",
        "generations",
        ["status", "status_changed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.execute(
        "UPDATE generations SET status = 'submitted' "
        "WHERE status IN ('processing', 'result_ready', 'storing_media', 'delivery_pending')"
    )
    op.drop_index("ix_generations_status_changed_at", table_name="generations")
    op.drop_column("generations", "status_reason")
    op.drop_column("generations", "failure_stage")
    op.drop_column("generations", "delivery_pending_at")
    op.drop_column("generations", "storage_started_at")
    op.drop_column("generations", "result_ready_at")
    op.drop_column("generations", "processing_at")
    op.drop_column("generations", "status_changed_at")
    op.drop_constraint("ck_generations_status", "generations", type_="check")
    op.create_check_constraint("ck_generations_status", "generations", _OLD_STATUS_CHECK)
