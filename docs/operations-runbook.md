# Production operations runbook

This runbook is the day-2 operational reference for FoxGen. Use it together with `production-deploy.md`, `postprocessing-reconciliation.md`, `minio-lifecycle-runbook.md` and `admin-control-plane.md`.

## Safety priorities

When diagnosing an incident, preserve these invariants before optimizing availability:

1. do not create a second billable provider submission for an ambiguous generation;
2. do not duplicate a Telegram delivery whose previous send may have succeeded;
3. do not mutate financial/audit history in place;
4. do not expose admin/internal credentials to restore access;
5. preserve durable evidence before destructive rollback/cleanup.

## Basic service health

On the production server:

```bash
cd /root/foxgen
export FOXGEN_IMAGE_TAG="$(git rev-parse HEAD)"
docker compose --env-file .env -f docker-compose.prod.yml ps
```

API readiness:

```bash
curl --fail --silent http://127.0.0.1:${FOXGEN_PUBLIC_API_PORT:-8080}/health/ready
```

Recent logs:

```bash
docker compose --env-file .env -f docker-compose.prod.yml logs --tail=200 minio-init
docker compose --env-file .env -f docker-compose.prod.yml logs --tail=200 api
docker compose --env-file .env -f docker-compose.prod.yml logs --tail=200 worker
docker compose --env-file .env -f docker-compose.prod.yml logs --tail=200 bot
```

Do not paste full production logs into public issues/chats without checking for user/provider metadata.

## Confirm deployed revision

```bash
cd /root/foxgen
git status --short
git branch --show-current
git rev-parse HEAD
git rev-parse origin/main
```

Expected:

- branch `main`;
- clean tracked working tree;
- deployed SHA matches the intended tested `main` revision.

A dirty tracked tree should be investigated rather than overwritten; the deployment script intentionally refuses it.

## Database migration check

```bash
docker compose --env-file .env -f docker-compose.prod.yml run --rm migrate alembic current --check-heads
```

If this invocation conflicts with the service command semantics in the currently deployed Compose version, run the equivalent command inside the application image/container without bypassing environment configuration.

For the admin control plane, verify migration `20260813_0008` is present after rollout.

## Telegram smoke test

From a controlled user/account:

1. `/menu` returns the current main menu;
2. Quick Start accepts one photo;
3. bot asks what to create from the reference;
4. model/settings navigation works without losing the reference;
5. cancel/menu returns cleanly;
6. a Telegram album is rejected rather than partially uploaded.

For a controlled paid smoke, verify active price/test balance first. Do not repeatedly launch paid provider tasks merely to test menu rendering.

## Admin smoke test

### Telegram

From an authorized bootstrap/durable admin:

```text
/admin
```

Verify summary and one safe read-only section.

From a regular user, verify `/admin` and copied admin callback data are denied.

### Signed HTTP

From the private/backend network, send a correctly signed:

```text
GET /internal/admin/health
```

Verify public ingress to the same path is denied/404.

Never troubleshoot an admin connectivity issue by changing `FOXGEN_ADMIN_NETWORK_ALLOWLIST` to `0.0.0.0/0`.

## Generation queue overview

Useful PostgreSQL aggregates:

```sql
select status, count(*)
from generations
group by status
order by status;

select event_type, status, count(*)
from outbox_events
group by event_type, status
order by event_type, status;
```

Watch specifically for growing:

- `submission_unknown`;
- `processing` older than normal provider latency;
- `storing_media`;
- `delivery_pending`;
- `dead_letter`;
- `delivery_unknown`.

## Reconciliation procedure

1. Run the read-only reconciliation report.
2. Review ambiguous external states separately.
3. Resolve `submission_unknown` only from provider evidence/callback/polling.
4. Resolve `delivery_unknown` only after checking Telegram delivery evidence.
5. Apply deterministic safe fixes.
6. Re-run the report.
7. Investigate repeated failure classes.

Never use reconciliation to call provider createTask again.

See `postprocessing-reconciliation.md`.

## `submission_unknown` incident

Meaning: the provider create call may have been accepted but local code did not durably record a definitive response.

Do:

- inspect known provider task identity/callback records;
- use provider status/dashboard evidence;
- allow normal polling/callback convergence;
- preserve the reserved balance until evidence settles the task;
- use evidence-based operator resolution if necessary.

Do not:

- requeue the original billable submit;
- release/capture funds based only on a timeout assumption;
- create a replacement provider task for the same user request without a separate deliberate product decision.

## `delivery_unknown` incident

Meaning: Telegram send may have succeeded but the response was lost/ambiguous.

Do:

- inspect recipient/history evidence;
- mark sent with verified message IDs when delivered;
- retry only after confirming not sent;
- fail/refund according to current policy when delivery cannot complete.

Do not automatically resend.

## Media archive failures

Inspect:

```sql
select status, count(*) from media_assets group by status;
```

For repeated `retry_wait`/`failed`:

- check provider result URL validity;
- check DNS/SSRF rejection reason;
- check download size/timeout;
- check S3/MinIO reachability/capacity/credentials;
- preserve already stored assets; do not restart the whole multi-file archive blindly.

## Temporary `inputs/` storage

Repository Compose deployments enforce the temporary `inputs/` lifecycle through the `minio-init` service. API, worker and bot are gated on successful lifecycle read-back verification.

Normal verification:

```bash
docker compose --env-file .env -f docker-compose.prod.yml logs --tail=200 minio-init
docker compose --env-file .env -f docker-compose.prod.yml run --rm minio-init
```

