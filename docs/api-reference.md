# HTTP API reference

This reference describes routes actually registered by the current FastAPI application, including the public Happy Fox Mini App. `/internal/admin/ui` remains a backend-only operator surface.

## Authentication classes

FoxGen uses separate credentials for separate trust boundaries.

### Public/read-only

Health and model catalog/validation routes do not create paid work.

### Trusted internal generation/user caller

Paid generation/balance/user-portal routes require the configured internal bearer token. User-scoped routes also bind the request to `X-FoxGen-User-Id`. Paid task creation and user payment invoice creation require `Idempotency-Key` where documented.

Telegram payment settlement and trusted promo redemption are accepted only through this owner-bound context; the public Mini App cannot submit a `successful_payment` result or a reward amount.

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

## Trusted user portal, Stars and promos

These routes use the trusted internal bearer + `X-FoxGen-User-Id` owner binding. Payment/promo recovery remains available independently of the paid-generation kill switch.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/v1/user-portal/tariff` | trusted internal + owner ID | Current published tariff |
| GET | `/v1/user-portal/payments/stars/packages` | trusted internal + owner ID | Stars-enabled top-up packages only |
| POST | `/v1/user-portal/payments/stars/invoices` | trusted internal + owner ID + `Idempotency-Key` | Create/replay durable order and Telegram XTR invoice URL |
| POST | `/v1/user-portal/payments/stars/pre-checkout` | trusted internal + owner ID | Validate native Telegram `pre_checkout_query` against order snapshot |
| POST | `/v1/user-portal/payments/stars/success` | trusted internal + owner ID | Persist `successful_payment` evidence and settle CREDIT exactly once |
| POST | `/v1/user-portal/promos/redeem` | trusted internal + owner ID | Redeem one server-defined promo bonus for this owner |
| GET | `/v1/user-portal/support` | trusted internal + owner ID | List own support tickets |
| POST | `/v1/user-portal/support` | trusted internal + owner ID | Create support ticket |
| GET | `/v1/user-portal/support/{ticket_id}` | trusted internal + owner ID | Own ticket detail |
| POST | `/v1/user-portal/support/{ticket_id}/messages` | trusted internal + owner ID | Reply to own ticket |
| POST | `/v1/user-portal/support/{ticket_id}/close` | trusted internal + owner ID | Close own ticket |
| GET | `/v1/user-portal/partner` | trusted internal + owner ID | Partner profile/withdrawals |
| POST | `/v1/user-portal/partner/join` | trusted internal + owner ID | Idempotent partner enrollment |
| POST | `/v1/user-portal/partner/withdrawals` | trusted internal + owner ID + `Idempotency-Key` | Request partner withdrawal |

Stars invoice creation snapshots CREDIT/XTR terms before the external Telegram call. Promo redemption accepts only `{code}`: reward amount, active state and remaining uses are loaded under a PostgreSQL lock from the server-side promo definition. Successful redemption atomically creates the immutable `promo-credit:<CODE>:<user-id>` ledger movement, durable redemption row and usage-counter increment. Repeating the same owner/code returns the existing result without another credit/use.

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

# Happy Fox public Mini App API

Happy Fox uses a short-lived Telegram-derived JWT. These routes are owner-scoped/read-only except for bounded user actions such as paid admission, safe cancellation, private input media, user portal operations, Stars invoice creation and promo redemption. Internal/admin credentials are never accepted by or exposed to the browser.

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/miniapp/auth` | Validate Telegram `initData` and issue Mini App JWT |
| GET | `/v1/miniapp/bootstrap` | Initial user, wallet, prices, ledger, schemas, jobs, feature flags and limits |
| GET | `/v1/miniapp/models` | Submission-enabled model catalog + JSON schemas |
| GET | `/v1/miniapp/models/{model_slug}` | Submission-enabled model detail |
| POST | `/v1/miniapp/models/{model_slug}/validate` | Free model-contract validation/normalization |
| GET | `/v1/miniapp/balance` | Current owner wallet projection |
| GET | `/v1/miniapp/prices` | Current active prices |
| GET | `/v1/miniapp/ledger` | Owner immutable ledger projection, max 200 |
| GET | `/v1/miniapp/generations` | Owner history, max 100 |
| GET | `/v1/miniapp/generations/{generation_id}` | Owner detail + short-lived stored-media URLs |
| POST | `/v1/miniapp/generations/{generation_id}/cancel` | Existing safe pre-provider cancellation boundary |
| POST | `/v1/miniapp/tasks` | Paid admission through shared `SubmissionService` + `Idempotency-Key` |
| POST | `/v1/miniapp/input-media` | Authenticated private image/video/audio upload |
| DELETE | `/v1/miniapp/input-media/{storage_key}` | Owner-scoped temporary input cleanup |
| GET | `/v1/miniapp/tariff` | Current published tariff version |
| GET | `/v1/miniapp/payments/stars/packages` | Purchasable XTR packages for the owner |
| POST | `/v1/miniapp/payments/stars/invoices` | Create/replay Stars invoice; requires `Idempotency-Key` |
| POST | `/v1/miniapp/promos/redeem` | Redeem a server-defined promo bonus once for this owner |
| GET | `/v1/miniapp/support` | List own support tickets |
| POST | `/v1/miniapp/support` | Create support ticket |
| GET | `/v1/miniapp/support/{ticket_id}` | Own ticket detail/history |
| POST | `/v1/miniapp/support/{ticket_id}/messages` | Reply to own ticket |
| POST | `/v1/miniapp/support/{ticket_id}/close` | Close own ticket |
| GET | `/v1/miniapp/partner` | Partner profile/withdrawals |
| POST | `/v1/miniapp/partner/join` | Idempotent partner enrollment |
| POST | `/v1/miniapp/partner/withdrawals` | Request withdrawal; requires `Idempotency-Key` |

