# Happy Fox user parity hardening

This document describes the production Mini App parity hardening added under issue #89. It only exposes behavior that already exists behind owner-scoped Happy Fox APIs and does not enable planned provider/product domains.

## Scope

The browser enhancements are loaded as `user-parity-hardening.js` and `user-parity-phase2.js` from the existing Mini App module graph.

They close user-facing gaps where backend behavior was already production-capable but the Happy Fox screen did not expose the complete result/action set:

- generation detail renders **every** stored media result instead of only `media[0]`;
- audio results use a native `<audio controls>` player;
- video results use native controls and `playsinline`;
- every generation result gets its own open/download action;
- publication detail renders every stored media item, including playable audio;
- succeeded-generation publication controls converge to **publish / unpublish** by querying the authenticated owner's publications and using the existing `DELETE /generations/{generation_id}/publications/{scope}` route;
- failed and cancelled generations expose the existing repeat-draft transition instead of ending on a dead detail screen;
- generic generation studios fail closed when no active server price is published;
- an insufficient CREDIT balance disables launch before paid admission and exposes the real Telegram Stars top-up action;
- the Profile payment row is upgraded from the obsolete placeholder to the existing Telegram Stars top-up action, while duplicate/stale payment rows are collapsed to one live action;
- stale Wallet copy is replaced with the real native Telegram Stars settlement semantics;
- the Profile publications counter scrolls to the user's publication section instead of being a dead control;
- generic no-price hardening does not duplicate the dedicated TTS/Suno price warnings.

## Trust boundary

The hardening modules do not introduce a new business API.

The authenticated enhancement follows the same Happy Fox boundary as the other browser modules:

1. send opaque `Telegram.WebApp.initData` to `POST /v1/miniapp/auth`;
2. keep the returned short-lived bearer token in JavaScript memory;
3. call only `/v1/miniapp/*` owner-scoped routes;
4. retry authentication once on `401`.

It never receives or sends the internal API token, KIE credentials, Telegram bot token, admin HMAC material, S3 credentials, price amounts, wallet deltas or provider task credentials.

Publication removal remains server-authorized. The browser supplies only generation identity and the requested publication scope; ownership is derived from the Mini App JWT by the backend.

Telegram Stars top-up remains owned by `complete-menu.js` and the existing durable package/invoice/payment settlement path. These slices only make that already-implemented action reachable from Profile and insufficient-balance states.

The no-price and insufficient-balance guards are UX fail-closed checks only. Backend model readiness, current price, balance, reservation and paid admission remain authoritative; the browser never creates its own commercial price or wallet mutation.

## Progressive enhancement and failure behavior

The canonical `parity-app.js` renderer remains the fallback.

The hardening modules observe screen changes and only enhance matching generation/publication/profile/wallet/studio DOM. If an authenticated enhancement fetch fails, it leaves the base renderer intact rather than hiding an otherwise usable screen.

Generation and publication media are re-fetched through owner-safe Mini App detail APIs so multi-result pages use fresh short-lived media URLs. No provider temporary URL is persisted in browser state.

The module does not poll independently for generation lifecycle state. Existing `parity-app.js` polling remains authoritative; media enhancement runs on the succeeded terminal screen.

Retry reuses the existing `data-repeat-generation` transition from `parity-app.js`, so a new draft/idempotency key is created through the ordinary studio path instead of resubmitting an old billable request.

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

`tests/test_miniapp_user_parity_phase2.py` checks:

- retry affordance for failed/cancelled generations;
- fail-closed no-price state;
- insufficient-balance state and real Stars top-up affordance.

`tests/test_miniapp_user_parity_phase2_polish.py` checks:

- profile payment rows converge to one live Stars action;
- admission notices reuse the existing sibling instead of duplicating;
- generic hardening does not duplicate dedicated TTS/Suno no-price warnings.

Local frontend smoke for these slices:

```bash
node --check src/foxgen/miniapp_static/user-parity-hardening.js
node --check src/foxgen/miniapp_static/user-parity-phase2.js
node --check src/foxgen/miniapp_static/promo-redeem.js
pytest -q tests/test_miniapp_user_parity_hardening.py tests/test_miniapp_user_parity_phase2.py tests/test_miniapp_user_parity_phase2_polish.py
```

The current narrow suite returns 12 passing tests. Full repository CI remains required before merge.

## Rollback

Rollback is transport-only:

1. remove the imports of `user-parity-hardening.js` and `user-parity-phase2.js` from `promo-redeem.js`;
2. remove the modules and their regression tests/documentation.

No database migration, provider operation, billing mutation or durable state rollback is required.
