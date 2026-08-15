"""Add publication feed, profile, comments, likes and remix lineage.

Revision ID: 20260814_0009
Revises: 20260813_0008
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260814_0009"
down_revision: str | None = "20260813_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "public_profiles",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=True),
        sa.Column("bio", sa.String(length=500), nullable=True),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("slug", name="uq_public_profiles_slug"),
    )
    op.create_index("ix_public_profiles_slug", "public_profiles", ["slug"], unique=True)

    op.create_table(
        "publications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("generation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
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
        sa.CheckConstraint("scope IN ('feed', 'profile')", name="ck_publications_scope"),
        sa.ForeignKeyConstraint(["generation_id"], ["generations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("generation_id", "scope", name="uq_publications_generation_scope"),
    )
    op.create_index(
        "ix_publications_scope_active_created",
        "publications",
        ["scope", "active", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_publications_user_scope_created",
        "publications",
        ["user_id", "scope", "created_at"],
        unique=False,
    )

    op.create_table(
        "generation_lineage",
        sa.Column("generation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_publication_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["generation_id"], ["generations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_publication_id"],
            ["publications.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("generation_id"),
    )
    op.create_index(
        "ix_generation_lineage_source_publication_id",
        "generation_lineage",
        ["source_publication_id"],
        unique=False,
    )

    op.create_table(
        "publication_likes",
        sa.Column("publication_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["publication_id"], ["publications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("publication_id", "user_id"),
    )
    op.create_index(
        "ix_publication_likes_user_id",
        "publication_likes",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "publication_comments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("publication_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("surface", sa.String(length=16), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("body", sa.String(length=1000), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "surface IN ('feed', 'profile')",
            name="ck_publication_comments_surface",
        ),
        sa.CheckConstraint(
            "length(trim(body)) BETWEEN 1 AND 1000",
            name="ck_publication_comments_body",
        ),
        sa.ForeignKeyConstraint(["publication_id"], ["publications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_publication_comments_publication_surface_created",
        "publication_comments",
        ["publication_id", "surface", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_publication_comments_publication_surface_created",
        table_name="publication_comments",
    )
    op.drop_table("publication_comments")
    op.drop_index("ix_publication_likes_user_id", table_name="publication_likes")
    op.drop_table("publication_likes")
    op.drop_index(
        "ix_generation_lineage_source_publication_id",
        table_name="generation_lineage",
    )
    op.drop_table("generation_lineage")
    op.drop_index("ix_publications_user_scope_created", table_name="publications")
    op.drop_index("ix_publications_scope_active_created", table_name="publications")
    op.drop_table("publications")
    op.drop_index("ix_public_profiles_slug", table_name="public_profiles")
    op.drop_table("public_profiles")
