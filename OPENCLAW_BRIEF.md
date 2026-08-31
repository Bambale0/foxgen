# OpenClaw Brief — HappyFox

## Role

OpenClaw is a separate development/operations assistant, not part of the Telegram or Instagram runtime.

For this repository, the product context is **HappyFox** in `Bambale0/foxgen`.

Production source of truth:

```text
main
```

Production identity:

```text
Product:         happyfox
Compose project: foxgen-happyfox
Container:       foxgen-happyfox-bot
Database:        happyfox
Redis prefix:    foxgen_happyfox
```

Do not treat historical NEUROMIX/Tanya/`banano_kling` docs as HappyFox production instructions.

## Technical mode

For code/server/API/database/payment/webhook tasks:

1. inspect current repository code/tests first;
2. identify exact branch/SHA and product boundary;
3. make focused changes on a branch/PR;
4. add or update regression tests;
5. update canonical docs when behavior/env/deploy contracts change;
6. require exact-head CI before merge;
7. verify exact-main CI/deploy before claiming production;
8. never print secrets or full `.env`.

Do not mutate `Bambale0/banano_kling` for a HappyFox task unless the user explicitly requests work in that repository.

## Channel architecture

```text
Telegram Bot + Mini App ─┐
                         ├─> shared HappyFox generation/billing/data core
Instagram ────────────────┘
```

Instagram is an adapter, not a second ledger/provider stack.

### Instagram current contract

- first step: Photo/Video;
- Photo -> Seedream 5 Pro High;
- first successful Instagram photo free, later photo paid 2.5 🐾;
- Video -> Seedance 2.5, always paid;
- choosing Video shows top-up before asking for media;
- Instagram top-up: YooKassa + Lava Top;
- Telegram payment menu remains separate and keeps CryptoBot when configured;
- RU/EN auto-detect/persist, with `English`/`Русский` explicit switch;
- paid resume: `Continue` / `Продолжить`;
- Meta webhook HMAC/idempotency must remain fail-closed;
- Instagram routes/worker are disabled unless `INSTAGRAM_ENABLED=1`.

Canonical spec: `docs/instagram-channel.md`.

## Production change safety

Normal path:

```text
branch -> PR main -> CI -> merge -> main CI -> exact-SHA deploy -> smoke
```

Do not call code “live” because it is merged or present in an image. For Instagram distinguish:

```text
code deployed
channel enabled/live
```

They are separate states.

## Destructive actions

Do not perform destructive database cleanup, secret rotation, payment repair, production data deletion or infrastructure replacement without an explicit task and a rollback/reconciliation plan.

For an Instagram-only incident, preferred containment is often:

```dotenv
INSTAGRAM_ENABLED=0
```

while preserving Telegram and durable Instagram state for diagnosis.

## Creative/business mode

For creator/marketing tasks, focus on outcome, hook, visual concept, prompt and CTA. Do not mix implementation details into customer-facing copy.

Instagram/creator copy should be short and creator-friendly. Russian and English meaning/tone should match.

## Documentation priority

When sources disagree:

1. current runtime code;
2. current regression tests;
3. CI/deploy workflows;
4. `.env.happyfox.example` / config;
5. canonical docs (`README.md`, `docs/README.md`, `docs/instagram-channel.md`, architecture/environment/FSM/QA/tracemaps);
6. historical/provider reference snapshots.
