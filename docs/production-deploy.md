# Production deployment

FoxGen uses a protected GitHub Actions deployment workflow. Automatic production deployment is allowed only for a `main` commit whose `CI` workflow completed successfully and only when the `production` Environment explicitly enables autodeploy.

The repository is currently public, but production secrets and the server `.env` remain private. Repository visibility does not relax any runtime secret requirement.

## Deployment guarantees

The workflow/deploy script is designed around these invariants:

- PR CI never directly deploys production;
- `AUTODEPLOY_ENABLED=true` is required in the `production` GitHub Environment;
- deployment receives the exact CI-tested `main` SHA;
- a tested SHA that has already been superseded on `main` is skipped/refused rather than deploying stale code;
- SSH uses strict known-host verification;
- concurrent production deploys are serialized;
- the server checkout must be a clean tracked `main` branch;
- update is `git pull --ff-only`, never a forced reset;
- server `.env` is required and never uploaded/overwritten by GitHub Actions;
- Compose configuration is validated before replacement;
- production image is tagged with the commit SHA;
- PostgreSQL/Redis must be healthy before migrations/application startup;
- Alembic upgrades run before the new API/worker/bot stack is considered ready;
- API readiness must pass after startup;
- PostgreSQL, Redis and MinIO are not publicly published by production Compose;
- API host binding is loopback-only for the reverse proxy.

## GitHub Environment

Environment name:

```text
production
```

Required secrets:

```text
DEPLOY_HOST
DEPLOY_SSH_PRIVATE_KEY
DEPLOY_KNOWN_HOSTS
```

Variables:

```text
AUTODEPLOY_ENABLED=true|false
DEPLOY_USER=root                  # default
DEPLOY_PORT=22                    # default
DEPLOY_PATH=/root/foxgen          # default
DEPLOY_COMPOSE_FILE=docker-compose.prod.yml
```

See `github-environment-setup.md` for setup/verification.

## Server prerequisites

Install:

- Git;
- Docker Engine;
- Docker Compose plugin;
- `curl`;
- `flock`.

Create the checkout once:

```bash
git clone https://github.com/Bambale0/foxgen.git /root/foxgen
cd /root/foxgen
git switch main
```

A public repository does not require a read credential for HTTPS cloning, but the deployment server still needs outbound GitHub access. If the repository later becomes private, configure a read-only deploy credential on the server separately from the GitHub-Actions-to-server SSH key.

## Production environment file

Bootstrap once:

```bash
cd /root/foxgen
cp deploy/production.env.example .env
chmod 600 .env
nano .env
```

Generate independent secrets, for example:

```bash
openssl rand -hex 32
```

Do not reuse one secret across internal API, KIE webhook verification, admin HMAC, database, Redis or storage.

Required groups depend on enabled features, but a normal production bot/generation deployment needs:

- Telegram bot token;
- database and Redis URLs/credentials;
- internal API token;
- KIE key and callback/webhook configuration;
- private S3/MinIO settings;
- worker/media settings;
- deliberate paid-submission/pricing configuration.

The full admin contour additionally needs a dedicated HMAC key/network allowlist/bootstrap/durable admin policy before it is enabled. See `configuration.md` and `admin-control-plane.md`.

## Validate before first deployment

```bash
cd /root/foxgen
FOXGEN_IMAGE_TAG="$(git rev-parse HEAD)" \
  docker compose --env-file .env -f docker-compose.prod.yml config --quiet
```

Production deploy also rejects known development PostgreSQL and MinIO secret values.

Before enabling automatic deployment, verify:

1. `FOXGEN_ENV=production`;
2. server `.env` permissions are restrictive;
3. production storage bucket is private;
4. lifecycle cleanup for temporary `inputs/` is configured externally;
5. reverse proxy exposes only intended public paths;
6. `/internal/admin/` is blocked on public ingress;
7. current database backup/restore procedure works;
8. GitHub Environment host key/private SSH key are correct.

## Temporary input lifecycle prerequisite

Current `main` requires a storage-level lifecycle rule for temporary Telegram references. The application does not currently install that rule during deploy.

