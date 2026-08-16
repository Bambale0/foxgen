import asyncio

from sqlalchemy import text

from foxgen.core.config import get_settings
from foxgen.infra.database import Database


REQUIRED_COLUMNS: dict[str, frozenset[str]] = {
    "users": frozenset({"id", "created_at"}),
    "generations": frozenset(
        {
            "id",
            "user_id",
            "status",
            "provider_task_id",
            "status_changed_at",
            "result_ready_at",
            "delivery_pending_at",
        }
    ),
    "outbox_events": frozenset(
        {"id", "event_type", "status", "attempts", "available_at", "dead_lettered_at"}
    ),
    "provider_events": frozenset({"id", "provider_task_id", "event_hash", "payload"}),
    "media_assets": frozenset(
        {"id", "generation_id", "status", "attempts", "next_retry_at", "storage_key"}
    ),
    "reference_assets": frozenset(
        {
            "id",
            "user_id",
            "storage_key",
            "content_type",
            "size_bytes",
            "checksum_sha256",
            "status",
            "created_at",
            "activated_at",
            "deleted_at",
        }
    ),
    "generation_deliveries": frozenset(
        {
            "id",
            "generation_id",
            "status",
            "attempts",
            "next_retry_at",
            "telegram_message_ids",
        }
    ),
    "wallet_accounts": frozenset({"user_id", "available_units", "reserved_units"}),
    "balance_reservations": frozenset({"generation_id", "status", "amount_units"}),
    "ledger_entries": frozenset({"idempotency_key", "entry_type", "available_delta"}),
    "admin_users": frozenset({"user_id", "role", "scopes", "active"}),
    "admin_commands": frozenset(
        {
            "id",
            "idempotency_key",
            "admin_user_id",
            "request_id",
            "action",
            "request_hash",
            "request_payload",
            "response_payload",
            "status",
        }
    ),
    "admin_audit_events": frozenset(
        {"id", "admin_user_id", "request_id", "action", "outcome", "payload"}
    ),
    "user_restrictions": frozenset({"user_id", "blocked", "reason", "updated_by"}),
    "tariff_versions": frozenset({"id", "version", "payload", "created_by"}),
    "payment_events": frozenset(
        {"id", "provider", "external_id", "user_id", "status", "credited_ledger_key"}
    ),
    "user_payment_orders": frozenset(
        {
            "id",
            "user_id",
            "provider",
            "idempotency_key",
            "request_hash",
            "package_code",
            "credits_units",
            "provider_amount",
            "provider_currency",
            "invoice_payload",
            "invoice_url",
            "status",
            "telegram_payment_charge_id",
            "credited_at",
        }
    ),
    "payment_refund_attempts": frozenset(
        {
            "id",
            "payment_id",
            "order_id",
            "user_id",
            "provider",
            "external_charge_id",
            "amount_units",
            "currency",
            "status",
            "attempts",
            "available_at",
            "locked_at",
            "debit_ledger_key",
            "restore_ledger_key",
            "attempted_at",
            "resolved_at",
        }
    ),
    "operation_events": frozenset(
        {"id", "parent_operation_id", "operation_type", "status", "payload"}
    ),
    "support_tickets": frozenset({"id", "user_id", "status", "assigned_admin_id"}),
    "support_messages": frozenset({"id", "ticket_id", "sender_kind", "body", "status"}),
    "support_outbox": frozenset(
        {"id", "message_id", "recipient_id", "status", "attempts", "available_at"}
    ),
    "cms_documents": frozenset({"id", "slug", "title", "published_version_id"}),
    "cms_document_versions": frozenset(
        {"id", "document_id", "version", "body", "created_by", "published_at"}
    ),
    "notification_campaigns": frozenset(
        {"id", "name", "message", "segment", "status", "created_by"}
    ),
    "notification_deliveries": frozenset(
        {"id", "campaign_id", "recipient_id", "status", "attempts", "available_at"}
    ),
    "admin_outbox": frozenset(
        {"id", "event_type", "target_id", "status", "attempts", "available_at"}
    ),
    "partner_profiles": frozenset({"user_id", "earned_units", "withdrawn_units"}),
    "partner_withdrawals": frozenset({"id", "user_id", "amount_units", "status"}),
    "promo_codes": frozenset({"code", "active", "reward_units", "uses"}),
    "promo_redemptions": frozenset(
        {"id", "promo_code", "user_id", "reward_units", "ledger_key", "redeemed_at"}
    ),
    "prompt_library_items": frozenset({"id", "title", "prompt", "status"}),
    "runtime_flags": frozenset({"key", "enabled", "value", "updated_by"}),
    "model_availability": frozenset({"model_slug", "enabled", "reason", "updated_by"}),
    "trend_items": frozenset({"id", "title", "payload", "active"}),
    "feed_moderation_actions": frozenset({"id", "content_id", "action", "active"}),
}


async def check_schema() -> None:
    database = Database(get_settings().database_url)
    try:
        async with database.engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        """
                        SELECT table_name, column_name
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                        """
                    )
                )
            ).all()
    finally:
        await database.close()

    actual: dict[str, set[str]] = {}
    for table_name, column_name in rows:
        actual.setdefault(str(table_name), set()).add(str(column_name))

    failures: list[str] = []
    for table_name, required_columns in REQUIRED_COLUMNS.items():
        if table_name not in actual:
            failures.append(f"missing table: {table_name}")
            continue
        missing = sorted(required_columns - actual[table_name])
        if missing:
            failures.append(f"{table_name}: missing columns {', '.join(missing)}")

    if failures:
        raise SystemExit("Schema smoke check failed:\n- " + "\n- ".join(failures))
    print(f"Schema smoke check passed for {len(REQUIRED_COLUMNS)} critical tables")


if __name__ == "__main__":
    asyncio.run(check_schema())