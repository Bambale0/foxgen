# Reference memory observability

Reference memory uses existing application/API/worker logging and the durable outbox. Operational dashboards should eventually surface at least:

- active reference count and bytes per user percentile;
- save failures by storage/database class;
- count and age of `uploading` rows;
- count and age of `delete_pending` rows;
- retry/dead-letter rate for `reference.delete` events;
- owner-scope resolve failures;
- quota rejection rate.

Until dedicated metrics are added, PostgreSQL row status plus outbox status are the durable incident source of truth.
