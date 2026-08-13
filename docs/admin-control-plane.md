# Administrative control plane

FoxGen implements one shared administrative domain layer through Telegram `/admin`, a signed backend HTTP API and a backend-only operator web surface. The public Mini App is intentionally outside this implementation.

## Architecture

```text
Telegram /admin ─────────────┐
                             │
Signed /internal/admin/* ────┼─> AdminPolicy
                             │      |
Backend operator UI ─────────┘      v
                                AdminServices
                                |    |    |
                                |    |    +-> immutable billing/admin ledger
                                |    +------> PostgreSQL domain state
                                +-----------> durable admin/support/campaign outboxes
                                                   |
                                                   v
                                               AdminWorker
```

Transports do not own independent write business logic.

## Security layers

A privileged UI is not an authorization mechanism. Every operation is revalidated server-side.

### RBAC

`AdminPolicy` is the common policy source. Current roles include:

- `superadmin`;
- `operator`;
- `support`;
- `moderator`;
- `finance`;
- `marketing`.

Durable administrators live in `admin_users` with role/scope state. `FOXGEN_ADMIN_SUPERUSER_IDS` bootstraps initial superadmin access and should be minimized after durable RBAC is established.

Every Telegram callback/FSM continuation, signed HTTP request and operator-web action resolves a fresh admin context and requires the relevant scope.

### Network allowlist

The signed API first checks `request.client.host` against CIDRs in:

```env
FOXGEN_ADMIN_NETWORK_ALLOWLIST=127.0.0.1/32,::1/128,172.16.0.0/12
```

Use the narrowest real backend subnet in production. Do not trust arbitrary `X-Forwarded-For` values for this check. Never set `0.0.0.0/0` merely to make an integration work.

The public reverse proxy must deny the whole admin prefix, for example:

```nginx
location ^~ /internal/admin/ {
    return 404;
}
```

Backend callers use the private service/VPC path.

### HMAC signature

Every `/internal/admin/*` request requires:

```text
X-Admin-User-Id
X-Request-Id
X-Admin-Timestamp
X-Admin-Signature
```

The signature is lowercase HMAC-SHA256 hex over exactly:

```text
<timestamp>\n<METHOD>\n<path>\n<request_id>\n<raw request body bytes>
```

The body must be the exact bytes sent. Do not parse JSON and reserialize after calculating the signature. Query parameters are not included in the current canonical string; the URL path is.

`FOXGEN_ADMIN_HMAC_MAX_SKEW_SECONDS` limits replay/stale requests.

### Write headers

All admin write routes require:

```text
Idempotency-Key
```

Routes classified as destructive/expensive additionally require:

```text
X-Admin-Confirm: CONFIRM
```

Confirmation is enforced by backend code, not merely a Telegram/web preview button.

## Command ledger and idempotency

Admin writes run through the command executor/repository. A durable command records fields equivalent to:

- admin user;
- request/correlation ID;
- action;
- target;
- request fingerprint/payload;
- response payload;
- command status;
- timestamps.

Behavior:

```text
same admin + action + Idempotency-Key + same request
    -> return stored result (replayed)

same admin + action + same key + changed request
    -> idempotency conflict
```

External side effects must not occur a second time merely because the HTTP client retried.

## Audit and redaction

Admin writes append audit records. Operator detail endpoints recursively redact sensitive fields whose keys contain terms such as:

```text
token
secret
password
authorization
api_key
webhook
callback
```

Do not put raw provider credentials into free-form reason/metadata fields. Redaction is a defense layer, not permission to store secrets in business payloads.

## Admin user/block enforcement

Blocking a user changes durable admin access state used by paid-generation admission. The transaction that admits a generation re-checks block status; the restriction does not rely on hiding Telegram buttons.

This protects against:

- old client state;
- direct internal API misuse with the blocked user ID;
- copied callbacks;
- stale UI.

## Runtime model controls

Administrative model availability is a runtime gate independent of the static provider registry readiness flags.

```text
registry production_ready
AND
runtime availability enabled
```

