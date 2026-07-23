"""Add model prices, wallet accounts, reservations and immutable ledger.

Revision ID: 20260723_0005
Revises: 20260723_0004
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260723_0005"
down_revision: str | None = "20260723_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wallet_accounts",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=16), server_default="CREDIT", nullable=False),
        sa.Column("available_units", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("reserved_units", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "available_units >= 0",
            name="ck_wallet_accounts_available_nonnegative",
        ),
        sa.CheckConstraint(
            "reserved_units >= 0",
            name="ck_wallet_accounts_reserved_nonnegative",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "model_prices",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("model_slug", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("amount_units", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=16), server_default="CREDIT", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "active_from",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("active_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount_units > 0", name="ck_model_prices_amount_positive"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_slug", "version", name="uq_model_prices_slug_version"),
    )
    op.create_index(
        op.f("ix_model_prices_enabled"),
        "model_prices",
        ["enabled"],
        unique=False,
    )
    op.create_index(
        op.f("ix_model_prices_model_slug"),
        "model_prices",
        ["model_slug"],
        unique=False,
    )

    op.create_table(
        "balance_reservations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("generation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("price_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount_units", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="reserved", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('reserved', 'captured', 'released', 'refunded')",
            name="ck_balance_reservations_status",
        ),
        sa.CheckConstraint(
            "amount_units > 0",
            name="ck_balance_reservations_amount_positive",
        ),
        sa.ForeignKeyConstraint(
            ["generation_id"],
            ["generations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["price_id"], ["model_prices.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "generation_id",
            name="uq_balance_reservations_generation_id",
        ),
    )
    op.create_index(
        op.f("ix_balance_reservations_generation_id"),
        "balance_reservations",
        ["generation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_balance_reservations_status"),
        "balance_reservations",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_balance_reservations_user_id"),
        "balance_reservations",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "ledger_entries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("generation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reservation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("entry_type", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column("available_delta", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("reserved_delta", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "entry_type IN ('credit', 'debit', 'reserve', 'capture', 'release', "
            "'refund', 'adjustment')",
            name="ck_ledger_entries_type",
        ),
        sa.CheckConstraint(
            "available_delta <> 0 OR reserved_delta <> 0",
            name="ck_ledger_entries_nonzero_delta",
        ),
        sa.ForeignKeyConstraint(
            ["generation_id"],
            ["generations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reservation_id"],
            ["balance_reservations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_ledger_entries_idempotency_key",
        ),
    )
    op.create_index(
        op.f("ix_ledger_entries_entry_type"),
        "ledger_entries",
        ["entry_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ledger_entries_generation_id"),
        "ledger_entries",
        ["generation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ledger_entries_reservation_id"),
        "ledger_entries",
        ["reservation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ledger_entries_user_id"),
        "ledger_entries",
        ["user_id"],
        unique=False,
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION foxgen_forbid_ledger_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'ledger_entries is append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_ledger_entries_immutable
        BEFORE UPDATE OR DELETE ON ledger_entries
        FOR EACH ROW EXECUTE FUNCTION foxgen_forbid_ledger_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_ledger_entries_immutable ON ledger_entries")
    op.execute("DROP FUNCTION IF EXISTS foxgen_forbid_ledger_mutation()")

    op.drop_index(op.f("ix_ledger_entries_user_id"), table_name="ledger_entries")
    op.drop_index(op.f("ix_ledger_entries_reservation_id"), table_name="ledger_entries")
    op.drop_index(op.f("ix_ledger_entries_generation_id"), table_name="ledger_entries")
    op.drop_index(op.f("ix_ledger_entries_entry_type"), table_name="ledger_entries")
    op.drop_table("ledger_entries")

    op.drop_index(
        op.f("ix_balance_reservations_user_id"),
        table_name="balance_reservations",
    )
    op.drop_index(
        op.f("ix_balance_reservations_status"),
        table_name="balance_reservations",
    )
    op.drop_index(
        op.f("ix_balance_reservations_generation_id"),
        table_name="balance_reservations",
    )
    op.drop_table("balance_reservations")

    op.drop_index(op.f("ix_model_prices_model_slug"), table_name="model_prices")
    op.drop_index(op.f("ix_model_prices_enabled"), table_name="model_prices")
    op.drop_table("model_prices")
    op.drop_table("wallet_accounts")
