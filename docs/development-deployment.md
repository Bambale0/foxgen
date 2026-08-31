# HappyFox development and release flow

This document replaces the imported NEUROMIX `dev -> tanyapi` release policy. For `Bambale0/foxgen`, production source of truth is `main`.

## Branch policy

| Branch | Purpose | Deploy |
| --- | --- | --- |
| `feature/*`, `fix/*`, `docs/*` | isolated work | CI only |
| `main` | accepted HappyFox production source | exact-SHA production pipeline |
| `legacy/*` | historical/reference | never deploy |

Normal path:

```text
branch
 -> PR to main
 -> CI on exact PR head
 -> merge
 -> CI on exact main SHA
 -> isolated HappyFox preflight
 -> exact-SHA production deploy
 -> health/revision smoke
```

Do not create a `tanyapi` release path inside `foxgen` and do not deploy HappyFox through the `banano_kling` repository.

## Local development

Backend baseline:

```bash
python -m pip install -r requirements.txt
python scripts/apply_visible_copy_fixes.py
python scripts/apply_happyfox_product_copy.py
python -m compileall -q bot scripts
pytest tests/ --ignore=tests/live -m 'not live_smoke'
```

Mini App:

```bash
cd frontend/miniapp-v0
npm ci
npm audit --omit=dev --audit-level=high
npm run lint
npm run build
```

Use separate dev/test databases, Redis prefixes and provider budgets. Never point local development at the production HappyFox database unless the task explicitly requires controlled production diagnostics.

## PR requirements

A feature PR should contain:

- implementation;
- regression tests for changed behavior;
- documentation updates when product/FSM/env/deploy contracts changed;
- no secrets or copied production `.env`;
- no unrelated `banano_kling` changes.

Before merge, the exact PR head must pass the repository CI gates.

## CI gates

`.github/workflows/ci.yml` validates:

- Python dependency install and runtime compile;
- HappyFox product-copy normalization;
- Ruff on HappyFox Python delta;
- safe backend regression suite;
- locked frontend dependencies + production dependency audit;
- frontend lint and production static export;
- critical browser journeys;
- Telegram startup on Chromium and iPhone WebKit;
- production Docker exact-source build/runtime import verification.

Channel work is not complete when unit tests pass but browser/Docker release gates are red.

## Instagram development

Instagram code should remain runnable with `INSTAGRAM_ENABLED=0`; unit/regression tests inject enabled settings without requiring real Meta credentials.

Recommended regression set:

```bash
pytest -q \
  tests/test_instagram_transport.py \
  tests/test_instagram_channel.py \
  tests/test_instagram_creator_flow.py \
  tests/test_instagram_generation.py \
  tests/test_instagram_model_contract.py \
  tests/test_instagram_i18n.py \
  tests/test_instagram_account_link.py \
  tests/test_instagram_account_link_router.py
```

Rules:

- keep transport normalization separate from generation/billing domain;
- new user-facing strings go through `bot/instagram_i18n.py`;
- do not weaken HMAC/idempotency/account-link security to simplify tests;
- free entitlement applies only to first successful photo;
- video remains paid before reference upload;
- Instagram top-up remains YooKassa/Lava only while Telegram providers stay independent.

## Database changes

Instagram/channel schemas use SQLite-compatible test paths and PostgreSQL production paths. Any new table/column must be safe for production startup/migration and covered by regression tests.

Do not silently reinterpret Telegram IDs as generic channel IDs.

## Payment changes

When changing Instagram payments, reuse existing production payment handlers wherever possible. Instagram should select presentation/provider options, not duplicate webhook/ledger logic.

Financial invariants:

- charge once;
- refund once on terminal paid generation failure;
- first-free-photo reservation is released on terminal provider failure;
- relinking an Instagram account cannot reset the free promotion;
- retries do not submit a second provider task when a persisted provider task ID exists.

## Documentation Definition of Done

If a PR changes Instagram model, pricing, language behavior, top-up UX, environment variables or live activation, update:

- `docs/instagram-channel.md`;
- `docs/architecture.md` if boundaries changed;
- `docs/environment.md` for env changes;
- `FSM_USER_FLOWS.md` for state changes;
- `QA_AUDIT_CHECKLIST.md` for new release invariants;
- relevant tracemap.

## Merge

Merge only after the exact head is green. If a new commit is pushed after CI success, wait for CI on the new head.

After merge, wait for `main` CI on the merge SHA. Production deploy should be triggered from verified `main`, not manually from an untested branch.

## Production deployment

Deployment workflow:

```text
.github/workflows/deploy-production.yml
```

It should:

1. resolve exact verified main SHA;
2. validate configuration;
3. check out that exact commit;
4. verify repository provenance;
5. configure pinned SSH;
6. resolve HappyFox Mini App/public origin;
7. run isolated runtime preflight;
8. deploy exact commit;
9. publish deployment status/summary.

See `production-deployment.md`.

## Hotfix

```text
fix/<incident> from main
 -> focused regression test
 -> PR to main
 -> exact-head CI
 -> merge
 -> main CI
 -> deploy
```

Do not patch production working trees outside Git as the final state. Emergency server edits must be converted immediately into a reviewed repository change.

## Rollback

Rollback target is a previously verified `foxgen` main SHA compatible with the current HappyFox database/schema.

For Instagram-only incident where Telegram/core are healthy, preferred first containment is:

```dotenv
INSTAGRAM_ENABLED=0
```

then redeploy/restart the verified runtime. This disables Instagram route registration without rolling back unrelated Telegram improvements.

## Release evidence

For significant production changes record:

- PR number;
- PR head SHA and CI run;
- merge/main SHA and main CI run;
- production deploy run;
- health/revision smoke result;
- channel-specific live smoke when applicable.
