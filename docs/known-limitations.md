# Known limitations and deferred hardening

This file records known gaps that must not be silently described as completed production behavior.

## 1. `FOXGEN_S3_CREATE_BUCKET` is declared but inactive

Status: **reserved setting; current application storage does not consume it**.

Tracked by issue **#57**.

`Settings` declares:

```text
FOXGEN_S3_CREATE_BUCKET=false
```

but current `S3MediaStorage` has no create-bucket option and expects the configured bucket to already exist. Setting this variable to `true` therefore does not provision an external S3 bucket.

Repository Compose MinIO bootstrap creates the bundled private bucket and enforces the temporary `inputs/` lifecycle rule through `minio-init`. For an external S3-compatible deployment, provision the private bucket separately and configure an equivalent temporary-input lifecycle policy.

The eventual #57 fix should either wire controlled application bootstrap semantics with tests or remove/deprecate the unused setting. Normal request-time media upload should not opportunistically create production buckets.

## Documentation rule

When a limitation is resolved:

1. merge executable code and tests first;
2. remove/update the limitation in the same PR;
3. update `api-reference.md`, `admin-capability-matrix.md`, `telegram-flows.md`, `configuration.md` or `input-media-lifecycle.md` as applicable;
4. update env examples and production preflight/runbook if operational setup changes.
