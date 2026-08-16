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

Secondary screens include generation detail, publication detail, public profile, wallet, durable reference memory, support, partner portal, published tariffs and Telegram Stars top-up.

`index.html` loads `parity-app.js`. `complete-menu.js` augments the wallet/tool launcher and owns Stars checkout. `promo-redeem.js`/`promo-redeem.css` add the owner promo control without duplicating financial policy in the browser.

## Visual contract

Happy Fox uses a dark graphite/orange system. Controls/media/comments/settings/wallet rows stay clean; restrained grunge remains decorative only. `--grunge-opacity` is regression-tested and must remain `<= 0.30`.

The layout is mobile-first and uses Telegram content-safe-area variables, BackButton navigation, theme/viewport events and reduced-motion support.

## Schema-driven generation studio

Backend registry + Pydantic JSON schema are the only source of truth for enabled generation models and their parameters. The browser never calls KIE directly and never changes wallet state directly.

Before paid admission, Happy Fox calls `/v1/miniapp/models/{slug}/validate`; `/v1/miniapp/tasks` validates again and enters shared `SubmissionService`.

Current image/video behavior includes Seedream text/edit resolution from reference presence, Nano Banana reference bounds, Seedance text/first/last/multimodal modes and private owner-scoped temporary uploads.

## Paid admission and remix lineage

`POST /v1/miniapp/tasks` requires `Idempotency-Key` and uses the same transaction as Telegram. Social remix source lineage is part of the request fingerprint and is committed with generation admission, wallet reservation and submit outbox creation.

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
| `GET` | `/v1/miniapp/payments/stars/packages` | current Stars-enabled top-up packages |
| `POST` | `/v1/miniapp/payments/stars/invoices` | create/replay owner-scoped XTR invoice; requires `Idempotency-Key` |
| `POST` | `/v1/miniapp/promos/redeem` | redeem one server-defined promo bonus for this owner |

### Stars

The browser creates a durable invoice and opens it through `Telegram.WebApp.openInvoice`. It cannot declare checkout success or request privileged refund. Telegram native updates and the trusted backend own settlement; operator refund is server-side.

### Promo redemption

The wallet mounts a promo panel after the wallet actions. `promo-redeem.js`:

1. accepts only a text code (`maxlength=64`);
2. obtains/refreshes the normal Telegram-derived Mini App JWT;
3. posts `{code}` to `/v1/miniapp/promos/redeem`;
4. displays granted CREDIT/current balance or an existing-redemption replay message;
5. refreshes the wallet projection after success.

The browser never receives/submits `reward_units`, `max_uses` or `uses`. The server normalizes/locks the admin promo definition and atomically commits wallet + immutable ledger + redemption + usage counter. Duplicate owner/code does not grant twice.

Outside Telegram, promo redemption fails closed because no trusted `initData` exists.

See `user-promos.md` and `billing.md`.

## Happy Fox user portal

Owner-scoped routes authenticated by the Telegram-derived JWT include tariff, support, partner enrollment/withdrawals, Stars packages/invoice and promo redemption. Equivalent trusted `/v1/user-portal/*` routes derive owner identity independently of the paid-task submission kill switch. Admin review/promo-definition/payment-refund actions remain privileged.

## Full user-parity program

Issue #89 is the master parity contract. Social/reference memory, tariffs/support/partner portal, Stars top-up/refund and explicit promo redemption now have executable backend/user surfaces.

Still tracked for backend + Telegram + Happy Fox delivery:

- voice/TTS/dialogue/audio cleanup;
- Suno music/extend/cover/lyrics/vocals/instrumental/stems/MIDI;
- motion control/talking avatar;
- Prompt AI and conversational assistant;
- dedicated Gemini Omni / Runway / Veo adapters where required;
- automatic purchase-triggered bonus policy if required beyond explicit promo codes;
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

Stars invoice/refund uses the configured Telegram bot token server-side; promo redemption requires no additional browser secret/provider credential.

The public reverse proxy routes `/mini-app/` and `/v1/miniapp/*` while `/internal/admin/*` remains private.

## Tests and rollback

Required regression coverage includes:

- valid/tampered/stale Telegram initData and JWT owner binding;
- no internal/admin credential in browser surface;
- schema-driven generation validation/admission;
- feed/profile/publish/remix/reference-memory boundaries;
- Stars package/invoice/payment/refund recovery;
- promo static UI contract and owner-scoped API auth;
- real PostgreSQL concurrent duplicate promo redemption;
- real PostgreSQL atomic `max_uses` enforcement;
- promo E2E: signed admin definition -> Happy Fox JWT redemption -> ledger -> duplicate replay -> exhausted second user;
- Alembic upgrade/downgrade/re-upgrade and real PostgreSQL/Redis tests;
- production image/security scans;
- final Telegram WebView/public HTTPS smoke after deployment.

`FOXGEN_MINIAPP_ENABLED=false` removes the public Mini App router/static mount and suppresses WebApp entrypoints without changing durable generation, billing, payment, promo, publication or reference-memory state.
