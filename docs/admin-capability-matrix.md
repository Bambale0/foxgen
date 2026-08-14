# FoxGen admin capability matrix

Status: **the administrative control plane and prepared extension transports are registered/reachable in runtime; public Mini App remains a separate workstream**.

This matrix is the current capability contract derived from the supplied NEUROMIX admin migration brief and implemented in FoxGen's architecture.

## Status meanings

- **active** — service exists and at least the listed current transport is registered/reachable in runtime;
- **backend only** — current admin backend capability exists; public Mini App UI is not implemented.

## Architecture invariants

- one server-side `AdminPolicy` authorizes admin operations;
- shared admin services own write behavior;
- Telegram/HTTP/operator-web adapters do not duplicate domain writes;
- writes use append-only command/audit state;
- same idempotency request replays stored result; payload drift conflicts;
- destructive/expensive actions require explicit confirmation;
- signed admin HTTP is backend-only, network allowlisted and HMAC-SHA256 signed over exact raw body bytes;
- support replies and notification campaigns are durable worker/outbox work;
- sensitive fields are recursively redacted;
- tariff/CMS publishing preserves versions;
- regular users fail closed even with forged callbacks/requests.

## Capability matrix

| Capability | Shared implementation | Current transport | Status | R/W | Audit | Idempotency | Worker |
|---|---|---|---|---|---|---|---|
| Admin policy/roles/scopes | `AdminPolicy`, access service, `admin_users` | signed HTTP/operator web + bootstrap policy | active | R/W | yes | admin mutations | no |
| Admin list/set role/scopes | access service | signed HTTP/operator web | active | R/W | yes | yes | no |
| Admin command ledger | command executor/repository, `admin_commands` | all registered writes | active | W | self | core invariant | no |
| Audit events/redaction | admin repository/query/security | signed HTTP/operator web | active | R | self | n/a | no |
| Summary/stats | query service | Telegram/signed HTTP/operator web | active | R | policy-bound | n/a | no |
| Dedicated analytics snapshot | analytics service | signed HTTP/operator web + Telegram extra | active | R | policy-bound | n/a | no |
| User lookup | query service | Telegram/signed HTTP/operator web | active | R | policy-bound | n/a | no |
| Block/unblock user | user service + admission guard | Telegram/signed HTTP/operator web | active | W | yes | yes | no |
| Balance adjustment | user service + immutable billing ledger | Telegram/signed HTTP/operator web | active | W | yes | yes | no |
| Generation inspection | query service | signed HTTP/operator web | active | R | policy-bound | n/a | no |
| Privileged generation preview | preview service | signed HTTP/operator web | active | R | policy-bound | n/a | no |
| Finance dashboard | query/finance services | Telegram/signed HTTP/operator web | active | R | policy-bound | n/a | no |
| CSV exports | query/export adapter | Telegram/signed HTTP | active | R | policy-bound | n/a | no |
| XLS exports | query/export extension | signed HTTP/Telegram extra | active | R | policy-bound | n/a | no |
| Payment list/detail | query service | Telegram/signed HTTP/operator web | active | R | policy-bound | n/a | no |
| Payment recheck | payment service/admin outbox | signed HTTP/operator web | active | W | yes | yes | yes |
| Payment reprocess | payment service/admin outbox + deterministic ledger key | signed HTTP/operator web | active | W | yes | yes | yes |
| Tariff current/history | tariff/query service | Telegram/signed HTTP/operator web | active | R | policy-bound | n/a | no |
| Tariff publish | tariff service | Telegram/signed HTTP/operator web | active | W | yes | yes | no |
| Package/image/video/partner/prompt pricing payload | versioned tariff data | Telegram/signed HTTP/operator web | active | R/W | yes | publish key | no |
| Operation list/detail/timeline | query service | Telegram/signed HTTP/operator web | active | R | policy-bound | n/a | no |
| Safe operation replay | operation service + admin worker | signed HTTP/operator web | active | W | yes | yes | yes |
| Operation refund | operation/finance service | signed HTTP/operator web | active | W | yes | yes | no |
| Partner analytics | query/partner service | Telegram/signed HTTP/operator web | active | R | policy-bound | n/a | no |
| Partner withdrawal queue/actions | partner service | Telegram/signed HTTP/operator web | active | R/W | yes for writes | yes | no |
| Approved-withdrawal pay shortcut | partner service | Telegram extra | active | W | yes | yes | no |
| Promo create/lookup/activate/deactivate | promo service | Telegram/signed HTTP/operator web | active | R/W | yes for writes | yes | no |
| Prompt library list/detail | query service | Telegram/signed HTTP/operator web | active | R | policy-bound | n/a | no |
| Prompt approve/reject/deactivate | prompt service | Telegram/signed HTTP/operator web | active | W | yes | yes | no |
| Subscription/runtime toggle | runtime service | Telegram/signed HTTP/operator web | active | W | yes | yes | no |
| Model availability | runtime service + paid-admission guard | Telegram/signed HTTP/operator web | active | W | yes | yes | no |
| Runtime config/preset actions | runtime/admin services | registered transports where exposed | active | W | yes | yes where mutating | no |
| Support ticket list/detail | query/support service | Telegram/signed HTTP/operator web | active | R | policy-bound | n/a | no |
| Ticket assign/update | support service | signed HTTP/operator web | active | W | yes | yes | no |
| Ticket reply | support service + support outbox | Telegram/signed HTTP/operator web | active | W | yes | yes | yes |
| CMS document/version read | query/CMS service | Telegram/signed HTTP/operator web | active | R | policy-bound | n/a | no |
| CMS save/publish | CMS service | signed HTTP/operator web | active | W | yes | yes | no |
| Broadcast/campaign preview | notification service | Telegram/signed HTTP/operator web | active | R | policy-bound | n/a | no |
| Campaign create/test/start/cancel | notification service | Telegram/signed HTTP/operator web | active | W | yes | yes | yes |
| Notification delivery status/retries | AdminWorker/query service | worker/operator web | active | R/W | yes | durable dedupe | yes |
| AI admin diagnostics | query/diagnostic service | Telegram/signed HTTP | active | R | policy-bound | n/a | no |
| Trend create/remove | moderation service | signed HTTP/operator web backend | active backend only | W | yes | yes | no |
| Feed blur/remove moderation | moderation service | signed HTTP/operator web backend | active backend only | W | yes | yes | no |

