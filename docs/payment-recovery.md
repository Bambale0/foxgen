# Unified YooKassa payment processing

The merchant cabinet must send `payment.succeeded` and `payment.canceled` notifications to **https://api.happy-fox.online/yookassa/webhook**. The legacy `/webhook/yookassa` URL runs the same dispatcher. Only one cabinet URL is needed for Telegram and MAX. Basic Auth credentials cannot read or publish cabinet notification settings; a cabinet operator must verify the saved URL and events. See [YooKassa notifications](https://yookassa.ru/developers/using-api/webhooks).

Incoming bodies provide a payment ID, never an authoritative channel, buyer, amount or balance. The dispatcher finds the local order and fetches the current provider object. Existing provider IDs take precedence over metadata. Successful credit requires `status=succeeded`, `paid=true`, matching ID, local order and amount, and RUB currency. `waiting_for_capture` never credits. An unavailable provider/database returns 503 so YooKassa retries; unknown or invalid verified orders are logged and never credited. Ambiguous cross-channel ownership returns 409. MAX metadata additionally matches its native buyer and product.

Both webhook and reconciliation share completion services. PostgreSQL locks the payment row; SQLite uses an immediate transaction. Buyer credits, referral rewards, promo usage, completion and notification intents commit together. Telegram and MAX keep separate native identities and wallets. Telegram partner commissions remain RUB; MAX commissions remain credits, converted through the shared policy. This change does not infer account links or merge historical money.

Checkout ownership and a durable creation snapshot are saved before the external POST. Reconciliation replays the identical snapshot and stable idempotence key after an ambiguous response, for at most 23 hours. YooKassa retains idempotence keys for 24 hours; older ambiguous orders remain pending and emit `manual_reconciliation_required`. Resolve these through provider history and the actual payment ID; never create another provider payment for the old order. A succeeded webhook can recover a missing ID from provider-confirmed metadata. Reconciliation rotates its bounded batches so unresolved old orders do not hide newer payments.

## Administrative policy

The existing authenticated, actor-audited, versioned tariffs API publishes `business_rules` alongside prices. Existing snapshots without this key receive bundled defaults. Fields and their defaults are in `bot/business_rules_defaults.json`; validation rejects unknown fields, non-finite values, invalid percentages, retry bounds, bonus maps and template placeholders. A completion snapshots monetary policy once. Historical finance reports use recorded commission amounts and rates rather than current tariffs. Partner screens display current shared rates.

Fields include first/second referral percentages, signup/inviter bonuses, MAX RUB-per-credit conversion, package promo bonuses, notification retry attempts/delays/poll interval and buyer/referrer templates. Preserve the entire price snapshot when publishing. Changed rates apply to future completions; they do not recalculate historical balances.

## Delivery and readiness

`payment_notification_outbox` stores channel, local order key, recipient, message, status, attempts, next attempt and last error type. Sends have a 60-second deadline and a 120-second claim lease. Transient errors use configured bounded exponential retries. Delivered rows are not sent again. A process crash after transport acceptance but before delivery commit can repeat a message: transport delivery is at least once, while financial credit remains exactly once. Exhausted retries become `failed` and remain visible for reconciliation. Disabled channels do not block active channel batches. No direct post-commit YooKassa send bypasses this queue.

Telemetry: `payment_webhook`, `payment_checkout`, `payment_delivery`, with channel/order/outcome and safe error type. `/health` retains its configured access gate and reports revision, database, Redis and payment worker liveness; dependency or worker failure returns 503.

Read-only operational queries:

```sql
SELECT channel,status,COUNT(*) FROM payment_notification_outbox GROUP BY channel,status;
SELECT channel,order_id,attempts,last_error FROM payment_notification_outbox WHERE status='failed';
SELECT order_id,status FROM transactions WHERE provider='yookassa' AND status='pending';
SELECT order_id,status FROM max_payment_orders WHERE status IN ('created','pending');
```

## Migration and release

Migration 3 adds checkout intents, promo redemption and delivery tables without deleting old schema or balances. Run the registered migrations before channel/delivery contexts. Existing pending orders with known IDs use the new path; legacy orders with missing IDs and no creation snapshot cannot be recreated safely. Historical completed orders do not receive unsolicited backfilled notifications. Rollback retains expanded tables and ledger data; pause the new delivery worker when rolling back rather than deleting records.

CI includes real PostgreSQL concurrency with 16 simultaneous completions for each channel, provider final-state checks, ownership mismatch, HTTP duplicate routing, atomic failure recovery, durable creation bounds, promo redemption and notification retries. Browser tests use mocked bridge/API data and do not establish successful live payment delivery. Native Telegram/MAX payment confirmation and cabinet configuration require separate external evidence.
