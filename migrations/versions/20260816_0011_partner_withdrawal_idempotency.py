"""add durable idempotency to partner withdrawals

Revision ID: 20260816_0011
Revises: 20260815_0010
"""

from alembic import op
import sqlalchemy as sa

revision = "20260816_0011"
down_revision = "20260815_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "partner_withdrawals", sa.Column("idempotency_key", sa.String(length=128), nullable=True)
    )
    op.add_column(
        "partner_withdrawals", sa.Column("request_hash", sa.String(length=64), nullable=True)
    )
    op.create_unique_constraint(
        "uq_partner_withdrawals_user_idempotency",
        "partner_withdrawals",
        ["user_id", "idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_partner_withdrawals_user_idempotency", "partner_withdrawals", type_="unique"
    )
    op.drop_column("partner_withdrawals", "request_hash")
    op.drop_column("partner_withdrawals", "idempotency_key")
