# HappyFox production deployment

Production source of truth: `Bambale0/foxgen:main`.

This document describes the accepted production path. Historical NEUROMIX service names, `tanyapi` branch instructions and old domains are not valid HappyFox deploy commands.

## Production identity

```text
Product:          happyfox
Dedicated host:   happyfox
Landing:          https://happy-fox.online/
Mini App:         https://app.happy-fox.online/mini-app/
API/webhooks:     https://api.happy-fox.online
Compose project:  foxgen-happyfox
Container:        foxgen-happyfox-bot
Database:         happyfox_cutover
Redis prefix:     foxgen_happyfox
Branch:           main
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
 -> pin dedicated HappyFox SSH host
 -> isolated runtime preflight
 -> deploy exact backend + static Mini App/landing
 -> reconcile Telegram webhook + Mini App menu and MAX subscription + quick commands
 -> public health/revision/payment-webhook smoke
 -> publish deployment status
```

Never deploy an arbitrary branch head or dirty server checkout.

## Runtime validation

Post-deploy checks should include:

```text
container/service healthy
https://api.happy-fox.online/health succeeds
Mini App static revision equals expected SHA
landing returns 200
PostgreSQL 17 reachable and pre/post backup verified
Redis namespace isolated
happyfox-docker-prune.timer enabled and waiting
Telegram webhook URL is https://api.happy-fox.online/webhook
Telegram pending_update_count = 0 and last_error_message is empty
Telegram native chat menu type = web_app and URL starts with https://app.happy-fox.online/mini-app/
MAX has exactly one subscription, matching MAX_WEBHOOK_URL (api.happy-fox.online)
MAX native quick commands are /start, /feed, /prompts, /help, /ref, /earn
YooKassa/provider webhook routes are live
```

### Telegram relay contract

The application/data plane stays on the dedicated `happyfox` host. Because its network path to Telegram is currently unreliable, Telegram uses a transport-only `apix` relay:

```dotenv
TELEGRAM_WEBHOOK_URL=https://api.happy-fox.online/webhook
TELEGRAM_WEBHOOK_IP_ADDRESS=<relay IPv4>
```

`setWebhook` must use `drop_pending_updates=False`. The relay presents a valid certificate for `api.happy-fox.online`, forwards the request to the dedicated API origin and does not run a second bot worker. Outbound Bot API traffic is carried by `happyfox-telegram-egress.service`.

The apix relay owns a separate Let's Encrypt certificate for `api.happy-fox.online`. Telegram still uses the canonical URL/SNI `https://api.happy-fox.online/webhook`; `TELEGRAM_WEBHOOK_IP_ADDRESS` only pins ingress to the relay IPv4. Certificate renewal is handled on the relay host and must be followed by `nginx -t`/reload verification.

After each deploy, the system menu must be reconciled to the native Mini App launcher (`MenuButtonWebApp`) using the versioned `MINI_APP_URL`. Bot commands (`/start`, `/feed`, `/prompts`, `/help`, `/ref`, `/earn`) must remain registered separately.

CI already validates production Docker image/runtime imports before the deploy workflow is allowed to act.

### Docker/containerd retention

The dedicated HappyFox host runs `happyfox-docker-prune.timer` once per day. Its service removes only unused Docker artifacts older than five days (`120h`):

- stopped containers older than the retention window;
- unused images older than the retention window;
- build cache older than the retention window.

The cleanup must never call `docker volume prune` and must never pass `--volumes`. PostgreSQL, Redis and MinIO named volumes are persistent production data.

Canonical implementation:

```text
scripts/happyfox_docker_prune.sh
deploy/systemd/happyfox-docker-prune.service
deploy/systemd/happyfox-docker-prune.timer
```

Production deploy installs and enables these units idempotently. The script logs disk usage before and after cleanup plus Docker disk accounting; inspect it with `journalctl -u happyfox-docker-prune.service`.


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

### MAX subscription verification

`scripts/check_max_connectivity.py` requires exactly one configured canonical
subscription, as well as the native quick-command contract. An extra historical
endpoint fails deployment verification: two listeners on the same HappyFox bot
can process the same update independently. The check never deletes subscriptions.
Before changing a binding, verify the native bot identity, preserve subscription
metadata outside Git, and target only the identified obsolete HappyFox binding.
Subscription secrets are not returned by MAX; restoration needs the receiving
service's original secret and a POST subscription request. Never clean bindings
on another bot or rotate credentials as an automatic remedy.