Expected policy is prefix-scoped short retention, by default 2-day completed objects. Bundled MinIO also uses explicit server-wide stale multipart cleanup (`FOXGEN_MINIO_STALE_UPLOADS_EXPIRY=24h`, `FOXGEN_MINIO_STALE_UPLOADS_CLEANUP_INTERVAL=6h`) because its lifecycle API does not round-trip `AbortIncompleteMultipartUpload`. The initializer preserves unrelated lifecycle rules and must never target `generations/`.

If object count grows unexpectedly or the bootstrap fails:

- inspect the current lifecycle configuration and `minio-init` error;
- verify MinIO reachability and lifecycle permissions;
- verify `FOXGEN_INPUT_RETENTION_DAYS` / `FOXGEN_INPUT_MULTIPART_ABORT_DAYS` values;
- rerun `minio-init` after fixing the root cause;
- do not start API/worker/bot with `--no-deps` to bypass the gate;
- do not delete durable result objects;
- do not make the bucket public;
- scope any manual cleanup strictly to confirmed abandoned temporary inputs.

If the deployment intentionally uses external S3-compatible storage instead of the repository's bundled MinIO topology, provide and verify an equivalent `inputs/` lifecycle policy in that infrastructure.

See `input-media-lifecycle.md` and `minio-lifecycle-runbook.md`.

## Billing checks

Useful queries:

```sql
select status, count(*) from balance_reservations group by status;
select entry_type, count(*) from ledger_entries group by entry_type;
```

Use reconciliation/admin finance tooling for normal diagnosis. Do not edit ledger rows.

For a payment reprocess incident, verify the deterministic credit key:

```text
payment-credit:<provider>:<external_id>
```

exists at most once as an effective credit.

## Admin worker checks

```sql
select status, count(*) from support_outbox group by status;
select status, count(*) from notification_deliveries group by status;
select status, count(*) from admin_outbox group by status;
```

Growing dead-letter counts indicate root-cause work, not an automatic reason to increase retry budgets.

For campaigns:

- stop/cancel through the admin service/API when possible;
- confirm recipient materialization before assuming sends occurred;
- inspect delivery statuses/rate limits;
- do not manually loop-send outside the durable campaign system.

## Emergency switches

### Freeze deployments

GitHub Environment:

```text
AUTODEPLOY_ENABLED=false
```

### Stop new paid generation admission

Server env:

```env
FOXGEN_TASK_SUBMISSION_ENABLED=false
```

Deploy/restart the affected services through the normal controlled procedure.

### Disable one problematic model

Use admin runtime model availability rather than disabling all generation when one provider model is failing.

### Disable full admin HTTP/web

```env
FOXGEN_ADMIN_API_ENABLED=false
FOXGEN_ADMIN_WEB_ENABLED=false
```

This is containment, not a database rollback. Retain command/audit/outbox history.

## Provider outage

Preferred response:

1. runtime-disable affected model(s);
2. leave already accepted tasks to callback/poll/reconciliation;
3. do not retry ambiguous create requests;
4. inspect failure classification and provider status;
5. re-enable only after controlled validation.

Do not loosen model contracts to make a provider outage disappear.

## Redis outage

Impact can include Telegram FSM/rate/event-isolation loss, but committed PostgreSQL generation/billing state remains authoritative.

After Redis recovery:

- expect some conversational drafts to expire;
- do not reconstruct paid durable state from FSM;
- ensure only one bot deployment consumes the Telegram token;
- verify rate/isolation behavior before high traffic.

## PostgreSQL outage

Paid admission and durable worker operations must fail closed. Restore PostgreSQL first; do not bypass database durability by sending directly to providers.

After recovery:

- verify `/health/ready`;
- check migrations/current head;
- inspect outbox leases/stale work;
- run reconciliation.

## Object-storage outage

Provider-complete generations may remain in result/storage stages. Preserve provider result metadata and retry only storage-safe actions. Do not mark success before archive/delivery completes.

After bundled MinIO recovery, rerun `minio-init` and require lifecycle verification before restoring the full Compose application stack. For external storage, verify the equivalent lifecycle policy through that provider.

## Telegram outage

Provider work may finish while delivery waits/retries. If send attempts become ambiguous, retain `delivery_unknown` for operator evidence. Do not mass-resend after Telegram recovery without durable state review.

## Public admin exposure incident

If `/internal/admin/*` becomes reachable publicly:

1. disable `FOXGEN_ADMIN_API_ENABLED` and `FOXGEN_ADMIN_WEB_ENABLED`;
2. fix reverse proxy/network policy;
3. rotate `FOXGEN_ADMIN_HMAC_KEY` if exposure could have leaked it;
4. inspect `admin_commands`/audit events for unexpected requests;
5. review bootstrap/durable admin identities;
6. re-enable only after public path returns 404/denial and backend signed health succeeds.

## Secret exposure

If any secret enters Git history/logs/public chat:

- rotate it immediately;
- remove/revoke the old credential at the issuing system;
- update production `.env`/GitHub Environment as appropriate;
- redeploy/restart clients using it;
- investigate use during exposure window;
- do not assume deleting the visible text revokes the credential.

## Application rollback

Prefer a Git revert on `main`, followed by normal CI/deploy. Do not force-reset production.

For migration-bearing releases, separate application rollback from schema/data rollback. Retain newer schema when the old application can tolerate it or use a forward repair migration. Never downgrade away admin/outbox/audit data while it is operationally required.

If rollback returns to code that no longer runs `minio-init`, keep the already installed `inputs/` rule in place and verify it externally before bringing application traffic back.

## Post-incident checklist

After recovery:

- API readiness green;
- bot/worker single intended instances healthy;
- generation/reconciliation anomaly counts reduced;
- no unexpected wallet/reservation mismatch;
- no rising dead-letter queue;
- object lifecycle/private bucket intact;
- public internal-admin route denied;
- current deployed SHA recorded;
- incident cause/action documented;
- tests/docs updated if the incident exposed a missing invariant.
