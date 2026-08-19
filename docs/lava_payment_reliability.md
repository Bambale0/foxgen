# Lava payment reliability

This change keeps both Lava identifiers and makes webhook delivery retry-safe.

## Identifier model

- `contractId` is the identifier delivered by `payment.success` / `payment.failed` webhooks.
- `invoiceId` is the identifier used with `GET /api/v2/invoices/{id}`.
- `transactions.payment_id` remains backward compatible with existing rows.
- `lava_payment_bindings` stores the durable `contractId -> invoiceId` mapping.

The invoice creation wrapper persists the mapping before the payment link is shown. Existing rows are backfilled from `GET /api/v2/invoices` when needed.

## Webhook behavior

- Unknown route probes return `200` and are ignored.
- Invalid JSON returns `400`.
- A configured webhook secret is verified using either `X-Api-Key` or HTTP Basic authentication.
- Without configured credentials, only Lava's documented source IP is accepted and the event is always verified against the invoice API.
- `payment.success` is completed only after the invoice API reports a successful status.
- Temporary `in_progress`, lookup failures, and database failures return `503`, allowing Lava to retry delivery.
- Amount and currency must match the local transaction.
- Raw headers, Basic credentials, request bodies, and buyer email are not logged.

## Environment variables

Preferred API-key webhook authentication:

```env
LAVA_WEBHOOK_SECRET=<the X-Api-Key configured in Lava>
```

HTTP Basic authentication can use either:

```env
LAVA_WEBHOOK_BASIC_USERNAME=<rotated username>
LAVA_WEBHOOK_BASIC_PASSWORD=<rotated password>
```

or:

```env
LAVA_WEBHOOK_BASIC_CREDENTIALS=<rotated username:password>
```

`LAVA_WEBHOOK_SECRET` also accepts the full Basic `username:password` value for backward compatibility.

The allowed source IP fallback defaults to Lava's documented sender address and can be overridden:

```env
LAVA_WEBHOOK_ALLOWED_IPS=158.160.60.174
```

## Reconciliation

The periodic reconciliation loop no longer marks stale pending rows as failed before checking Lava. It now:

1. resolves `contractId` to `invoiceId`;
2. checks the invoice status;
3. atomically completes successful transactions;
4. marks a transaction failed only when Lava reports a final failed status;
5. records lookup failures as errors instead of silently counting them as pending.

## Deployment safety

Rotate previously exposed Basic credentials before enabling credential verification. Deploy the code, restart the Telegram service, then run the existing Lava success audit over the period that may contain missed payments. Atomic payment completion prevents duplicate crediting when a webhook is resent.
