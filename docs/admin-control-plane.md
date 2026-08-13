# FoxGen administrative control plane

## Purpose

FoxGen exposes one administrative domain layer through three transports:

```text
Telegram /admin ───────┐
                       ├─> AdminPolicy -> AdminServices -> PostgreSQL/ledger/outboxes
Signed internal HTTP ──┤
                       └─> internal admin web operator surface
                                      |
                                      v
                       AdminWorker -> Telegram / local safe replay jobs
```

The public mini-app is intentionally outside this implementation. The operator web surface lives only under `/internal/admin/ui` and is protected by the same server-side role policy as the other transports.

## Security model

### Internal HTTP signature

Every request to `/internal/admin/*` requires:

- `X-Admin-User-Id` — administrator Telegram/internal ID;
- `X-Request-Id` — caller-generated correlation ID;
- `X-Admin-Timestamp` — Unix seconds;
- `X-Admin-Signature` — lowercase HMAC-SHA256 hex digest.

The signed byte sequence is exactly:

```text
<timestamp>\n<METHOD>\n<path>\n<request_id>\n<raw request body bytes>
```

Query parameters are not part of the signature. The body is: the exact bytes received by FastAPI, not a reserialized JSON object. Timestamp skew is limited by `FOXGEN_ADMIN_HMAC_MAX_SKEW_SECONDS`.

All write commands additionally require `Idempotency-Key`. Destructive or expensive commands require `X-Admin-Confirm: CONFIRM`.

### Network allowlist

The application checks `request.client.host` against `FOXGEN_ADMIN_NETWORK_ALLOWLIST` CIDRs before HMAC/RBAC. The default production example allows loopback plus RFC1918 Docker addresses because the Telegram bot is a separate backend container.

Do not trust `X-Forwarded-For` for this decision. If a reverse proxy sits in front of the API, the proxy itself must deny the admin prefix from public ingress.

Recommended Nginx rule in the public virtual host:

```nginx
location ^~ /internal/admin/ {
    return 404;
}
```

Backend-only callers use `http://api:8080/internal/admin/...` over the private Docker/VPC network and never traverse the public virtual host.

### RBAC

`AdminPolicy` is the only role/scopes source used by application code. Roles currently include:

- `superadmin`
- `operator`
- `support`
- `moderator`
- `finance`
- `marketing`

Bootstrap superusers can be supplied via `FOXGEN_ADMIN_SUPERUSER_IDS`. This is a bootstrap path only; durable administrators live in `admin_users` and can have additional explicit scopes. Every Telegram callback/FSM continuation, HTTP request and web action re-runs server-side authorization.

### Audit and redaction

Every write goes through `AdminCommandExecutor` and creates an append-only command record plus an audit event. The same `(admin_user_id, action, Idempotency-Key)` replays the stored result when the request hash matches and returns a conflict when the request changed.

Audit/operation output recursively redacts keys containing:

- `token`
- `secret`
- `password`
- `authorization`
- `api_key`
- `webhook`
- `callback`

Do not place raw provider secrets into arbitrary free-form fields.

## Durable background work

`AdminWorker` is executed from the normal `foxgen-worker` process and claims work with row locks and `SKIP LOCKED`.

### Support replies

HTTP/Telegram admin flows create `SupportMessage(status=queued)` and `SupportOutbox(status=pending)` in one transaction. The worker performs Telegram delivery later. Retriable failures use bounded exponential backoff. Network-ambiguous sends are not automatically retried because Telegram may already have accepted the message; they go to manual review/dead letter rather than intentionally duplicating the reply.

### Notification campaigns

Starting a campaign materializes one `NotificationDelivery` per recipient under a unique `(campaign_id, recipient_id)` constraint. Workers lease deliveries, apply the configured global send rate, retry safe failures and complete the campaign after no pending/retry/processing deliveries remain.

### Payment reprocess

A completed payment is credited through a deterministic immutable-ledger key:

```text
payment-credit:<provider>:<external_id>
```

A second reprocess observes that key and cannot apply another credit. `recheck` uses a provider adapter; when no adapter for that payment provider is registered, the job remains fail-closed and eventually dead-letters instead of inventing provider state.

### Operation replay

