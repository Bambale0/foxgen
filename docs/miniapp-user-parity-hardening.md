# Happy Fox user parity hardening

This document describes the production Mini App parity hardening added under issue #89. It only exposes behavior that already exists behind owner-scoped Happy Fox APIs and does not enable planned provider/product domains.

## Scope

The browser enhancement is loaded as `user-parity-hardening.js` from the existing Mini App module graph.

It closes user-facing gaps where backend behavior was already production-capable but the Happy Fox screen did not expose the complete result/action set:

- generation detail renders **every** stored media result instead of only `media[0]`;
- audio results use a native `<audio controls>` player;
- video results use native controls and `playsinline`;
- every generation result gets its own open/download action;
- publication detail renders every stored media item, including playable audio;
- succeeded-generation publication controls converge to **publish / unpublish** by querying the authenticated owner's publications and using the existing `DELETE /generations/{generation_id}/publications/{scope}` route;
- the Profile payment row is upgraded from the obsolete placeholder to the existing Telegram Stars top-up action;
- stale Wallet copy is replaced with the real native Telegram Stars settlement semantics;
- the Profile publications counter scrolls to the user's publication section instead of being a dead control.

## Trust boundary

The hardening module does not introduce a new business API.

It authenticates exactly like the other Happy Fox browser modules:

1. send opaque `Telegram.WebApp.initData` to `POST /v1/miniapp/auth`;
2. keep the returned short-lived bearer token in JavaScript memory;
3. call only `/v1/miniapp/*` owner-scoped routes;
4. retry authentication once on `401`.

It never receives or sends the internal API token, KIE credentials, Telegram bot token, admin HMAC material, S3 credentials, price amounts, wallet deltas or provider task credentials.

Publication removal remains server-authorized. The browser supplies only generation identity and the requested publication scope; ownership is derived from the Mini App JWT by the backend.

Telegram Stars top-up remains owned by `complete-menu.js` and the existing durable package/invoice/payment settlement path. This slice only makes that already-implemented action reachable from the Profile surface.

## Progressive enhancement and failure behavior

The canonical `parity-app.js` renderer remains the fallback.

The hardening module observes screen changes and only enhances matching generation/publication/profile/wallet DOM. If an enhancement fetch fails, it leaves the base renderer intact rather than hiding an otherwise usable screen.

Generation and publication media are re-fetched through owner-safe Mini App detail APIs so multi-result pages use fresh short-lived media URLs. No provider temporary URL is persisted in browser state.

The module does not poll independently for generation lifecycle state. Existing `parity-app.js` polling remains authoritative; enhancement runs after each terminal render.

## Planned products remain planned

This change does **not** enable Motion Control/talking avatar, Prompt AI, conversational assistant, Gemini Omni, dialogue/voice cloning/audio cleanup, or the remaining Suno issue #15 workflows. Those buttons must stay disabled until their backend + Telegram + Happy Fox slices satisfy issue #89.

## Regression coverage

`tests/test_miniapp_user_parity_hardening.py` checks:

- module wiring;
- all-result rendering;
- playable audio/video controls;
- per-result open/download actions;
- owner publication lookup and server-side unpublish;
- real Telegram Stars profile affordance;
- multi-media publication detail;
- absence of internal/admin/provider credentials in the browser module.

Local frontend smoke for this slice:

```bash
node --check src/foxgen/miniapp_static/user-parity-hardening.js
node --check src/foxgen/miniapp_static/promo-redeem.js
pytest -q tests/test_miniapp_user_parity_hardening.py
```

Full repository CI remains required before merge.

## Rollback

Rollback is transport-only:

1. remove the import of `user-parity-hardening.js` from `promo-redeem.js`;
2. remove the module and its regression test/documentation.

No database migration, provider operation, billing mutation or durable state rollback is required.
