"""Restore the database default for generation status timestamps.

Revision ID: 20260817_0018
Revises: 20260817_0017
Create Date: 2026-08-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260817_0018"
down_revision: str | None = "20260817_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Migration 0006 made status_changed_at NOT NULL after backfilling existing rows,
    # but did not retain the server default declared by the ORM model. Core INSERTs
    # that omit the column therefore fail before billing admission can roll back
    # cleanly. Keep PostgreSQL and the mapped model in sync.
    op.execute("ALTER TABLE generations ALTER COLUMN status_changed_at SET DEFAULT now()")


def downgrade() -> None:
    op.execute("ALTER TABLE generations ALTER COLUMN status_changed_at DROP DEFAULT")
