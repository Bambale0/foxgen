# Docker deployment for the Telegram backend

This deployment replaces only the Python/systemd process. Existing host Nginx,
PostgreSQL, Redis, TLS certificates and public webhook URLs remain unchanged.

## Why host networking is intentional

The production service already listens on localhost and is reached through host
Nginx. `compose.backend.yml` uses Linux host networking so the container can keep
using the existing values such as:

- `WEBHOOK_BIND_HOST=127.0.0.1`
- `WEBHOOK_PORT=1888`
- `REDIS_URL=redis://127.0.0.1:6379/0`
- a local PostgreSQL address from `.env.postgres`

No database migration and no public container port are required for the first
cutover.

## Persistent paths

The following host directories are mounted into the container:

- `data/`
- `static/uploads/`
- `logs/`
- `backups/`
- `outputs/`

The deployment script changes their ownership to container UID/GID `10001`.
Override `APP_UID` and `APP_GID` when another ownership model is required.

## First deployment

From the backend server project directory:

```bash
cd /root/tanya/banano_kling

git fetch origin
git switch tanyapi
git pull --ff-only origin tanyapi

sudo bash scripts/deploy_backend_docker.sh deploy
```

The script performs this sequence:

1. validates Docker Compose and environment files;
2. builds the image while the systemd service is still serving traffic;
3. compiles Python inside the image and checks FFmpeg and database tools;
4. creates a database backup;
5. stops `banano-kling.service`;
6. starts the host-networked container;
7. waits for Docker health status;
8. disables systemd only after the container becomes healthy;
9. rolls back to systemd automatically when startup or health checks fail.

## Status and logs

```bash
sudo bash scripts/deploy_backend_docker.sh status
sudo bash scripts/deploy_backend_docker.sh logs
```

Direct Compose commands:

```bash
docker compose -f compose.backend.yml ps
docker compose -f compose.backend.yml logs --tail=200 bot
docker inspect banano-kling-bot --format '{{json .State.Health}}'
```

## Roll back to systemd

```bash
sudo bash scripts/deploy_backend_docker.sh rollback
```

This stops the Compose service and enables/restarts `banano-kling.service`.

## Deploy an image published by CI

Successful pushes to `tanyapi` publish:

```text
ghcr.io/bambale0/banano-kling-bot:tanyapi
```

Use the registry image instead of a local build:

```bash
cd /root/tanya/banano_kling

export BANANO_IMAGE=ghcr.io/bambale0/banano-kling-bot:tanyapi
export PULL_IMAGE=1
sudo -E bash scripts/deploy_backend_docker.sh deploy
```

For a deterministic rollback or release, use the immutable SHA tag printed by CI:

```text
ghcr.io/bambale0/banano-kling-bot:sha-<12-character-commit>
```

## CI pipeline

`.github/workflows/ci.yml` now runs:

1. dependency validation and Ruff on changed Python files;
2. shell syntax checks for deployment scripts;
3. the full safe pytest regression suite;
4. a production Docker build with BuildKit cache;
5. imports and runtime-binary checks inside the built image;
6. Compose configuration validation;
7. GHCR publication only for successful branch pushes.

Live paid/provider smoke tests remain restricted to pushes on `main`.
