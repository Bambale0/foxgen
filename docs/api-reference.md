# HTTP API reference

This reference describes routes actually registered by the current FastAPI application on `main`. The public Mini App is outside scope; `/internal/admin/ui` is a backend-only operator surface.

Prepared extension modules that are present in the source tree but not currently registered are listed separately under **Prepared but inactive admin extensions**. See issue #55 and `known-limitations.md`.

## Authentication classes

FoxGen uses separate credentials for separate trust boundaries.

### Public/read-only

Health and model catalog/validation routes do not create paid work.

### Trusted internal generation caller

Paid generation/balance user-context routes require the configured internal bearer token. User-scoped routes also bind the request to `X-FoxGen-User-Id`. Paid task creation requires `Idempotency-Key`.

### Legacy billing administrator

Legacy `/v1/admin/*` billing/reconciliation routes use the separately protected billing-admin bearer credential and remain disabled unless explicitly enabled.

### Full internal admin control plane

Registered `/internal/admin/*` machine routes require:

- source address in `FOXGEN_ADMIN_NETWORK_ALLOWLIST`;
- `X-Admin-User-Id`;
- `X-Request-Id`;
- `X-Admin-Timestamp`;
- `X-Admin-Signature`;
- server-side RBAC through `AdminPolicy`.

Signature input:

```text
<timestamp>\n<METHOD>\n<path>\n<request_id>\n<exact raw body bytes>
```

Admin writes require `Idempotency-Key`. Destructive/expensive writes additionally require `X-Admin-Confirm: CONFIRM` where enforced.

# Core API

## Health

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health/live` | none | Process liveness/version |
| GET | `/health/ready` | none | PostgreSQL/Redis readiness when resources are managed |

## Model catalog and task admission

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/v1/models` | none | Catalog/readiness flags |
| GET | `/v1/models/{slug}` | none | Model detail + local input schema |
| POST | `/v1/models/{slug}/validate` | none | Free local contract validation |
| POST | `/v1/models/{slug}/tasks` | trusted internal | Atomic paid generation admission |
| POST | `/webhooks/kie` | KIE HMAC | Verified provider callback intake |

Paid task admission validates authentication, positive user identity, idempotency, strict model contract, registry/runtime availability, rate/concurrency limits, active price and sufficient balance before generation/reservation/outbox commit.

## Billing and wallet

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/v1/prices` | none | Active model prices |
| GET | `/v1/users/{user_id}/balance` | trusted internal | Wallet snapshot |
| GET | `/v1/users/{user_id}/ledger` | trusted internal | Immutable ledger history |
| POST | `/v1/admin/users/{user_id}/balance-adjustments` | legacy billing admin | Idempotent manual adjustment |
| PUT | `/v1/admin/prices/{model_slug}` | legacy billing admin | Publish model-price version |

## Generation operations

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/v1/generations/{generation_id}` | trusted internal + owner ID | Owner-scoped lifecycle status |
| POST | `/v1/generations/{generation_id}/cancel` | trusted internal + owner ID | Pre-provider cancellation |
| GET | `/v1/admin/generations/stuck` | legacy billing admin | Stuck-generation report |
| POST | `/v1/admin/generations/{id}/resolve-unknown` | legacy billing admin | Evidence-based `submission_unknown` resolution |
| GET | `/v1/admin/reconciliation` | legacy billing admin | Read-only consistency report |
| POST | `/v1/admin/reconciliation/run` | legacy billing admin | Report/deterministic safe fixes |
| POST | `/v1/admin/generations/{id}/resolve-delivery` | legacy billing admin | Manual `delivery_unknown` resolution |

Cancellation is rejected once provider submission may have started. Unknown provider/Telegram outcomes are never resolved through blind retry.

# Registered signed internal admin API

All paths below are relative to:

```text
/internal/admin
```

Every route is private/signed/RBAC-protected even when the table labels it read-only.

## Health, summary and audit

