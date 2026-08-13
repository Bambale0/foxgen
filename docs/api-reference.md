# HTTP API reference

This reference describes routes wired by the current FastAPI application. The public Mini App is outside scope; `/internal/admin/ui` is a backend-only operator surface.

## Authentication classes

FoxGen deliberately uses separate credentials for separate trust boundaries.

### Public/read-only

Health and model catalog/validation routes do not create paid work.

### Trusted internal generation caller

Paid generation/balance user-context routes require the configured internal bearer token. User-scoped routes also bind the request to `X-FoxGen-User-Id`. Paid task creation requires `Idempotency-Key`.

### Legacy billing administrator

Legacy `/v1/admin/*` billing/reconciliation routes use the separately protected billing-admin bearer credential and remain disabled unless explicitly enabled.

### Full internal admin control plane

`/internal/admin/*` uses all of:

- source address in `FOXGEN_ADMIN_NETWORK_ALLOWLIST`;
- `X-Admin-User-Id`;
- `X-Request-Id`;
- `X-Admin-Timestamp`;
- `X-Admin-Signature`;
- server-side RBAC through `AdminPolicy`.

The signature input is:

```text
<timestamp>\n<METHOD>\n<path>\n<request_id>\n<exact raw body bytes>
```

Admin writes require `Idempotency-Key`. Destructive/expensive writes additionally require `X-Admin-Confirm: CONFIRM` where the route enforces manual confirmation.

## Health

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health/live` | none | Process liveness/version |
| GET | `/health/ready` | none | PostgreSQL/Redis readiness when resources are managed |

## Model catalog and task admission

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/v1/models` | none | Catalog and readiness flags |
| GET | `/v1/models/{slug}` | none | Model detail + local input JSON schema |
| POST | `/v1/models/{slug}/validate` | none | Free local contract validation |
| POST | `/v1/models/{slug}/tasks` | trusted internal | Atomic paid generation admission |
| POST | `/webhooks/kie` | KIE HMAC | Verified provider callback intake |

Task admission validates authentication, positive user identity, idempotency key, exact model contract, runtime model availability, rate/concurrency limits, active price and sufficient balance before committing generation/reservation/outbox state.

## Billing and wallet

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/v1/prices` | none | Active model prices |
| GET | `/v1/users/{user_id}/balance` | trusted internal | Wallet snapshot |
| GET | `/v1/users/{user_id}/ledger` | trusted internal | Immutable ledger history |
| POST | `/v1/admin/users/{user_id}/balance-adjustments` | legacy billing admin | Idempotent manual wallet adjustment |
| PUT | `/v1/admin/prices/{model_slug}` | legacy billing admin | Publish new model-price version |

The full admin control plane also provides balance/tariff actions through shared admin services and command audit/idempotency.

## Generation operations

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/v1/generations/{generation_id}` | trusted internal + owner ID | Owner-scoped lifecycle status |
| POST | `/v1/generations/{generation_id}/cancel` | trusted internal + owner ID | Pre-provider cancellation |
| GET | `/v1/admin/generations/stuck` | legacy billing admin | Read-only stuck-generation report |
| POST | `/v1/admin/generations/{id}/resolve-unknown` | legacy billing admin | Evidence-based `submission_unknown` resolution |
| GET | `/v1/admin/reconciliation` | legacy billing admin | Read-only consistency report |
| POST | `/v1/admin/reconciliation/run` | legacy billing admin | Report or deterministic safe fixes |
| POST | `/v1/admin/generations/{id}/resolve-delivery` | legacy billing admin | Manual `delivery_unknown` resolution |

Cancellation is intentionally rejected once provider submission may have started. Unknown provider or Telegram outcomes are never resolved through blind retry.

# Signed internal admin API

Prefix: `/internal/admin`.

## Health and summary

| Method | Path |
|---|---|
| GET | `/health` |
| GET | `/summary` |
| GET | `/finance` |
| GET | `/audit` |
| GET | `/ai/diagnostics` |
| GET | `/commands/{command_id}` |

`/ai/diagnostics` is read-only and additionally requires the AI-admin scope.

## Users

| Method | Path | Write semantics |
|---|---|---|
| GET | `/users` | search/list |
| POST | `/users/{user_id}/block` | idempotent + confirm |
| POST | `/users/{user_id}/unblock` | idempotent + confirm |
| POST | `/users/{user_id}/balance-adjustments` | idempotent + confirm |

