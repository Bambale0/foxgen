# HappyFox migration rules

This file records general migration guardrails. Task-specific scripts/runtime code remain the source of truth.

## Product boundary

HappyFox was created from a known production-core import, but current production data belongs exclusively to HappyFox.

Never use a NEUROMIX/Tanya database, Redis namespace, media root or `.env` as a migration shortcut or rollback target.

## Schema migrations

For any schema change:

```text
code + migration/startup DDL
 -> regression tests
 -> backup/rollback plan
 -> PR/main CI
 -> exact-SHA deploy
 -> post-deploy DB/runtime smoke
```

Production is PostgreSQL. SQLite compatibility may be retained for tests, but a SQLite-only migration is not production-complete.

## Channel migrations

Instagram-specific persistent structures include channel identities, link tokens, promotions, language state and durable generation sessions/jobs.

Do not:

- fabricate Telegram IDs for Instagram identities;
- reset promotions during account relink;
- drop durable provider task/result state during schema cleanup;
- change billing ownership without a data backfill/reconciliation plan.

## Financial/data repairs

Repairs must be targeted and idempotent. Before manual changes record relevant user/channel/job/transaction identifiers and take a compatible HappyFox backup.

Do not manually credit/refund before reconciling the original transaction/generation state.

## Infrastructure migration

Use `happyfox-production-cutover.md` and `production-deployment.md`. Instagram may be temporarily disabled using `INSTAGRAM_ENABLED=0` while preserving Telegram if the migration risk is channel-specific.
