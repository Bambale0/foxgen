# Telegram input media lifecycle

Telegram references are stored under the private object prefix `inputs/` and are never exposed through a public bucket URL.

## Product rules

- one Telegram message equals one upload operation;
- Telegram albums (`media_group_id`) are rejected before download and must be resent as individual files;
- updates for one FSM key are serialized by Redis event isolation;
- explicit `/menu`, cancel, replacement of a Quick Start reference and incompatible old-state recovery delete known `inputs/` objects;
- provider-readable presigned URLs are created only at final confirmation;
- input objects are not deleted immediately after queue admission because the provider may still need the presigned URL;
- failed cleanup is non-destructive and is emitted as `telegram_input_cleanup_failed` with a low-cardinality failed count.

## Required bucket lifecycle rule

Redis TTL expiry removes conversation state, so the application can no longer enumerate abandoned object keys after that point. The production bucket must therefore include a lifecycle rule for the `inputs/` prefix.

Recommended initial policy:

```text
prefix: inputs/
expire current objects after: 2 days
abort incomplete multipart uploads after: 1 day
```

The retention window must be longer than the maximum provider fetch delay and longer than `FOXGEN_TELEGRAM_FSM_TTL_SECONDS`. Generation results under `generations/` must not use this short retention rule.

## Failure classification

- `validation_error`: permanent user input error, including albums, unsupported type, empty file and size limit;
- `input_download_failed`: retryable Telegram transfer failure;
- `input_storage_failed`: retryable object-storage failure;
- cleanup failure: logged for operations, but the user action still completes because S3 lifecycle remains the final safety net.

## Verification checklist

1. Upload a single photo and confirm an `inputs/<user>/...` object appears.
2. Cancel and confirm the object is deleted.
3. Send an album and confirm no object is created.
4. Simulate a Telegram download failure and confirm the draft remains at the same input step.
5. Simulate an S3 write failure and confirm no FSM transition occurs.
6. Verify the bucket lifecycle rule applies only to `inputs/`.
