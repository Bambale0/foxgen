# HappyFox production cutover

This runbook establishes or changes an isolated HappyFox production runtime.

## Isolation boundary

HappyFox must own its own:

- Telegram bot token;
- public origin/Mini App domain;
- PostgreSQL database/user;
- Redis DB/prefix;
- provider secrets/webhooks;
- payment credentials/offers;
- media storage;
- admin/support configuration;
- deployment secrets and runtime identity.

Never reuse NEUROMIX/Tanya credentials or data plane as an implicit shortcut.

## Canonical runtime identity

```text
Product ID:       happyfox
Compose project:  foxgen-happyfox
Container:        foxgen-happyfox-bot
Database:         happyfox
Redis prefix:     foxgen_happyfox
Production branch: main
```

Public URLs are environment configuration. Current production origin is documented in the root README/handoff.

## Preflight

Use:

```bash
python scripts/validate_happyfox_env.py .env .env.happyfox.runtime .env.postgres
```

Expected fail-closed checks include product identity, PostgreSQL, Redis isolation, selected payment/provider credentials and known forbidden legacy domains/namespaces.

## Base cutover sequence

1. Prepare isolated PostgreSQL/Redis.
2. Configure HappyFox `.env` from `.env.happyfox.example` without copying secrets from another product.
3. Configure Nginx/TLS for public origin and Mini App.
4. Configure Telegram webhook for the HappyFox bot.
5. Configure provider/payment webhooks required by the selected production integrations.
6. Merge change to `main` through CI.
7. Run exact-SHA production deploy.
8. Verify public `/health` and Mini App revision.
9. Smoke Telegram start/bootstrap/generation/balance/payment paths.
10. Record deploy SHA/run.

## Payment cutover

HappyFox supports multiple payment integrations, but channels may present different subsets.

Telegram general UI can keep configured providers including CryptoBot.

Instagram handoff is intentionally:

```text
YooKassa
Lava Top -> card / SBP
```

Do not delete CryptoBot globally to enforce the Instagram subset.

HappyFox Lava offer IDs must be configured from HappyFox environment and must not reuse imported Tanya offer IDs.

## Instagram dark deploy

Instagram should first be deployed dark:

```dotenv
INSTAGRAM_ENABLED=0
```

This verifies that new code can coexist with Telegram/Mini App without registering the Meta routes/worker.

## Instagram live cutover

### External prerequisites

- Professional Instagram Creator/Business account;
- Meta app configured for Instagram Login;
- required permissions/access for basic profile, messages, comments and content publishing;
- public HTTPS HappyFox webhook;
- valid Instagram user access token and professional account ID.

### Runtime variables

```dotenv
INSTAGRAM_ENABLED=1
INSTAGRAM_APP_ID=...
INSTAGRAM_APP_SECRET=...
INSTAGRAM_VERIFY_TOKEN=...
INSTAGRAM_ACCESS_TOKEN=...
INSTAGRAM_IG_USER_ID=...
INSTAGRAM_API_VERSION=v24.0
INSTAGRAM_WEBHOOK_PATH=/instagram/webhook
INSTAGRAM_SUBSCRIBED_FIELDS=messages,messaging_postbacks,comments
```

### Verification before enable

1. GET webhook verification returns `hub.challenge` only for the configured verify token.
2. Invalid `X-Hub-Signature-256` POST is rejected.
3. Valid signed webhook normalizes correctly.
4. `/{ig_user_id}/subscribed_apps` includes `messages,messaging_postbacks,comments`.
5. Meta access token can send a reply in a user-initiated conversation.
6. Public media URL used for result/publishing is HTTPS and reachable by Meta.

### Enable and deploy

Change production runtime configuration to `INSTAGRAM_ENABLED=1`, then deploy/restart the exact tested `main` SHA. Do not enable by modifying application source or bypassing GitHub release evidence.

### Live smoke

- RU user receives Russian flow after meaningful Russian text;
- EN user receives English flow after meaningful English text;
- attachment-first entry is bilingual until language is known;
- first successful photo uses Seedream 5 Pro High and is free;
- failed first photo preserves entitlement;
- second photo asks for linked balance/paid confirmation;
- Video immediately shows paid top-up before accepting reference;
- YooKassa top-up path works;
- Lava Top card/SBP path works;
- `Продолжить` and `Continue` resume paid video after balance check;
- comment acquisition goes to Direct chooser;
- duplicate webhook does not duplicate charge/provider submit/result delivery.

## Instagram rollback

If Instagram causes an incident and Telegram remains healthy:

1. set `INSTAGRAM_ENABLED=0`;
2. redeploy/restart verified HappyFox runtime;
3. verify Telegram/Mini App health;
4. preserve DB job state for investigation;
5. do not delete Instagram identities/promotions/jobs as an emergency action unless data repair is explicitly required.

## Full rollback

For a broader application incident, redeploy a previously verified HappyFox `main` SHA with compatible schema/data backup.

Never use `banano_kling` runtime/database as a rollback target.

## Evidence to retain

- main SHA;
- CI run;
- deploy run;
- health/revision result;
- Telegram smoke;
- Instagram activation flag and smoke if enabled;
- Meta subscription fields (without secrets/tokens).
