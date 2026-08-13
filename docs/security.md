# Security model

FoxGen handles billable provider requests, Telegram identities, financial credits, private media and administrative operations. Security boundaries are therefore explicit and fail-closed.

## Trust boundaries

### Public/untrusted

- Telegram users and message/callback payloads;
- public HTTP clients;
- provider result URLs until validated;
- public reverse-proxy traffic;
- any public Mini App/frontend code when introduced later.

### Trusted internal

- bot/backend calls using the ordinary internal API token;
- production worker/database/Redis/storage network;
- KIE callback requests only after webhook verification;
- admin HTTP callers only after network allowlist + HMAC + RBAC.

A request does not become trusted because it originated from a hidden UI control or contains a Telegram user ID.

## Secret separation

Use independent credentials for:

- Telegram bot token;
- KIE API key;
- KIE webhook HMAC secret;
- ordinary internal generation API bearer token;
- legacy billing-admin bearer token if enabled;
- full admin HMAC secret;
- PostgreSQL;
- Redis;
- S3-compatible storage;
- GitHub-to-production SSH deployment.

Do not reuse secrets across these boundaries. Never embed server secrets in Telegram callback data, public frontend JavaScript or Mini App bundles.

## Paid generation authentication

Paid task creation requires the internal service credential and an explicit user context. The server independently validates:

- positive user ID;
- idempotency key;
- user block state;
- strict model contract;
- registry and runtime model availability;
- rate/concurrency limits;
- active price;
- sufficient wallet balance.

Provider API access occurs only after atomic durable admission.

## Provider callback security

KIE callbacks require the configured callback HMAC scheme and bounded timestamp/replay window. Callback identity/payload is recorded through a deduplicated provider-event inbox before lifecycle application.

Never disable callback verification to recover from a provider incident. Use polling/evidence-based reconciliation instead.

## Provider result download / SSRF

Provider-returned URLs are untrusted input. Result archival enforces safety controls before storing bytes, including the current implementation's HTTPS/source/address/redirect restrictions, timeout and size limits.

Do not forward provider URLs directly to users as a substitute for archive validation.

## Object storage

User inputs/results are private. Public clients never receive bucket credentials. Provider-readable and Telegram-readable access uses bounded presigned URLs where required.

Temporary `inputs/` need independent object lifecycle cleanup because Redis FSM expiry can orphan draft objects. Current `main` requires the lifecycle rule to be configured externally.

## Financial integrity

- integer credit units only;
- wallet mutations inside database transactions;
- immutable append-only ledger;
- deterministic idempotency keys for settlement/payment credits;
- reservation state reflects provider acceptance/ambiguity;
- ambiguous provider submission never auto-resubmits;
- manual adjustments require protected admin path and reason/audit.

Do not repair money by editing old ledger rows.

## Telegram side-effect integrity

Telegram send is potentially non-idempotent. Once delivery reaches the send boundary, an ambiguous transport result becomes `delivery_unknown` rather than an automatic resend.

The same principle applies to support/admin notification sends where ambiguity can duplicate user-visible messages.

## Full admin HTTP security

Admin requests require:

```text
network allowlist
+ X-Admin-User-Id
+ X-Request-Id
+ X-Admin-Timestamp
+ X-Admin-Signature
+ server-side AdminPolicy
```

HMAC input includes the exact raw body. Write endpoints require `Idempotency-Key`; destructive/expensive actions require explicit confirmation.

Public ingress must deny `/internal/admin/`.

## Admin session/operator web

The backend-only operator surface is enabled separately and uses short-lived admin sessions plus server-side authorization/network checks. A session token is a privileged credential; do not place it in public analytics/logging or expose the operator UI on public ingress.

The current public Mini App workstream is separate and must not reuse backend admin session/HMAC secrets.

## RBAC

Admin role/scopes are resolved server-side. Bootstrap superuser IDs are temporary initial policy inputs; durable `admin_users` records are the operational source for long-lived administrators.

Every privileged callback/FSM continuation/action is re-authorized. Never cache "is admin" only in client state.

## Admin audit and redaction

Writes create command/audit records. Output recursively redacts sensitive key patterns including token/secret/password/authorization/api_key/webhook/callback.

Do not deliberately store secrets in business/audit payloads even when redaction exists.

## Network exposure

Production Compose keeps PostgreSQL, Redis and MinIO off public host ports. The API is host-loopback-bound for the reverse proxy.

The public proxy should expose only intended public/provider routes. Internal admin paths are denied; internal callers use private Docker/VPC network paths.

## CI/security scanning

CI includes:

- Gitleaks secret scan;
- Trivy filesystem/misconfiguration/vulnerability scan;
- Trivy production image scan;
- dependency review on PRs;
- exact dependency lock and deterministic image build;
- real Postgres/Redis/migration tests.

A clean scanner result is not proof that a credential was never exposed. Rotate any credential that reaches an untrusted location.

## Deployment security

Production deployment uses:

- GitHub `production` Environment;
- explicit `AUTODEPLOY_ENABLED` gate;
- dedicated SSH private key;
- strict `known_hosts` validation;
- exact tested SHA;
- clean-tree/fast-forward-only update;
- server-owned `.env` that CI never uploads/overwrites.

## Incident containment switches

Useful fail-closed controls:

```env
FOXGEN_TASK_SUBMISSION_ENABLED=false
FOXGEN_ADMIN_API_ENABLED=false
FOXGEN_ADMIN_WEB_ENABLED=false
```

A problematic model can also be runtime-disabled through the admin service without deploying a provider contract change.

## Prohibited shortcuts

- `0.0.0.0/0` admin allowlist to fix networking;
- public S3 bucket to fix media delivery;
- blind retry of provider createTask;
- blind resend of `delivery_unknown`;
- direct SQL wallet/audit mutation for normal operator recovery;
- embedding backend credentials in public frontend/Mini App;
- disabling signature verification as an outage workaround;
- sharing production private keys/tokens in issues, PRs or chats.

## Related docs

- `architecture.md`;
- `billing.md`;
- `admin-control-plane.md`;
- `input-media-lifecycle.md`;
- `production-deploy.md`;
- `operations-runbook.md`.