| Method | Path | Semantics |
|---|---|---|
| GET | `/health` | signed/RBAC identity/health check |
| GET | `/summary` | operational summary |
| GET | `/finance` | finance dashboard |
| GET | `/audit` | audit event list |
| GET | `/commands/{command_id}` | command/result detail |
| GET | `/ai/diagnostics` | read-only diagnostic synthesis; AI-admin scope required |

## Users

| Method | Path | Write semantics |
|---|---|---|
| GET | `/users` | search/list |
| POST | `/users/{user_id}/block` | idempotent + confirm |
| POST | `/users/{user_id}/unblock` | idempotent + confirm |
| POST | `/users/{user_id}/balance-adjustments` | idempotent + confirm |

Blocked-user state is rechecked at transactional paid admission.

## Generations

| Method | Path | Semantics |
|---|---|---|
| GET | `/generations` | generation list/filter |

## Operations

| Method | Path | Write semantics |
|---|---|---|
| GET | `/operations` | list/filter |
| GET | `/operations/{operation_id}` | detail with sensitive payload redaction |
| GET | `/operations/{operation_id}/timeline` | parent/child history |
| POST | `/operations/{operation_id}/replay` | idempotent + confirm; safe local work only |
| POST | `/operations/{operation_id}/refund` | idempotent + confirm |

Admin replay never replays the billable `generation.submit` boundary.

## Payments

| Method | Path | Write semantics |
|---|---|---|
| GET | `/payments` | list/filter |
| GET | `/payments/{payment_id}` | detail |
| POST | `/payments/{payment_id}/recheck` | idempotent, worker-backed |
| POST | `/payments/{payment_id}/reprocess` | idempotent + confirm, worker-backed |

Payment credit uses a deterministic immutable-ledger key, preventing double credit across repeated reprocess commands.

## Tariffs and pricing

| Method | Path | Write semantics |
|---|---|---|
| GET | `/tariffs` | current published tariff payload |
| GET | `/tariffs/versions` | immutable version history |
| GET | `/tariffs/versions/{version_id}` | version detail |
| POST | `/tariffs/publish` | idempotent + confirm |

## Support

| Method | Path | Write semantics |
|---|---|---|
| GET | `/tickets` | list/filter |
| GET | `/tickets/{ticket_id}` | ticket/messages/detail |
| POST | `/tickets/{ticket_id}/assign` | idempotent |
| POST | `/tickets/{ticket_id}/update` | idempotent |
| POST | `/tickets/{ticket_id}/reply` | idempotent + confirm; durable outbox |

A reply request commits support message/outbox state. Telegram delivery occurs later in the worker.

## CMS

| Method | Path | Write semantics |
|---|---|---|
| GET | `/cms/documents` | list |
| GET | `/cms/documents/{document_id}` | document/version detail |
| POST | `/cms/documents` | idempotent save/new version |
| POST | `/cms/documents/{document_id}/publish` | idempotent + confirm |

## Notification campaigns / broadcasts

| Method | Path | Write semantics |
|---|---|---|
| POST | `/notifications/preview` | read-only segment/preview calculation |
| GET | `/notifications/campaigns` | list |
| POST | `/notifications/campaigns` | idempotent create |
| GET | `/notifications/campaigns/{campaign_id}` | detail/delivery summary |
| POST | `/notifications/campaigns/{campaign_id}/test` | idempotent test delivery |
| POST | `/notifications/campaigns/{campaign_id}/start` | idempotent + confirm |
| POST | `/notifications/campaigns/{campaign_id}/cancel` | idempotent + confirm |

Campaign start materializes durable recipient deliveries once; mass send never runs inline in the request lifecycle.

## Partners

| Method | Path | Write semantics |
|---|---|---|
| GET | `/partners/summary` | partner analytics |
| GET | `/partners/withdrawals` | withdrawal queue/filter |
| POST | `/partners/withdrawals/{withdrawal_id}/actions` | idempotent + confirm |

## Promos

| Method | Path | Write semantics |
|---|---|---|
| GET | `/promos/{code}` | lookup |
| POST | `/promos` | idempotent create |
| POST | `/promos/{code}/active` | idempotent + confirm enable/disable |

