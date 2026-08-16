# Happy Fox Telegram Mini App

`Happy Fox` is FoxGen's public Telegram Mini App. User-facing branding is **Happy Fox only**; internal package/database/service names remain `foxgen`.

The Mini App is served by FastAPI at `/mini-app/`; user-safe browser APIs are under `/v1/miniapp/*`. The browser never receives the internal API token, admin HMAC, KIE key, S3 credentials or any operator credential.

## Telegram entrypoints

When a public HTTPS URL is configured, Happy Fox is reachable through:

- the first `/start` / `/menu` inline WebApp button;
- Telegram's default chat menu button (`Happy Fox`);
- BotFather Main Mini App when configured;
- `startapp` deep links used for post/profile/remix/generation/model entry.

`FOXGEN_MINIAPP_PUBLIC_URL` is preferred. If absent, FoxGen derives `/mini-app/` from `FOXGEN_KIE_CALLBACK_BASE_URL`. Missing public configuration fails closed instead of presenting a fake working entrypoint.

## Authentication and trust boundary

1. Telegram provides opaque `Telegram.WebApp.initData`.
2. `POST /v1/miniapp/auth` sends it to FoxGen.
3. FoxGen validates Telegram's HMAC and `auth_date` server-side.
4. FoxGen issues a short-lived HS256 JWT with audience `happy-fox-miniapp`.
5. Every owner-scoped browser action derives `user_id` from that JWT; browser-supplied user IDs are never trusted.

Demo mode outside Telegram is presentation-only. It cannot create paid work, mutate wallet/social state, upload private media or access owner data.

## Current navigation

The canonical parity runtime is `miniapp_static/parity-app.js` with:

- **Лента** — recent/top-day/top publications, profiles, likes, comments and remix;
- **Создать** — schema-driven model catalog, Quick Start and adaptive generation studio;
- **Работы** — owner generation history/detail/status polling/cancel/repeat/publish;
- **Профиль** — public profile, own publications, wallet/ledger and reference memory.

Secondary screens include generation detail, publication detail, public profile, wallet, durable reference memory, support, partner portal, published tariffs and Telegram Stars top-up.

The previous `app.js` remains packaged only as a rollback artifact; `index.html` loads `parity-app.js`. `complete-menu.js` augments the current wallet/tool launcher and owns the Stars checkout interaction without duplicating backend financial logic.

## Visual contract

Happy Fox uses a dark graphite/orange system. `parity.css` adds restrained grunge to selected hero/card backgrounds, stamps and dividers only. Controls, media, comments, generation settings and wallet rows stay clean.

`--grunge-opacity` is regression-tested and must remain `<= 0.30`.

The layout is mobile-first and uses Telegram content-safe-area CSS variables, BackButton navigation, theme/viewport events and reduced-motion support.

## Schema-driven generation studio

Backend registry + Pydantic JSON schema are the only source of truth for enabled generation models and their parameters.

Each enabled model exposes:

- slug/title/family/media kind;
- capability metadata and recommendations;
- defaults;
- reviewed input contract;
- `input_schema` including enums, bounds, required fields and media fields;
- current active FoxGen price via wallet pricing.

The UI maps schema fields to bounded controls and authenticated media pickers. Before paid admission, the browser calls `/v1/miniapp/models/{slug}/validate`; `/v1/miniapp/tasks` validates again and enters the shared `SubmissionService`.

The browser never calls KIE directly and never changes wallet state directly.

### Current image/video behavior

- Seedream text/edit provider slug is resolved from reference presence without a redundant user mode screen.
- Nano Banana image references follow backend max-item bounds.
- Seedance exposes text, first-frame, first+last-frame and multimodal-reference modes; frame and multimodal modes remain mutually exclusive.
- private temporary uploads are stored under `inputs/miniapp/<telegram-user-id>/...`;
- incompatible/reset uploads are explicitly cleaned where possible; retention remains the final orphan backstop.

## Paid admission and remix lineage

`POST /v1/miniapp/tasks` requires `Idempotency-Key` and uses the same admission transaction as Telegram.

