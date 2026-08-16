# Happy Fox Telegram Mini App

`Happy Fox` is FoxGen's public Telegram Mini App. User-facing branding is **Happy Fox only**; internal package/database/service names remain `foxgen`.

The Mini App is served by FastAPI at `/mini-app/`; user-safe browser APIs are under `/v1/miniapp/*`. The browser never receives the internal API token, admin HMAC, KIE key, Telegram bot token, S3 credentials or any operator credential.

## Telegram entrypoints

When a public HTTPS URL is configured, Happy Fox is reachable through:

- the first `/start` / `/menu` inline WebApp button;
- Telegram's default chat menu button (`Happy Fox`);
- BotFather Main Mini App when configured;
- `startapp` deep links used for post/profile/remix/generation/model entry.

`FOXGEN_MINIAPP_PUBLIC_URL` is preferred. If absent, FoxGen derives `/mini-app/` from `FOXGEN_KIE_CALLBACK_BASE_URL`. Missing public configuration fails closed.

## Authentication and trust boundary

1. Telegram provides opaque `Telegram.WebApp.initData`.
2. `POST /v1/miniapp/auth` sends it to FoxGen.
3. FoxGen validates Telegram HMAC and `auth_date` server-side.
4. FoxGen issues a short-lived HS256 JWT with audience `happy-fox-miniapp`.
5. Every owner-scoped browser action derives `user_id` from that JWT; browser-supplied user IDs are never trusted.

Demo mode outside Telegram is presentation-only. It cannot create paid work, mutate wallet/social state, redeem promos, upload private media or access owner data.

## Current navigation

The canonical parity runtime is `miniapp_static/parity-app.js` with:

- **Лента** — recent/top-day/top publications, profiles, likes, comments and remix;
- **Создать** — schema-driven model catalog, Quick Start and adaptive generation studio;
- **Работы** — owner generation history/detail/status polling/cancel/repeat/publish;
- **Профиль** — public profile, own publications, wallet/ledger and reference memory.

Executable creation products currently include image/video models, ElevenLabs Turbo 2.5 TTS and Suno V5 core music generation. Planned product buttons remain disabled until their complete backend + Telegram + Happy Fox slices exist.

`index.html` loads:

- `parity-app.js` — core authenticated Mini App runtime/studio;
- `complete-menu.js` — product launcher, result-open action and Stars checkout;
- `tts-parity.js` — TTS Audio product presentation;
- `suno-parity.js` — Suno Music product presentation/mode-aware field visibility;
- `promo-redeem.js` — owner promo redemption.

These parity modules never own billing/provider credentials. Backend JSON Schema and server-side validation remain authoritative.

## Visual contract

Happy Fox uses a dark graphite/orange system. Controls/media/comments/settings/wallet rows stay clean; restrained grunge remains decorative only. `--grunge-opacity` is regression-tested and must remain `<= 0.30`.

The layout is mobile-first and uses Telegram content-safe-area variables, BackButton navigation, theme/viewport events and reduced-motion support.

## Schema-driven generation studio

Backend registry + Pydantic JSON schema are the source of truth for enabled generation models and parameters. The browser never calls KIE directly and never changes wallet state directly.

Before paid admission, Happy Fox calls `/v1/miniapp/models/{slug}/validate`; `/v1/miniapp/tasks` validates again and enters shared `SubmissionService`.

Current image/video behavior includes Seedream text/edit resolution from reference presence, Nano Banana reference bounds, Seedance text/first/last/multimodal modes and private owner-scoped temporary uploads.

### ElevenLabs Turbo 2.5

Happy Fox exposes an **Аудио** section for `elevenlabs-turbo-2-5`. The studio schema contains text, Voice ID/name, stability, similarity, style, speed, timestamps, context and language-code controls.

`tts-parity.js` only localizes/presents those backend-owned fields and explicitly disables launch when no active price exists. TTS uses the normal `/v1/miniapp/tasks` admission and audio archive/delivery lifecycle.

### Suno V5 core

Happy Fox exposes a **Музыка** section for `suno-v5`.

The reviewed server schema supports:

- simple prompt mode;
- custom vocal mode;
- custom instrumental mode;
- negative tags, vocal gender and bounded advanced weights in custom mode.

`suno-parity.js` keeps the screen compact by hiding custom-only fields in simple mode and hiding lyrics/prompt for custom instrumental mode. This is presentation only: backend validation still enforces all Suno mode combinations before paid admission.

The browser does not contain KIE's `/api/v1/generate` endpoint or credentials. Worker-side `ModelSpec.api_family="suno"` selects the dedicated provider adapter. Multi-track Suno results stay separate and are archived/delivered as canonical audio results.

See `suno-core.md`.

## Paid admission and remix lineage

`POST /v1/miniapp/tasks` requires `Idempotency-Key` and uses the same transaction as Telegram. Social remix source lineage is part of the request fingerprint and is committed with generation admission, wallet reservation and submit outbox creation.

Image, video, TTS and Suno all use this same paid boundary. Missing active price or insufficient balance fails before provider submission.

## Feed, profiles and publication

Happy Fox exposes the merged social domain through Telegram-JWT-safe wrappers, including feed/profile reads, likes/comments, profile updates, generation publication/unpublication and fresh remix-source resolution.

Publication remains a projection over succeeded generation + stored media. Provider temporary URLs are never social storage. Likes are state-setting rather than browser-owned counters.

## Durable reference memory

