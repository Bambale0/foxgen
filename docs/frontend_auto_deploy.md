# NEUROMIX frontend auto deploy

The workflow `.github/workflows/deploy-frontend-production.yml` validates and deploys the
Mini App frontend when relevant files change on `tanyapi`.

## Execution order

1. build and test on a GitHub-hosted Ubuntu runner;
2. when that trusted push fails, retry the complete frontend validation on the
   self-hosted runner selected by `[self-hosted, linux, x64, nuromix]`;
3. wait for the matching full backend CI run;
4. connect to the standalone frontend host with a pinned SSH host key;
5. refuse deployment when the frontend checkout contains local changes;
6. reset `/opt/banano-kling-src` to the exact `tanyapi` commit;
7. run `cdn.sh --deploy-domain cdn.chillcreative.ru`;
8. verify `/frontend-health`, `/mini-app/`, and the static Next.js asset links;
9. print Nginx, installer, CDN, and Git diagnostics when deployment fails.

Pull requests never run code on the self-hosted `nuromix` runner and never deploy
to production.

## Trigger paths

Automatic frontend validation/deployment is triggered by changes to:

- `frontend/**`;
- `cdn.sh`;
- `scripts/install_miniapp_frontend_https_host.sh`;
- `.github/workflows/deploy-frontend.yml`.

A manual run is also available through `workflow_dispatch`.

## Repository secrets

Create these under **Settings → Secrets and variables → Actions**:

| Secret | Value |
| --- | --- |
| `FRONTEND_SSH_HOST` | `91.200.84.187` or the frontend DNS name |
| `FRONTEND_SSH_KNOWN_HOSTS` | pinned ED25519 known-hosts line for the frontend host |
| `FRONTEND_SSH_PRIVATE_KEY` | dedicated private deploy key; optional when `PROD_SSH_PRIVATE_KEY` is authorized on both hosts |
| `FRONTEND_SSH_USER` | optional, defaults to `root` |
| `FRONTEND_SSH_PORT` | optional, defaults to `22` |
| `FRONTEND_PROJECT_PATH` | optional, defaults to `/opt/banano-kling-src` |
| `FRONTEND_DOMAIN` | optional, defaults to `cdn.chillcreative.ru` |

The frontend host key must be stored separately from the backend host key because
the servers are different.

## One-time server key setup

Run on the frontend server as the deployment account:

```bash
install -d -m 0700 ~/.ssh
ssh-keygen -t ed25519 \
  -f ~/.ssh/github-actions-neuromix-frontend \
  -N '' \
  -C 'github-actions-neuromix-frontend'

PUB="$(cat ~/.ssh/github-actions-neuromix-frontend.pub)"
grep -Fq "$PUB" ~/.ssh/authorized_keys 2>/dev/null || \
  printf 'no-agent-forwarding,no-port-forwarding,no-X11-forwarding,no-pty %s\n' \
  "$PUB" >> ~/.ssh/authorized_keys
chmod 0600 ~/.ssh/authorized_keys
```

Save the complete output below as `FRONTEND_SSH_PRIVATE_KEY`, then delete the
private copy from the server:

```bash
cat ~/.ssh/github-actions-neuromix-frontend
shred -u ~/.ssh/github-actions-neuromix-frontend 2>/dev/null || \
  rm -f ~/.ssh/github-actions-neuromix-frontend
```

Create `FRONTEND_SSH_KNOWN_HOSTS` on the frontend server:

```bash
HOST='91.200.84.187'
printf '%s %s\n' "$HOST" "$(cat /etc/ssh/ssh_host_ed25519_key.pub)"
```

Do not send the private key through chat.

## Required frontend host state

Before activation, the host must already contain:

- repository checkout at `/opt/banano-kling-src`;
- profile `/etc/banano-miniapp/profiles/cdn.chillcreative.ru.env`;
- Node/npm and Nginx prerequisites handled by the existing installer;
- a clean Git working tree.

## Manual production run

After secrets are configured, use:

`Actions → Deploy — NEUROMIX frontend → Run workflow`

or push a frontend change to `tanyapi`.