## Current transport wiring

### Registered FastAPI routers

Current `create_app()` registers:

```text
create_billing_router(...)
create_generation_router(...)
create_admin_router(...)
create_admin_extensions_router(...)
create_admin_web_extensions_router(...)
create_admin_web_router(...)
```

The operator-web extension router intentionally precedes the base web router because the base router owns generic `GET /internal/admin/ui/api/{section}`. Specific `/analytics` and `/admins` routes must win route matching rather than be shadowed by the generic section handler.

Active extension endpoints are listed in `api-reference.md` and include admin identity management, dedicated analytics, privileged generation preview and XLS exports.

### Registered Telegram routers

The bot dispatcher registers routers in this order:

```text
foxgen-admin-extras
foxgen-admin
foxgen-quick-start
foxgen-generation
foxgen-shell
```

This keeps privileged extension callbacks ahead of the broad shell stale-callback fallback. Each extra callback still performs a fresh signed Admin API health/authorization check before reading or mutating state.

The extension callbacks cover dedicated analytics, XLS download, approved-withdrawal inspection and the confirmed/idempotent `mark_paid` shortcut.

## Admin roles

Current policy roles include:

- `superadmin`;
- `operator`;
- `support`;
- `moderator`;
- `finance`;
- `marketing`.

Durable admins live in `admin_users`; `FOXGEN_ADMIN_SUPERUSER_IDS` is bootstrap configuration, not the preferred long-term operational policy store.

## Core domain entities

The admin migration/model layer includes:

