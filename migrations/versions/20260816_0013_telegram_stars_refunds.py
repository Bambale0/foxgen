"""add durable Telegram Stars refund attempts

Revision ID: 20260816_0013
Revises: 20260816_0012
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260816_0013"
down_revision = "20260816_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_user_payment_orders_status",
        "user_payment_orders",
        type_="check",
    )
    op.create_check_constraint(
        "ck_user_payment_orders_status",
        "user_payment_orders",
        "status IN ("
        "'created', 'invoice_ready', 'paid', 'credited', "
        "'refund_pending', 'refund_unknown', 'refunded', 'failed'"
        ")",
    )

    op.create_table(
        "payment_refund_attempts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("external_charge_id", sa.String(length=255), nullable=False),
        sa.Column("amount_units", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=16), server_default="CREDIT", nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("requested_by", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("debit_ledger_key", sa.String(length=255), nullable=False),
        sa.Column("restore_ledger_key", sa.String(length=255), nullable=True),
        sa.Column(
            "provider_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("amount_units > 0", name="ck_payment_refunds_amount_positive"),
        sa.CheckConstraint("attempts >= 0", name="ck_payment_refunds_attempts_nonnegative"),
        sa.CheckConstraint(
            "status IN ("
            "'pending', 'processing', 'succeeded', 'failed', 'unknown', "
            "'resolved_refunded', 'resolved_not_refunded'"
            ")",
            name="ck_payment_refunds_status",
        ),
        sa.ForeignKeyConstraint(["payment_id"], ["payment_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["order_id"], ["user_payment_orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("debit_ledger_key", name="uq_payment_refunds_debit_ledger_key"),
        sa.UniqueConstraint("restore_ledger_key", name="uq_payment_refunds_restore_ledger_key"),
    )
    op.create_index(
        "ix_payment_refund_attempts_payment_id", "payment_refund_attempts", ["payment_id"]
    )
    op.create_index("ix_payment_refund_attempts_order_id", "payment_refund_attempts", ["order_id"])
    op.create_index("ix_payment_refund_attempts_user_id", "payment_refund_attempts", ["user_id"])
    op.create_index("ix_payment_refund_attempts_provider", "payment_refund_attempts", ["provider"])
    op.create_index(
        "ix_payment_refund_attempts_external_charge_id",
        "payment_refund_attempts",
        ["external_charge_id"],
    )
    op.create_index(
        "ix_payment_refund_attempts_requested_by", "payment_refund_attempts", ["requested_by"]
    )
    op.create_index("ix_payment_refund_attempts_status", "payment_refund_attempts", ["status"])
    op.create_index(
        "ix_payment_refund_attempts_available_at", "payment_refund_attempts", ["available_at"]
    )
    op.create_index(
        "ix_payment_refund_attempts_locked_at", "payment_refund_attempts", ["locked_at"]
    )
    op.create_index(
        "ix_payment_refund_attempts_created_at", "payment_refund_attempts", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_payment_refund_attempts_created_at", table_name="payment_refund_attempts")
    op.drop_index("ix_payment_refund_attempts_locked_at", table_name="payment_refund_attempts")
    op.drop_index("ix_payment_refund_attempts_available_at", table_name="payment_refund_attempts")
    op.drop_index("ix_payment_refund_attempts_status", table_name="payment_refund_attempts")
    op.drop_index("ix_payment_refund_attempts_requested_by", table_name="payment_refund_attempts")
    op.drop_index(
        "ix_payment_refund_attempts_external_charge_id",
        table_name="payment_refund_attempts",
    )
    op.drop_index("ix_payment_refund_attempts_provider", table_name="payment_refund_attempts")
    op.drop_index("ix_payment_refund_attempts_user_id", table_name="payment_refund_attempts")
    op.drop_index("ix_payment_refund_attempts_order_id", table_name="payment_refund_attempts")
    op.drop_index("ix_payment_refund_attempts_payment_id", table_name="payment_refund_attempts")
    op.drop_table("payment_refund_attempts")

    op.drop_constraint(
        "ck_user_payment_orders_status",
        "user_payment_orders",
        type_="check",
    )
    op.create_check_constraint(
        "ck_user_payment_orders_status",
        "user_payment_orders",
        "status IN ('created', 'invoice_ready', 'paid', 'credited', 'failed', 'refunded')",
    )
