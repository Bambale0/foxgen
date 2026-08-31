# HappyFox FSM and user flows

This document is the canonical state-flow map for Telegram Bot + Mini App + Instagram creator channel.

## 1. Core rule

Channel UI may differ, but generation/billing side effects must stay durable and shared. Temporary Telegram wizard data belongs in `FSMContext`; Instagram creator state is persisted in Instagram session/job tables because it must survive webhook retries and process restarts.

## 2. Telegram FSM groups

Main state groups remain:

- `GenerationStates` — image/video creation;
- `PaymentStates` — balance/top-up;
- `AdminStates` — admin contour;
- `BatchGenerationStates` — batch generation;
- `ImageAnalyzerStates` — prompt-from-photo;
- feature-specific states in their respective handlers.

Do not store per-user temporary wizard state in process globals.

## 3. Telegram main flows

### Photo

```text
/start
 -> Create photo
 -> model
 -> optional references
 -> ratio/quality/count/options
 -> prompt
 -> balance validation/charge
 -> provider job
 -> result
 -> repeat/publish/library/animate
```

### Video

```text
/start
 -> Create video
 -> model
 -> generation type
 -> references/media
 -> duration/ratio/model options
 -> prompt
 -> balance validation/charge
 -> provider job
 -> result
 -> repeat/publish/library
```

### Balance

```text
Balance
 -> Top up
 -> package/promo
 -> provider
 -> pending transaction/payment URL
 -> signed provider webhook
 -> shared balance credit
 -> notification
```

Telegram payment UI uses the providers enabled for Telegram. CryptoBot remains valid here when configured.

### Mini App

```text
Telegram WebView
 -> initData
 -> /mini-app/api/bootstrap
 -> live UI
 -> create/history/feed/profile/billing actions
```

Browser/open-outside-Telegram fallback is separate from normal Telegram WebView auth.

## 4. Instagram durable state model

Instagram does not use Telegram `FSMContext` as its primary state store.

Key persisted data:

```text
channel_identities
instagram_channel_languages
instagram_generation_sessions
instagram_generation_jobs
channel promotion/link tables
```

Session state contains selected creator kind, media/prompt draft and resume step. Jobs contain billing mode, provider task/result/delivery checkpoints and retry state.

## 5. Instagram entry

Every creator interaction starts from creation-type choice unless a valid in-progress session already dictates the next step.

```text
IG_START
 -> Фото / Photo
 -> Видео / Video
```

If first interaction is attachment-only and language is unknown, show a bilingual chooser. Media must not bypass creation-type selection.

## 6. Instagram language FSM

```text
no stored language
 -> meaningful RU text -> ru persisted
 -> meaningful EN text -> en persisted
 -> media only -> bilingual copy, language remains unknown
```

Explicit switch:

```text
English -> en
Русский -> ru
```

`Photo/Фото` and `Video/Видео` can establish language. New Instagram user-facing strings must use `bot/instagram_i18n.py`.

## 7. Instagram photo FSM

Model:

```text
Seedream 5 Pro
provider: seedream/5-pro-image-to-image
quality: high
ratio: 1:1
paid price: 2.5 🐾
```

### First successful photo — free

```text
IG_START
 -> Photo
 -> IG_PHOTO_WAIT_REFERENCE_FREE
 -> image reference
 -> IG_PHOTO_WAIT_PROMPT_FREE
 -> prompt
 -> reserve first-photo entitlement
 -> IG_PHOTO_GENERATING_FREE
 -> provider/result delivery success
 -> consume entitlement
 -> IG_PHOTO_RESULT_FREE
 -> top-up/continue offer
```

Failure before successful result delivery:

```text
provider terminal failure
 -> release entitlement
 -> free attempt remains available
```

### Paid photo

```text
Photo
 -> promotion already consumed
 -> if unlinked: account-link/top-up handoff
 -> if linked: reference
 -> prompt
 -> IG_PHOTO_CONFIRM_PAID
 -> YES/ДА
 -> deduct 2.5 🐾
 -> durable job
 -> result
```

Insufficient balance returns to top-up/resume instead of provider submit.

Terminal provider failure after charge -> refund once.

## 8. Instagram video FSM

Model:

```text
Seedance 2.5
provider: bytedance/seedance-2-5
resolution: 720p
ratio: 9:16
price: shared HappyFox/Telegram Seedance pricing
```

**Video is always paid.**

```text
IG_START
 -> Video
 -> IG_VIDEO_AWAITING_TOPUP
 -> show YooKassa/Lava Top handoff
 -> do not accept/store new media reference
 -> user pays in Telegram
 -> returns to Direct
 -> Continue / Продолжить
 -> verify linked user + sufficient balance
 -> IG_VIDEO_WAIT_SOURCE
 -> image/video reference
 -> IG_VIDEO_WAIT_PROMPT
 -> prompt
 -> IG_VIDEO_CONFIRM_PAID
 -> YES/ДА
 -> charge
 -> IG_VIDEO_GENERATING
 -> result
```

If balance is still low on `Continue`, remain in paywall state.

If provider fails terminally after charge, refund once.

## 9. Instagram top-up/account-link FSM

```text
paid action requires account/balance
 -> create one-time iglink token
 -> Telegram /start iglink_<token>
 -> consume token
 -> bind Instagram identity to HappyFox user
 -> show Instagram-specific top-up providers
```

Instagram-specific Telegram handoff:

```text
YooKassa -> package -> existing YooKassa handler
Lava Top -> package -> card/SBP -> existing Lava handler
```

After payment:

```text
return to Direct -> Continue / Продолжить -> balance re-check -> resume saved flow
```

Do not expose CryptoBot in this Instagram handoff, and do not remove CryptoBot from the normal Telegram payment menu.

## 10. Instagram comment acquisition

```text
comment keyword/intention
 -> normalized comment event
 -> one private-reply invitation
 -> user enters Direct
 -> Photo/Video chooser
```

Comment reply is acquisition only; it does not skip creator FSM or payment rules.

## 11. Durable job FSM

Simplified job states:

```text
prepared
 -> queued
 -> processing
 -> result persisted
 -> delivered/finalized
```

Retry paths:

```text
processing + provider_task_id -> resume same provider task
result persisted + delivery error -> retry delivery without regeneration
successful delivery + local finalization error -> retry finalization without re-sending when checkpoint exists
```

Financial/promotion invariants:

- prepare before side effect;
- one charge per paid job;
- one refund on terminal paid failure;
- free-photo reserve -> consume only after success;
- free-photo reserve -> release on terminal failure;
- no free video path.

## 12. User-visible cancel/confirm controls

RU/EN inputs accepted by channel-specific normalizers should include the documented confirmation/cancel vocabulary (`ДА/НЕТ`, `YES/NO`, `Продолжить/Continue`) without changing the stored model/billing contract.

## 13. Router ordering

Specific routers must win before broad fallback handlers. The Instagram `/start iglink_*` Telegram router must run before a generic legacy `/start` handler.

## 14. Completion criteria

A release is UX-complete when these paths work without undocumented commands:

1. Telegram photo create -> result.
2. Telegram video create -> result.
3. Telegram top-up through configured provider -> balance.
4. Telegram Mini App bootstrap -> create/history/feed/balance.
5. Instagram RU first photo -> free result -> top-up offer.
6. Instagram EN photo -> English follow-ups.
7. Instagram Video -> immediate paywall -> YooKassa/Lava -> Continue -> reference -> paid result.
8. Instagram comment invite -> Direct -> chooser.
9. Provider/retry failure does not double-charge, consume free entitlement incorrectly or duplicate provider submit.
