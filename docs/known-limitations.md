# Known limitations and deferred hardening

This file records known gaps that must not be silently described as completed production behavior.

## Current status

### Payments, promos and bonuses beyond current Telegram Stars scope

FoxGen supports user-facing digital-credit top-up inside Telegram through Telegram Stars (`XTR`): Happy Fox can request an owner-scoped package/invoice, Telegram checkout is pre-validated against the durable local order, and `successful_payment` settles into the immutable `CREDIT` ledger exactly once.

Privileged native Stars refunds are implemented through the operator control plane. Refund execution first holds the original CREDIT locally, then a dedicated durable worker calls Telegram. Ambiguous provider outcomes converge to `refund_unknown`; CREDIT remains held until an administrator resolves the attempt with evidence. A `not_refunded` resolution restores the hold exactly once through a compensating immutable ledger entry.

Explicit promo-code bonuses are implemented: admins define server-side reward/usage limits, Happy Fox users can redeem a code through the Telegram-JWT owner boundary, and one `(promo_code, user_id)` transaction atomically updates the wallet, immutable ledger, redemption audit row and usage counter.

Stars packages may publish an explicit non-negative purchase bonus (`bonus_units` or `bonus_credits`). Base CREDIT, bonus CREDIT and the XTR price are snapshotted into the durable payment order before invoice creation. Settlement, generic payment reprocess and native Stars refund operate on the full base+bonus CREDIT grant.

The current production slice deliberately does **not** claim every possible commercial payment/bonus policy:

- external web checkout/acquiring providers are not implemented;
- dynamic, segmented or rule-driven bonus campaigns are not implemented; purchase bonus is supported only when the published Stars package explicitly contains the bonus amount;
- the current Stars refund policy requires the user to still have the full originally credited amount available; FoxGen does not create debt or partially reclaim credits already spent;
- refund ambiguity resolution is evidence-based/manual after bounded retries; FoxGen does not guess an external financial outcome.

Do not bypass Stars/promo services by mutating wallet rows from the browser/bot or direct SQL.

### Voice/TTS

ElevenLabs Turbo 2.5 TTS is an executable production product in Telegram and Happy Fox. It uses the shared paid admission, immutable ledger, generation lifecycle, audio archive and Telegram delivery pipeline. No commercial price is hardcoded: launch remains fail-closed until an active model price is published.

The current TTS slice does **not** claim voice cloning, speech-to-speech, dialogue synthesis or audio cleanup. Those remain separate EPIC #5 slices.

### Suno/music

Suno V5 core text-to-song, owner-bound V5 Extend, owner-bound V5 Upload & Cover and owner-bound V5 Upload & Extend are executable product slices. Core generation supports simple/custom and vocal/instrumental modes. Extend lets a user choose only their own `SUCCEEDED` + STORED Suno result, then either inherit source parameters or submit a custom V5 continuation. Upload products accept only FoxGen-owned private audio; the public client never supplies a trusted KIE `uploadUrl`.

All four products use dedicated KIE Suno API-family routing and the shared paid reservation/capture, immutable ledger, multi-track archive and Telegram delivery lifecycle. No commercial price is hardcoded; each model slug remains fail-closed until an active price is published.

Extend deliberately adds stronger source ownership than ordinary text generation:

- user surfaces list only owner-scoped durable Suno source tracks;
- previews use short-lived stored-media URLs rather than provider URLs;
- the application re-verifies `(user_id, source_generation_id, audio_id)` before paid submission;
- PostgreSQL revision `20260816_0016` rejects forged `suno-v5-extend` generation rows even if a future caller tries to bypass the owner service through generic task admission.

Upload & Cover and Upload & Extend add a corresponding private-input boundary:

- Telegram/Happy Fox upload audio into owner-scoped FoxGen input storage;
- durable generation input contains only `input_storage_key`, never a provider URL;
- the application checks owner prefix, existence, size and `audio/*` before paid admission;
- PostgreSQL revisions `20260817_0017` and `20260817_0018` reject forged/foreign input keys for Cover and Upload & Extend respectively;
- the worker resolves a fresh short-lived FoxGen URL immediately before the KIE POST;
- default/simple modes expose only reviewed minimal fields; custom-only controls are not sent in default mode;
- provider helper/source/stream/artwork URLs are not archived as generated assets.

KIE documents an 8-minute maximum uploaded-audio duration for the Upload & Extend request contract and requires custom `continueAt` to be greater than zero and lower than source duration. FoxGen currently has reliable owner/content-type/byte-size metadata but does not derive trustworthy audio duration for private uploads. FoxGen therefore validates positive `continue_at` locally while KIE remains authoritative for the upper source-duration bound. Do not claim local duration/8-minute pre-validation until duration metadata/media probing is implemented.

The Suno implementation still does **not** claim the rest of issue #15:

- add vocals / add instrumental / replace section;
- lyrics-only workflows;
- WAV conversion/download helpers;
- vocal/instrument separation / stems;
- MIDI;
- mashup / music video / Suno voice features;
- dedicated Suno callback ingestion. Current generation/Extend/Cover/Upload-Extend flows remain polling-driven until that callback contract is reviewed separately.

### Remaining planned generation products

Motion Control/talking avatar, Prompt AI, conversational assistant and Gemini Omni remain intentionally disabled until their backend + lifecycle + bot + Mini App slices are implemented. A visible planned product is not production capability.

### Storage provisioning

Storage provisioning is explicit: application request/worker code never creates external S3 buckets, repository Compose provisions its bundled private MinIO bucket through `minio-init`, and external S3-compatible deployments must provision a private bucket before FoxGen startup.

## Documentation rule

When a new limitation is discovered:

1. create/identify the tracked issue;
2. document only executable current behavior and the exact gap;
3. do not describe prepared/unwired code as production-active.

When a limitation is resolved:

1. merge executable code and tests first;
2. remove/update the limitation in the same PR;
3. update the relevant API/configuration/runbook documentation;
4. update env examples and production preflight when operational setup changes.
