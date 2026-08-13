# GitHub production Environment setup

FoxGen production deployment is protected by a GitHub Actions Environment named `production`. The deploy workflow remains inert unless the required secrets exist and `AUTODEPLOY_ENABLED=true`.

Use the GitHub web UI or `gh`/GitHub API according to the permissions available to the repository administrator. This guide uses the web UI to create/review the Environment and `gh` for repeatable secret/variable setup.

## 1. Create or open `production`

Repository:

```text
Bambale0/foxgen
```

Open repository **Settings → Environments** and create/open:

```text
production
```

Optional protection rules can require an approving reviewer before the SSH deployment job starts.

## 2. Required secrets

The deployment workflow expects Environment secrets:

| Secret | Purpose |
|---|---|
| `DEPLOY_HOST` | Production hostname/public IP used by SSH |
| `DEPLOY_SSH_PRIVATE_KEY` | Dedicated deployment Ed25519 private key |
| `DEPLOY_KNOWN_HOSTS` | Verified SSH host-key line |

Example with GitHub CLI:

```bash
gh secret set DEPLOY_HOST --repo Bambale0/foxgen --env production --body "your-server-host"
gh secret set DEPLOY_KNOWN_HOSTS --repo Bambale0/foxgen --env production --body "your-server-host ssh-ed25519 AAAA..."
gh secret set DEPLOY_SSH_PRIVATE_KEY --repo Bambale0/foxgen --env production --body "$(cat ~/.ssh/foxgen_deploy)"
```

Never paste the private deployment key into an issue, pull request, chat or repository file.

## 3. Verify the host key before storing it

From a trusted network:

```bash
ssh-keyscan -p 22 your-server-host
```

Verify the fingerprint through an independent trusted channel before using the line as `DEPLOY_KNOWN_HOSTS`. The workflow uses strict host-key checking; it does not automatically trust a newly presented host key.

## 4. Environment variables

Required activation variable:

```text
AUTODEPLOY_ENABLED=true
```

Optional variables and workflow defaults:

| Variable | Default |
|---|---|
| `DEPLOY_USER` | `root` |
| `DEPLOY_PORT` | `22` |
| `DEPLOY_PATH` | `/root/foxgen` |
| `DEPLOY_COMPOSE_FILE` | `docker-compose.prod.yml` |

Set them through **Settings → Environments → production → Environment variables**, or with GitHub API/CLI tooling available to your account.

One repeatable `gh api` pattern is:

```bash
gh api \
  --method POST \
  -H "Accept: application/vnd.github+json" \
  /repos/Bambale0/foxgen/environments/production/variables \
  -f name='AUTODEPLOY_ENABLED' \
  -f value='true'
```

For an existing variable, update it rather than creating a duplicate. The web UI is the simplest way to review the final values.

## 5. Server prerequisites

GitHub Environment configuration is only the remote trigger side. The server must already have:

- Git;
- Docker Engine;
- Docker Compose plugin;
- `curl`;
- `flock`;
- repository checkout at `DEPLOY_PATH` on branch `main`;
- a protected server-side `.env`;
- Git credentials/deploy key that permit `git fetch/pull` from the public or configured repository origin as appropriate.

The GitHub Actions SSH key is for connecting **to the production server**. It is not the same as any Git credential the server may use to update its checkout.

## 6. Server `.env`

Create from the repository example once, then manage it as server configuration:

```bash
cd /root/foxgen
cp deploy/production.env.example .env
chmod 600 .env
```

Replace every placeholder. Do not have CI copy or overwrite `.env` during normal deploys.

Important production groups include:

- Telegram token;
- PostgreSQL/Redis credentials and URLs;
- internal generation token;
- KIE key/callback HMAC;
- full admin HMAC/network/bootstrap settings if the admin API is enabled;
- S3/MinIO credentials;
- pricing/submission switches.

See `configuration.md` and `admin-control-plane.md`.

## 7. Enable deployment only after validation

Before setting `AUTODEPLOY_ENABLED=true`, validate on the server:

```bash
cd /root/foxgen
FOXGEN_IMAGE_TAG="$(git rev-parse HEAD)" \
  docker compose --env-file .env -f docker-compose.prod.yml config --quiet
```

Also confirm:

- production `.env` does not contain development PostgreSQL/MinIO credentials;
- the public reverse proxy exposes only intended public routes;
- `/internal/admin/` is denied by public ingress;
- required object-storage lifecycle for temporary `inputs/` exists;
- database backup/rollback procedure is understood before a migration-bearing release.

Then enable:

```text
AUTODEPLOY_ENABLED=true
```

## 8. Verify configuration

Examples:

```bash
gh secret list --repo Bambale0/foxgen --env production
gh api /repos/Bambale0/foxgen/environments/production/variables
```

Do not expect secret values to be readable back from GitHub; verify names/presence and test the deployment path instead.

## 9. Trigger behavior

A normal sequence is:

```text
merge/push main
  -> CI
  -> CI succeeds
  -> Deploy production workflow
  -> production Environment gate
  -> exact tested SHA over SSH
```

A manual deployment can also be started from **Actions → Deploy production → Run workflow**. The optional SHA must resolve to the current deployable `main` commit; the server script rejects/safely skips superseded commits.

## 10. Disable immediately

To stop future automatic deployment without editing code:

```text
AUTODEPLOY_ENABLED=false
```

This does not roll back the currently running release. For rollback/containment see `production-deploy.md` and `operations-runbook.md`.