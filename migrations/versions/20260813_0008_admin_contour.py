"""Add the full administrative control-plane schema.

Revision ID: 20260813_0008
Revises: 20260725_0007
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260813_0008"
down_revision: str | None = "20260725_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def uuid_pk() -> sa.Column[object]:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def created_at(*, indexed: bool = False) -> sa.Column[object]:
    del indexed
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
        "admin_users",
        sa.Column("user_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="operator"),
        sa.Column(
            "scopes", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        created_at(),
        updated_at(),
    )
    op.create_index("ix_admin_users_active", "admin_users", ["active"])

    op.create_table(
        "admin_commands",
        uuid_pk(),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("admin_user_id", sa.BigInteger(), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("target_id", sa.String(255), nullable=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column(
            "request_payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("response_payload", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="reserved"),
        sa.Column("error_code", sa.String(64), nullable=True),
        created_at(),
        updated_at(),
        sa.UniqueConstraint(
            "admin_user_id",
            "action",
            "idempotency_key",
            name="uq_admin_commands_actor_action_key",
        ),
        sa.CheckConstraint(
            "status IN ('reserved', 'succeeded', 'failed')",
            name="ck_admin_commands_status",
        ),
    )
    op.create_index("ix_admin_commands_admin_user_id", "admin_commands", ["admin_user_id"])
    op.create_index("ix_admin_commands_request_id", "admin_commands", ["request_id"])
    op.create_index("ix_admin_commands_action", "admin_commands", ["action"])
    op.create_index("ix_admin_commands_target_id", "admin_commands", ["target_id"])

    op.create_table(
        "admin_audit_events",
        uuid_pk(),
        sa.Column("admin_user_id", sa.BigInteger(), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("target_id", sa.String(255), nullable=True),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        created_at(),
    )
    op.create_index("ix_admin_audit_events_admin_user_id", "admin_audit_events", ["admin_user_id"])
    op.create_index("ix_admin_audit_events_request_id", "admin_audit_events", ["request_id"])
    op.create_index("ix_admin_audit_events_action", "admin_audit_events", ["action"])
    op.create_index("ix_admin_audit_events_target_id", "admin_audit_events", ["target_id"])
    op.create_index("ix_admin_audit_events_created_at", "admin_audit_events", ["created_at"])

    op.create_table(
        "user_restrictions",
        sa.Column("user_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("blocked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("source", sa.String(32), nullable=False, server_default="admin"),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True),
        updated_at(),
    )
    op.create_index("ix_user_restrictions_blocked", "user_restrictions", ["blocked"])

    op.create_table(
        "tariff_versions",
        uuid_pk(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column(
            "published_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        created_at(),
        sa.UniqueConstraint("version", name="uq_tariff_versions_version"),
        sa.CheckConstraint("version > 0", name="ck_tariff_versions_positive"),
    )
    op.create_index("ix_tariff_versions_published_at", "tariff_versions", ["published_at"])

    op.create_table(
        "payment_events",
        uuid_pk(),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("amount_units", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(16), nullable=False, server_default="CREDIT"),
        sa.Column("credited_ledger_key", sa.String(255), nullable=True, unique=True),
        sa.Column(
            "raw_payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        created_at(),
        updated_at(),
        sa.UniqueConstraint("provider", "external_id", name="uq_payment_events_provider_external"),
        sa.CheckConstraint("amount_units >= 0", name="ck_payment_events_amount_nonnegative"),
    )
    op.create_index("ix_payment_events_provider", "payment_events", ["provider"])
    op.create_index("ix_payment_events_external_id", "payment_events", ["external_id"])
    op.create_index("ix_payment_events_user_id", "payment_events", ["user_id"])
    op.create_index("ix_payment_events_status", "payment_events", ["status"])
    op.create_index("ix_payment_events_created_at", "payment_events", ["created_at"])

    op.create_table(
        "operation_events",
        uuid_pk(),
        sa.Column(
            "generation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("generations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "parent_operation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("operation_events.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("operation_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        created_at(),
    )
    op.create_index("ix_operation_events_generation_id", "operation_events", ["generation_id"])
    op.create_index(
        "ix_operation_events_parent_operation_id", "operation_events", ["parent_operation_id"]
    )
    op.create_index("ix_operation_events_operation_type", "operation_events", ["operation_type"])
    op.create_index("ix_operation_events_status", "operation_events", ["status"])
    op.create_index("ix_operation_events_created_at", "operation_events", ["created_at"])

    op.create_table(
        "support_tickets",
        uuid_pk(),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("assigned_admin_id", sa.BigInteger(), nullable=True),
        sa.Column("priority", sa.String(16), nullable=False, server_default="normal"),
        sa.Column("operator_note", sa.Text(), nullable=True),
        created_at(),
        updated_at(),
        sa.CheckConstraint(
            "status IN ('open', 'pending', 'resolved', 'closed')",
            name="ck_support_tickets_status",
        ),
    )
    op.create_index("ix_support_tickets_user_id", "support_tickets", ["user_id"])
    op.create_index("ix_support_tickets_status", "support_tickets", ["status"])
    op.create_index(
        "ix_support_tickets_assigned_admin_id", "support_tickets", ["assigned_admin_id"]
    )
    op.create_index("ix_support_tickets_created_at", "support_tickets", ["created_at"])

    op.create_table(
        "support_messages",
        uuid_pk(),
        sa.Column(
            "ticket_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("support_tickets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sender_kind", sa.String(16), nullable=False),
        sa.Column("sender_id", sa.BigInteger(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="stored"),
        created_at(),
    )
    op.create_index("ix_support_messages_ticket_id", "support_messages", ["ticket_id"])
    op.create_index("ix_support_messages_created_at", "support_messages", ["created_at"])

    op.create_table(
        "support_outbox",
        uuid_pk(),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("support_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("recipient_id", sa.BigInteger(), nullable=False),
        sa.Column("deduplication_key", sa.String(255), nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        created_at(),
        sa.UniqueConstraint("deduplication_key", name="uq_support_outbox_deduplication_key"),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'retry_wait', 'sent', 'dead_letter')",
            name="ck_support_outbox_status",
        ),
    )
    op.create_index("ix_support_outbox_message_id", "support_outbox", ["message_id"])
    op.create_index("ix_support_outbox_recipient_id", "support_outbox", ["recipient_id"])
    op.create_index("ix_support_outbox_status", "support_outbox", ["status"])
    op.create_index("ix_support_outbox_available_at", "support_outbox", ["available_at"])

    op.create_table(
        "cms_documents",
        uuid_pk(),
        sa.Column("slug", sa.String(128), nullable=False, unique=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("published_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        created_at(),
        updated_at(),
    )
    op.create_index("ix_cms_documents_slug", "cms_documents", ["slug"])

    op.create_table(
        "cms_document_versions",
        uuid_pk(),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cms_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        created_at(),
        sa.UniqueConstraint(
            "document_id",
            "version",
            name="uq_cms_document_versions_document_version",
        ),
        sa.CheckConstraint("version > 0", name="ck_cms_document_versions_positive"),
    )
    op.create_index(
        "ix_cms_document_versions_document_id", "cms_document_versions", ["document_id"]
    )

    op.create_table(
        "notification_campaigns",
        uuid_pk(),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "segment", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        created_at(),
        sa.CheckConstraint(
            "status IN ('draft', 'ready', 'running', 'completed', 'cancelled')",
            name="ck_notification_campaigns_status",
        ),
    )
    op.create_index("ix_notification_campaigns_status", "notification_campaigns", ["status"])
    op.create_index(
        "ix_notification_campaigns_created_at", "notification_campaigns", ["created_at"]
    )

    op.create_table(
        "notification_deliveries",
        uuid_pk(),
        sa.Column(
            "campaign_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("notification_campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("recipient_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        created_at(),
        sa.UniqueConstraint(
            "campaign_id",
            "recipient_id",
            name="uq_notification_deliveries_campaign_recipient",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'retry_wait', 'sent', 'failed')",
            name="ck_notification_deliveries_status",
        ),
    )
    op.create_index(
        "ix_notification_deliveries_campaign_id", "notification_deliveries", ["campaign_id"]
    )
    op.create_index(
        "ix_notification_deliveries_recipient_id", "notification_deliveries", ["recipient_id"]
    )
    op.create_index("ix_notification_deliveries_status", "notification_deliveries", ["status"])
    op.create_index(
        "ix_notification_deliveries_available_at", "notification_deliveries", ["available_at"]
    )

    op.create_table(
        "admin_outbox",
        uuid_pk(),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("target_id", sa.String(255), nullable=False),
        sa.Column("deduplication_key", sa.String(255), nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        created_at(),
        sa.UniqueConstraint("deduplication_key", name="uq_admin_outbox_deduplication_key"),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'retry_wait', 'completed', 'dead_letter')",
            name="ck_admin_outbox_status",
        ),
    )
    op.create_index("ix_admin_outbox_event_type", "admin_outbox", ["event_type"])
    op.create_index("ix_admin_outbox_target_id", "admin_outbox", ["target_id"])
    op.create_index("ix_admin_outbox_status", "admin_outbox", ["status"])
    op.create_index("ix_admin_outbox_available_at", "admin_outbox", ["available_at"])

    op.create_table(
        "partner_profiles",
        sa.Column("user_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("earned_units", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("withdrawn_units", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("referrals_count", sa.Integer(), nullable=False, server_default="0"),
        created_at(),
        updated_at(),
    )

    op.create_table(
        "partner_withdrawals",
        uuid_pk(),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("amount_units", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("destination", sa.String(255), nullable=True),
        sa.Column("reviewed_by", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        created_at(),
        sa.CheckConstraint("amount_units > 0", name="ck_partner_withdrawals_positive"),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'paid', 'rejected')",
            name="ck_partner_withdrawals_status",
        ),
    )
    op.create_index("ix_partner_withdrawals_user_id", "partner_withdrawals", ["user_id"])
    op.create_index("ix_partner_withdrawals_status", "partner_withdrawals", ["status"])
    op.create_index("ix_partner_withdrawals_created_at", "partner_withdrawals", ["created_at"])

    op.create_table(
        "promo_codes",
        sa.Column("code", sa.String(64), primary_key=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("reward_units", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("max_uses", sa.Integer(), nullable=True),
        sa.Column("uses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        created_at(),
    )
    op.create_index("ix_promo_codes_active", "promo_codes", ["active"])

    op.create_table(
        "prompt_library_items",
        uuid_pk(),
        sa.Column("author_user_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("moderation_reason", sa.Text(), nullable=True),
        sa.Column("moderated_by", sa.BigInteger(), nullable=True),
        sa.Column("moderated_at", sa.DateTime(timezone=True), nullable=True),
        created_at(),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'inactive')",
            name="ck_prompt_library_items_status",
        ),
    )
    op.create_index(
        "ix_prompt_library_items_author_user_id", "prompt_library_items", ["author_user_id"]
    )
    op.create_index("ix_prompt_library_items_status", "prompt_library_items", ["status"])
    op.create_index("ix_prompt_library_items_created_at", "prompt_library_items", ["created_at"])

    op.create_table(
        "runtime_flags",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "value", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        updated_at(),
    )

    op.create_table(
        "model_availability",
        sa.Column("model_slug", sa.String(128), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        updated_at(),
    )
    op.create_index("ix_model_availability_enabled", "model_availability", ["enabled"])

    op.create_table(
        "trend_items",
        uuid_pk(),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        created_at(),
    )
    op.create_index("ix_trend_items_active", "trend_items", ["active"])

    op.create_table(
        "feed_moderation_actions",
        uuid_pk(),
        sa.Column("content_id", sa.String(255), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        created_at(),
    )
    op.create_index(
        "ix_feed_moderation_actions_content_id", "feed_moderation_actions", ["content_id"]
    )
    op.create_index("ix_feed_moderation_actions_action", "feed_moderation_actions", ["action"])
    op.create_index("ix_feed_moderation_actions_active", "feed_moderation_actions", ["active"])
    op.create_index(
        "ix_feed_moderation_actions_created_at", "feed_moderation_actions", ["created_at"]
    )


def downgrade() -> None:
    for table in (
        "feed_moderation_actions",
        "trend_items",
        "model_availability",
        "runtime_flags",
        "prompt_library_items",
        "promo_codes",
        "partner_withdrawals",
        "partner_profiles",
        "admin_outbox",
        "notification_deliveries",
        "notification_campaigns",
        "cms_document_versions",
        "cms_documents",
        "support_outbox",
        "support_messages",
        "support_tickets",
        "operation_events",
        "payment_events",
        "tariff_versions",
        "user_restrictions",
        "admin_audit_events",
        "admin_commands",
        "admin_users",
    ):
        op.drop_table(table)
