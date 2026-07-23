"""Add secure idempotent generation submission fields.

Revision ID: 20260723_0002
Revises: 20260723_0001
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260723_0002"
down_revision: str | None = "20260723_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_ALLOWED_STATUSES = (
    "'draft', 'queued', 'submitting', 'submitted', "
    "'submission_unknown', 'succeeded', 'failed', 'cancelled'"
)


def upgrade() -> None:
    op.add_column(
        "generations",
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "generations",
        sa.Column("request_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "generations",
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.execute(
        "UPDATE generations "
        "SET idempotency_key = 'legacy-' || id::text "
        "WHERE idempotency_key IS NULL"
    )
    op.execute(
        "UPDATE generations "
        "SET request_hash = encode(digest(id::text, 'sha256'), 'hex') "
        "WHERE request_hash IS NULL"
    )

    op.alter_column("generations", "idempotency_key", nullable=False)
    op.alter_column("generations", "request_hash", nullable=False)
    op.alter_column(
        "generations",
        "status",
        existing_type=sa.String(length=32),
        server_default="draft",
        existing_nullable=False,
    )
    op.create_unique_constraint(
        "uq_generations_user_id_idempotency_key",
        "generations",
        ["user_id", "idempotency_key"],
    )
    op.create_check_constraint(
        "ck_generations_status",
        "generations",
        f"status IN ({_ALLOWED_STATUSES})",
    )


def downgrade() -> None:
    op.drop_constraint("ck_generations_status", "generations", type_="check")
    op.drop_constraint(
        "uq_generations_user_id_idempotency_key",
        "generations",
        type_="unique",
    )
    op.alter_column(
        "generations",
        "status",
        existing_type=sa.String(length=32),
        server_default=None,
        existing_nullable=False,
    )
    op.drop_column("generations", "submitted_at")
    op.drop_column("generations", "request_hash")
    op.drop_column("generations", "idempotency_key")