Owner-scoped reference memory is durable in PostgreSQL/S3. Happy Fox can list, explicitly save, resolve and delete its own references. Immediately before paid generation, references are re-resolved so stale/deleted/foreign assets fail before provider side effects.

## Generation history and lifecycle

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/miniapp/generations` | owner history, bounded to 100 |
| `GET` | `/v1/miniapp/generations/{id}` | detail + short-lived stored-media URLs |
| `POST` | `/v1/miniapp/generations/{id}/cancel` | existing safe cancellation boundary |

Active detail screens poll until terminal state. Cancellation remains forbidden after the provider-side-effect safety boundary; Repeat creates a new draft/idempotency key.

## Wallet, pricing, Stars and promo bonuses

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/miniapp/balance` | available/reserved/total materialized balance |
| `GET` | `/v1/miniapp/prices` | active generation prices |
| `GET` | `/v1/miniapp/ledger` | immutable owner ledger, bounded to 200 |
| `GET` | `/v1/miniapp/payments/stars/packages` | Stars packages with base/bonus/total CREDIT projection |
| `POST` | `/v1/miniapp/payments/stars/invoices` | create/replay owner-scoped XTR invoice; requires `Idempotency-Key` |
| `POST` | `/v1/miniapp/promos/redeem` | redeem one server-defined promo bonus for this owner |

### Stars and package bonus

The browser creates a durable invoice and opens it through `Telegram.WebApp.openInvoice`. A published Stars package may include an explicit server-owned non-negative purchase bonus. `complete-menu.js` displays total CREDIT and an explicit bonus line, while invoice creation still sends only `package_code`.

The browser never computes/submits a bonus, cannot declare checkout success and cannot request privileged refund. Telegram native updates and the trusted backend own settlement.

### Promo redemption

The wallet promo panel accepts only a text code, authenticates with the normal Mini App JWT and posts `{code}` to `/v1/miniapp/promos/redeem`. Reward amount/limits remain server-owned and duplicate owner/code cannot grant twice.

See `telegram-stars-payments.md`, `user-promos.md` and `billing.md`.

## Happy Fox user portal

Owner-scoped routes authenticated by the Telegram-derived JWT include tariff, support, partner enrollment/withdrawals, Stars packages/invoice and promo redemption. Equivalent trusted `/v1/user-portal/*` routes derive owner identity independently of the paid-task submission kill switch. Admin review/promo-definition/payment-refund actions remain privileged.

## Full user-parity program

Issue #89 is the master parity contract. Executable user surfaces now include social/reference memory, tariffs/support/partner portal, Stars top-up/refund, package bonuses, promo redemption, ElevenLabs Turbo 2.5 TTS and Suno V5 core generation.

Still tracked for backend + Telegram + Happy Fox delivery:

- additional voice features: dialogue, cloning/speech-to-speech and audio cleanup;
- remaining Suno #15 workflows: extend/cover/lyrics/add vocals/instrumental/stems/WAV/MIDI/mashup/persona/music video/callback ingestion;
- motion control/talking avatar;
- Prompt AI and conversational assistant;
- dedicated Gemini Omni / Runway / Veo adapters where required;
- dynamic/segmented purchase-bonus campaign rules beyond explicit per-package bonus amounts;
- remaining referral attribution/anti-fraud mechanics required by EPIC #8;
- the undefined `boring_work` product requires an explicit product contract before implementation.

Operator/admin APIs remain separate and are not ordinary Mini App parity.

## Production setup

```env
FOXGEN_MINIAPP_ENABLED=true
FOXGEN_MINIAPP_PUBLIC_URL=https://foxgen.example.com/mini-app/
FOXGEN_MINIAPP_JWT_SECRET=<dedicated-random-secret>
FOXGEN_MINIAPP_AUTH_MAX_AGE_SECONDS=86400
FOXGEN_MINIAPP_JWT_TTL_SECONDS=3600
FOXGEN_MINIAPP_MEDIA_URL_TTL_SECONDS=300
```

TTS/Suno need no browser provider credential. Their production launches additionally require active backend model prices; no commercial prices are hardcoded by these product slices.

The public reverse proxy routes `/mini-app/` and `/v1/miniapp/*` while `/internal/admin/*` remains private.

## Tests and rollback

Required regression coverage includes:

- valid/tampered/stale Telegram initData and JWT owner binding;
- no internal/admin/provider credential in browser surface;
- schema-driven generation validation/admission;
- TTS Audio launcher/schema/task/static trust boundary;
- TTS real PostgreSQL paid admission and cross-layer audio archive/delivery E2E;
- Suno Music launcher, mode-aware field visibility and no direct provider request;
- Suno strict simple/custom/instrumental validation;
- Suno real PostgreSQL no-price rollback and exactly-once paid admission;
- Suno E2E: Happy Fox JWT -> paid admission -> routed provider lifecycle -> intermediate processing -> two MP3 results -> archive/delivery -> `SUCCEEDED`;
- feed/profile/publish/remix/reference-memory boundaries;
- Stars package/invoice/payment/refund recovery and package bonus E2E;
- promo owner/concurrency/E2E invariants;
- Alembic upgrade/downgrade/re-upgrade and real PostgreSQL/Redis tests;
- production image/security scans;
- final Telegram WebView/public HTTPS smoke after deployment.

`FOXGEN_MINIAPP_ENABLED=false` removes the public Mini App router/static mount and suppresses WebApp entrypoints without changing durable generation, billing, payment, promo, publication or reference-memory state.
