# Production autodeploy

FoxGen deploys only a commit from `main` whose `CI` workflow completed successfully. The deployment workflow connects to the server over SSH and streams `scripts/deploy-production.sh`; it does not copy application secrets through GitHub Actions.

## Safety properties

- autodeploy is disabled until `AUTODEPLOY_ENABLED=true` is set in the `production` GitHub Environment;
- pull-request checks never deploy;
- the exact CI-tested commit SHA is passed to the server;
- a deployment is skipped when that SHA has already been superseded on `main`;
- the server repository is updated with `git pull --ff-only`;
- tracked local changes stop the deployment;
- `.env` must already exist on the server and is never created or overwritten;
- `flock` prevents concurrent deployments;
- PostgreSQL and Redis must be healthy before migrations run;
- the API, worker and bot must be running, and `/health/ready` must pass;
- PostgreSQL, Redis and MinIO are not published to the Internet;
- the API is bound to host loopback for an Nginx or Caddy reverse proxy.

## 1. Prepare the server

Install Git, Docker Engine, the Docker Compose plugin, `curl` and `flock`. Clone the private repository with a read-only GitHub deploy key:

```bash
install -d -m 700 /root/.ssh
git clone git@github.com:Bambale0/foxgen.git /root/foxgen
cd /root/foxgen
git switch main
```

Create the server-side configuration:

```bash
cp deploy/production.env.example .env
chmod 600 .env
nano .env
```

Replace every placeholder. Generate independent secrets rather than reusing one value:

```bash
openssl rand -hex 32
```

The following values must agree:

- `FOXGEN_POSTGRES_DB`, `FOXGEN_POSTGRES_USER` and `FOXGEN_POSTGRES_PASSWORD` with `FOXGEN_DATABASE_URL`;
- `FOXGEN_REDIS_PASSWORD` with `FOXGEN_REDIS_URL`;
- `FOXGEN_S3_ACCESS_KEY_ID` and `FOXGEN_S3_SECRET_ACCESS_KEY` are the credentials of the private MinIO service;
- `FOXGEN_PUBLIC_API_PORT` is the host loopback port used by the reverse proxy.

Validate the production configuration without starting it:

```bash
cd /root/foxgen
FOXGEN_IMAGE_TAG="$(git rev-parse HEAD)" \
  docker compose --env-file .env -f docker-compose.prod.yml config --quiet
```

The production deploy script rejects the development PostgreSQL and MinIO credentials.

## 2. Prepare SSH access for GitHub Actions

Create a dedicated Ed25519 key pair. Put the public key in the deployment user's `~/.ssh/authorized_keys`. Store the private key in GitHub; do not put it in the repository.

Collect the real host key from a trusted network:

```bash
ssh-keyscan -p 22 your-server.example.com
```

Review the fingerprint before saving this output. The workflow uses strict host-key checking and does not accept a new key automatically.

## 3. Configure the GitHub Environment

In repository settings, create an Environment named `production`.

Environment secrets:

| Name | Value |
| --- | --- |
| `DEPLOY_HOST` | Production hostname or public IP |
| `DEPLOY_SSH_PRIVATE_KEY` | Complete private Ed25519 key |
| `DEPLOY_KNOWN_HOSTS` | Verified `ssh-keyscan` line |

Environment variables:

| Name | Default | Purpose |
| --- | --- | --- |
| `AUTODEPLOY_ENABLED` | `false` | Set to `true` only after the server is ready |
| `DEPLOY_USER` | `root` | SSH deployment user |
| `DEPLOY_PORT` | `22` | SSH port |
| `DEPLOY_PATH` | `/root/foxgen` | Existing server checkout |
| `DEPLOY_COMPOSE_FILE` | `docker-compose.prod.yml` | Production Compose file |

Optional Environment protection rules can require manual approval before the SSH job starts.

## 4. Enable and run

Set `AUTODEPLOY_ENABLED=true`. Every successful `CI` run caused by a push to `main` will then deploy its tested SHA.

A manual run is available under **Actions → Deploy production → Run workflow**. The optional SHA must be the full current `main` commit. The server intentionally refuses to deploy an older superseded SHA.

## What the deploy script does

```text
CI-tested main SHA
  -> strict SSH
  -> deployment lock
  -> verify production .env
  -> fetch origin/main
  -> exact-SHA and clean-tree checks
  -> fast-forward pull
  -> validate Compose
  -> build foxgen:<commit-sha>
  -> start PostgreSQL, Redis and MinIO
  -> create private media bucket
  -> run Alembic migrations
  -> start API, worker and bot
  -> container and /health/ready checks
```

## Reverse proxy

Expose only HTTPS through the host reverse proxy. Proxy the public domain to the loopback API port, for example `127.0.0.1:8080`. Do not publish PostgreSQL, Redis or MinIO ports.

`FOXGEN_KIE_CALLBACK_BASE_URL` must use the public HTTPS origin accepted by KIE.ai.

## Stop or recover

Disable future deployments immediately by setting:

```text
AUTODEPLOY_ENABLED=false
```

For a bad application change, revert the commit on `main` and let the reverted commit pass CI and deploy normally. Do not force-reset the production branch. Database migrations are not automatically downgraded; write a forward repair migration when a schema change has already reached production.

Inspect the current stack on the server:

```bash
cd /root/foxgen
FOXGEN_IMAGE_TAG="$(git rev-parse HEAD)" \
  docker compose --env-file .env -f docker-compose.prod.yml ps

FOXGEN_IMAGE_TAG="$(git rev-parse HEAD)" \
  docker compose --env-file .env -f docker-compose.prod.yml logs --tail=200 api worker bot
```
