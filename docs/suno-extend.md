# Suno V5 Extend

FoxGen supports owner-bound continuation of durable Suno V5 results through KIE's Suno Extend API. This slice deliberately does not accept arbitrary provider `audioId` values from the public UI.

## User flow

Telegram:

```text
Создать музыку
  -> Новый трек | Продолжить свой трек
  -> owner Suno source picker
  -> inherit | custom
  -> (custom) prompt -> style -> title -> continueAt
  -> active price + balance confirmation
  -> owner-verified paid submission
```

Happy Fox loads `/mini-app/suno-extend.js`. The Music section adds `Продолжить свой трек`, fetches only the authenticated user's stored Suno tracks and uses short-lived private preview URLs. The browser never receives a KIE key or calls `/api/v1/generate/extend` directly.

## Owner APIs

Trusted Telegram transport:

```text
GET  /v1/user-portal/music/suno/sources
POST /v1/user-portal/music/suno/extend
```

Happy Fox:

```text
GET  /v1/miniapp/music/suno/sources
POST /v1/miniapp/music/suno/extend
```

Extend POST requires `Idempotency-Key` and contains:

```json
{
  "source_generation_id": "<owner generation UUID>",
  "audio_id": "<track id returned by owner source list>",
  "default_param_flag": false
}
```

For custom V5 extension, `default_param_flag=true` additionally requires non-empty `prompt`, `style`, `title` and positive `continue_at`. The application rejects a known `continue_at` that is at or after the source duration.

## Trust boundary

`SunoExtendService` resolves `(user_id, source_generation_id, audio_id)` from durable FoxGen state before shared paid admission. A source is eligible only when:

- the generation belongs to the authenticated user;
- generation status is `succeeded`;
- source model is `suno-v5` or `suno-v5-extend`;
- the requested track ID exists in durable `result_payload.tracks`;
- its canonical audio URL has a `STORED` `media_assets` row.

The provider request never contains `source_generation_id`; that UUID is FoxGen audit/ownership metadata only.

## Database guard

Alembic revision `20260816_0016` installs `foxgen_validate_suno_extend_source()` and trigger `trg_generations_suno_extend_source` on `generations`.

For `model_slug='suno-v5-extend'`, the trigger requires an owner-matching, succeeded Suno source generation and matching `audio_id`. This is a second line of defense below HTTP/service code: direct generic task admission with a foreign/fabricated source rolls back the whole transaction before a generation/reservation/ledger/outbox can commit.

Do not remove this trigger unless an equivalent durable ownership constraint replaces it.

## Billing

`suno-v5-extend` has its own normal FoxGen model price. No price is embedded in code or migration.

The user flow is fail-closed when the active price is missing or balance is insufficient. After source verification, Extend uses the same `SubmissionService` and reservation lifecycle as other paid generation products:

```text
available CREDIT -> reserved -> captured
```

Provider-side failures follow the existing generation release/refund rules. There is no separate Suno wallet.

## Provider routing

Registry metadata selects `api_family=suno_extend`. The routed KIE client submits to the reviewed Suno Extend endpoint and normalizes polling through the existing lifecycle. Multi-track success produces canonical audio URLs only; each resulting MP3 is archived independently and delivered through the common media pipeline.

## Required regression tests

The release gate must include:

- strict contract/provider payload tests, including absence of `source_generation_id` in KIE body;
- owner service tests for foreign source and invalid `continue_at`;
- Telegram music hub/source picker/inherited/custom/fail-closed price tests;
- Happy Fox static contract proving `suno-extend.js` is loaded and does not call KIE directly;
- Alembic upgrade/schema/downgrade/re-upgrade including the owner trigger;
- real PostgreSQL generic-submit bypass test proving a forged source has no financial/outbox effect;
- cross-layer E2E: create durable Suno source -> archive two tracks -> owner list -> foreign denial -> owner custom Extend -> provider Extend -> archive/deliver two extended tracks -> `SUCCEEDED` with both reservations captured;
- production image/Compose and Trivy gates.

## Rollback

Do not run application code that exposes `suno-v5-extend` against a schema downgraded below `20260816_0016`. A rollback that removes the trigger must also remove/disable Extend admission first. Existing generation, ledger, reservation and media history should be retained.
