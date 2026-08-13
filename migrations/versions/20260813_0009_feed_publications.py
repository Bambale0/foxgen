"""Add feed/profile publication domain.

Revision ID: 20260813_0009
Revises: 20260813_0008
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260813_0009"
down_revision: str | None = "20260813_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def uuid_pk() -> sa.Column[object]:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def created_at() -> sa.Column[object]:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


def updated_at() -> sa.Column[object]:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


def upgrade() -> None:
    op.create_table(
        "user_profiles",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
            autoincrement=False,
        ),
        sa.Column("public_slug", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(80), nullable=False),
        sa.Column("avatar_url", sa.String(1000), nullable=True),
        sa.Column("bio", sa.String(500), nullable=True),
        created_at(),
        updated_at(),
        sa.UniqueConstraint("public_slug", name="uq_user_profiles_public_slug"),
    )
    op.create_index("ix_user_profiles_public_slug", "user_profiles", ["public_slug"])

    op.create_table(
        "publications",
        uuid_pk(),
        sa.Column(
            "generation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("generations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="published"),
        sa.Column(
            "prompt_visible",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("unpublished_at", sa.DateTime(timezone=True), nullable=True),
        created_at(),
        updated_at(),
        sa.UniqueConstraint(
            "generation_id",
            "scope",
            name="uq_publications_generation_scope",
        ),
        sa.CheckConstraint(
            "scope IN ('feed', 'profile')",
            name="ck_publications_scope",
        ),
        sa.CheckConstraint(
            "status IN ('published', 'unpublished')",
            name="ck_publications_status",
        ),
    )
    op.create_index("ix_publications_generation_id", "publications", ["generation_id"])
    op.create_index("ix_publications_author_user_id", "publications", ["author_user_id"])
    op.create_index("ix_publications_scope", "publications", ["scope"])
    op.create_index("ix_publications_status", "publications", ["status"])
    op.create_index("ix_publications_published_at", "publications", ["published_at"])
    op.create_index(
        "ix_publications_surface_listing",
        "publications",
        ["scope", "status", "published_at"],
    )
    op.create_index(
        "ix_publications_author_surface_listing",
        "publications",
        ["author_user_id", "scope", "status", "published_at"],
    )

    op.create_table(
        "generation_derivatives",
        sa.Column(
            "derived_generation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("generations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "source_publication_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("publications.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False, server_default="remix"),
        created_at(),
        sa.CheckConstraint(
            "kind IN ('remix')",
            name="ck_generation_derivatives_kind",
        ),
    )
    op.create_index(
        "ix_generation_derivatives_source_publication_id",
        "generation_derivatives",
        ["source_publication_id"],
    )

    op.create_table(
        "publication_likes",
        uuid_pk(),
        sa.Column(
            "publication_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("publications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        created_at(),
        sa.UniqueConstraint(
            "publication_id",
            "user_id",
            name="uq_publication_likes_publication_user",
        ),
    )
    op.create_index("ix_publication_likes_publication_id", "publication_likes", ["publication_id"])
    op.create_index("ix_publication_likes_user_id", "publication_likes", ["user_id"])

    op.create_table(
        "publication_comments",
        uuid_pk(),
        sa.Column(
            "publication_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("publications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("surface", sa.String(16), nullable=False),
        sa.Column("text", sa.String(300), nullable=False),
        created_at(),
        sa.CheckConstraint(
            "surface IN ('feed', 'profile')",
            name="ck_publication_comments_surface",
        ),
    )
    op.create_index(
        "ix_publication_comments_publication_id",
        "publication_comments",
        ["publication_id"],
    )
    op.create_index("ix_publication_comments_user_id", "publication_comments", ["user_id"])
    op.create_index("ix_publication_comments_surface", "publication_comments", ["surface"])
    op.create_index("ix_publication_comments_created_at", "publication_comments", ["created_at"])
    op.create_index(
        "ix_publication_comments_surface_listing",
        "publication_comments",
        ["publication_id", "surface", "created_at"],
    )

    op.create_table(
        "publication_share_events",
        uuid_pk(),
        sa.Column(
            "publication_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("publications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("surface", sa.String(16), nullable=False),
        created_at(),
        sa.CheckConstraint(
            "surface IN ('feed', 'profile')",
            name="ck_publication_share_events_surface",
        ),
    )
    op.create_index(
        "ix_publication_share_events_publication_id",
        "publication_share_events",
        ["publication_id"],
    )
    op.create_index(
        "ix_publication_share_events_user_id",
        "publication_share_events",
        ["user_id"],
    )
    op.create_index(
        "ix_publication_share_events_surface",
        "publication_share_events",
        ["surface"],
    )
    op.create_index(
        "ix_publication_share_events_created_at",
        "publication_share_events",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_publication_share_events_created_at", table_name="publication_share_events")
    op.drop_index("ix_publication_share_events_surface", table_name="publication_share_events")
    op.drop_index("ix_publication_share_events_user_id", table_name="publication_share_events")
    op.drop_index("ix_publication_share_events_publication_id", table_name="publication_share_events")
    op.drop_table("publication_share_events")

    op.drop_index("ix_publication_comments_surface_listing", table_name="publication_comments")
    op.drop_index("ix_publication_comments_created_at", table_name="publication_comments")
    op.drop_index("ix_publication_comments_surface", table_name="publication_comments")
    op.drop_index("ix_publication_comments_user_id", table_name="publication_comments")
    op.drop_index("ix_publication_comments_publication_id", table_name="publication_comments")
    op.drop_table("publication_comments")

    op.drop_index("ix_publication_likes_user_id", table_name="publication_likes")
    op.drop_index("ix_publication_likes_publication_id", table_name="publication_likes")
    op.drop_table("publication_likes")

    op.drop_index(
        "ix_generation_derivatives_source_publication_id",
        table_name="generation_derivatives",
    )
    op.drop_table("generation_derivatives")

    op.drop_index("ix_publications_author_surface_listing", table_name="publications")
    op.drop_index("ix_publications_surface_listing", table_name="publications")
    op.drop_index("ix_publications_published_at", table_name="publications")
    op.drop_index("ix_publications_status", table_name="publications")
    op.drop_index("ix_publications_scope", table_name="publications")
    op.drop_index("ix_publications_author_user_id", table_name="publications")
    op.drop_index("ix_publications_generation_id", table_name="publications")
    op.drop_table("publications")

    op.drop_index("ix_user_profiles_public_slug", table_name="user_profiles")
    op.drop_table("user_profiles")
