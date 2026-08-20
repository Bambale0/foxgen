# Production auto deploy

Production NEUROMIX deploys strictly from branch `tanyapi`.

Branch `main` is not part of this project's release flow.

Normal release path:

```text
feature branch
    -> pull request to dev
    -> automatic DEV deploy
    -> manual Telegram smoke on DEV bot
    -> pull request dev -> tanyapi
    -> merge to tanyapi
    -> automatic production deploy
```

Full DEV setup and release procedure: [development-deployment.md](development-deployment.md).

## Backend production workflow

Workflow:

```text
.github/workflows/deploy-production.yml
```

It deploys every successful push to `tanyapi` to the production backend host.

Deployment order:

1. wait for the matching `CI — Tanya TG Bot` run;
2. refuse deployment when that CI run is not successful;
3. connect to the production host with a pinned SSH host key;
4. refuse deployment when tracked local repository changes exist;
5. fetch and reset the server checkout to the exact GitHub commit SHA from `tanyapi`;
6. run `scripts/deploy_backend_docker.sh deploy`;
7. verify Docker health and the image revision label;
8. print Docker/systemd diagnostics when a deployment fails.

The existing deploy script creates a database backup and restores the production systemd service automatically when Docker health fails after a systemd-to-Docker cutover.

## Frontend production workflow

Workflow:

```text
.github/workflows/deploy-frontend-production.yml
```

It deploys production Mini App changes only from `tanyapi` and uses the production frontend profile/domain.

Development frontend uses a separate workflow, domain, checkout and profile. DEV frontend artifacts must never be copied into the production web root manually.

## GitHub environment

Recommended environment name:

```text
production
```

Restrict the environment to branch `tanyapi` and store production-only credentials there. GitHub environment secrets with the same names can replace existing repository-level secrets without changing workflow references.

Do not make DEV workflows fall back to `PROD_*` secrets. A missing DEV configuration must fail rather than deploying to production accidentally.

## Required production secrets

Create these under repository Settings -> Environments -> `production`, or keep the existing repository secrets until migration is complete:

| Secret | Value |
| --- | --- |
| `PROD_SSH_HOST` | Public IPv4 address or DNS name of the production backend server |
| `PROD_SSH_PRIVATE_KEY` | Private ED25519 key used only by GitHub Actions |
| `PROD_SSH_KNOWN_HOSTS` | Pinned OpenSSH known-hosts line for the production host |
| `PROD_SSH_USER` | Optional, defaults to `root` |
| `PROD_SSH_PORT` | Optional, defaults to `22` |
| `PROD_PROJECT_PATH` | Optional, defaults to `/root/tanya/banano_kling` |

Frontend production uses its existing `FRONTEND_*` secrets and production domain/profile.

## Create a dedicated Actions key on the server

Run as the account that GitHub Actions will use, currently `root`:

```bash
install -d -m 0700 ~/.ssh
ssh-keygen -t ed25519 \
  -f ~/.ssh/github-actions-banano \
  -N '' \
  -C 'github-actions-banano-production'
cat ~/.ssh/github-actions-banano.pub >> ~/.ssh/authorized_keys
chmod 0600 ~/.ssh/authorized_keys
```

Put the full output of this command into `PROD_SSH_PRIVATE_KEY`:

```bash
cat ~/.ssh/github-actions-banano
```

After the secret has been saved, remove the private copy from the server:

```bash
shred -u ~/.ssh/github-actions-banano 2>/dev/null || rm -f ~/.ssh/github-actions-banano
```

Keep the `.pub` file for auditing or remove it after confirming that its content is present in `authorized_keys`.

## Pin the server host key

For port 22 and a host stored in `$HOST`, create the known-hosts value from the server's existing ED25519 host public key:

```bash
HOST='SERVER_PUBLIC_IP_OR_DNS'
printf '%s %s\n' "$HOST" "$(cat /etc/ssh/ssh_host_ed25519_key.pub)"
```

For a non-standard SSH port:

```bash
HOST='SERVER_PUBLIC_IP_OR_DNS'
PORT='2222'
printf '[%s]:%s %s\n' "$HOST" "$PORT" "$(cat /etc/ssh/ssh_host_ed25519_key.pub)"
```

Save exactly that line as `PROD_SSH_KNOWN_HOSTS`. The workflow deliberately does not use `StrictHostKeyChecking=no` and does not trust a live `ssh-keyscan` result.

## Release activation

A production release must come from a reviewed pull request:

```text
dev -> tanyapi
```

Before merge:

- DEV exact SHA is deployed;
- strict DEV CI passed;
- Telegram smoke passed on the separate DEV bot;
- release PR contains no untested extra changes;
- production secrets and `.env` were not copied to DEV.

After merge, the production workflows start from the new `tanyapi` SHA automatically.

The production host must already contain:

- the repository at `PROD_PROJECT_PATH`;
- `.env` and optional `.env.postgres` with the production bot token;
- Docker with the Compose plugin;
- the existing `banano-kling.service` for automatic rollback during first cutover.

## Production smoke

After production deploy:

- check backend health;
- open production bot `/start`;
- fully close and reopen production Mini App;
- verify bootstrap and balance;
- verify one low-cost test generation if release risk warrants it;
- verify webhook completion;
- verify media and profile/feed rendering;
- confirm DEV users/data did not appear in production.

## Emergency rollback

On the production server:

```bash
cd /root/tanya/banano_kling
sudo bash scripts/deploy_backend_docker.sh rollback
```

Prefer a revert commit in `tanyapi` so Git history and deployed state remain aligned.

After a production hotfix or revert, synchronize the resulting `tanyapi` state back into `dev` before the next normal release.

To stop automatic production deployment immediately, disable the production workflow or remove access to the `production` environment secrets. Do not modify DEV secrets as a production rollback mechanism.
