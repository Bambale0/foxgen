# Reference memory storage layout

The configured private S3-compatible bucket has three ownership classes relevant to generation:

```text
inputs/       temporary Telegram ingress, short retention lifecycle
references/   durable user-owned reusable source images, no short retention
 generations/ durable generated result archive, no short retention
```

Reference objects use `references/<telegram-user-id>/<uuid>.<ext>`. The key is generated server-side and is not accepted from the Telegram user. PostgreSQL stores the canonical key and ownership metadata.

Do not attach the `inputs/` lifecycle rule to `references/` or `generations/`.
