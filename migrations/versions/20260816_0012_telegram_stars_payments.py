"""add durable Telegram Stars payment orders

Revision ID: 20260816_0012
Revises: 20260816_0011
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260816_0012"
down_revision = "20260816_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_payment_orders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "provider", sa.String(length=64), server_default="telegram_stars", nullable=False
        ),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("package_code", sa.String(length=128), nullable=False),
        sa.Column("package_title", sa.String(length=255), nullable=False),
        sa.Column("package_description", sa.String(length=512), server_default="", nullable=False),
        sa.Column("credits_units", sa.BigInteger(), nullable=False),
        sa.Column("provider_amount", sa.BigInteger(), nullable=False),
        sa.Column("provider_currency", sa.String(length=16), server_default="XTR", nullable=False),
        sa.Column("invoice_payload", sa.String(length=128), nullable=False),
        sa.Column("invoice_url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="created", nullable=False),
        sa.Column("telegram_payment_charge_id", sa.String(length=255), nullable=True),
        sa.Column("provider_payment_charge_id", sa.String(length=255), nullable=True),
        sa.Column(
            "raw_payment",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("credited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("credits_units > 0", name="ck_user_payment_orders_credits_positive"),
        sa.CheckConstraint("provider_amount > 0", name="ck_user_payment_orders_amount_positive"),
        sa.CheckConstraint(
            "status IN ('created', 'invoice_ready', 'paid', 'credited', 'failed', 'refunded')",
            name="ck_user_payment_orders_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "idempotency_key", name="uq_user_payment_orders_user_idempotency"
        ),
        sa.UniqueConstraint("invoice_payload", name="uq_user_payment_orders_invoice_payload"),
        sa.UniqueConstraint(
            "telegram_payment_charge_id", name="uq_user_payment_orders_telegram_charge"
        ),
    )
    op.create_index("ix_user_payment_orders_user_id", "user_payment_orders", ["user_id"])
    op.create_index("ix_user_payment_orders_provider", "user_payment_orders", ["provider"])
    op.create_index("ix_user_payment_orders_status", "user_payment_orders", ["status"])
    op.create_index(
        "ix_user_payment_orders_telegram_payment_charge_id",
        "user_payment_orders",
        ["telegram_payment_charge_id"],
    )
    op.create_index("ix_user_payment_orders_created_at", "user_payment_orders", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_user_payment_orders_created_at", table_name="user_payment_orders")
    op.drop_index(
        "ix_user_payment_orders_telegram_payment_charge_id",
        table_name="user_payment_orders",
    )
    op.drop_index("ix_user_payment_orders_status", table_name="user_payment_orders")
    op.drop_index("ix_user_payment_orders_provider", table_name="user_payment_orders")
    op.drop_index("ix_user_payment_orders_user_id", table_name="user_payment_orders")
    op.drop_table("user_payment_orders")
