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
