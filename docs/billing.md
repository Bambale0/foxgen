# Billing and pricing

FoxGen uses integer internal balance units. Floating-point money is never stored or calculated. Every balance mutation is represented by an append-only ledger entry and a materialized wallet account balance.

## Fail-closed release gate

A generation can be admitted only when all of the following are true:

1. paid submission is explicitly enabled;
2. the trusted internal service is authenticated;
3. the selected model has a currently active versioned price;
4. the user has enough available units;
5. the generation, reservation, ledger entry and outbox event can be committed together.

If a price is missing, FoxGen returns `pricing_unavailable`. If funds are insufficient, it returns `insufficient_credits`. No provider request is created in either case.

## Account model

Each user has one wallet account:

- `available_units` — spendable balance;
- `reserved_units` — funds held for admitted generations;
- `currency` — currently `CREDIT`;
- `version` — incremented on each account mutation.

Database constraints prevent negative available or reserved balances.

## Price catalog

`model_prices` is versioned by `(model_slug, version)`. Publishing a new price disables the previous active version and keeps historical rows for audit. Prices have explicit activation windows and optional metadata.

No default commercial values are invented by migrations. Administrators must configure prices deliberately before enabling paid submission.

## Atomic reservation

Generation admission runs in one PostgreSQL transaction:

```text
insert generation(status=queued)
lock wallet account
select active model price
available_units -= price
reserved_units += price
insert balance_reservation(status=reserved)
insert immutable ledger entry(type=reserve)
insert outbox event(type=generation.submit)
commit
```

Any failure rolls back the entire operation. A user can never have a queued billable generation without a matching reservation.

## Settlement policy

### Provider accepted the task

When the worker transitions a generation to `submitted`, it captures the reservation in the same transaction:

```text
reserved_units -= price
reservation.status = captured
ledger += capture
```

### Ambiguous provider submission

`submission_unknown` keeps funds reserved. FoxGen neither captures nor releases the balance until callback, polling, operator reconciliation or an explicit policy resolves the ambiguity.

### Deterministic failure before capture

A reserved amount is released:

```text
available_units += price
reserved_units -= price
reservation.status = released
ledger += release
```

### Failure after capture

The current policy refunds the full captured amount:

```text
available_units += price
reservation.status = refunded
ledger += refund
```

The same settlement rules apply whether completion arrives through callback or polling. Ledger idempotency keys and reservation row locks make repeated transitions harmless.

## Immutable ledger

`ledger_entries` is append-only. A database trigger rejects updates and deletes. Each entry includes:

- user and optional generation/reservation IDs;
- entry type;
- available and reserved deltas;
- currency;
- unique idempotency key;
- actor and human-readable reason;
- metadata and timestamp.

The wallet account is a fast materialized balance. The ledger is the audit trail and reconciliation source.

## Administration API

Price and balance mutations use a separate, disabled-by-default administrator credential:

```env
FOXGEN_BILLING_ADMIN_API_ENABLED=true
FOXGEN_BILLING_ADMIN_API_TOKEN=<separate-long-random-secret>
```

Endpoints:

- `GET /v1/prices` — active price catalog;
- `GET /v1/users/{user_id}/balance` — trusted internal balance read;
- `GET /v1/users/{user_id}/ledger` — trusted internal ledger history;
- `POST /v1/admin/users/{user_id}/balance-adjustments` — idempotent manual credit/debit;
- `PUT /v1/admin/prices/{model_slug}` — publish a new price version.

The billing administrator token must be distinct from the ordinary internal service token and must never be exposed to Telegram clients, mini apps or browsers.

## Reconciliation

Production operations should periodically verify:

```text
account.available_units + account.reserved_units
= sum(ledger.available_delta + ledger.reserved_delta)
```

and ensure each active generation has exactly one reservation. Automated reconciliation and anomaly alerts are tracked under reliability and administration work.
