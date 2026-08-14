# Administrative control plane

FoxGen implements one shared administrative domain layer through the registered Telegram `/admin`, signed backend HTTP API and backend-only operator web surface. The public Mini App is intentionally outside this implementation.

The extension modules for direct admin management, dedicated analytics, generation preview, XLS export and Telegram admin extras are registered runtime transports. They reuse the same shared services, policy, audit and idempotency boundaries as the core admin contour.

## Architecture

```text
Telegram /admin + extras ─────┐
                              │
Signed /internal/admin/* ─────┼─> AdminPolicy
                              │      |
Backend operator UI ──────────┘      v
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

The extension admin-role update and Telegram withdrawal `mark_paid` shortcut preserve these same controls; no extension handler writes domain state directly.

## Command ledger and idempotency

Admin writes run through the command executor/repository. A durable command records admin identity, request/correlation ID, action/target, request fingerprint/payload, result/error and timestamps.

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

A support reply request commits `SupportMessage(status=queued)` plus `SupportOutbox(status=pending)`. The admin worker later claims and sends the reply. Ambiguous external acceptance must not intentionally create duplicate replies.

## Notification campaigns

Campaign start validates the campaign/segment, materializes `NotificationDelivery` recipients once, commits durable state and returns. Workers lease deliveries, apply `FOXGEN_ADMIN_NOTIFICATION_RATE_PER_SECOND`, retry safe failures and converge campaign state.

Mass send never runs inline in the request lifecycle.

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

Runtime router order is:

```text
foxgen-admin-extras
foxgen-admin
foxgen-quick-start
foxgen-generation
foxgen-shell
```

The privileged routers intentionally precede broad product/shell fallbacks. Every admin callback/FSM continuation re-authorizes through the signed backend Admin API.

The core router provides summary/users/finance/payments/partners/withdrawals/tariffs/promos/prompts/broadcast/support/operations/runtime/AI/CMS/CSV workflows. `bot/admin_extras.py` adds active callbacks for:

- dedicated 24-hour analytics;
- user/finance XLS download;
- approved-withdrawal listing;
- confirmed/idempotent withdrawal `mark_paid` shortcut.

See `telegram-flows.md`.

## Registered signed HTTP API

Current FastAPI app registers both the core and extension routers:

```text
create_admin_router(...)
create_admin_extensions_router(...)
```

Together they expose:

- health/summary/users;
- durable admin-user list/update;
- dedicated analytics;
- generations and privileged generation preview;
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
- CSV and XLS exports.

Exact registered paths are listed in `api-reference.md`.

## Registered backend operator web

The extension web router is registered **before** the base generic web router:

```text
create_admin_web_extensions_router(...)
create_admin_web_router(...)
```

This order is security/reachability significant because the base router owns `GET /internal/admin/ui/api/{section}`. Registering specific `/analytics` or `/admins` after the generic route would shadow them even though route enumeration still showed them.

When both admin API and web switches are enabled, the backend-only surface includes:

- signed session mint and private HTML dashboard;
- server-authorized generic section reads/actions;
- dedicated analytics snapshot;
- privileged generation preview;
- durable admin identity list/update.

All extension web actions use the same `_session_context` network/session/RBAC boundary. Admin identity updates additionally require idempotency and explicit confirmation.

The operator surface must not be published as a public Mini App.

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
8. Test signed `/internal/admin/health`, `/analytics` and `/admins` over the backend path.
9. Send `/admin` from the bootstrap admin and exercise one read-only extra callback.
10. Verify a regular user is denied from `/admin` and copied callback data.
11. Perform one controlled idempotent balance adjustment and inspect audit/ledger.
12. Test one support reply; verify durable outbox exists before worker delivery.
13. Test one-recipient notification campaign and verify one delivery row/message.
14. If partner payouts are enabled, test the approved-withdrawal shortcut only with a controlled fixture and verify audit/idempotency.
15. Enable `FOXGEN_ADMIN_WEB_ENABLED=true` only if the private operator surface is required and its network/session boundary is verified.
16. Verify `/internal/admin/ui/api/analytics` and `/admins` resolve to their dedicated routes rather than the generic section handler.
17. Move long-lived operator identity from environment bootstrap toward durable `admin_users` according to operational policy.

## Smoke checks

### Signed health and extensions

```text
GET /internal/admin/health
GET /internal/admin/analytics
GET /internal/admin/admins
```

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

### Operator-web extensions

With a valid private admin session:

```text
GET /internal/admin/ui/api/analytics
GET /internal/admin/ui/api/admins
```

These must return the dedicated service responses, not `Unknown admin UI section` from the generic route.

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

Only remove/downgrade the admin schema when no support reply/campaign/payment/admin outbox job must be retained and audit/forensic consequences were explicitly reviewed. In ordinary production incidents, retaining schema/history and disabling routes is safer than deleting operational evidence.

## Incident rules

- Never bypass confirmation by calling a lower-level write path directly.
- Never expose admin HMAC/session tokens through a public frontend.
- Never broaden network allowlist as a debugging shortcut.
- Never mass-send campaigns directly from a request handler.
- Never replay `generation.submit` through admin operation replay.
- Never insert a second manual ledger credit to reprocess a payment.
- Never mutate historical tariff/CMS/audit/ledger rows simply to make an operator UI look correct.
- Never move a specific admin extension route behind a generic catch-all route without a regression test proving reachability.

## Related documents

- `admin-capability-matrix.md` — capability/transport status;
- `api-reference.md` — registered routes;
- `telegram-flows.md` — Telegram router order and extras;
- `known-limitations.md` — remaining production gaps;
- `configuration.md` — env reference;
- `security.md` — trust boundaries;
- `operations-runbook.md` — day-2 operations;
- `billing.md` — financial invariants.