Admin replay creates a child `OperationEvent` without charging. The worker only replays local non-billable `generation.archive` and `generation.deliver` outbox events. Provider submission (`generation.submit`) is deliberately not replayable through this path.

## Environment variables

```env
FOXGEN_ADMIN_API_ENABLED=false
FOXGEN_ADMIN_WEB_ENABLED=false
FOXGEN_ADMIN_HMAC_KEY=<random dedicated secret>
FOXGEN_ADMIN_HMAC_MAX_SKEW_SECONDS=300
FOXGEN_ADMIN_NETWORK_ALLOWLIST=127.0.0.1/32,::1/128,172.16.0.0/12
FOXGEN_ADMIN_SUPERUSER_IDS=<telegram-id>[,<telegram-id>...]
FOXGEN_ADMIN_SESSION_TTL_SECONDS=900
FOXGEN_ADMIN_WORKER_BATCH_SIZE=50
FOXGEN_ADMIN_WORKER_LEASE_SECONDS=120
FOXGEN_ADMIN_WORKER_MAX_ATTEMPTS=8
FOXGEN_ADMIN_NOTIFICATION_RATE_PER_SECOND=20
```

Use a dedicated admin HMAC secret. Do not reuse the internal task token, Telegram token, KIE key or webhook secret.

## Rollout order

1. Deploy code with `FOXGEN_ADMIN_API_ENABLED=false` and `FOXGEN_ADMIN_WEB_ENABLED=false`.
2. Run `alembic upgrade head` and verify revision `20260813_0008`.
3. Configure `FOXGEN_ADMIN_HMAC_KEY`, the narrowest practical backend CIDR allowlist and one bootstrap admin ID.
4. Confirm the public reverse proxy returns `404` for `/internal/admin/health` from the Internet.
5. Enable `FOXGEN_ADMIN_API_ENABLED=true` and restart API, bot and worker.
6. Send `/admin` from the bootstrap admin and verify the summary screen.
7. Verify a non-admin gets denied from `/admin` and cannot continue a copied callback.
8. Test a small positive then negative balance adjustment on a dedicated test user and confirm the ledger/audit record.
9. Test one support reply and confirm it appears first as outbox work, then `sent` after the worker consumes it.
10. Create a notification campaign targeted to one test user, preview it, start it and confirm one delivery row and one Telegram message.
11. Enable `FOXGEN_ADMIN_WEB_ENABLED=true` only after the same HMAC/network checks pass; mint a short session with `POST /internal/admin/ui/session`.
12. Remove bootstrap IDs from environment after equivalent durable `admin_users` rows exist, when operational policy allows.

## Smoke checks

Signed health:

```text
GET /internal/admin/health
```

Expected: `200`, correct `admin_user_id`, role and request ID. The same request with a stale timestamp, modified raw body, wrong signature, non-allowlisted source or regular user must fail.

Operational checks:

```text
GET /internal/admin/summary
GET /internal/admin/finance
GET /internal/admin/runtime
GET /internal/admin/audit
```

Database checks:

```sql
select status, count(*) from admin_commands group by status;
select action, outcome, count(*) from admin_audit_events group by action, outcome;
select status, count(*) from support_outbox group by status;
select status, count(*) from notification_deliveries group by status;
select status, count(*) from admin_outbox group by status;
```

Any growing `dead_letter` count requires operator review before increasing retry limits.

## Rollback

Fast containment requires no schema rollback:

1. set `FOXGEN_ADMIN_API_ENABLED=false` and `FOXGEN_ADMIN_WEB_ENABLED=false`;
2. restart API/bot so new admin commands cannot be accepted;
3. if an active campaign must stop, cancel it before disabling the API or update its durable state through a controlled database procedure;
4. retain admin/audit/outbox tables for forensic history.

Only run `alembic downgrade 20260725_0007` when there is no admin command/support/campaign/payment work that must be retained. The downgrade intentionally removes all admin-control-plane history.

## Incident rules

- Never bypass manual confirmation by changing a handler to call a service directly.
- Never execute support send or campaign fan-out in an HTTP request lifecycle.
- Never replay `generation.submit` to recover an ambiguous provider submission.
- Never expose an admin session token, HMAC key or provider credential in audit payloads.
- Never broaden the network allowlist to `0.0.0.0/0` as a workaround for proxy/network configuration.
