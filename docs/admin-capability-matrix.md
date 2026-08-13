# FoxGen admin capability matrix

Status: **implemented in `main` through PR #54**.

This matrix is the current capability contract for the FoxGen administrative control plane. It was derived from the supplied NEUROMIX admin migration brief and implemented in FoxGen's own architecture rather than by copying one legacy handler. The public Mini App remains a separate workstream; backend moderation/operator contracts are implemented and can be consumed by a future UI.

## Architecture invariants

- one server-side `AdminPolicy` authorizes every admin transport;
- shared admin services own write behavior;
- Telegram/HTTP/operator-web layers are thin adapters;
- every write command is represented in the append-only admin command/audit layer;
- idempotent actions replay stored results for the same request and conflict on changed payload;
- destructive/expensive actions require explicit confirmation;
- signed admin HTTP is backend-only, network allowlisted and HMAC-SHA256 signed over exact raw body bytes;
- support replies and notification campaigns are durable worker/outbox work;
- sensitive fields are recursively redacted from administrative output;
- published tariff/CMS history is versioned rather than overwritten;
- regular users fail closed even when they forge callbacks/requests.

## Capability matrix

| Capability | Shared implementation | Transport | R/W | Audit | Idempotency | Worker |
|---|---|---|---|---|---|---|
| Admin role/scopes | `AdminPolicy`, access service, `admin_users` | Telegram/HTTP/operator web | R/W | yes | admin changes | no |
| Admin command ledger | command executor/repository, `admin_commands` | all writes | W | self | core invariant | no |
| Audit events/redaction | admin repository/query/security | HTTP/operator web | R | self | n/a | no |
| Summary/stats/analytics | query/analytics services | Telegram/HTTP/operator web | R | policy-bound | n/a | no |
| User lookup | query service | Telegram/HTTP/operator web | R | policy-bound | n/a | no |
| Block/unblock user | user service + admission guard | Telegram/HTTP/operator web | W | yes | yes | no |
| Balance adjustment | user service + immutable billing ledger | Telegram/HTTP/operator web | W | yes | yes | no |
| Generation inspection | query service | HTTP/operator web | R | policy-bound | n/a | no |
| Privileged generation preview | preview service | HTTP/operator web | R | policy-bound | n/a | no |
| Finance dashboard | query/finance services | Telegram/HTTP/operator web | R | policy-bound | n/a | no |
| CSV/XLS operator exports | query/export adapters | Telegram/HTTP | R | policy-bound | n/a | no |
| Payment list/detail | query service | HTTP/operator web | R | policy-bound | n/a | no |
| Payment recheck | payment service/admin outbox | HTTP/operator web | W | yes | yes | yes |
| Payment reprocess | payment service/admin outbox + deterministic ledger key | HTTP/operator web | W | yes | yes | yes |
| Tariff current/history | tariff/query service | Telegram/HTTP/operator web | R | policy-bound | n/a | no |
| Tariff publish | tariff service | Telegram/HTTP/operator web | W | yes | yes | no |
| Package/image/video/partner/prompt pricing payload | versioned tariff data | Telegram/HTTP/operator web | R/W | yes | publish key | no |
| Operation list/detail/timeline | query service | HTTP/operator web | R | policy-bound | n/a | no |
| Safe operation replay | operation service + admin worker | HTTP/operator web | W | yes | yes | yes |
| Operation refund | operation/finance service | HTTP/operator web | W | yes | yes | no |
| Partner analytics | query/partner service | Telegram/HTTP/operator web | R | policy-bound | n/a | no |
| Partner withdrawal queue/detail/actions | partner service | Telegram/HTTP/operator web | R/W | yes for writes | yes | no |
| Promo create/lookup/activate/deactivate | promo service | Telegram/HTTP/operator web | R/W | yes for writes | yes | no |
| Prompt library list/detail | query service | Telegram/HTTP/operator web | R | policy-bound | n/a | no |
| Prompt approve/reject/deactivate | prompt service | Telegram/HTTP/operator web | W | yes | yes | no |
| Subscription/runtime toggle | runtime service | Telegram/HTTP/operator web | W | yes | yes | no |
| Model availability | runtime service + paid-admission guard | Telegram/HTTP/operator web | W | yes | yes | no |
| Runtime config/preset actions | runtime/admin services | Telegram/HTTP | W | yes | yes where mutating | no |
| Support ticket list/detail | query/support service | HTTP/operator web | R | policy-bound | n/a | no |
| Ticket assign/update | support service | HTTP/operator web | W | yes | yes | no |
| Ticket reply | support service + support outbox | HTTP/operator web | W | yes | yes | yes |
| CMS document/version read | query/CMS service | HTTP/operator web | R | policy-bound | n/a | no |
| CMS save/publish | CMS service | HTTP/operator web | W | yes | yes | no |
| Broadcast/campaign preview | notification service | Telegram/HTTP/operator web | R | policy-bound | n/a | no |
| Campaign create/test/start/cancel | notification service | Telegram/HTTP/operator web | W | yes | yes | yes |
| Notification delivery status/retries | AdminWorker/query service | worker/operator web | R/W | yes | durable dedupe | yes |
| AI admin diagnostics | query/analytics | Telegram/HTTP | R | policy-bound | n/a | no |
| Trend create/remove | moderation service | HTTP/operator web backend | W | yes | yes | no |
| Feed blur/remove moderation | moderation service | HTTP/operator web backend | W | yes | yes | no |

