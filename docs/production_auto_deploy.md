# HappyFox production auto-deploy

HappyFox production deploy is driven by verified `main`, not by the historical `tanyapi` branch.

## Trigger contract

```text
PR -> main
  -> CI green on PR head
  -> merge
  -> CI green on main merge SHA
  -> Deploy HappyFox production
```

The deployment workflow must deploy the exact verified `main` SHA. A workflow run for an older SHA is not evidence that the newest code is live.

## Workflow

```text
.github/workflows/deploy-production.yml
```

The workflow verifies:

- deployment configuration;
- exact commit checkout;
- repository provenance;
- pinned SSH configuration;
- HappyFox public/Mini App domain resolution;
- isolated PostgreSQL/Redis/runtime preflight;
- exact backend/Mini App deployment;
- deployment summary/status publication.

CI also builds/verifies the production Docker image before deployment.

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
production deploy target == tested main SHA
runtime/static revision == deploy target SHA
```

If any equality is unknown, treat deployment status as unverified.

## Instagram

Instagram does not require a separate deploy pipeline. Its code ships in the same HappyFox artifact.

Activation is controlled by runtime config:

```dotenv
INSTAGRAM_ENABLED=0|1
```

This allows safe dark deployment of Instagram changes. `0` means code is present but routes/worker are not registered.

When switching to `1`, the deployment should still follow exact-SHA rules and the live smoke in `instagram-channel.md`/`production-deployment.md`.

## Rollback

General rollback = redeploy a previously green `foxgen/main` SHA.

For an Instagram-only incident, first containment can be configuration rollback to:

```dotenv
INSTAGRAM_ENABLED=0
```

followed by redeploy/restart, avoiding rollback of unrelated Telegram fixes.

## Status

Successful deployment should publish the repository deployment status context used by HappyFox operations and include the deployed SHA in the workflow summary.
