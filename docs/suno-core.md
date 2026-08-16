# Suno V5 production core

FoxGen's first production Suno slice implements text-to-song generation through KIE's dedicated Suno API family while reusing FoxGen's existing paid generation, media archive and delivery lifecycle.

This slice is tracked by #109 and is intentionally smaller than the full Suno suite in #15.

## Provider boundary

Suno is not submitted through KIE Market `/api/v1/jobs/createTask`. The reviewed core adapter uses:

```text
POST /api/v1/generate
GET  /api/v1/generate/record-info?taskId=<id>
```

`ModelSpec.api_family="suno"` selects `SunoClient`; Market models continue using the existing Market client contract. Worker code routes by the reviewed model specification rather than guessing from model names.

The core slice is polling-driven. The dedicated Suno callback contract is deferred to a separate #15 slice.

## Model contract

FoxGen slug:

```text
suno-v5
```

Provider model:

```text
V5
```

Media kind is `audio`; capability is `music_generation`.

### Simple mode

```json
{
  "custom_mode": false,
  "instrumental": false,
  "prompt": "Warm indie pop song about a late-night train"
}
```

Rules:

- prompt required;
- prompt <= 500 characters;
- custom-only style/title/weights are rejected.

### Custom vocal mode

```json
{
  "custom_mode": true,
  "instrumental": false,
  "prompt": "[Verse]\nCity lights and empty roads",
  "style": "indie pop, warm female vocal",
  "title": "Last Train",
  "negative_tags": "metal",
  "vocal_gender": "f",
  "style_weight": 0.8,
  "weirdness_constraint": 0.25,
  "audio_weight": 0.7
}
```

Custom V5 limits:

- prompt <= 5000;
- style required, <= 1000;
- title required, <= 80;
- custom vocal prompt required;
- advanced numeric weights are bounded to 0..1.

### Custom instrumental mode

Custom instrumental requires style + title but does not require lyrics prompt.

All validation happens before paid admission and provider side effects.

## Lifecycle routing

```text
Happy Fox / Telegram
  -> shared SubmissionService
  -> atomic price + wallet reservation
  -> generation.submit outbox
  -> GenerationWorker selects api_family=suno
  -> SunoClient POST /api/v1/generate
  -> submitted / processing
  -> SunoClient GET record-info
  -> result_ready
  -> generation.archive
  -> generation.deliver
  -> succeeded
```

Known intermediate Suno states such as `PENDING`, `TEXT_SUCCESS` and `FIRST_SUCCESS` normalize to FoxGen `processing`. Reviewed terminal Suno failures normalize to the normal failed/refund path.

No Suno-specific wallet or billing subsystem exists.

## Multi-track result normalization

Suno can return multiple tracks. FoxGen does not collapse them to one result.

The adapter normalizes provider output to:

```json
{
  "audioUrls": [
    "https://.../track-a.mp3",
    "https://.../track-b.mp3"
  ],
  "tracks": [
    {"id": "track-a", "title": "Track A"},
    {"id": "track-b", "title": "Track B"}
  ],
  "task_type": "generate"
}
```

Only canonical `audioUrl` values are placed in `audioUrls`. `streamAudioUrl` and `imageUrl` are removed from track metadata before generic media extraction so the archive pipeline does not accidentally store artwork or stream endpoints as generation results.

Every canonical audio result gets its own `media_assets` row, private stored object and delivery URL.

## Telegram UX

Main menu `Создать музыку (песню)` uses a dedicated Redis FSM:

```text
simple/custom
  -> vocal/instrumental
  -> required prompt/style/title fields
  -> live price + balance
  -> shared paid submit
```

Simple mode is intentionally short. Custom instrumental skips lyrics input. Existing pre-release `planned:music` callbacks forward into the current flow after deployment.

`/menu`, back, cancel, invalid input, stale callback and stable idempotency behavior are defined in `fsm_contract.py`.

## Happy Fox UX

The Music launcher is active and opens a visible `Музыка / Suno V5` product card.

The studio continues to use backend JSON Schema. `suno-parity.js` only:

- localizes field names;
- shows/hides mode-relevant fields;
- keeps simple mode compact;
- hides lyrics prompt for custom instrumental;
- disables launch when no active price is published.

The browser has no KIE secret and no direct `/api/v1/generate` request.

## Pricing

No Suno price is hardcoded or created by migration. Production launch is fail-closed until an administrator publishes an active `model_prices` row for `suno-v5`.

## Required E2E

The release-gate E2E keeps only external networks fake. It uses real FoxGen HTTP/auth, PostgreSQL financial state, outbox/lifecycle repositories and media pipeline:

```text
Happy Fox JWT
  -> validate Suno V5
  -> paid /v1/miniapp/tasks
  -> reserve 55 CREDIT from 200
  -> routed Suno submit
  -> TEXT_SUCCESS -> processing
  -> SUCCESS with two MP3 URLs
  -> archive both MP3s
  -> deliver both URLs
  -> generation SUCCEEDED
  -> wallet 145 available / 0 reserved
  -> reservation CAPTURED
  -> immutable CREDIT + RESERVE + CAPTURE ledger
```

A Suno core change is not release-ready if unit tests pass but real PostgreSQL integration, all E2E, readiness or production container/Trivy gates fail.

## Deferred #15 scope

Not implemented by this core slice:

- extend and upload-extend;
- cover/upload-cover;
- add vocals / add instrumental / replace section;
- lyrics-only;
- WAV helpers;
- stems/vocal separation;
- MIDI;
- mashup/persona/music video/Suno voice;
- dedicated Suno callback ingestion.