## Admin roles

Current policy roles include:

- `superadmin`;
- `operator`;
- `support`;
- `moderator`;
- `finance`;
- `marketing`.

Roles map to scopes in the shared policy. Durable admins live in `admin_users`; `FOXGEN_ADMIN_SUPERUSER_IDS` is a bootstrap mechanism, not the long-term policy store.

## Core domain entities

The admin migration/model layer includes the administrative equivalents of the required capability contract:

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
- partner profile/withdrawal entities;
- promo codes;
- prompt-library items;
- runtime flags/model availability;
- trend/feed moderation records;
- admin outbox work.

Database schema is introduced by Alembic revision `20260813_0008_admin_contour.py`.

## Important state machines

### Admin command

```text
reserved -> succeeded
         -> failed
```

A succeeded command is immutable from the operator perspective. Same admin/action/key/request hash returns the stored response; payload drift conflicts.

### Payment admin work

Payment operations distinguish observed/current state from durable recheck/reprocess request work. Completed payment credit is protected by:

```text
payment-credit:<provider>:<external_id>
```

so a second reprocess cannot append a second credit.

### Support

Ticket business state supports open/pending/resolved/closed and authorized reopening. A reply commits:

```text
SupportMessage(status=queued)
SupportOutbox(status=pending)
```

before the worker performs Telegram delivery.

Support outbox follows a leased retry/dead-letter lifecycle rather than sending only inside the HTTP request.

### CMS

Documents own immutable versions. Publishing selects/promotes a version; previously published content is not silently edited in place.

### Notification campaigns

Campaigns progress from draft/ready into running/completed or cancellation. Starting a campaign materializes recipient deliveries once under durable uniqueness.

### Partner withdrawals

Allowed transitions cover pending review to approval/payment or rejection. Actions are server-validated and audited.

### Prompt moderation

Pending content can be approved/rejected; approved content can later be deactivated according to current service rules.

## Security contract

For `/internal/admin/*`:

```text
network allowlist
+ X-Admin-User-Id
+ X-Request-Id
+ X-Admin-Timestamp
+ X-Admin-Signature
+ AdminPolicy authorization
```

Write routes also require `Idempotency-Key`. Destructive/expensive actions require `X-Admin-Confirm: CONFIRM` where applicable.

The HMAC canonical bytes are:

```text
<timestamp>\n<METHOD>\n<path>\n<request_id>\n<exact raw body bytes>
```

Audit/operation output redacts sensitive keys containing `token`, `secret`, `password`, `authorization`, `api_key`, `webhook` or `callback`.

## Durable side-effect rules

### Support

HTTP/Telegram creates durable message/outbox state. Worker sends later.

### Campaigns

HTTP/Telegram creates/starts durable campaign state. Worker leases recipient deliveries and applies rate/retry policy.

### Payment reprocess

Admin request creates durable work; deterministic payment ledger key prevents double credit.

### Operation replay

Creates auditable child operation. Worker permits only safe non-billable local replay such as archive/delivery orchestration. `generation.submit` is explicitly forbidden.

## Transport parity

### Telegram `/admin`

Thin interactive shell for summary, users, finance, pricing/tariffs, partners, promos, prompt moderation, campaigns and operational tools. Each callback/FSM continuation re-authorizes.

### Signed internal HTTP

Explicit testable router under `/internal/admin/*`; endpoint inventory is in `api-reference.md`.

### Backend operator web

Internal-only operator surface under `/internal/admin/ui`, protected by the same server-side policy/session/HMAC/network boundaries. It is not the public Mini App.

### Future public Mini App

Out of current scope. When implemented, it must call protected backend admin capabilities and must never trust client-side hidden controls as authorization.

## Acceptance coverage

Automated coverage includes:

- HMAC/timestamp/raw-body verification;
- network allowlist;
- role/scope checks;
- confirmation parsing;
- recursive redaction;
- payload/tariff/campaign validation;
- signed admin API requests;
- idempotent balance adjustment;
- payment reprocess double-credit prevention;
- operation replay without double charge;
- support reply creating outbox instead of direct-only send;
- campaign recipient materialization once;
- blocked user rejection at transactional paid admission;
- Telegram non-admin denial/callback/FSM protection;
- operator-web server-side authorization.

## Operational documents

- `admin-control-plane.md` — security/rollout/runbook;
- `api-reference.md` — endpoint inventory;
- `configuration.md` — environment variables;
- `operations-runbook.md` — production smoke/incident flow.

## Change rule

Any new admin capability is incomplete until the matrix specifies transport, read/write semantics, audit requirement, idempotency requirement and worker requirement, and until all exposed transports reuse the shared domain/service behavior.