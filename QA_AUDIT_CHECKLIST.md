# HappyFox QA and release checklist

Use this checklist for release audits of `Bambale0/foxgen`. Production source of truth is `main`.

## 1. Release evidence

Before calling a change production-ready:

```text
[ ] PR targets main
[ ] exact PR head SHA is known
[ ] backend regression is green on that head
[ ] Ruff HappyFox delta is green
[ ] Mini App lint/build is green
[ ] Chromium critical journeys are green
[ ] iPhone WebKit Telegram startup is green
[ ] production Docker exact-source build/runtime is green
[ ] PR head was not changed after the successful run
[ ] merged main SHA is known
[ ] main CI is green on that SHA
[ ] production deploy target equals that SHA
[ ] public health/revision smoke is green
```

A green CI run for an older SHA is not release evidence for a newer head.

## 2. Product isolation

```text
[ ] PRODUCT_ID=happyfox
[ ] no NEUROMIX/Tanya bot token reuse
[ ] HappyFox PostgreSQL database is isolated
[ ] HappyFox Redis DB/prefix is isolated
[ ] HappyFox domains/media storage are isolated
[ ] HappyFox Lava offers come from HappyFox env
[ ] no production SQLite
[ ] secrets are absent from Git/logs/docs
```

## 3. Telegram regression

```text
[ ] /start -> main menu
[ ] Mini App bootstrap with valid Telegram initData
[ ] expected auth failure without valid initData
[ ] create photo -> charge -> provider -> result
[ ] create video -> charge -> provider -> result
[ ] provider terminal failure -> correct refund behavior
[ ] repeat/remix/history uses own task only
[ ] balance -> package -> payment -> shared balance update
[ ] CryptoBot remains available in Telegram when configured
[ ] YooKassa/Lava/Stars behavior matches configured Telegram UI
[ ] admin routes remain restricted
```

## 4. Instagram transport/security

When `INSTAGRAM_ENABLED=0`:

```text
[ ] Instagram routes/worker are not registered
[ ] Telegram/Mini App are unaffected
```

When testing the Instagram implementation:

```text
[ ] GET webhook verification checks verify token/challenge
[ ] POST verifies raw-body X-Hub-Signature-256 HMAC-SHA256
[ ] invalid signature fails closed
[ ] messages normalize correctly
[ ] postbacks normalize correctly
[ ] comments normalize correctly
[ ] outgoing echoes do not loop back into generation
[ ] duplicate webhook event is idempotent
[ ] Redis/idempotency failure does not silently process duplicates
```

## 5. Instagram language RU/EN

```text
[ ] Russian meaningful text -> ru persisted
[ ] English meaningful text -> en persisted
[ ] attachment-first -> bilingual Photo/Video chooser
[ ] Фото -> Russian flow
[ ] Photo -> English flow
[ ] Видео -> Russian video flow
[ ] Video -> English video flow
[ ] English explicitly switches existing RU session
[ ] Русский explicitly switches existing EN session
[ ] Продолжить and Continue both resume the relevant paid flow
[ ] no new Instagram user-facing hard-coded RU-only copy bypasses instagram_i18n
```

## 6. Instagram photo contract

Canonical model:

```text
Seedream 5 Pro
provider: seedream/5-pro-image-to-image
quality: high
ratio: 1:1
paid price: 2.5 🐾
```

Checklist:

```text
[ ] first successful Instagram photo is free
[ ] entitlement is keyed to Instagram identity, not Telegram account
[ ] account relink cannot reset the gift
[ ] duplicate/concurrent request cannot reserve two free generations
[ ] provider failure releases free reservation
[ ] failed free attempt remains available
[ ] successful result consumes entitlement only after delivery checkpoint
[ ] second/later photo is paid
[ ] paid photo confirmation shows 2.5 🐾
[ ] paid charge happens once
[ ] terminal paid failure refunds once
```

## 7. Instagram video contract

Canonical model:

```text
Seedance 2.5
provider: bytedance/seedance-2-5
resolution: 720p
ratio: 9:16
price: shared HappyFox/Telegram pricing
```

