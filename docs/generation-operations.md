# Generation lifecycle operations

FoxGen exposes the durable generation stage without exposing provider payloads or storage URLs.

## User-scoped operations

Internal channel adapters authenticate with the internal bearer token and `X-FoxGen-User-Id`.

```text
GET  /v1/generations/{generation_id}
POST /v1/generations/{generation_id}/cancel
```

Cancellation is accepted only while the durable state is `draft` or `queued`. The transaction:

1. locks the owned generation;
2. moves it to `cancelled`;
3. releases the billing reservation exactly once;
4. completes any pending submission outbox event.

Once the state is `submitting`, cancellation is rejected because a billable provider request may already have started.

## Stuck-generation report

Billing administrator authentication is required.

```text
GET /v1/admin/generations/stuck?older_than_minutes=30&limit=100
```

The report includes only non-terminal recovery states:

- `submission_unknown`;
- `processing`;
- `result_ready`;
- `storing_media`;
- `delivery_pending`.

It is read-only. It never repeats provider submission and never automatically retries an ambiguous Telegram send.

## Resolving `submission_unknown`

```text
POST /v1/admin/generations/{generation_id}/resolve-unknown
```

Supported actions:

- `submitted` — provider dashboard confirms the task exists;
- `processing` — provider confirms the task exists and is running;
- `result_ready` — provider confirms success and a verified result payload is supplied;
- `failed` — provider confirms that no accepted task exists.

Accepted-task actions require `provider_task_id`. `result_ready` additionally requires a verified `result_payload`. The service first records `submitted`, which atomically captures the existing reservation, and only then advances to processing or result-ready. No new provider request is sent.

Example:

```json
{
  "action": "submitted",
  "provider_task_id": "provider-task-123",
  "reason": "provider dashboard verified"
}
```

## Safety rules

- Never resolve an unknown task from guesswork.
- Verify provider identity, model and user before supplying a result payload.
- Use `failed` only when the provider confirms no billable task was accepted.
- Do not replay `delivery_unknown`; inspect Telegram and resolve it through the delivery reconciliation controls introduced in the following epic.