- `AdminUser`;
- `AdminCommand`;
- `AdminAuditEvent`;
- `TariffVersion`;
- `PaymentEvent`;
- `OperationEvent`;
- `SupportTicket`;
- `SupportMessage`;
- `SupportOutbox`;
- `CmsDocument` / `CmsDocumentVersion`;
- `NotificationCampaign` / `NotificationDelivery`;
- `AdminOutbox`;
- partner profile/withdrawal entities;
- promo codes;
- prompt-library items;
- runtime flags/model availability;
- trend/feed moderation records;
- user restrictions.

Schema is introduced by Alembic revision `20260813_0008_admin_contour.py`.

## State/invariant highlights

### Admin command

```text
reserved -> succeeded
         -> failed
```

Same admin/action/key/request hash replays the stored result; payload drift conflicts.

### Payment credit

Completed-payment credit is protected by:

```text
payment-credit:<provider>:<external_id>
```

so a second reprocess cannot append another effective credit.

### Support

A reply commits `SupportMessage` + `SupportOutbox` before worker delivery. The request handler is not the only copy of the side effect.

### Campaigns

Starting a campaign materializes recipient deliveries once under unique `(campaign_id, recipient_id)` state; workers send later with retries/rate limiting.

### Operation replay

Replay creates a child operation and is restricted to safe non-billable local work. `generation.submit` is forbidden.

## Security contract

For registered `/internal/admin/*` machine routes:

```text
network allowlist
+ X-Admin-User-Id
+ X-Request-Id
+ X-Admin-Timestamp
+ X-Admin-Signature
+ AdminPolicy authorization
```

Writes require `Idempotency-Key`; destructive/expensive actions require `X-Admin-Confirm: CONFIRM` where applicable.

Canonical HMAC bytes:

```text
<timestamp>\n<METHOD>\n<path>\n<request_id>\n<exact raw body bytes>
```

Audit/operation output redacts sensitive keys containing `token`, `secret`, `password`, `authorization`, `api_key`, `webhook` or `callback`.

## Transport notes

### Telegram `/admin`

The admin routers are thin transport shells for summary/users/finance/payments/partners/withdrawals/tariffs/promos/prompts/broadcast/support/operations/runtime/AI/CMS/export plus the extension analytics/XLS/approved-withdrawal callbacks. Every callback/FSM continuation re-authorizes through signed server-side health/action calls.

### Signed internal HTTP

Registered route inventory is in `api-reference.md`.

### Backend operator web

The registered `/internal/admin/ui` supports a signed session mint, server-side session/RBAC section reads and generic shared-service action dispatch. Dedicated analytics/preview/admin-management extension routes are active and protected by the same session/network/RBAC boundary.

### Public Mini App

Out of current scope. Future UI must call server-protected capabilities and must never trust client-side hidden state as authorization.

## Acceptance coverage

Automated coverage includes HMAC/timestamp/raw-body verification, allowlist, roles/scopes, confirmation, redaction, validation, signed admin API requests, balance idempotency, payment double-credit protection, safe replay, support outbox, campaign materialization, blocked-user paid-admission denial, Telegram non-admin protection and operator-web server-side authorization.

Extension wiring coverage additionally asserts:

- all extension route/method pairs are present in the FastAPI route table;
- disabled admin surfaces return 404;
- enabled signed analytics returns 200;
- enabled operator-web analytics returns 200 rather than being shadowed by the generic section route;
- Telegram extension router ordering precedes product/shell fallbacks;
- analytics, XLS and approved-withdrawal/payment callbacks re-authorize through the signed Admin API.

## Related documents

- `admin-control-plane.md`;
- `api-reference.md`;
- `database-schema.md`;
- `configuration.md`;
- `known-limitations.md`;
- `operations-runbook.md`.

## Change rule

A new admin capability is complete only when shared service/domain behavior exists, audit/idempotency/worker requirements are defined, the intended transport is actually registered, tests prove reachability/security, and this matrix/API reference reflect the runtime state.
