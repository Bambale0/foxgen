# MinIO input lifecycle runbook

## Purpose

FoxGen stores temporary Telegram references under `inputs/`. The application image runs `scripts/configure_minio_input_lifecycle.py` through the `minio-init` Compose service before API, worker and bot startup.

The managed rule must:

- use ID `foxgen-expire-telegram-inputs`;
- filter only the `inputs/` prefix;
- expire completed input objects after `FOXGEN_INPUT_RETENTION_DAYS`;
- abort incomplete multipart uploads after `FOXGEN_INPUT_MULTIPART_ABORT_DAYS`;
- preserve every lifecycle rule not owned by FoxGen.

`minio-init` also preserves the Compose responsibility of creating the bundled private MinIO bucket when it does not yet exist. Application API/bot/worker code has no bucket-creation switch and never provisions external S3 infrastructure.

## Normal deployment

A normal Compose startup gates API, worker and bot on successful lifecycle verification. To run the bootstrap explicitly:

```bash
docker compose --env-file .env -f docker-compose.prod.yml run --rm minio-init
```

Then start the application stack normally:

```bash
docker compose --env-file .env -f docker-compose.prod.yml up -d api worker bot
```

Defaults:

```env
FOXGEN_INPUT_RETENTION_DAYS=2
FOXGEN_INPUT_MULTIPART_ABORT_DAYS=1
FOXGEN_MINIO_INIT_ATTEMPTS=30
FOXGEN_MINIO_INIT_RETRY_SECONDS=2
```

The retention value must stay longer than the maximum provider fetch delay and the intended Telegram FSM interaction window.

## Verification

```bash
docker compose --env-file .env -f docker-compose.prod.yml logs minio-init
docker compose --env-file .env -f docker-compose.prod.yml ps
```

Expected initializer output includes the bucket, `inputs/` prefix, retention days and multipart-abort days. API, worker and bot must not start when `minio-init` exits unsuccessfully.

The initializer reads the bucket lifecycle back after writing it. Success means exactly one enabled rule with ID `foxgen-expire-telegram-inputs` matches the requested `inputs/` policy. Unrelated lifecycle rules must remain intact.

## Failure recovery

1. Confirm MinIO is running and reachable from the backend network.
2. Confirm access key, secret key, bucket and region values in the server-side `.env`.
3. Run `minio-init` manually and inspect the exact S3 error.
4. Check that the credentials can read and write bucket lifecycle configuration.
5. Do not bypass the dependency gate by starting application services with `--no-deps`.
6. Do not broaden the rule to the whole bucket or to `generations/`.

Re-running the initializer is safe and idempotent. It replaces only the FoxGen-managed rule and preserves unrelated rules.

## External S3-compatible storage

`docker-compose.prod.yml` manages the bundled MinIO service. If production deliberately replaces that topology with an external S3-compatible provider:

1. provision the private bucket explicitly before FoxGen startup;
2. give FoxGen only the object permissions required by normal media operations;
3. configure an equivalent private-bucket `inputs/` lifecycle rule through the provider's infrastructure mechanism;
4. verify bucket existence, privacy and lifecycle during deployment;
5. do not expect application request/worker execution to create the bucket.

Do not point public clients at storage credentials or make the bucket public as a workaround.

## Rollback

Reverting application code does not remove a lifecycle rule that was already installed. Keep the prefix-scoped rule in place unless temporary input storage is moved elsewhere. Removing it without an equivalent cleanup mechanism allows abandoned private objects to accumulate indefinitely.

If rollback returns to a revision whose Compose stack does not run `minio-init`, verify the rule externally before bringing API/worker/bot back online.
