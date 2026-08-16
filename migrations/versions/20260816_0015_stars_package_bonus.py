"""add Stars package bonus snapshot

Revision ID: 20260816_0015
Revises: 20260816_0014
"""

from alembic import op
import sqlalchemy as sa

revision = "20260816_0015"
down_revision = "20260816_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_payment_orders",
        sa.Column("bonus_units", sa.BigInteger(), server_default="0", nullable=False),
    )
    op.create_check_constraint(
        "ck_user_payment_orders_bonus_nonnegative",
        "user_payment_orders",
        "bonus_units >= 0",
    )
    op.create_check_constraint(
        "ck_user_payment_orders_base_credits_positive",
        "user_payment_orders",
        "credits_units > bonus_units",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_user_payment_orders_base_credits_positive",
        "user_payment_orders",
        type_="check",
    )
    op.drop_constraint(
        "ck_user_payment_orders_bonus_nonnegative",
        "user_payment_orders",
        type_="check",
    )
    op.drop_column("user_payment_orders", "bonus_units")
