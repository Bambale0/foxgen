# MinIO input lifecycle runbook

## Purpose

FoxGen stores temporary Telegram references under `inputs/`. The application image runs `scripts/configure_minio_input_lifecycle.py` through the `minio-init` Compose service before API, worker and bot startup.

The managed rule must:

- use ID `foxgen-expire-telegram-inputs`;
- filter only the `inputs/` prefix;
- expire completed input objects after `FOXGEN_INPUT_RETENTION_DAYS`;
- abort incomplete multipart uploads after `FOXGEN_INPUT_MULTIPART_ABORT_DAYS`;
- preserve every lifecycle rule not owned by FoxGen.

## Normal deployment

```bash
docker compose --env-file .env -f docker-compose.prod.yml run --rm minio-init
docker compose --env-file .env -f docker-compose.prod.yml up -d api worker bot
```

A normal production deployment already performs the initializer before application startup through Compose dependencies.

## Verification

```bash
docker compose --env-file .env -f docker-compose.prod.yml logs minio-init
docker compose --env-file .env -f docker-compose.prod.yml ps
```

Expected initializer output includes the bucket, `inputs/` prefix, retention days and multipart-abort days. API, worker and bot must not start when `minio-init` exits unsuccessfully.

## Failure recovery

1. Confirm MinIO is running and reachable from the backend network.
2. Confirm access key, secret key, bucket and region values in the server-side `.env`.
3. Run `minio-init` manually and inspect the exact S3 error.
4. Do not bypass the dependency gate by starting application services with `--no-deps`.
5. Do not broaden the rule to the whole bucket or to `generations/`.

Re-running the initializer is safe and idempotent. It replaces only the FoxGen-managed rule and preserves unrelated rules.

## Rollback

Reverting application code does not remove the already configured lifecycle rule. Keep it in place unless temporary input storage is moved elsewhere. Removing the rule without an equivalent cleanup mechanism allows abandoned private objects to accumulate indefinitely.