For a social remix, the request also includes `source_publication_id`. That value reaches the same `SubmissionService`; lineage is part of the request fingerprint and is committed atomically with generation admission, wallet reservation and submit outbox creation. Source publication media is re-read immediately before submit so the browser does not rely on an old signed URL.

## Feed, profiles and publication

The social domain from #58 is merged and exposed to Happy Fox through Telegram-JWT-safe wrappers.

### Feed/read routes

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/miniapp/feed` | `recent`, `top_day`, `top` feed pagination |
| `GET` | `/v1/miniapp/publications/{id}` | publication detail |
| `GET` | `/v1/miniapp/profiles/{slug}` | public profile |
| `GET` | `/v1/miniapp/profiles/{slug}/publications` | profile publication grid |
| `GET` | `/v1/miniapp/me/profile` | ensure/read own public profile |
| `GET` | `/v1/miniapp/me/publications` | own publication management |

### Social writes

| Method | Path | Purpose |
|---|---|---|
| `PUT` | `/v1/miniapp/publications/{id}/like` | set like state idempotently |
| `GET/POST` | `/v1/miniapp/publications/{id}/comments` | surface-scoped comments |
| `PUT` | `/v1/miniapp/me/profile` | update own slug/name/bio |
| `POST` | `/v1/miniapp/generations/{id}/publications` | publish eligible generation |
| `DELETE` | `/v1/miniapp/generations/{id}/publications/{scope}` | unpublish without deleting generation |
| `GET` | `/v1/miniapp/publications/{id}/remix` | fresh server-validated remix source |

Publication remains a projection over an immutable succeeded generation + stored media. Provider temporary URLs are never social storage. Derivatives cannot enter the global feed; derivative public prompt/action redaction remains server-enforced.

Likes are state-setting rather than browser-owned counters. Comments remain isolated between `feed` and `profile` surfaces.

## Durable reference memory

The reference-memory domain from #69 is merged and exposed in Happy Fox.

### Browser routes

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/miniapp/reference-memory` | owner library, usage and quotas |
| `POST` | `/v1/miniapp/reference-memory` | explicitly promote an owner temporary image |
| `POST` | `/v1/miniapp/reference-memory/resolve` | fresh active/owner validation + preview/provider capability URLs |
| `DELETE` | `/v1/miniapp/reference-memory/{id}` | schedule durable deletion |

Reference metadata lives in PostgreSQL; bytes live under private `references/<user>/<uuid>` S3 keys. Redis owns only ephemeral UI selection. Saved references survive FSM expiry/redeploys until explicit deletion.

The service accepts exactly two temporary owner namespaces:

```text
inputs/<telegram-user-id>/...
inputs/miniapp/<telegram-user-id>/...
```

A foreign Mini App/Telegram input is rejected before file access. The library enforces configured item/byte quotas and per-owner checksum deduplication. Deletion immediately makes the reference unresolvable, then the worker deletes S3 bytes through the durable outbox lifecycle.

Immediately before paid generation the Mini App calls `/reference-memory/resolve` again; stale/deleted/foreign references fail before provider side effects.

## Generation history and lifecycle

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/miniapp/generations` | owner history, bounded to 100 |
| `GET` | `/v1/miniapp/generations/{id}` | detail + short-lived stored-media URLs |
| `POST` | `/v1/miniapp/generations/{id}/cancel` | existing safe cancellation boundary |

Active detail screens poll until terminal state. Cancellation remains forbidden after the existing provider-side-effect safety boundary; the browser does not invent a blind retry. Repeat creates a new draft/idempotency key.

## Wallet, pricing and Telegram Stars

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/miniapp/balance` | available/reserved/total materialized balance |
| `GET` | `/v1/miniapp/prices` | active generation prices |
| `GET` | `/v1/miniapp/ledger` | immutable owner ledger, bounded to 200 |
| `GET` | `/v1/miniapp/payments/stars/packages` | current Stars-enabled top-up packages |
| `POST` | `/v1/miniapp/payments/stars/invoices` | create/replay owner-scoped XTR invoice; requires `Idempotency-Key` |

