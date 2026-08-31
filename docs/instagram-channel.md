# Instagram channel — canonical specification

Status: implemented in `foxgen/main`; runtime registration is disabled unless `INSTAGRAM_ENABLED=1`.

This is the canonical product/engineering specification for the HappyFox Instagram contour.

## 1. Purpose

Instagram is an acquisition and creator channel over the same HappyFox generation/billing core. It must not clone the Telegram UI or create a second ledger.

Primary journey:

```text
Reel/Post comment or Direct
  -> Photo / Video choice
  -> creator flow
  -> result in Direct
  -> top-up/resume when paid
```

Telegram remains the full application. Instagram is intentionally short, conversational and creator-oriented.

## 2. Meta transport

Primary integration: **Instagram API with Instagram Login** for Professional Creator/Business accounts.

Runtime host:

```text
https://graph.instagram.com
```

Default API version:

```text
v24.0
```

Permissions used by the implemented contour:

```text
instagram_business_basic
instagram_business_manage_messages
instagram_business_manage_comments
instagram_business_content_publish
```

Webhook path:

```text
/instagram/webhook
```

Subscribed fields:

```text
messages,messaging_postbacks,comments
```

The Send API conversation is user-initiated: do not treat Instagram as an arbitrary cold-DM transport.

## 3. Security contract

- GET webhook verification checks Meta `hub.mode`, `hub.verify_token`, `hub.challenge`.
- POST webhook verifies the raw request body with `X-Hub-Signature-256` HMAC-SHA256 using `INSTAGRAM_APP_SECRET`.
- Signature verification is fail-closed.
- Redis idempotency protects replay/duplicate webhook processing.
- Tokens/secrets are environment-only and must never enter repository/log output.
- Outgoing message echoes must not re-enter generation logic.

Transport implementation: `bot/instagram_api.py`.

## 4. Channel identity and account linking

Instagram users are not represented by fake Telegram IDs.

`channel_identities` maps:

```text
channel=instagram
account_id=<Instagram professional account>
external_user_id=<Instagram sender ID>
user_id=<nullable HappyFox users.id>
```

Before account link, the Instagram identity can use the first-free-photo entitlement. Paid generation requires a linked HappyFox account/balance.

Account-link flow:

```text
Instagram Direct
 -> one-time iglink token
 -> https://t.me/<HappyFoxBot>?start=iglink_<token>
 -> Telegram consumes token once
 -> Instagram identity.user_id = HappyFox user.id
 -> shared balance/history
```

Tokens are stored as hashes, expire, are one-use, and cannot silently relink an identity already bound to another user.

## 5. Language: RU/EN auto-switch

Supported languages:

```text
ru
en
```

Rules:

- first meaningful Cyrillic text -> Russian;
- first meaningful Latin/English text -> English;
- if the first interaction is attachment-only, show the creator choice bilingually;
- `Фото`/`Photo`, `Видео`/`Video` can establish language;
- explicit `English` or `Русский` switches the persisted language;
- language is stored per Instagram identity in `instagram_channel_languages`;
- all user-facing creator, billing, error/refund and resume copy must go through `bot/instagram_i18n.py`.

Do not add new hard-coded RU-only strings to Instagram handlers.

## 6. Entry FSM

Every creator session starts with:

```text
What to create?
  -> Photo
  -> Video
```

Recognized values are normalized by `bot/instagram_model_contract.py`.

If creation type is not selected, media attachments must not start generation.

## 7. Photo flow

Model contract:

```text
Product key:   seedream_5_pro
Provider:      seedream/5-pro-image-to-image
Quality:       high
Aspect ratio:  1:1
Paid price:    2.5 🐾
```

### First photo

Only the first **successful Instagram photo generation** is free.

```text
Photo selected
 -> ask image reference
 -> ask prompt
 -> reserve instagram_first_image entitlement
 -> enqueue durable Seedream job
 -> provider success
 -> deliver image to Direct
 -> consume entitlement
 -> offer top-up/continue
```

If provider generation fails before successful delivery, release the entitlement so the free attempt remains available.

### Later photos

```text
Photo selected
 -> account/balance check
 -> reference
 -> prompt
 -> show 2.5 🐾 confirmation
 -> YES/ДА
 -> deduct 2.5 🐾
 -> enqueue
 -> deliver
```

If the provider fails terminally after charge, refund the charge. A retry must not double-charge or create a second provider task.

## 8. Video flow

Model contract:

```text
Product key:   seedance_2_5
Provider:      bytedance/seedance-2-5
Resolution:    720p
Aspect ratio:  9:16
Default UX duration: 5s
Price source:  shared HappyFox/Telegram Seedance pricing
```