The frontend renders model controls from backend schemas and validates again server-side before paid admission. Wallet routes are projections only. Stars success/refund remain server-side. Promo redemption is a bounded financial command where the browser supplies only a code; the backend owns the CREDIT amount and max-use policy.

# Registered signed internal admin API

All paths below are relative to `/internal/admin`. Every route is private/signed/RBAC-protected even when read-only.

## Health, summary, analytics and access

| Method | Path | Semantics |
|---|---|---|
| GET | `/health` | signed/RBAC identity/health check |
| GET | `/summary` | operational summary |
| GET | `/finance` | finance dashboard |
| GET | `/analytics` | dedicated analytics snapshot; optional `hours` window |
| GET | `/admins` | list durable admin identities/roles/scopes |
| PUT | `/admins/{user_id}` | idempotent + confirm admin role/scope/active update |
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

## Generations

| Method | Path | Semantics |
|---|---|---|
| GET | `/generations` | generation list/filter |
| POST | `/previews/generation` | privileged local preview; does not bypass normal paid submission |

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
| POST | `/payments/{payment_id}/refund` | idempotent + confirm; hold CREDIT then queue native Stars refund |
| POST | `/payments/{payment_id}/refund/resolve` | idempotent + confirm; evidence-based resolution of `refund_unknown` |

Payment credit/reprocess and Stars refund use independent immutable ledger/idempotency boundaries. Direct browser/user refund writes do not exist.

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
| GET | `/promos/{code}` | lookup definition |
| POST | `/promos` | idempotent create of server-owned reward/max-use policy |
| POST | `/promos/{code}/active` | idempotent + confirm enable/disable |

Admin promo routes define policy; they do not themselves credit a user. User redemption runs through `/v1/user-portal/promos/redeem` or `/v1/miniapp/promos/redeem` and is recorded in `promo_redemptions` + immutable ledger. Redemption audit prevents deletion of a promo definition that already has user-redemption rows.

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

## Active exports

| Method | Path | Format |
|---|---|---|
| GET | `/exports/users.csv` | UTF-8 CSV |
| GET | `/exports/finance.csv` | UTF-8 CSV |
| GET | `/exports/users.xls` | SpreadsheetML 2003 / Excel-readable XLS |
| GET | `/exports/finance.xls` | SpreadsheetML 2003 / Excel-readable XLS |

# Registered internal operator web

When both admin API/web switches are enabled, the operator surface registers session-backed equivalents of supported admin reads/actions. The extension router is registered before the base generic section route to prevent shadowing. Native Stars refund resolution remains a dedicated signed API because of stricter evidence semantics.

# Idempotency and error semantics

Admin writes use the command executor:

```text
same (admin, action, key) + same effective request
  -> stored result, replayed=true

same (admin, action, key) + changed effective request
  -> idempotency conflict
```

User promo redemption uses durable business idempotency rather than a client-controlled reward request: unique `(promo_code,user_id)` plus unique `promo-credit:<CODE>:<user-id>` ledger key.

Authentication/authorization failure is always server-side. Hidden buttons, copied callbacks or forged operator actions do not bypass policy.

# Raw-body signing example

```text
raw = exact bytes sent on wire
canonical = timestamp + "\n" + method + "\n" + path + "\n" + request_id + "\n" + raw
signature = hex(HMAC-SHA256(admin_hmac_key, canonical))
```

Do not JSON-reserialize after signing. Query parameters are not included in the current canonical signature string; the URL path is.

See `admin-control-plane.md`, `telegram-stars-payments.md`, `user-promos.md`, `billing.md` and `known-limitations.md` for active contracts and remaining limitations.