User blocking is rechecked at transactional paid-generation admission; it is not only a UI restriction.

## Generations and operations

| Method | Path | Write semantics |
|---|---|---|
| GET | `/generations` | filter by user/status |
| GET | `/operations` | filter/list |
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

Payment credit uses a deterministic immutable-ledger key, so repeated reprocessing cannot double-credit one payment.

## Tariffs and pricing

| Method | Path | Write semantics |
|---|---|---|
| GET | `/tariffs` | current published tariff payload |
| GET | `/tariffs/versions` | immutable version history |
| GET | `/tariffs/versions/{version_id}` | version detail |
| POST | `/tariffs/publish` | idempotent + confirm |

The versioned tariff payload is the administrative surface for packages and product pricing dimensions. Historical published versions are retained.

## Support

| Method | Path | Write semantics |
|---|---|---|
| GET | `/tickets` | list/filter |
| GET | `/tickets/{ticket_id}` | ticket/messages/detail |
| POST | `/tickets/{ticket_id}/assign` | idempotent |
| POST | `/tickets/{ticket_id}/update` | idempotent |
| POST | `/tickets/{ticket_id}/reply` | idempotent + confirm; durable outbox |

A reply request commits a support message/outbox record. Telegram delivery is performed later by the admin worker.

## CMS

| Method | Path | Write semantics |
|---|---|---|
| GET | `/cms/documents` | list |
| GET | `/cms/documents/{document_id}` | document/version detail |
| POST | `/cms/documents` | idempotent save/new version |
| POST | `/cms/documents/{document_id}/publish` | idempotent + confirm |

Published content is versioned; old published versions are not mutated in place.

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

Starting a campaign materializes recipient delivery rows once; mass send never runs inline in the HTTP request.

## Partners

| Method | Path | Write semantics |
|---|---|---|
| GET | `/partners/summary` | partner analytics |
| GET | `/partners/withdrawals` | queue/filter |
| POST | `/partners/withdrawals/{withdrawal_id}/actions` | idempotent + confirm |

Allowed withdrawal state transitions are enforced in the shared service/domain layer.

## Promos

| Method | Path | Write semantics |
|---|---|---|
| GET | `/promos/{code}` | lookup |
| POST | `/promos` | idempotent create |
| POST | `/promos/{code}/active` | idempotent + confirm enable/disable |

Promo codes are normalized and validated server-side.

## Prompt library moderation

| Method | Path | Write semantics |
|---|---|---|
| GET | `/prompts` | filter by moderation status |
| GET | `/prompts/{item_id}` | detail |
| POST | `/prompts/{item_id}/moderate` | idempotent + confirm |

Moderation actions cover approval/rejection/deactivation according to current service state rules.

## Runtime and model availability

| Method | Path | Write semantics |
|---|---|---|
| GET | `/runtime` | current runtime flags/model overrides |
| POST | `/runtime/flags/{key}` | idempotent + confirm |
| POST | `/models/{model_slug}/availability` | idempotent + confirm |

Runtime model availability is revalidated before paid admission. Disabling a model does not require application deployment.

## Moderation backend

| Method | Path | Write semantics |
|---|---|---|
| GET | `/moderation` | trend/feed moderation state |
| POST | `/trends` | idempotent create |
| POST | `/trends/{trend_id}/remove` | idempotent + confirm |
| POST | `/feed/{content_id}/moderate` | idempotent + confirm |

These are backend administrative contracts. Their presence does not imply the public Mini App UI is implemented.

## Exports

| Method | Path |
|---|---|
| GET | `/exports/users.csv` |
| GET | `/exports/finance.csv` |

Telegram `/admin` also exposes operator export actions including XLS-compatible outputs where implemented by the bot adapter.

## Error/idempotency behavior

For a write command, the admin command executor records the request fingerprint and result. Repeating the same `(admin, action, idempotency key)` with the same effective request returns the stored result and sets `replayed`; reusing the key for different parameters returns an idempotency conflict.

Authentication/authorization failure is always server-side. No hidden button, copied callback or forged operator request bypasses policy.

## Raw-body signing example

Pseudo-code:

```text
raw = exact bytes sent on wire
canonical = timestamp + "\n" + method + "\n" + path + "\n" + request_id + "\n" + raw
signature = hex(HMAC-SHA256(admin_hmac_key, canonical))
```

Do not JSON-reserialize a body after signing it. Query parameters are not included in the current signature string; the URL path is.

See `admin-control-plane.md` for rollout and security rules.