Recommended baseline:

```text
prefix: inputs/
expire after: 2 days
abort incomplete multipart uploads after: 1 day
```

Do not apply this short retention to durable generated results. See `input-media-lifecycle.md`.

## Normal deployment sequence

```text
push/merge main
  -> CI runs full quality/infrastructure/security/image pipeline
  -> CI success
  -> Deploy production workflow
  -> production Environment gate
  -> strict SSH
  -> flock deployment lock
  -> verify server configuration
  -> fetch origin/main
  -> verify exact expected SHA/current main
  -> clean-tree check
  -> git pull --ff-only
  -> docker compose config
  -> build foxgen:<commit-sha>
  -> start/verify PostgreSQL, Redis, MinIO
  -> ensure media bucket exists
  -> alembic upgrade head
  -> start API, worker, bot
  -> wait for API/container readiness
  -> HTTP /health/ready smoke check
```

## Migration-bearing releases

The admin control-plane release adds Alembic revision `20260813_0008` and its durable admin/support/campaign/audit state.

For any migration-bearing deployment:

- take/verify a database backup appropriate to the environment;
- read the migration before rollout;
- confirm CI upgrade + downgrade/re-upgrade passed;
- prefer forward repair migrations after a production schema rollout;
- do not downgrade away admin/outbox history while queued or forensic data is still needed.

## Reverse proxy

Expose the public HTTPS application through the host reverse proxy to loopback API port, for example:

```text
127.0.0.1:8080
```

Do not expose PostgreSQL, Redis or MinIO host ports in production.

Provider callback origin:

```env
FOXGEN_KIE_CALLBACK_BASE_URL=https://your-public-origin.example
```

The public proxy must allow required provider/public API routes while explicitly denying internal administrative routes. Recommended public Nginx rule:

```nginx
location ^~ /internal/admin/ {
    return 404;
}
```

Backend bot/operator clients call internal admin routes through the private container/VPC path instead.

## Manual deployment

Use **Actions → Deploy production → Run workflow**. When supplying a commit SHA, use the full current `main` SHA intended for deployment. The server script intentionally avoids deploying an old superseded SHA.

## Verify after deployment

On the server:

```bash
cd /root/foxgen
export FOXGEN_IMAGE_TAG="$(git rev-parse HEAD)"
docker compose --env-file .env -f docker-compose.prod.yml ps
docker compose --env-file .env -f docker-compose.prod.yml logs --tail=200 api worker bot
curl --fail --silent http://127.0.0.1:${FOXGEN_PUBLIC_API_PORT:-8080}/health/ready
```

Also smoke test according to enabled features:

- Telegram `/menu` and Quick Start;
- model catalog/validation;
- one controlled paid test generation when appropriate;
- `/admin` for an authorized bootstrap/durable admin;
- signed `/internal/admin/health` from backend network;
- denial of `/internal/admin/health` through public ingress;
- worker processing/dead-letter counts.

See `operations-runbook.md`.

## Stop automatic deployment

Set:

```text
AUTODEPLOY_ENABLED=false
```

This prevents future automatic deploy jobs but does not modify the currently running release.

## Application rollback

Preferred application rollback is a normal Git revert on `main`:

```text
bad release
  -> revert commit/PR on main
  -> CI
  -> deploy the tested revert commit
```

Do not force-reset the production checkout.

A database schema that already reached production may not be safely downgradable with the application. Prefer a forward repair migration when durable data/history must be retained.

## Emergency containment

Depending on the incident:

- set `AUTODEPLOY_ENABLED=false` to freeze deployments;
- set `FOXGEN_TASK_SUBMISSION_ENABLED=false` to stop new paid generation admission;
- runtime-disable an affected model through the admin contour;
- set `FOXGEN_ADMIN_API_ENABLED=false` / `FOXGEN_ADMIN_WEB_ENABLED=false` to contain admin exposure;
- stop/cancel a campaign through controlled admin state before disabling its control path;
- preserve database/audit/outbox evidence.

See `operations-runbook.md` for incident-specific steps.