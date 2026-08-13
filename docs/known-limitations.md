# Known limitations and deferred hardening

This file records known gaps that must not be silently described as completed production behavior.

## 1. Automatic temporary-input lifecycle bootstrap

Status: **not active in current `main`**.

Application cleanup removes temporary `inputs/` objects while the draft still knows their keys, but Redis TTL/crash abandonment can orphan objects. Production storage therefore requires an externally configured lifecycle rule.

Recommended baseline:

```text
prefix: inputs/
expire current objects after: 2 days
abort incomplete multipart uploads after: 1 day
```

Tracked by issue **#50**. An implementation exists on an unmerged branch/PR but must be rebased/revalidated against current `main` before documentation can describe it as active.

## 2. Admin extension transport wiring

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

## Documentation rule

When either limitation is resolved:

1. merge executable code and tests first;
2. remove/update the limitation in the same PR;
3. update `api-reference.md`, `admin-capability-matrix.md`, `telegram-flows.md` or `input-media-lifecycle.md` as applicable;
4. update production preflight/runbook if operational setup changes.