# HappyFox roadmap

Updated: 2026-08-31. Production source: `Bambale0/foxgen:main`.

This roadmap records current direction, not promised dates. GitHub issues/PRs remain the execution tracker.

## Delivered baseline

### Product/core

- standalone HappyFox repository/runtime isolated from NEUROMIX/Tanya;
- Telegram bot + Telegram Mini App;
- image/video generation, references, history/feed/profile/remix;
- shared HappyFox balance/transactions;
- PostgreSQL production + Redis;
- exact-SHA CI/CD and isolated production preflight;
- YooKassa, Lava Top and retained Telegram payment integrations including CryptoBot where configured.

### Instagram foundation

Implemented in source:

- Instagram API with Instagram Login transport;
- signed webhook verification and Redis idempotency;
- message/postback/comment normalization;
- channel-neutral Instagram identities;
- secure Telegram account linking;
- Direct creator flow with first Photo/Video choice;
- Photo -> Seedream 5 Pro High;
- first successful Instagram photo free;
- later photos paid at 2.5 🐾 current contract;
- Video -> Seedance 2.5, always paid;
- video paywall before reference upload;
- Instagram top-up via YooKassa/Lava Top using shared ledger;
- `Продолжить / Continue` resume;
- automatic persisted RU/EN language switching;
- durable provider task/result/delivery checkpoints, refund/promotion recovery.

Instagram code can ship dark; live route registration requires `INSTAGRAM_ENABLED=1`.

## P0: Instagram live activation

Remaining external/operational work before calling the channel live:

- configure Meta production app/account with Instagram Login;
- confirm required permissions/access level;
- provision production access token/account ID/secrets outside Git;
- verify public `/instagram/webhook` GET challenge;
- verify valid/invalid `X-Hub-Signature-256` behavior;
- subscribe `messages,messaging_postbacks,comments`;
- run controlled RU/EN Direct smoke;
- run first-free-photo smoke;
- run YooKassa and Lava Top top-up/resume smoke;
- run paid Seedance video smoke;
- validate comment acquisition/private-reply limits;
- document activation evidence and rollback.

## P1: Instagram publishing

Transport primitives exist; product publishing should remain an explicit user action.

Next work:

- explicit `Publish` confirmation after generation;
- public HTTPS media preparation/retention policy;
- Reel/image container status handling and user-friendly failures;
- publish result/history linkage;
- duplicate publish protection;
- RU/EN publishing copy;
- permissions/review validation in Meta live app.

Do not auto-publish generated media without user confirmation.

## P1: observability

- structured channel/event/job correlation IDs;
- Instagram webhook valid/invalid/idempotent counters;
- generation queue/lease/retry metrics;
- provider latency/failure metrics by model;
- payment pending/reconcile alerts;
- free-promotion reserve/consume/release metrics;
- deployment SHA and runtime version in operational health/summary;
- alerting for PostgreSQL/Redis/disk/media failures.

## P1: payment reliability

- keep provider webhook idempotency tests current;
- reconciliation tooling for YooKassa/Lava/CryptoBot and other active Telegram providers;
- safe manual repair audit trail;
- alert on aged pending transactions;
- keep Instagram provider subset separated from Telegram global provider availability.

## P1: creator UX

- keep Instagram creator path within a few conversational steps;
- improve media/prompt examples without adding technical jargon;
- preserve language automatically through result/top-up/resume;
- add creator-friendly recovery for expired account-link/token/top-up flow;
- consider result actions that make sense specifically in Direct rather than copying Telegram menus.

## P2: architecture cleanup

- continue extracting large legacy modules behind clear application/service boundaries;
- channel adapters must depend inward on shared domain/services;
- unify shared provider task lifecycle without coupling core to Telegram/Meta payload objects;
- keep compatibility IDs until a deliberate migration exists;
- add migrations/tests before schema cleanup.

## P2: data and recovery

- test backup restore, not just backup creation;
- formalize retention for uploaded/generated media;
- monitor storage growth;
- document targeted repair for stuck generation/payment/promotion state;
- add migration smoke for channel tables/jobs in PostgreSQL.

## P2: documentation quality

Canonical documentation now lives around HappyFox/main and the Instagram contour. Continue with:

- automated Markdown link checking;
- stale NEUROMIX/Tanya term audit for non-historical docs;
- document freshness metadata where useful;
- keep provider API snapshots explicitly labeled reference-only;
- update FSM/QA/tracemaps in the same PR as behavioral changes.

## P3: developer experience

- one local quality-gate command for backend + Mini App + Instagram subset;
- pre-commit formatting/lint/docs checks;
- provider mocks/fixtures for generation lifecycle;
- easier safe local Meta webhook fixtures;
- dependency update policy;
- documented non-production environment with isolated data/payment credentials.

## Non-goals without migration plan

Do not casually:

- mass-rename `banana_*` / `banano_*` compatibility identifiers;
- change model/provider IDs for branding;
- merge Telegram and Instagram user IDs into one numeric namespace;
- create a second Instagram ledger/payment backend;
- remove CryptoBot from Telegram because Instagram hides it;
- bypass HMAC/idempotency to make Meta integration easier;
- reuse NEUROMIX runtime/data as rollback.

## Stable production definition

Current HappyFox is stable when:

- exact-SHA deployment evidence is reproducible;
- Telegram/Mini App critical flows remain green on Chromium+iPhone WebKit;
- payment/generation idempotency and refunds are covered;
- PostgreSQL/Redis and backups are operationally verified;
- if Instagram is disabled, it cannot destabilize Telegram;
- if Instagram is enabled, RU/EN photo/video/payment/comment smoke passes;
- operators can diagnose common failures from canonical docs without relying on old NEUROMIX instructions.