Checklist:

```text
[ ] video has no free entitlement
[ ] choosing Video immediately enters paywall/top-up state
[ ] media sent before top-up is not accepted as a new reference
[ ] top-up copy points to YooKassa/Lava Top
[ ] Continue with insufficient balance stays in paywall
[ ] Continue with sufficient linked balance asks for photo/video reference
[ ] reference -> prompt -> price confirmation -> charge -> provider
[ ] terminal provider failure refunds once
[ ] retry does not create a second provider task
```

## 8. Instagram account link/top-up

```text
[ ] iglink token is random and stored only as digest
[ ] token expires
[ ] token is one-use
[ ] used token cannot silently relink another account
[ ] linked identity uses shared HappyFox balance/history
[ ] Instagram top-up provider chooser contains YooKassa
[ ] Instagram top-up provider chooser contains Lava Top
[ ] Instagram chooser does not expose CryptoBot
[ ] Instagram chooser does not expose Telegram Stars
[ ] Lava Top supports package -> card
[ ] Lava Top supports package -> SBP
[ ] YooKassa reuses existing production payment handler
[ ] Telegram normal payment UI still keeps CryptoBot when enabled
[ ] successful payment updates the same HappyFox ledger used by generation
```

## 9. Durable Instagram job invariants

```text
[ ] durable job exists before charge/promotion side effect
[ ] provider task ID persists immediately after submit
[ ] restart/retry resumes same provider task
[ ] result URL persists before delivery retry
[ ] delivery checkpoint persists after successful send
[ ] local finalization retry does not intentionally regenerate
[ ] local finalization retry does not intentionally re-send when delivered checkpoint exists
[ ] paid retry does not double-charge
[ ] refund cannot be applied twice
[ ] free promotion cannot be consumed twice
```

Do not claim mathematically exactly-once remote delivery across a crash between Meta accepting a message and local checkpoint commit.

## 10. Payment/webhook safety

For each enabled provider:

```text
[ ] signature/auth validation
[ ] provider payment ID uniqueness
[ ] pending -> success transition
[ ] duplicate success webhook is idempotent
[ ] amount/currency/package validation
[ ] transaction belongs to correct HappyFox user
[ ] no double credit
[ ] failures are user-friendly and logged safely
```

## 11. Data/security

```text
[ ] no secrets committed
[ ] no tokens in exception/user output
[ ] PostgreSQL constraints/indexes match runtime usage
[ ] channel identity uniqueness is enforced
[ ] payment/generation ownership prevents IDOR
[ ] public media URL validation prevents obviously invalid local URLs
[ ] webhook HMAC uses raw body
[ ] internal API HMAC remains separate from Meta webhook auth
[ ] admin permissions are enforced server-side
[ ] file paths/uploads resist traversal
```

## 12. Manual live smoke for Instagram activation

Only after Meta credentials/access are configured and change control allows live activation:

```text
[ ] INSTAGRAM_ENABLED=1 deployed on exact green SHA
[ ] webhook subscribed fields: messages,messaging_postbacks,comments
[ ] RU Direct smoke
[ ] EN Direct smoke
[ ] first free photo result
[ ] second photo paid flow
[ ] video immediate paywall before reference
[ ] YooKassa top-up/resume
[ ] Lava card/SBP top-up/resume
[ ] comment -> private invite -> Direct chooser
[ ] duplicate test event does not duplicate business side effect
```

Rollback smoke:

```text
[ ] INSTAGRAM_ENABLED=0 disables Instagram without breaking Telegram/Mini App
```

## 13. Severity

- **P0** — money/security/data loss/full outage.
- **P1** — core Telegram/Instagram creator flow broken.
- **P2** — partial flow or recovery/edge-case defect.
- **P3** — UX/refactor/documentation improvement.

## 14. Final audit format

```text
Production-ready: yes/no
Exact tested SHA: ...
Main SHA: ...
Deploy SHA/run: ...
Blocking defects: ...
Telegram smoke: ...
Instagram dark/live status: ...
Payment invariants: ...
Manual checks still required: ...
```
