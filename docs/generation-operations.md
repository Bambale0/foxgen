# Generation lifecycle operations

FoxGen exposes durable generation operations without requiring operators or clients to manipulate provider payloads or database state directly.

## Durable lifecycle

Current generation states:

```text
draft
queued
submitting
submitted
processing
submission_unknown
result_ready
storing_media
delivery_pending
succeeded
failed
cancelled
```

The normal success path is:

```text
queued -> submitting -> submitted -> processing
       -> result_ready -> storing_media -> delivery_pending -> succeeded
```

Provider success is not equal to product success. FoxGen reports `succeeded` only after durable media storage and confirmed Telegram delivery.

## Owner-scoped status

Trusted internal channel adapters use the ordinary internal bearer token plus `X-FoxGen-User-Id`.

```text
GET /v1/generations/{generation_id}
```

The operation returns only the generation owned by the authenticated user context and exposes lifecycle/error/timestamp information rather than raw storage credentials.

## User cancellation

```text
POST /v1/generations/{generation_id}/cancel
```

Cancellation is accepted only before a billable provider request may have started. The durable operation locks the owned generation and, when legal:

1. transitions it to `cancelled`;
2. releases the existing reservation exactly once;
3. suppresses pending submission work;
4. commits state/billing consistently.

Once the generation is `submitting` or beyond, user cancellation is rejected. FoxGen does not claim it can cancel work that may already have been accepted/charged by the provider.

## Stuck-generation reporting

Legacy billing-admin authentication protects:

```text
GET /v1/admin/generations/stuck?older_than_minutes=30&limit=100
```

The report focuses on non-terminal states that can need operations review, including ambiguity, long provider processing, storage and delivery stages. It is read-only and never triggers another provider submission.

The full admin control plane also provides broader generation and operation inspection:

```text
GET /internal/admin/generations
GET /internal/admin/operations
GET /internal/admin/operations/{operation_id}
GET /internal/admin/operations/{operation_id}/timeline
```

## `submission_unknown`

`submission_unknown` means local code cannot safely prove whether the provider accepted a billable create request. Automatic retry is forbidden.

Potential evidence sources:

- verified provider callback;
- read-only provider polling;
- provider dashboard/manual evidence;
- known provider task ID correlated to the local generation.

### Legacy evidence-based resolution

```text
POST /v1/admin/generations/{generation_id}/resolve-unknown
```

Supported actions include:

- `submitted` — provider confirms accepted task;
- `processing` — accepted and running;
- `result_ready` — verified success with result payload;
- `failed` — provider evidence confirms no accepted billable task exists.

Accepted-task actions require a verified `provider_task_id`. `result_ready` additionally requires a verified result payload. The service settles the existing reservation according to the normal lifecycle; it never creates another provider task.

Example:

```json
{
  "action": "submitted",
  "provider_task_id": "provider-task-123",
  "reason": "verified in provider dashboard"
}
```

## Admin operation replay

The full signed admin API exposes:

```text
POST /internal/admin/operations/{operation_id}/replay
```

Replay is not a generic "run the failed thing again" button. The admin worker allows only explicitly safe local non-billable operation classes such as archive/delivery orchestration. Provider submission (`generation.submit`) is intentionally excluded.

Replay:

- requires admin authorization;
- requires `Idempotency-Key`;
- requires explicit confirmation;
- creates an auditable child operation;
- is processed durably by the worker;
- does not create another provider charge.

## Admin refund

```text
POST /internal/admin/operations/{operation_id}/refund
```

Refund is an audited/idempotent administrative action with required confirmation and human-readable reason. It must converge with the immutable billing ledger rather than editing financial history.

## Provider polling

Polling is read-only and may use bounded retries. It is the fallback when callback delivery is delayed/missing and also helps resolve `submission_unknown` when a provider task identity is known.

Polling never authorizes a new createTask call.

## Result storage stages

A provider-complete task progresses through:

```text
result_ready -> storing_media -> delivery_pending
```

Storage is per-result asset. Multi-file results can partially archive and later retry only incomplete assets. Durable result URLs are never replaced by provider URLs in user-facing delivery.

See `postprocessing-reconciliation.md`.

## Delivery ambiguity

After Telegram send begins, a timeout may mean Telegram accepted the request but the response was lost. Such delivery becomes `delivery_unknown`.

Automatic resend is forbidden.

Legacy protected resolution route:

```text
POST /v1/admin/generations/{generation_id}/resolve-delivery
```

Operator actions:

- `mark_sent` with verified Telegram message IDs;
- `retry` only after confirming the original send did not happen and providing a fresh idempotency key;
- `failed` to terminate and settle/refund according to current policy.

## Reconciliation

Read-only report:

```text
GET /v1/admin/reconciliation
```

Safe local fixes:

```text
POST /v1/admin/reconciliation/run
```

Safe reconciliation can repair deterministic local inconsistencies such as reservation settlement or a generation whose delivery is already durably `sent`. It does not submit providers or resend ambiguous Telegram messages.

## Incident decision table

| Situation | Safe automatic action | Human/evidence required |
|---|---|---|
| API admission response lost, same idempotency key | replay local admission result | no |
| createTask response ambiguous | move/keep `submission_unknown` | yes for final resolution unless callback/poll proves it |
| provider status GET timeout | retry bounded read | no |
| archive download fails before durable storage | retry according to failure class | no for retryable error |
| Telegram fails before send starts | retry may be safe | no if boundary definitely not crossed |
| Telegram result ambiguous after send starts | none | yes |
| dead-lettered provider submission | do not resubmit | yes |
| captured generation terminally fails | deterministic refund policy | operator investigation if recurrent |

## Operator rules

- Never resolve provider ambiguity from guesswork.
- Never replay `generation.submit` through admin tools.
- Never retry `delivery_unknown` without confirming not sent.
- Never modify reservation/ledger rows directly for ordinary recovery.
- Preserve evidence in operation/admin audit reason fields.
- Investigate repeated `failure_class` clusters before increasing retry budgets.