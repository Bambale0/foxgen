# HappyFox production deployment

Production source of truth: `Bambale0/foxgen:main`.

This document describes the accepted production path. Historical NEUROMIX service names, `tanyapi` branch instructions and old domains are not valid HappyFox deploy commands.

## Production identity

```text
Product:         happyfox
Public origin:   https://alena.chillcreative.ru
Mini App:        https://alena.chillcreative.ru/mini-app/
Compose project: foxgen-happyfox
Container:       foxgen-happyfox-bot
Database:        happyfox
Redis prefix:    foxgen_happyfox
Branch:          main
```

Runtime secrets and host-specific paths are supplied through production environment/GitHub configuration and must not be committed.

## Preconditions

Before deploy:

- exact `main` SHA has successful CI;
- production environment passes `scripts/validate_happyfox_env.py`;
- PostgreSQL/Redis are HappyFox-isolated;
- public domain/TLS are valid;
- provider/payment credentials selected for runtime are complete;
- no NEUROMIX/Tanya domains or shared data plane are configured;
- deployment SSH uses pinned host keys.

## Deployment workflow

Canonical workflow:

```text
.github/workflows/deploy-production.yml
```

Expected sequence:

```text
main CI success
 -> resolve verified SHA
 -> validate deployment configuration
 -> checkout exact SHA
 -> verify repository provenance
 -> configure pinned SSH
 -> resolve HappyFox domain
 -> isolated runtime preflight
 -> deploy exact backend + Mini App
 -> public health/revision smoke
 -> publish deployment status
```

Never deploy an arbitrary branch head or dirty server checkout.

## Runtime validation

Post-deploy checks should include:

```text
container/service healthy
public /health succeeds
Mini App static revision equals expected SHA
PostgreSQL reachable
Redis namespace isolated
Telegram webhook/runtime starts
```

CI already validates production Docker image/runtime imports before the deploy workflow is allowed to act.

## Instagram deployment state

Instagram implementation can be present in the production image while the channel remains disabled.

Safe default:

```dotenv
INSTAGRAM_ENABLED=0
```

When disabled, `bot/internal_api.py` does not register Instagram webhook routes/worker.

### Activating Instagram live

Configure outside Git:

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

Before flipping the flag:

1. Meta app/account access is ready for Instagram Login.
2. Required permissions are granted.
3. Public HTTPS webhook points to this HappyFox production origin.
4. GET verification succeeds.
5. Invalid HMAC POST is rejected; valid signed POST is accepted.
6. `subscribed_apps` contains required fields.
7. YooKassa/Lava top-up flow is configured for paid Instagram actions.
8. Telegram CryptoBot configuration is left untouched unless a separate Telegram task explicitly changes it.

After enabling and deploying, smoke both languages and both creator branches.

## Instagram live smoke

Minimum:

```text
RU Direct -> Фото -> reference -> prompt -> first free result
EN Direct -> Photo -> English result/copy
Second photo -> linked balance/payment confirmation
Video -> immediate paywall before reference
Top-up -> Telegram -> YooKassa path
Top-up -> Telegram -> Lava Top card/SBP path
Return -> Продолжить/Continue -> video reference requested
Comment acquisition -> private invite -> Direct Photo/Video chooser
Duplicate webhook -> no duplicate charge/provider task/delivery
```

Do not perform a real paid generation in smoke unless production change control permits it; provider/payment sandbox or controlled low-value account may be used when available.

## Rollback

### General rollback

Redeploy a previously verified HappyFox `main` SHA compatible with current schema/data.

Do not restore a NEUROMIX database/runtime as rollback target.

### Instagram-only containment

If Instagram is unhealthy while Telegram is healthy:

```dotenv
INSTAGRAM_ENABLED=0
```

Redeploy/restart the same verified application version. This removes Instagram route registration while preserving Telegram/Mini App functionality.

## Payment safety

Instagram paid flow reuses the shared HappyFox ledger and existing YooKassa/Lava production handlers. There is no independent Instagram balance.

Provider presentation:

- Instagram handoff: YooKassa + Lava Top;
- Telegram general balance menu: configured Telegram providers, including CryptoBot when enabled.

Do not globally delete a Telegram provider to satisfy an Instagram UX requirement.

## Release evidence

Record for every significant production deployment:

```text
PR number
PR exact head SHA + CI run
main merge SHA + CI run
production deploy run
health/revision result
channel-specific smoke result
```

## Related docs

- `happyfox-production-cutover.md`
- `happyfox-handoff.md`
- `environment.md`
- `instagram-channel.md`
- `development-deployment.md`
- `../QA_AUDIT_CHECKLIST.md`
