# Reference memory

FoxGen reference memory is a durable, user-owned library of image inputs that can be reused from compatible Telegram generation screens.

## User contract

From an image-reference screen or compatible video-media screen, the user can open `📚 Память реф` and:

- view one private image preview at a time;
- navigate through the saved library;
- select or unselect multiple images;
- see the selected count against the current model/scenario capacity;
- upload a new image directly into durable memory;
- explicitly save image inputs that are already present in the current temporary draft;
- delete a saved image;
- apply the selection back to the active image/video generation draft.

For first/last-frame video, selection order is significant and becomes frame order. Temporary draft inputs remain first, followed by saved references in the order selected.

## Ownership and persistence

Durable metadata lives in PostgreSQL table `reference_assets`. Every row belongs to exactly one Telegram user through `user_id`.

Durable bytes live in the configured private S3-compatible bucket under:

```text
references/<telegram-user-id>/<reference-uuid>.<extension>
```

The `references/` prefix is intentionally outside the short-retention `inputs/` lifecycle. A saved reference survives Redis FSM expiry, `/menu`, bot/API/worker restarts and application deployments until the owner deletes it.

Temporary Telegram inputs are never silently promoted. Saving is always an explicit user action.

## Status lifecycle

```text
uploading -> active -> delete_pending -> deleted
     |                         |
     +-------> failed          +-- reference.delete outbox -> worker -> S3 delete
```

The save path reserves PostgreSQL quota before copying bytes. S3 storage must succeed before the row becomes `active`. If storage fails, the row becomes `failed` and the partially written object is deleted best-effort.

Deletion is transactional on the metadata side: an active row becomes `delete_pending` and a deduplicated `reference.delete` outbox event is committed in the same transaction. The worker deletes the S3 object and then marks the row `deleted`. Reclaimed deletion events are idempotent.

## Quotas and de-duplication

Quotas are configured globally and enforced per owner:

- `FOXGEN_REFERENCE_MEMORY_MAX_ITEMS` — default 50 images;
- `FOXGEN_REFERENCE_MEMORY_MAX_TOTAL_BYTES` — default 500 MiB.

The repository locks the owner `users` row while reserving a new asset, so concurrent saves cannot race past the quota. Both `uploading` and `active` rows consume quota during reservation.

Within one owner's active memory, saving identical image bytes is de-duplicated by SHA-256. The existing active asset is returned and the bytes are not copied again.

## Preview and provider access

The bucket is private. FoxGen never exposes permanent object URLs or storage credentials.

`GET /v1/reference-memory` returns fresh, short-lived signed preview URLs. Telegram uses those URLs to render the private preview card.

At final generation admission, reference UUIDs stored in Redis are resolved again through the authenticated internal API. The API re-checks that every requested asset is still `active` and belongs to the same Telegram user, then returns fresh short-lived signed URLs. Provider payloads therefore never trust a stale URL captured when the library was opened.

The signing TTL is configured with `FOXGEN_REFERENCE_MEMORY_PRESIGNED_URL_TTL_SECONDS`.

## Telegram draft representation

Temporary and durable inputs use distinct locators:

```json
{"kind": "image", "storage_key": "inputs/42/temporary.png"}
{"kind": "image", "reference_id": "7a39..."}
```

Redis contains only ephemeral selection/browser state and reference IDs. It does not own the durable library.

`/start` and `/menu` remove only temporary input objects known to the current draft. Saved reference assets are not deleted when a generation flow is cancelled or reset.

## Model compatibility

The current model/scenario capability remains authoritative:

- image models use `max_references`;
- first-frame video accepts one image total;
- first+last-frame video accepts two ordered images total;
- multimodal video combines the global reference total with the model's image-reference limit;
- text-only video does not expose reference memory.

The browser limits selection before applying it. Final draft validation and provider contract validation still run afterwards, so the memory feature cannot bypass model-specific constraints.

## Internal API

All endpoints require the trusted internal bearer credential plus `X-FoxGen-User-Id`:

```text
GET    /v1/reference-memory?offset=0&limit=20
POST   /v1/reference-memory
POST   /v1/reference-memory/resolve
DELETE /v1/reference-memory/{reference_id}
```

`POST /v1/reference-memory` accepts only a current private `inputs/` storage key. The API reads the shared private input volume, validates the asset as an image, enforces quota and copies it into durable private S3 storage.

`POST /resolve` is the final owner/active-state gate used before generation submission.

## Operations

Useful incident checks:

1. confirm the database row status before touching S3 manually;
2. `uploading` rows should normally be short-lived; repeated occurrences indicate save/storage failure before exception recovery;
3. `delete_pending` plus retrying `reference.delete` outbox events indicates S3 deletion failure;
4. never apply the `inputs/` lifecycle rule to `references/`;
5. never publish the S3 bucket to make previews work — fix signing/network access instead;
6. a deleted/deactivated reference selected in an old Redis draft must fail closed at final `/resolve`.

## Related documentation

- `telegram-flows.md` — generation screen navigation and FSM behavior;
- `input-media-lifecycle.md` — temporary input ownership and cleanup;
- `database-schema.md` — durable tables;
- `configuration.md` — environment settings;
- `api-reference.md` — internal endpoints;
- `architecture.md` — trust and storage boundaries.
