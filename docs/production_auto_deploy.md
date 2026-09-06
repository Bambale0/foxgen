# HappyFox production auto-deploy

HappyFox production deploy is driven by verified `main`, not by the historical `tanyapi` branch.

## Trigger contract

```text
PR -> main
  -> CI green on PR head
  -> merge
  -> CI green on main merge SHA
  -> Deploy HappyFox production
  -> pinned SSH to happyfox
  -> server-side gh verifies current main SHA
  -> exact checkout + backup + build + health gates
```

The deployment workflow must deploy the exact verified `main` SHA. A workflow run for an older SHA is not evidence that the newest code is live.

## Workflow

```text
.github/workflows/deploy-production.yml
```

GitHub Actions is deliberately a thin trigger. It does **not** copy the HappyFox runtime environment to production. The production host owns `.env`, `.env.happyfox.runtime` and `.env.happyfox.channels`; this prevents an old Actions secret from overwriting newer server configuration.

The workflow verifies:

- deployment configuration;
- pinned SSH configuration and dedicated HappyFox SSH host key;
- server-side GitHub CLI availability/authentication;
- `Bambale0/foxgen:main` through `gh api`;
- exact commit checkout after `gh auth setup-git`;
- isolated PostgreSQL/Redis/runtime preflight;
- exact backend + landing/Mini App static deployment;
- Telegram webhook/quick-command reconciliation and MAX subscription reconciliation;
- public health/static revision checks;
- deployment summary publication.

CI also builds/verifies the production Docker image before deployment.

## Production host GitHub CLI

Production source synchronization runs on `happyfox` through the GitHub CLI. Required checks:

```bash
gh --version
gh auth status -h github.com
gh api repos/Bambale0/foxgen/commits/main --jq .sha
```

The checkout lives at:

```text
/opt/happyfox/repo
```

The deploy workflow calls `gh auth setup-git` on the host before the exact `git fetch/reset`. This means Git authentication is derived from the host's authenticated `gh` session rather than from a repository credential copied by Actions.

The `gh` auth file and production runtime env files are secrets. Do not print their values into CI logs, shell history, docs, or support output.

## Server-authoritative runtime

Every deploy canonicalizes the public production topology and safety invariants on the host:

```text
landing:  https://happy-fox.online
Mini App: https://app.happy-fox.online/mini-app/
API:      https://api.happy-fox.online
DB:       happyfox_cutover
PERSIST_PROVIDER_RESULTS=1
```

Telegram's webhook remains `https://api.happy-fox.online/webhook`; its fixed relay IP is part of the current production network workaround. Channel credentials remain in the protected server overlay.

## Source-of-truth rule

Only `Bambale0/foxgen:main` may be used for HappyFox production release automation.

Never use:

```text
Bambale0/banano_kling:tanyapi
legacy/foxgen-pre-tanyapi-20260820
arbitrary feature branch
server working-tree edits
```

as the final production source.

## Exact SHA rule

Required evidence chain:

```text
PR head SHA == tested PR SHA
merge/main SHA == tested main SHA
server gh main SHA == deploy target SHA
production checkout == deploy target SHA
runtime/static revision == deploy target SHA
```

If any equality is unknown, treat deployment status as unverified.

## Rollback

A verified PostgreSQL backup is taken before a healthy backend is replaced and again after a successful release. General rollback is a redeploy of a previously green `foxgen/main` SHA; do not patch the running container manually.

For an Instagram-only incident, first containment can be configuration rollback to:

```dotenv
INSTAGRAM_ENABLED=0
```

followed by redeploy/restart, avoiding rollback of unrelated Telegram fixes.

## Instagram

Instagram does not require a separate deploy pipeline. Its code ships in the same HappyFox artifact.

Activation is controlled by runtime config:

```dotenv
INSTAGRAM_ENABLED=0|1
```

This allows safe dark deployment of Instagram changes. `0` means code is present but routes/worker are not registered.

When switching to `1`, the deployment should still follow exact-SHA rules and the live smoke in `instagram-channel.md`/`production-deployment.md`.

## Successful deployment evidence

A deployment is complete only after all of the following are true:

- main CI is green;
- deploy workflow is green;
- backend container is healthy;
- image/runtime/static revision equals the verified main SHA;
- API, Mini App and landing public smokes pass;
- Telegram/MAX reconciliation passes;
- post-deploy PG17 backup succeeds.