Paid generation remains responsible for atomic reserve/capture/release/refund. Happy Fox only reads wallet projections and submits generation through the shared paid boundary.

For top-up, the browser authenticates with the same Telegram-derived JWT, obtains Stars-enabled packages, creates a durable invoice order and opens the returned URL through `Telegram.WebApp.openInvoice`. A session-scoped idempotency key is reused across network retries.

The browser **cannot** declare checkout success. Telegram sends native `pre_checkout_query` and `successful_payment` updates to the bot; the trusted backend validates the order, persists charge evidence as `status=paid`, then settles CREDIT exactly once. If the second settlement boundary fails, the user must not pay again: durable payment evidence remains recoverable through the operator payment reprocess path.

See `telegram-stars-payments.md` and `billing.md`.

## Happy Fox user portal

Owner-scoped routes authenticated by the Telegram-derived JWT include:

- `GET /v1/miniapp/tariff` — current published tariff version;
- `GET|POST /v1/miniapp/support` — list/create support tickets;
- `GET /v1/miniapp/support/{ticket_id}` — ticket detail/history;
- `POST /v1/miniapp/support/{ticket_id}/messages` — reply;
- `POST /v1/miniapp/support/{ticket_id}/close` — close own ticket;
- `GET /v1/miniapp/partner` — partner dashboard and withdrawals;
- `POST /v1/miniapp/partner/join` — idempotent partner enrollment;
- `POST /v1/miniapp/partner/withdrawals` — create withdrawal request; requires `Idempotency-Key`.

The equivalent `/v1/user-portal/*` trusted-service routes authenticate user context independently of the paid-task submission kill switch. Admin review/approval actions remain under the privileged admin control plane.

## Full user-parity program

Issue #89 is the master parity contract. Social/reference memory, tariffs/support/partner portal and Stars top-up are executable product surfaces. Remaining planned Telegram entries must **not** be represented as working browser features until their backend/product domains are implemented and tested.

Still tracked for backend + Telegram + Happy Fox delivery:

- voice/TTS/dialogue/audio cleanup;
- Suno music/extend/cover/lyrics/vocals/instrumental/stems/MIDI;
- motion control/talking avatar;
- Prompt AI and conversational assistant;
- dedicated Gemini Omni / Runway / Veo adapters where required;
- promo/bonus coupling and Telegram Stars refund workflow;
- remaining referral attribution/anti-fraud mechanics required by EPIC #8;
- the currently undefined `boring_work` product requires an explicit product contract before implementation.

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

Stars invoice creation uses the configured Telegram bot token server-side; no payment-provider or bot credential is added to browser configuration.

The public reverse proxy must route `/mini-app/`, `/v1/miniapp/*` and the signed read-only reference-media route to FoxGen while keeping `/internal/admin/*` private.

## Tests and rollback

Required regression coverage includes:

- valid/tampered/stale Telegram initData and JWT owner binding;
- no internal/admin credential in browser surface;
- schema-driven model validation before paid admission;
- stable idempotency and remix source lineage;
- owner generation history/detail/cancel;
- feed/profile/publish/like/comment/remix JWT boundary;
- reference-memory owner namespace, resolve/delete and foreign-key rejection;
- user portal tariff/support/partner ownership;
- Stars package/invoice JWT ownership and idempotency;
- bot pre-checkout fail-closed behavior and successful-payment transport;
- real PostgreSQL exactly-once Stars credit plus forced paid-but-uncredited recovery test;
- parity runtime/index markers and four primary navigation surfaces;
- restrained grunge token `<=0.30`;
- Alembic upgrade/downgrade/re-upgrade and real PostgreSQL/Redis lifecycle tests;
- production image build/security scans;
- final Telegram WebView/public HTTPS smoke after deployment.

`FOXGEN_MINIAPP_ENABLED=false` removes the public Mini App router/static mount and suppresses Telegram WebApp entrypoints without changing durable generation, billing, payment, publication or reference-memory state.
