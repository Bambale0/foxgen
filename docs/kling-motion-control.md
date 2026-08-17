# Kling 3.0 Motion Control

FoxGen exposes KIE Kling 3.0 Motion Control as a backend-first, owner-scoped product. The user provides one character image and one motion video; FoxGen validates both inputs before paid admission, persists only private storage keys, and resolves fresh provider URLs inside the worker immediately before KIE submission.

## Production model

- FoxGen slug: `kling-3-motion-control`
- KIE model: `kling-3.0/motion-control`
- API family: `kling_motion`
- capability: `motion_control`
- output: video
- reviewed: 2026-08-17

Current reviewed input subset:

| Field | FoxGen rule |
|---|---|
| `prompt` | required, 1..2500 characters |
| character image | JPEG/PNG, <=10 MB, both dimensions >340 px, ratio 2:5..5:2 |
| motion video | MP4/QuickTime, <=100 MB, both dimensions >340 px, ratio 2:5..5:2 |
| `mode` | `720p` or `1080p` |
| `character_orientation=image` | preserve image orientation; motion video 3..10 seconds |
| `character_orientation=video` | follow motion-video orientation; motion video 3..30 seconds |
| `background_source` | `input_video` only until another value is explicitly documented and contract-tested |

The public API never accepts trusted provider `input_urls` / `video_urls`. Durable generation input contains `image_storage_key` and `video_storage_key`; the worker turns those into short-lived signed URLs immediately before `POST /api/v1/jobs/createTask`.

## Admission and security boundary

1. Mini App authenticates through Telegram `initData` -> short-lived FoxGen JWT.
2. Image/video bytes upload into owner-scoped `inputs/miniapp/{user_id}/...` objects.
3. The Motion application service validates storage ownership, MIME type, size, dimensions, aspect ratio and video duration.
4. Generic submission admission independently rejects foreign or URL-shaped `*_storage_key` values before rate limiting, wallet reservation or outbox creation.
5. Normal price/balance/model-availability checks then reserve CREDIT transactionally.
6. Worker re-opens the private media, validates type/size again, resolves fresh signed URLs and sends only those URLs to KIE.
7. Existing callback/polling, archive, delivery, settlement, retry and reconciliation paths remain authoritative.

The browser never receives KIE/internal/admin/S3 credentials and does not choose a monetary price.

## Happy Fox UX

The generic schema row is deliberately hidden for this product because private storage keys are implementation details. Happy Fox instead presents:

1. character photo;
2. motion video;
3. prompt;
4. 720p/1080p quality;
5. image/video character-orientation mode;
6. server-derived price and current balance;
7. one explicit create action.

Browser validation gives immediate feedback, but backend validation is authoritative. If no active server price exists, submission remains disabled rather than guessing a price. On insufficient CREDIT the user is routed to the normal wallet/Telegram Stars flow.

## Operational checks

Before enabling/keeping the product available:

- `ModelRegistry().get("kling-3-motion-control").production_ready` is true;
- an active server-side price exists for the model;
- `/v1/miniapp/bootstrap` lists the model and price;
- image/video upload routes require a valid Mini App JWT;
- owner A cannot submit storage keys belonging to owner B;
- 11-second video fails with `character_orientation=image`;
- 30-second video succeeds validation with `character_orientation=video`;
- provider POST contains `input_urls` and `video_urls`, never FoxGen storage keys;
- production Mini App shell includes `motion-control.js` and the current cache-busting shell marker.

## Rollback

The feature has no database migration. To disable it without affecting other generation products:

1. disable/unpublish the model price and/or runtime model availability;
2. remove `kling-3-motion-control` from the submission allowlist if a code rollback is required;
3. remove the Motion Mini App module/import after backend submission is disabled;
4. redeploy an exact green `main` SHA.

Queued generations continue through the existing durable lifecycle; do not delete generation/outbox/reservation rows manually.
