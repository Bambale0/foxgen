# HTTP API reference

This reference describes routes wired by the current FastAPI application. The public Mini App is outside scope; `/internal/admin/ui` is a backend-only operator surface.

## Authentication classes

FoxGen uses separate credentials for separate trust boundaries.

### Public/read-only

Health and model catalog/validation routes do not create paid work.

### Trusted internal generation caller

Paid generation/balance user-context routes require the configured internal bearer token. User-scoped routes also bind the request to `X-FoxGen-User-Id`. Paid task creation requires `Idempotency-Key`.

### Legacy billing administrator

Legacy `/v1/admin/*` billing/reconciliation routes use the separately protected billing-admin bearer credential and remain disabled unless explicitly enabled.

### Full internal admin control plane

`/internal/admin/*` requires all of:

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

Admin writes require `Idempotency-Key`. Destructive/expensive writes additionally require `X-Admin-Confirm: CONFIRM` where enforced by the route/service.

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

# Signed internal admin API

All paths below are relative to:

```text
/internal/admin
```

Unless noted otherwise, every route still requires signed admin authentication/RBAC. A table marking a route `read` does not mean it is public.

## Health, analytics and audit

| Method | Path | Semantics |
|---|---|---|
| GET | `/health` | signed/RBAC health identity check |
| GET | `/summary` | operational summary |
| GET | `/analytics?hours=24` | bounded analytics snapshot |
| GET | `/finance` | finance dashboard |
| GET | `/audit` | audit event list |
| GET | `/commands/{command_id}` | command/audit result detail |
| GET | `/ai/diagnostics` | read-only diagnostic synthesis; AI-admin scope required |

## Admin identity/RBAC

| Method | Path | Write semantics |
|---|---|---|
| GET | `/admins` | list durable administrators |
| PUT | `/admins/{user_id}` | idempotent + confirm role/scopes/active update |

Bootstrap IDs from environment are only initial access. Durable role/scopes belong here/`admin_users`.

## Users

| Method | Path | Write semantics |
|---|---|---|
| GET | `/users` | search/list |
| POST | `/users/{user_id}/block` | idempotent + confirm |
| POST | `/users/{user_id}/unblock` | idempotent + confirm |
| POST | `/users/{user_id}/balance-adjustments` | idempotent + confirm |

Blocked-user state is rechecked at transactional paid admission.

## Generations and previews

| Method | Path | Semantics |
|---|---|---|
| GET | `/generations` | generation list/filter |
| POST | `/previews/generation` | privileged generation input/model preview; no paid submit |

The preview endpoint validates/normalizes privileged generation input through admin policy; it does not replace normal paid-admission gates.

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

The versioned tariff payload is the administrative history for packages/product pricing dimensions. Runtime per-model generation pricing remains enforced by the billing admission layer.

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

Published content is versioned; historical published versions are not overwritten.

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

Campaign start materializes durable recipient deliveries once. Mass send never runs inline in the request lifecycle.

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

Promo input is normalized/validated server-side.

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

These are backend administrative contracts. They do not imply that the public Mini App moderation UI is implemented.

## Exports

| Method | Path | Format |
|---|---|---|
| GET | `/exports/users.csv` | UTF-8 CSV |
| GET | `/exports/finance.csv` | UTF-8 CSV |
| GET | `/exports/users.xls` | SpreadsheetML 2003 / Excel-readable XLS |
| GET | `/exports/finance.xls` | SpreadsheetML 2003 / Excel-readable XLS |

The XLS endpoints intentionally generate SpreadsheetML without adding a heavyweight mutable spreadsheet library to the production image.

## Internal operator web

When `FOXGEN_ADMIN_WEB_ENABLED=true`, the application also exposes an internal operator surface under:

```text
/internal/admin/ui
```

and protected session/action endpoints defined by the admin web routers. This surface is backend-only and uses server-confirmed admin policy/session behavior. It is not the public Mini App.

For machine integrations, prefer the explicit signed JSON API documented above.

# Idempotency and error semantics

For a write command, the admin command executor records request fingerprint and result.

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

See `admin-control-plane.md` for roles, confirmation, rollout and security rules.