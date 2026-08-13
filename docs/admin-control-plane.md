# Administrative control plane

FoxGen implements one shared administrative domain layer through the registered Telegram `/admin`, signed backend HTTP API and backend-only operator web surface. The public Mini App is intentionally outside this implementation.

Prepared extension modules also exist in the source tree but are not yet registered by runtime entrypoints. They are tracked by issue #55 and are documented separately so source-file presence is not confused with production reachability.

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

## Server-side authorization

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

Every registered Telegram admin callback/FSM continuation, signed HTTP request and operator-web action resolves a fresh admin context and requires the relevant scope.

## Network allowlist

The signed API first checks `request.client.host` against CIDRs in:

```env
FOXGEN_ADMIN_NETWORK_ALLOWLIST=127.0.0.1/32,::1/128,172.16.0.0/12
```

Use the narrowest real backend subnet in production. Do not trust arbitrary `X-Forwarded-For` values for this check. Never set `0.0.0.0/0` merely to make an integration work.

Public reverse proxy must deny the whole admin prefix, for example:

```nginx
location ^~ /internal/admin/ {
    return 404;
}
```

Backend callers use the private service/VPC path.

## HMAC signature

Registered machine routes under `/internal/admin/*` require:

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

`FOXGEN_ADMIN_HMAC_MAX_SKEW_SECONDS` limits stale/replay requests.

## Write safety

All registered admin write routes require:

```text
Idempotency-Key
```

Routes classified as destructive/expensive additionally require:

```text
X-Admin-Confirm: CONFIRM
```

Confirmation is enforced by backend code, not merely a Telegram/web preview button.

## Command ledger and idempotency

Admin writes run through the command executor/repository. A durable command records:

- admin user;
- request/correlation ID;
- action and target;
- request fingerprint/payload;
- response payload/error;
- command status and timestamps.

Behavior:

```text
same admin + action + Idempotency-Key + same request
    -> stored result (replayed)

same admin + action + same key + changed request
    -> idempotency conflict
```

External side effects must not occur twice merely because an HTTP/Telegram client retried.

## Audit and redaction

Admin writes append audit records. Operator output recursively redacts sensitive fields whose keys contain terms such as:

```text
token
secret
password
authorization
api_key
webhook
callback
```

Redaction is a defense layer, not permission to store raw credentials in arbitrary reason/metadata fields.

## User restriction enforcement

Blocking a user changes durable restriction state used by paid-generation admission. The transaction that admits a generation re-checks block status; the restriction does not rely on hiding Telegram controls.

This protects against stale client state, copied callbacks and direct internal API attempts using a blocked user ID.

## Runtime model controls

Administrative model availability is independent of static provider-registry readiness:

```text
registry production_ready
AND
runtime availability enabled
```

must both hold before paid admission. A failing model can therefore be disabled without deployment while keeping its reviewed contract intact.

## Durable support replies

A support reply request does not send Telegram as its sole side effect inside the request transaction.

The service commits:

```text
SupportMessage(status=queued)
SupportOutbox(status=pending)
```

The admin worker later claims and sends the reply. Ambiguous external acceptance must not intentionally create duplicate replies.

## Notification campaigns

Campaign start does not iterate and send recipients inside the HTTP request.

The service:

1. validates campaign/segment;
2. materializes `NotificationDelivery` recipients once;
3. commits campaign state;
4. returns the durable command result.

Workers lease deliveries, apply `FOXGEN_ADMIN_NOTIFICATION_RATE_PER_SECOND`, retry safe failures and converge campaign state.

## Payment recheck/reprocess

Admin payment operations are durable worker jobs. Completed-payment credit uses:

```text
payment-credit:<provider>:<external_id>
```

as the immutable billing-ledger idempotency key. Reprocessing the same payment cannot produce a second effective credit even when another admin request uses a new command key.

A provider without a supported recheck adapter fails closed rather than inventing remote state.

## Safe operation replay

Admin replay creates an auditable child `OperationEvent`. The worker permits only explicitly safe local/non-billable replay classes supported by current code.

Forbidden through replay:

```text
generation.submit
```

because it crosses the billable non-idempotent provider boundary.

## Versioned content/configuration

### Tariffs

Tariff publishing creates immutable/versioned history. Do not overwrite historical published commercial state in place.

### CMS

Documents own versions. Publishing one version does not rewrite prior published history.

### Runtime flags

Feature flags/model availability are mutable operational state protected by policy, audit and idempotency. They are not a replacement for code/provider-contract changes when schemas actually change.

## Registered Telegram `/admin`

The current main admin router provides the core interactive shell for summary/users/finance/payments/partners/withdrawals/tariffs/promos/prompts/broadcast/support/operations/runtime/AI/CMS/export workflows exposed by `bot/admin.py`.

Every privileged callback/FSM continuation re-authorizes through the signed backend admin API. Dangerous operations use explicit confirmation and shared services.

`bot/admin_extras.py` is currently **not registered**. Dedicated analytics, XLS-export and approved-withdrawal shortcut callbacks from that module are tracked by #55 and must not be treated as active until wired/tested.

See `telegram-flows.md`.

## Registered signed HTTP API

Current FastAPI app registers `create_admin_router()`. It provides the active core routes for:

