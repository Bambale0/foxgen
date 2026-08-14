# Known limitations and deferred hardening

This file records known gaps that must not be silently described as completed production behavior.

## 1. Admin extension transport wiring

Status: **service/extension modules exist, but selected extension routers are not registered by the current runtime entrypoints**.

Tracked by issue **#55**.

Files currently present include:

```text
src/foxgen/api/admin_extensions.py
src/foxgen/api/admin_web_extensions.py
src/foxgen/bot/admin_extras.py
```

Current FastAPI application registers:

```text
create_admin_router(...)
create_admin_web_router(...)
```

but not the two extension routers. Current Telegram dispatcher registers the main `admin_router` but not `admin_extras.router`.

Therefore the following prepared affordances must **not** be treated as active production transport endpoints until #55 is merged/tested:

- signed `/internal/admin/admins` list/update endpoints;
- signed `/internal/admin/analytics`;
- signed `/internal/admin/previews/generation`;
- signed XLS export endpoints `/exports/users.xls` and `/exports/finance.xls`;
- `/internal/admin/ui/api/analytics`;
- `/internal/admin/ui/api/preview-generation`;
- `/internal/admin/ui/api/admins` list/update;
- Telegram extra callbacks for analytics, XLS export and approved-withdrawal payment shortcut.

The underlying admin services/domain models remain present. Existing registered admin routes — users, finance, payments, tariffs, operations, support, CMS, notifications, partners, promos, prompts, runtime, moderation, audit, AI diagnostics and CSV exports — remain active according to the currently registered `create_admin_router`.

Do not work around this gap by duplicating service logic in new handlers. The correct fix is to register the existing extension routers before broad fallbacks, add route/FSM regression tests and then update this document/API reference.

## 2. `FOXGEN_S3_CREATE_BUCKET` is declared but inactive

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
