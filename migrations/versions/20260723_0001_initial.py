"""Initial users and generations tables.

Revision ID: 20260723_0001
Revises:
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260723_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

media_kind = sa.Enum("IMAGE", "VIDEO", "AUDIO", "CHAT", name="media_kind")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    media_kind.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "generations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("media_kind", media_kind, nullable=False),
        sa.Column("model_slug", sa.String(length=128), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider_task_id", sa.String(length=255), nullable=True),
        sa.Column("input_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_task_id"),
    )
    op.create_index(op.f("ix_generations_status"), "generations", ["status"], unique=False)
    op.create_index(op.f("ix_generations_user_id"), "generations", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_generations_user_id"), table_name="generations")
    op.drop_index(op.f("ix_generations_status"), table_name="generations")
    op.drop_table("generations")
    op.drop_table("users")
    media_kind.drop(op.get_bind(), checkfirst=True)