- health/summary/users;
- generations;
- finance/payments/tariffs;
- operations/timeline/replay/refund;
- support;
- CMS;
- notifications;
- partners/withdrawals;
- promos/prompts;
- runtime/model availability;
- moderation;
- audit/commands/AI diagnostics;
- CSV exports.

Exact registered paths are listed in `api-reference.md`.

## Registered backend operator web

`create_admin_web_router()` exposes `/internal/admin/ui` when both admin API and admin web switches are enabled.

The registered surface includes:

- signed session mint;
- private HTML dashboard;
- server-authorized section reads;
- generic shared-service action dispatcher with idempotency and destructive confirmation.

It is backend/operator-only and must not be published as a public Mini App.

## Prepared but inactive extensions — issue #55

Current source tree also contains:

```text
src/foxgen/api/admin_extensions.py
src/foxgen/api/admin_web_extensions.py
src/foxgen/bot/admin_extras.py
```

but runtime entrypoints do not register these routers.

Prepared, currently inactive affordances include:

- direct admin-user list/set routes;
- dedicated analytics route;
- privileged generation-preview route;
- XLS export routes;
- operator-web analytics/preview/admin-management extension routes;
- Telegram analytics/XLS/approved-withdrawal extra callbacks.

Underlying services exist, but those extension transports are not production-reachable until #55 is merged. Do not duplicate their service logic as a workaround.

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

Use a dedicated admin HMAC secret. Do not reuse Telegram token, ordinary internal token, billing-admin token, KIE credentials or storage/database credentials.

## Rollout order

1. Deploy code with admin API/web disabled.
2. Run `alembic upgrade head` and verify revision `20260813_0008` is applied.
3. Configure dedicated HMAC key and narrow backend CIDR allowlist.
4. Configure one bootstrap admin ID.
5. Verify public ingress denies `/internal/admin/health`.
6. Enable `FOXGEN_ADMIN_API_ENABLED=true`.
7. Restart/deploy API, bot and worker.
8. Test signed `/internal/admin/health` over the backend path.
9. Send `/admin` from the bootstrap admin.
10. Verify a regular user is denied from `/admin` and copied callback data.
11. Perform one controlled idempotent balance adjustment and inspect audit/ledger.
12. Test one support reply; verify durable outbox exists before worker delivery.
13. Test one-recipient notification campaign and verify one delivery row/message.
14. Enable `FOXGEN_ADMIN_WEB_ENABLED=true` only if the private operator surface is required and its network/session boundary is verified.
15. Move long-lived operator identity from environment bootstrap toward durable `admin_users` according to operational policy. Direct admin-management extension routes themselves remain #55 until wired.

## Smoke checks

### Signed health

```text
GET /internal/admin/health
```

Expected success contains authorized admin identity/role/request ID.

Negative cases that must fail:

- missing/invalid signature;
- raw body changed after signing;
- stale timestamp;
- source outside allowlist;
- regular/non-admin user;
- API disabled.

### Core reads

```text
GET /internal/admin/summary
GET /internal/admin/finance
GET /internal/admin/runtime
GET /internal/admin/audit
```

Do not use a prepared #55 extension path as a smoke check until the router is registered.

### Database health

```sql
select status, count(*) from admin_commands group by status;
select action, outcome, count(*) from admin_audit_events group by action, outcome;
select status, count(*) from support_outbox group by status;
select status, count(*) from notification_deliveries group by status;
select status, count(*) from admin_outbox group by status;
```

Rising dead-letter counts require root-cause review before retry-budget changes.

## Emergency containment

1. Set `FOXGEN_ADMIN_API_ENABLED=false`.
2. Set `FOXGEN_ADMIN_WEB_ENABLED=false`.
3. Deploy/restart API and bot so no new admin commands are accepted.
4. If a campaign must stop, cancel it through the controlled path before disabling access when possible.
5. Keep command/audit/outbox tables for forensic evidence.
6. Inspect in-flight admin worker jobs before changing durable state.

## Rollback

Application rollback can disable the feature and revert application code while keeping durable admin tables/history.

Only remove/downgrade the admin schema when:

- no support reply is queued;
- no campaign/delivery is running/pending;
- no payment/admin outbox job must be retained;
- no audit/forensic history is required;
- migration/data consequences were explicitly reviewed.

In ordinary production incidents, retaining schema/history and disabling routes is safer than deleting operational evidence.

## Incident rules

- Never bypass confirmation by calling a lower-level write path directly.
- Never expose admin HMAC/session tokens through a public frontend.
- Never broaden network allowlist as a debugging shortcut.
- Never mass-send campaigns directly from a request handler.
- Never replay `generation.submit` through admin operation replay.
- Never insert a second manual ledger credit to reprocess a payment.
- Never mutate historical tariff/CMS/audit/ledger rows simply to make an operator UI look correct.
- Never document a prepared extension as active merely because its source file exists.

## Related documents

- `admin-capability-matrix.md` — capability/transport status;
- `api-reference.md` — registered routes and inactive #55 extensions;
- `known-limitations.md` — current admin/storage gaps;
- `configuration.md` — env reference;
- `security.md` — trust boundaries;
- `operations-runbook.md` — day-2 operations;
- `billing.md` — financial invariants.