## Prompt library moderation

| Method | Path | Write semantics |
|---|---|---|
| GET | `/prompts` | filter/list by status |
| GET | `/prompts/{item_id}` | detail |
| POST | `/prompts/{item_id}/moderate` | idempotent + confirm |

## Runtime and model availability

| Method | Path | Write semantics |
|---|---|---|
| GET | `/runtime` | current runtime flags/model overrides |
| POST | `/runtime/flags/{key}` | idempotent + confirm |
| POST | `/models/{model_slug}/availability` | idempotent + confirm |

Runtime model availability is revalidated before paid admission.

## Moderation backend

| Method | Path | Write semantics |
|---|---|---|
| GET | `/moderation` | trend/feed moderation state |
| POST | `/trends` | idempotent create |
| POST | `/trends/{trend_id}/remove` | idempotent + confirm |
| POST | `/feed/{content_id}/moderate` | idempotent + confirm |

These backend contracts do not imply a finished public Mini App UI.

## Active exports

| Method | Path | Format |
|---|---|---|
| GET | `/exports/users.csv` | UTF-8 CSV |
| GET | `/exports/finance.csv` | UTF-8 CSV |

# Registered internal operator web

When both admin API/web switches are enabled, `create_admin_web_router()` registers:

| Method | Path | Auth |
|---|---|---|
| POST | `/internal/admin/ui/session` | signed admin HTTP + network/RBAC; mints short session |
| GET | `/internal/admin/ui?session=...` | admin session + network/RBAC |
| GET | `/internal/admin/ui/api/summary` | `X-Admin-Session` + network/RBAC |
| GET | `/internal/admin/ui/api/{section}` | `X-Admin-Session` + network/RBAC |
| POST | `/internal/admin/ui/api/action` | session + idempotency; confirmation for destructive action classes |

Current generic section names supported by the registered router include users, payments, operations, tickets, tariffs, campaigns, moderation, runtime, partners, prompts, CMS, audit and finance.

Current generic action dispatcher supports shared-service actions including user block/unblock/balance adjustment, payment recheck/reprocess, operation replay/refund, ticket reply, tariff publish, campaign create/start/cancel, CMS save/publish, model availability/runtime flag and trend/feed moderation.

This operator surface is backend-only. It is not the public Mini App.

# Prepared but inactive admin extensions — issue #55

The repository also contains extension modules that are **not registered by the current FastAPI entrypoint**:

```text
src/foxgen/api/admin_extensions.py
src/foxgen/api/admin_web_extensions.py
```

Accordingly, the following prepared routes are not current production endpoints:

```text
GET /internal/admin/admins
PUT /internal/admin/admins/{user_id}
GET /internal/admin/analytics
POST /internal/admin/previews/generation
GET /internal/admin/exports/users.xls
GET /internal/admin/exports/finance.xls

GET /internal/admin/ui/api/analytics
POST /internal/admin/ui/api/preview-generation
GET /internal/admin/ui/api/admins
PUT /internal/admin/ui/api/admins/{user_id}
```

Do not integrate against those paths until issue #55 is merged and this section is removed/updated. The underlying shared access/analytics/preview services exist, but source-file presence is not route registration.

# Idempotency and error semantics

For a write command, the admin command executor records request fingerprint/result.

```text
same (admin, action, key) + same effective request
  -> stored result, replayed=true

same (admin, action, key) + changed effective request
  -> idempotency conflict
```

Authentication/authorization failure is always server-side. Hidden buttons, copied callback data or forged operator actions do not bypass policy.

# Raw-body signing example

Pseudo-code:

```text
raw = exact bytes sent on wire
canonical = timestamp + "\n" + method + "\n" + path + "\n" + request_id + "\n" + raw
signature = hex(HMAC-SHA256(admin_hmac_key, canonical))
```

Do not JSON-reserialize after signing. Query parameters are not included in the current canonical signature string; the URL path is.

See `admin-control-plane.md`, `known-limitations.md` and issue #55 for admin transport status.