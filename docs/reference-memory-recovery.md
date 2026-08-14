# Reference memory recovery

Reference memory has two recoverable non-terminal metadata states.

## `uploading`

Normal save flow changes this state to `active` only after the durable S3 write succeeds. Application-caught storage failures mark the row `failed` and delete any partial object best-effort.

If a process is terminated between quota reservation and recovery, an `uploading` row can remain. Such a row is not selectable and is counted in quota to fail safe. Operators should investigate the corresponding application/storage incident before changing it; do not blindly activate it without confirming the object checksum and ownership.

## `delete_pending`

The row is already hidden from list/resolve. A deduplicated `reference.delete` event in the shared durable outbox asks the worker to delete the private S3 object. The event can be reclaimed safely because S3 object deletion and the final `deleted` transition are idempotent.

If `delete_pending` persists, inspect the outbox failure class and S3 connectivity/permissions. Do not return the row to `active` merely to clear an operational alarm.
