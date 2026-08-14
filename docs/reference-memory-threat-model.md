# Reference memory security invariants

Reference memory is treated as private user content.

1. A Telegram user never supplies the durable `user_id` owner field; it comes from the authenticated internal service context.
2. A create request may reference only a validated `inputs/` key. Arbitrary filesystem/S3 keys are rejected.
3. A resolve/delete request scopes every database read by both `user_id` and reference UUID where applicable.
4. Library rows are usable by generation only in `active` state.
5. Permanent public URLs are forbidden. Preview and provider-read URLs are generated as expiring signatures from the private bucket.
6. Redis stores IDs and ephemeral browser state only. Durable ownership and deletion state remain PostgreSQL truth.
7. Temporary-flow cleanup never treats `references/` as disposable `inputs/` data.
8. S3 deletion is driven by an idempotent durable outbox event after the row leaves `active`, so a failed storage delete cannot make the reference selectable again.
9. Quota reservation locks the owner row and counts in-flight uploads, preventing concurrent quota bypass.
10. Provider admission re-resolves every durable reference immediately before task creation instead of trusting browser-time preview URLs.