must both hold before paid admission. Operators can disable a failing model without deployment, while the reviewed provider contract remains intact for later re-enable.

## Durable support replies

A support reply request does not send Telegram as its sole effect inside the HTTP transaction.

The service commits:

```text
SupportMessage(status=queued)
SupportOutbox(status=pending)
```

The admin worker later claims and sends the reply.

Safe retry/dead-letter behavior follows the same non-idempotent boundary principle as other Telegram sends: ambiguous external acceptance must not intentionally create duplicate replies.

## Notification campaigns

Campaign start does not loop through recipients inside the HTTP request.

The service:

1. validates campaign/segment;
2. materializes recipient `NotificationDelivery` rows once;
3. moves the campaign into the appropriate running state;
4. returns the durable command result.

Workers then lease deliveries, apply `FOXGEN_ADMIN_NOTIFICATION_RATE_PER_SECOND`, retry safe failures and eventually complete/cancel/fail according to durable state.

## Payment recheck/reprocess

Admin payment operations are durable worker jobs.

Completed-payment credit uses:

```text
payment-credit:<provider>:<external_id>
```

as the immutable billing ledger idempotency key. Reprocessing the same payment cannot produce a second credit even when the admin command uses a new request/idempotency key.

A payment provider without a supported recheck adapter fails closed; the worker does not invent remote payment state.

## Safe operation replay

Admin replay creates an auditable child `OperationEvent`. The worker permits only explicitly safe local/non-billable replay classes, such as archive/delivery orchestration supported by current code.

Forbidden through replay:

```text
generation.submit
```

because it crosses the billable non-idempotent provider boundary.

## Versioned content/configuration

### Tariffs

Tariff publishing creates version history. Do not mutate historical published pricing in place.

### CMS

Documents own versions. Publishing a version does not overwrite prior published history.

### Runtime flags

Operational feature flags/model availability are mutable admin state and are audit/idempotency protected. They are not a replacement for reviewed code/config changes when provider contracts or schemas actually change.

## Telegram `/admin`

Telegram is a thin privileged shell around shared capabilities. Current panel groups include user/finance/payment/pricing/partner/promo/prompt/campaign/operational functionality and read-only diagnostics.

Requirements for every admin Telegram flow:

- authorize `/admin` entry;
- authorize every callback;
- authorize every FSM continuation;
- validate user input;
- use preview/confirmation for dangerous actions;
- call shared admin service/signed admin API rather than direct write SQL;
- preserve idempotency/correlation context.

A non-admin must be unable to execute an admin callback even when callback data is known exactly.

## Backend operator web

FoxGen includes a server-protected internal operator surface under `/internal/admin/ui` when:

```env
FOXGEN_ADMIN_WEB_ENABLED=true
```

It uses short-lived sessions plus the same underlying policy/services. This surface is for backend/operator access and must not be published as a public Mini App.

Future public/admin Mini App work must still revalidate every action server-side through the protected backend.

## Endpoint reference

See `api-reference.md` for the complete current `/internal/admin/*` route inventory, including:

- health/summary/users;
- payments/finance/tariffs;
- operations/timeline/replay/refund;
- support;
- CMS;
- notifications;
- partners/withdrawals;
- promos/prompts;
- runtime/model availability;
- moderation;
- audit/AI diagnostics/exports.

## Environment variables

```env
FOXGEN_ADMIN_API_ENABLED=false
FOXGEN_ADMIN_WEB_ENABLED=false
FOXGEN_ADMIN_HMAC_KEY=<dedicated-random-secret>
FOXGEN_ADMIN_HMAC_MAX_SKEW_SECONDS=300
FOXGEN_ADMIN_NETWORK_ALLOWLIST=127.0.0.1/32,::1/128,172.16.0.0/12
FOXGEN_ADMIN_SUPERUSER_IDS=<telegram-id>[,<telegram-id>...]
FOXGEN_ADMIN_SESSION_TTL_SECONDS=900
FOXGEN_ADMIN_WORKER_BATCH_SIZE=50
FOXGEN_ADMIN_WORKER_LEASE_SECONDS=120
FOXGEN_ADMIN_WORKER_MAX_ATTEMPTS=8
FOXGEN_ADMIN_NOTIFICATION_RATE_PER_SECOND=20
```

