# HappyFox production runbook

Production source: `Bambale0/foxgen:main`.

## Daily status

Prefer GitHub deployment evidence + public health over ad-hoc server edits.

Check:

```text
latest main SHA
main CI conclusion
latest Deploy HappyFox production conclusion/target SHA
public /health
Mini App revision/static availability
```

Runtime identity:

```text
Compose project: foxgen-happyfox
Container:       foxgen-happyfox-bot
Database:        happyfox
Redis prefix:    foxgen_happyfox
```

Host-specific SSH paths are environment/deploy configuration; do not copy old NEUROMIX service/path examples from historical docs.

## Release/restart rule

Normal changes go through:

```text
PR -> main -> CI -> merge -> main CI -> exact-SHA production deploy
```

Do not patch the production checkout as the lasting fix.

For an operational restart with no code change, preserve current verified SHA and environment. After restart, verify health and logs without printing secrets.

## Health

Public smoke:

```bash
curl -fsS https://alena.chillcreative.ru/health
```

If a protected/internal health route is used, follow deployment monitoring configuration rather than exposing secrets in shell history/screenshots.

Check PostgreSQL/Redis through existing diagnostic scripts/preflight where possible.

## Logs

Use container/system logs for the HappyFox runtime. Filter for the incident and redact tokens, headers, signed webhook bodies and payment secrets before sharing.

Useful search concepts:

```text
instagram
webhook
signature
idempotency
provider_task_id
payment
refund
health
postgres
redis
```

## Telegram incident triage

1. Confirm production deploy SHA.
2. Confirm Telegram webhook/runtime health.
3. Distinguish expected Mini App auth failure without valid `initData` from backend outage.
4. Check database/Redis connectivity.
5. Check provider/payment-specific logs.
6. Reproduce with a safe test user before changing production state.

## Instagram status

Instagram code may be deployed but inactive.

The first question is always runtime flag status:

```dotenv
INSTAGRAM_ENABLED=0|1
```

`0` means no Instagram routes/worker registration by design.

When enabled, verify:

- Meta GET verification route;
- signed POST handling;
- subscribed fields `messages,messaging_postbacks,comments`;
- access token/account ID;
- Redis idempotency;
- account-link/top-up path.

Never paste `INSTAGRAM_APP_SECRET`, verify token or access token into an issue/chat.

## Fast Instagram containment

If Instagram is causing an incident but Telegram/Mini App are healthy:

```dotenv
INSTAGRAM_ENABLED=0
```

Redeploy/restart the verified runtime, then confirm Telegram health. Preserve Instagram DB/job state for diagnosis instead of deleting it.

## Instagram creator smoke

Dark/unit smoke can run in tests without real Meta credentials.

Live smoke after approved activation:

```text
RU Direct -> Photo -> first free result
EN Direct -> Photo -> English copy
Video -> immediate top-up, no reference accepted yet
YooKassa/Lava Top -> shared balance
Continue/Продолжить -> reference requested when balance enough
comment -> private invite -> Direct chooser
```

## Payment operations

Shared HappyFox balance is the source of truth.

Channel presentation:

```text
Instagram top-up: YooKassa + Lava Top
Telegram: configured Telegram payment providers, CryptoBot included when enabled
```

If a user reports paid-but-no-balance:

1. identify provider transaction without exposing secrets;
2. check provider status/webhook receipt;
3. verify idempotent transaction row/status;
4. verify credit applied to correct HappyFox user;
5. do not manually credit twice without reconciling transaction state.

For generation refund complaints, trace generation job/task -> charge -> provider terminal state -> refund transaction/state.

## Instagram stuck job

Check persisted job fields conceptually:

```text
status
provider_task_id
result_url
delivered_at_epoch
attempt_count/retry/lease
billing_mode/cost
```

Interpretation:

- provider task ID exists: worker should resume same provider task;
- result URL exists: delivery can retry without regeneration;
- delivered checkpoint exists: local finalization can retry without intentional duplicate send;
- paid terminal failure: refund should occur once;
- free-photo terminal failure: promotion should be released.

Do not manually resubmit a provider task before checking whether a persisted provider task ID already exists.

## Language support

If an Instagram user receives the wrong language, ask them to send:

```text
English
```

or

```text
Русский
```

Then verify persisted channel language. Do not globally change product language because one identity has stale state.

## Backups and data changes

Before manual data repair:

- create/verify compatible HappyFox backup;
- identify exact user/channel/job IDs;
- prefer targeted, idempotent repair;
- record the reason and before/after state;
- never restore NEUROMIX/Tanya data into HappyFox.

## Rollback

General rollback:

```text
previously green foxgen/main SHA -> exact-SHA redeploy
```

Ensure schema compatibility before rollback.

Instagram-only rollback: disable the channel flag first when possible.

## Safe env inspection

Show only set/empty status, never values. Use the inventory snippet in `environment.md`.

## Escalation evidence

For a production incident capture:

```text
UTC/local incident time
main SHA
deploy run/target SHA
channel affected
request/event/job/transaction identifier (non-secret)
expected vs actual
sanitized log lines
reproduction result
rollback/containment performed
```
