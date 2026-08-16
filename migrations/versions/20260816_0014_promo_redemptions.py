"""add durable promo redemptions

Revision ID: 20260816_0014
Revises: 20260816_0013
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260816_0014"
down_revision = "20260816_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "promo_redemptions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("promo_code", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("reward_units", sa.BigInteger(), nullable=False),
        sa.Column("ledger_key", sa.String(length=255), nullable=False),
        sa.Column(
            "redeemed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("reward_units > 0", name="ck_promo_redemptions_reward_positive"),
        sa.ForeignKeyConstraint(["promo_code"], ["promo_codes.code"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "promo_code",
            "user_id",
            name="uq_promo_redemptions_code_user",
        ),
        sa.UniqueConstraint("ledger_key", name="uq_promo_redemptions_ledger_key"),
    )
    op.create_index("ix_promo_redemptions_promo_code", "promo_redemptions", ["promo_code"])
    op.create_index("ix_promo_redemptions_user_id", "promo_redemptions", ["user_id"])
    op.create_index("ix_promo_redemptions_redeemed_at", "promo_redemptions", ["redeemed_at"])


def downgrade() -> None:
    op.drop_index("ix_promo_redemptions_redeemed_at", table_name="promo_redemptions")
    op.drop_index("ix_promo_redemptions_user_id", table_name="promo_redemptions")
    op.drop_index("ix_promo_redemptions_promo_code", table_name="promo_redemptions")
    op.drop_table("promo_redemptions")
