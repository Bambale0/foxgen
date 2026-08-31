# Документация HappyFox

Этот каталог относится к `Bambale0/foxgen` и текущему продукту **HappyFox**. Production source of truth — ветка `main`.

Старые документы, импортированные вместе с production-core из `banano_kling`, могут содержать исторические названия NEUROMIX/Tanya, старые домены, ветки `dev/tanyapi` или provider snapshots. Они не являются текущим production runbook, если явно не перечислены ниже как canonical.

## Canonical docs

| Документ | Назначение |
| --- | --- |
| [../README.md](../README.md) | краткий current-state проекта |
| [instagram-channel.md](instagram-channel.md) | Instagram Direct/comments, Photo/Video FSM, RU/EN, billing, Meta activation |
| [architecture.md](architecture.md) | текущая channel-neutral архитектура |
| [environment.md](environment.md) | production/dev env contract и Instagram variables |
| [development-deployment.md](development-deployment.md) | branch/PR/CI flow для `foxgen` |
| [production-deployment.md](production-deployment.md) | exact-SHA production deployment |
| [production_auto_deploy.md](production_auto_deploy.md) | правила автоматического production deploy из `main` |
| [happyfox-production-cutover.md](happyfox-production-cutover.md) | isolated HappyFox runtime/cutover и Instagram live activation |
| [happyfox-handoff.md](happyfox-handoff.md) | product boundary и handoff evidence |
| [runbook.md](runbook.md) | ежедневные production операции |
| [troubleshooting.md](troubleshooting.md) | диагностика runtime/Instagram/payment ошибок |
| [../FSM_USER_FLOWS.md](../FSM_USER_FLOWS.md) | Telegram + Instagram FSM |
| [../QA_AUDIT_CHECKLIST.md](../QA_AUDIT_CHECKLIST.md) | обязательный release QA |
| [../tracemap_generation.md](../tracemap_generation.md) | generation trace map |
| [../tracemap_payments.md](../tracemap_payments.md) | payment trace map |

## Current release flow

```text
feature/fix/docs branch
    -> PR to main
    -> CI on exact PR head
    -> merge
    -> CI on exact main SHA
    -> isolated HappyFox preflight
    -> exact-SHA production deploy
    -> health + revision smoke
```

Не использовать старую схему `dev -> tanyapi` для HappyFox. Она относится к исходному NEUROMIX history и не является release policy `foxgen`.

## Current product topology

```text
Telegram Bot ───────────┐
Telegram Mini App ──────┼──> HappyFox backend/core ──> providers / billing / DB
Instagram Direct ───────┤
Instagram comments ─────┘

Public origin: https://alena.chillcreative.ru
Mini App:      https://alena.chillcreative.ru/mini-app/
Compose:       foxgen-happyfox
Container:     foxgen-happyfox-bot
Database:      happyfox
Redis prefix:  foxgen_happyfox
Branch:        main
```

## Instagram summary

Instagram is a channel adapter over the same HappyFox user/generation/billing domain.

- first interaction -> `Фото / Photo` or `Видео / Video`;
- Photo -> Seedream 5 Pro High;
- first successful Instagram photo is free;
- later photos are paid;
- Video -> Seedance 2.5 and is always paid;
- video selection immediately enters top-up/resume flow before reference upload;
- Instagram top-up shows YooKassa and Lava Top only;
- Telegram payment menu keeps its own providers, including CryptoBot;
- language auto-detects RU/EN and persists per Instagram identity;
- live route registration is gated by `INSTAGRAM_ENABLED=1`.

See [instagram-channel.md](instagram-channel.md).

## Documentation ownership

When changing a channel, payment flow, model contract, env variable, deploy workflow or user FSM, update in the same PR:

1. the canonical feature document;
2. architecture/environment if boundaries changed;
3. FSM/tracemap if user transitions changed;
4. QA checklist if a new invariant needs regression coverage;
5. README/index links if a new canonical document was added.

## Provider reference snapshots

Files such as `banana_api.md`, `kling_api*.md`, `veo_api.md`, `motion_control_api.md`, `crypto_api.md`, `tbank_api.md`, `kie_ai_integration.md` may be external API snapshots or historical integration notes. They are useful as references but do not override runtime code/tests.

Priority when docs disagree:

1. `bot/*` and `bot/services/*`;
2. current tests;
3. `.github/workflows/*` and deploy scripts;
4. `.env.happyfox.example` / `bot/config.py`;
5. canonical docs above;
6. historical/provider reference docs.

## Historical documents

Date-stamped audits, old migration notes and NEUROMIX-specific docs are preserved for provenance. Do not execute old paths, domains, service names, branch policies or payment instructions without checking the canonical HappyFox docs first.
