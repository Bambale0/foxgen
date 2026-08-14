# Reference memory test matrix

| Area | Required coverage |
|---|---|
| Save | image-only validation, persistent prefix, duplicate checksum, storage failure cleanup |
| Quota | item limit, byte limit, concurrent owner serialization |
| List | owner scope, active-only, pagination, usage totals |
| Resolve | owner scope, active-only, order preservation, stale/deleted fail closed |
| Delete | active -> delete_pending, deduplicated outbox, idempotent worker S3 removal |
| Telegram | preview, navigation, multi-select, add, save current, delete confirm, back/apply |
| Models | image max refs, first frame, first+last order, multimodal image and total limits |
| Security | internal bearer + user header, no permanent URLs, no public bucket |
| Migration | upgrade, downgrade, re-upgrade, schema smoke |
