# Release checklist

Use this checklist for production-impacting FoxGen releases. It complements CI; it does not replace repository tests or operational judgment.

## Scope

- [ ] PR states product/API/schema/security/deployment scope.
- [ ] Public Mini App impact is explicitly included or explicitly excluded.
- [ ] Linked issue/epic matches the implementation.
- [ ] No unrelated stale branch behavior is being described as current `main` behavior.

## Code and tests

- [ ] Ruff/lint passes.
- [ ] Changed Python files are formatter-clean.
- [ ] strict mypy passes.
- [ ] pytest/coverage passes.
- [ ] Relevant integration tests cover PostgreSQL/Redis/idempotency/locking behavior.
- [ ] Provider contract changes have strict valid/invalid fixtures.
- [ ] Admin changes include negative authorization/idempotency/confirmation tests.
- [ ] Money/provider/delivery changes explicitly test duplicate/ambiguity safety.

## Database

- [ ] New durable schema has a forward Alembic revision.
- [ ] SQLAlchemy metadata and migration agree.
- [ ] Critical schema smoke check updated.
- [ ] CI upgrade/head/downgrade-reupgrade passes.
- [ ] Production data-retention/rollback consequence reviewed.
- [ ] No historical ledger/audit/version data is destructively rewritten.

## Configuration

- [ ] `Settings` updated for new variables.
- [ ] `.env.example` updated.
- [ ] `deploy/production.env.example` updated when production-relevant.
- [ ] `docs/configuration.md` updated.
- [ ] New secrets have a distinct trust boundary and are not reused.

## Telegram/FSM

- [ ] Every new FSM state has success/back/cancel/timeout/invalid/stale behavior.
- [ ] Handler order does not make intended routers unreachable.
- [ ] Active drafts survive invalid/stale input where intended.
- [ ] Reference input cleanup/preservation behavior is covered.
- [ ] Concurrent/duplicate updates do not create duplicate upload/billing effects.

## Provider and generation lifecycle

- [ ] Exact KIE provider ID/API family verified for model changes.
- [ ] Paid provider createTask is not made automatically retryable.
- [ ] `submission_unknown` recovery remains evidence-based.
- [ ] Callback/poll transitions are idempotent.
- [ ] Provider completion still passes through durable archive/delivery before `succeeded`.

## Billing

- [ ] Active price behavior understood.
- [ ] Admission/reservation remains atomic.
- [ ] Ledger operations have deterministic idempotency.
- [ ] Settlement/refund policy remains consistent with generation state.
- [ ] Payment reprocess cannot double-credit.

## Media and delivery

- [ ] Result URLs remain untrusted/SSRF-validated.
- [ ] Storage remains private.
- [ ] Temporary `inputs/` lifecycle exists in production infrastructure.
- [ ] Durable result retention is not accidentally shortened by input cleanup.
- [ ] `delivery_unknown` cannot auto-resend.

## Admin

- [ ] Every privileged route/callback re-authorizes server-side.
- [ ] Admin network allowlist remains private/narrow.
- [ ] HMAC signs exact raw request bytes.
- [ ] Writes require idempotency.
- [ ] Destructive/expensive actions require confirmation.
- [ ] Support/campaign sends remain durable worker work.
- [ ] Audit output redacts sensitive fields.
- [ ] Any new router/module is actually registered by runtime entrypoints.

## Documentation

- [ ] `README.md` current implementation section updated.
- [ ] `docs/README.md` index updated for new docs.
- [ ] architecture/schema/state docs updated.
- [ ] API/Telegram docs updated for transport behavior.
- [ ] operations/rollback notes updated.
- [ ] `known-limitations.md` updated when a gap is fixed or discovered.
- [ ] No roadmap wording incorrectly describes completed behavior as future work.

## CI/PR

- [ ] Full head-SHA CI succeeded.
- [ ] Real infrastructure job succeeded.
- [ ] migration/API readiness smoke succeeded.
- [ ] Gitleaks/Trivy/container checks succeeded.
- [ ] No unresolved blocking review thread.
- [ ] PR is mergeable against current `main`.

## Production preflight

- [ ] GitHub `production` Environment secrets/variables are present.
- [ ] `AUTODEPLOY_ENABLED` value is intentional.
- [ ] Server checkout is clean `main`.
- [ ] Server `.env` is protected/current.
- [ ] Compose validates.
- [ ] Public ingress denies `/internal/admin/`.
- [ ] Backup/restore plan reviewed for migration-bearing release.
- [ ] One controlled smoke plan is defined before deploy.

## Post-deploy

- [ ] deployed SHA recorded/matches intended `main`.
- [ ] `/health/ready` succeeds.
- [ ] API/worker/bot containers healthy.
- [ ] `/menu` smoke succeeds.
- [ ] Admin smoke succeeds if admin enabled.
- [ ] generation/outbox/dead-letter counts show no new anomaly.
- [ ] reconciliation report has no unexplained critical finding.
- [ ] no unexpected billing/reservation mismatch.
- [ ] object-storage privacy/lifecycle remains intact.

## Rollback decision

- [ ] Determine whether issue is application-only, config, provider, data/schema or external service.
- [ ] Prefer containment/runtime disable over destructive rollback when possible.
- [ ] Application revert goes through `main` + CI + normal deployment.
- [ ] Schema downgrade is used only after durable-data consequences are explicitly reviewed.
- [ ] Preserve admin/audit/ledger/outbox evidence.