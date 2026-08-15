"""Add durable user-owned reference memory.

Revision ID: 20260815_0010
Revises: 20260814_0009
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260815_0010"
down_revision: str | None = "20260814_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reference_assets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="uploading"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("storage_key", name="uq_reference_assets_storage_key"),
        sa.CheckConstraint("size_bytes > 0", name="ck_reference_assets_size_positive"),
        sa.CheckConstraint(
            "status IN ('uploading', 'active', 'delete_pending', 'deleted', 'failed')",
            name="ck_reference_assets_status",
        ),
    )
    op.create_index("ix_reference_assets_user_id", "reference_assets", ["user_id"])
    op.create_index("ix_reference_assets_status", "reference_assets", ["status"])
    op.create_index("ix_reference_assets_created_at", "reference_assets", ["created_at"])
    op.create_index(
        "ix_reference_assets_user_status_created",
        "reference_assets",
        ["user_id", "status", "created_at"],
    )
    op.create_index(
        "ix_reference_assets_user_checksum",
        "reference_assets",
        ["user_id", "checksum_sha256"],
    )


def downgrade() -> None:
    op.drop_index("ix_reference_assets_user_checksum", table_name="reference_assets")
    op.drop_index("ix_reference_assets_user_status_created", table_name="reference_assets")
    op.drop_index("ix_reference_assets_created_at", table_name="reference_assets")
    op.drop_index("ix_reference_assets_status", table_name="reference_assets")
    op.drop_index("ix_reference_assets_user_id", table_name="reference_assets")
    op.drop_table("reference_assets")