Use a dedicated admin HMAC secret. Do not reuse:

- Telegram bot token;
- ordinary internal API token;
- billing-admin token;
- KIE API key;
- KIE webhook HMAC key;
- storage/database credentials.

## Rollout order

1. Deploy code with admin API/web disabled.
2. Run `alembic upgrade head` and verify revision `20260813_0008` is applied.
3. Configure dedicated HMAC key and narrow backend CIDR allowlist.
4. Configure one bootstrap admin ID.
5. Verify public ingress returns 404/denial for `/internal/admin/health`.
6. Enable `FOXGEN_ADMIN_API_ENABLED=true`.
7. Restart/deploy API, bot and worker.
8. Test signed `/internal/admin/health` from the backend path.
9. Send `/admin` from the bootstrap admin.
10. Verify a regular user is denied from `/admin` and copied callback data.
11. Perform a controlled idempotent balance adjustment on a test account and inspect audit/ledger.
12. Test one support reply; verify durable outbox exists before worker send.
13. Test a campaign against one controlled recipient; verify one delivery row and one message.
14. Enable `FOXGEN_ADMIN_WEB_ENABLED=true` only if the backend operator surface is needed and its private network/session path is verified.
15. Migrate operational admin identity from environment bootstrap to durable `admin_users` according to team policy.

## Smoke checks

### Signed health

```text
GET /internal/admin/health
```

Expected success contains the authorized admin identity/role/request ID.

Negative cases that must fail:

- missing/invalid signature;
- raw body changed after signing;
- stale timestamp;
- source outside allowlist;
- regular/non-admin user;
- API disabled.

### Core operator reads

```text
GET /internal/admin/summary
GET /internal/admin/finance
GET /internal/admin/runtime
GET /internal/admin/audit
```

### Database health

Useful aggregates:

```sql
select status, count(*) from admin_commands group by status;
select action, outcome, count(*) from admin_audit_events group by action, outcome;
select status, count(*) from support_outbox group by status;
select status, count(*) from notification_deliveries group by status;
select status, count(*) from admin_outbox group by status;
```

Rising `dead_letter` counts require root-cause review before changing retry limits.

## Emergency containment

Fast containment usually does not require dropping schema/history.

1. Set `FOXGEN_ADMIN_API_ENABLED=false`.
2. Set `FOXGEN_ADMIN_WEB_ENABLED=false`.
3. Deploy/restart API and bot so no new admin commands are accepted.
4. If a campaign must stop, cancel it through the controlled path before disabling access where possible.
5. Keep audit/command/outbox tables for forensic evidence.
6. Investigate any in-flight admin worker jobs before changing their state.

## Rollback

Application rollback can disable the feature and revert application code while keeping durable admin tables/history.

Only execute schema downgrade removing the admin contour when all of these are true:

- no support reply is queued;
- no campaign/delivery is running/pending;
- no payment/admin outbox job must be retained;
- no audit/forensic history is required;
- rollback migration has been explicitly reviewed for the deployed data.

In normal production incidents, retaining schema and disabling routes is safer than deleting operational history.

## Incident rules

- Never bypass confirmation by calling a lower-level write path directly.
- Never expose admin HMAC/session tokens through a public frontend.
- Never broaden network allowlist as a debugging shortcut.
- Never directly mass-send campaign messages from a request handler.
- Never replay `generation.submit` through admin operation replay.
- Never reprocess a payment by inserting a second ledger credit manually.
- Never mutate historical tariff/CMS/audit/ledger rows simply to make the UI look correct.

## Related documents

- `admin-capability-matrix.md` — capability/status matrix;
- `api-reference.md` — route inventory;
- `configuration.md` — full env reference;
- `operations-runbook.md` — day-2 operations;
- `billing.md` — immutable financial invariants.