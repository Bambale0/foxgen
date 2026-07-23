"""Add durable media archive and Telegram delivery state.

Revision ID: 20260723_0004
Revises: 20260723_0003
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260723_0004"
down_revision: str | None = "20260723_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "media_assets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("generation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
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
            "status IN ('pending', 'stored', 'failed')",
            name="ck_media_assets_status",
        ),
        sa.ForeignKeyConstraint(
            ["generation_id"],
            ["generations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "generation_id",
            "source_url",
            name="uq_media_assets_generation_id_source_url",
        ),
        sa.UniqueConstraint("storage_key", name="uq_media_assets_storage_key"),
    )
    op.create_index(
        op.f("ix_media_assets_generation_id"),
        "media_assets",
        ["generation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_media_assets_status"),
        "media_assets",
        ["status"],
        unique=False,
    )

    op.create_table(
        "generation_deliveries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("generation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "telegram_message_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('pending', 'sending', 'sent', 'delivery_unknown', 'failed')",
            name="ck_generation_deliveries_status",
        ),
        sa.ForeignKeyConstraint(
            ["generation_id"],
            ["generations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "generation_id",
            name="uq_generation_deliveries_generation_id",
        ),
    )
    op.create_index(
        op.f("ix_generation_deliveries_generation_id"),
        "generation_deliveries",
        ["generation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_generation_deliveries_status"),
        "generation_deliveries",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_generation_deliveries_status"),
        table_name="generation_deliveries",
    )
    op.drop_index(
        op.f("ix_generation_deliveries_generation_id"),
        table_name="generation_deliveries",
    )
    op.drop_table("generation_deliveries")

    op.drop_index(op.f("ix_media_assets_status"), table_name="media_assets")
    op.drop_index(op.f("ix_media_assets_generation_id"), table_name="media_assets")
    op.drop_table("media_assets")