**Video is always paid. There is no free video entitlement.**

Entry rule:

```text
Video selected
 -> immediate top-up/paywall message
 -> do NOT request/store a new reference yet
 -> user tops up
 -> returns to Direct
 -> Continue / Продолжить
 -> verify linked balance
 -> only then ask photo/video reference
 -> ask prompt
 -> show price confirmation
 -> charge
 -> enqueue Seedance job
 -> deliver result
```

A media attachment sent while state is `video:awaiting_topup` must not bypass the paywall.

## 9. Top-up and payments

HappyFox has one shared ledger. Instagram does not create a separate checkout backend.

Instagram Telegram handoff intentionally exposes only:

```text
YooKassa
Lava Top
```

Lava Top path:

```text
provider -> package -> card or SBP -> existing Lava production handler
```

YooKassa path:

```text
provider -> package -> existing YooKassa production handler
```

After payment:

```text
return to Instagram Direct -> Continue / Продолжить
```

Important separation:

- **Instagram handoff:** YooKassa + Lava Top only.
- **Telegram general payment UI:** keeps its configured providers, including CryptoBot. Do not remove CryptoBot from Telegram when changing Instagram top-up UX.

## 10. Durable generation and crash safety

Instagram jobs are persisted in `instagram_generation_jobs`.

Important checkpoints:

- prepared job exists before financial side effect;
- charge/promotion reservation is recoverable;
- provider `task_id` is persisted immediately after submit;
- worker restart resumes polling the same provider task rather than submitting a duplicate;
- `result_url` is persisted before delivery retry;
- `delivered_at_epoch` prevents duplicate media delivery during later finalization retries;
- terminal paid failure refunds once;
- terminal free-photo failure releases promotion once.

There remains an unavoidable remote/local ambiguity if Meta accepts a send and the process crashes before the local delivery checkpoint is committed; do not document this as mathematically exactly-once delivery.

## 11. Comments acquisition

Keyword comments such as `ХОЧУ`/equivalent acquisition intent can receive one private-reply invitation to continue in Direct. The actual creator flow still begins with Photo/Video selection.

Keep Meta private-reply restrictions in mind: comment private reply is not a general unlimited DM mechanism.

## 12. Publishing primitives

The client contains container/status/publish primitives for Instagram publishing. Publishing must remain explicit user action; do not auto-publish generated media without confirmation.

Media supplied to Meta publishing endpoints must be reachable via public HTTPS URL.

## 13. Environment

Required to enable live:

```dotenv
INSTAGRAM_ENABLED=1
INSTAGRAM_APP_ID=...
INSTAGRAM_APP_SECRET=...
INSTAGRAM_VERIFY_TOKEN=...
INSTAGRAM_ACCESS_TOKEN=...
INSTAGRAM_IG_USER_ID=...
INSTAGRAM_API_VERSION=v24.0
INSTAGRAM_WEBHOOK_PATH=/instagram/webhook
INSTAGRAM_REQUEST_TIMEOUT_SECONDS=30
INSTAGRAM_IDEMPOTENCY_TTL_SECONDS=604800
INSTAGRAM_SUBSCRIBED_FIELDS=messages,messaging_postbacks,comments
```

Default `.env.happyfox.example` must keep `INSTAGRAM_ENABLED=0` until credentials, app access/review and live webhook validation are ready.

## 14. Live activation checklist

1. Instagram account is Professional Creator/Business.
2. Meta app uses Instagram Login setup.
3. Required permissions/access are granted.
4. Runtime secrets are configured outside Git.
5. Public HTTPS `/instagram/webhook` reaches HappyFox backend.
6. GET verification succeeds with the configured verify token.
7. Signed POST webhook succeeds; invalid signature gets rejected.
8. `subscribed_apps` includes `messages,messaging_postbacks,comments`.
9. Set `INSTAGRAM_ENABLED=1`.
10. Deploy exact tested `main` SHA.
11. Live smoke: RU Direct, EN Direct, first free photo, paid photo top-up, paid video top-up/resume, comment invite.
12. Confirm duplicate webhook does not duplicate charge/generation/delivery.

## 15. Regression tests

Canonical tests include:

```text
tests/test_instagram_transport.py
tests/test_instagram_channel.py
tests/test_instagram_creator_flow.py
tests/test_instagram_generation.py
tests/test_instagram_model_contract.py
tests/test_instagram_i18n.py
tests/test_instagram_account_link.py
tests/test_instagram_account_link_router.py
tests/test_channel_identity.py
tests/test_channel_promotions.py
```

Any product change to Instagram must update these contracts before merge.
