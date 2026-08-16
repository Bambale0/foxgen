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

Suno V5 core text-to-song is an executable product slice after #109 lands. It supports simple and custom generation, vocal/instrumental modes, dedicated KIE Suno API-family routing, polling through Suno record-info, and preservation/archive/delivery of multiple canonical audio tracks through the shared paid lifecycle. No commercial price is hardcoded.

The Suno core slice deliberately does **not** claim the rest of issue #15:

- extend / upload-extend;
- upload cover / cover;
- add vocals / add instrumental / replace section;
- lyrics-only workflows;
- WAV conversion/download helpers;
- vocal/instrument separation / stems;
- MIDI;
- mashup / persona / music video / Suno voice features;
- dedicated Suno callback ingestion. Core generation is intentionally polling-driven until that callback contract is reviewed separately.

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
