# HappyFox AI Platform

> **Multi-channel AI product** · Telegram · Instagram · Python · PostgreSQL · Redis · Next.js/React · Playwright · CI/CD
>
> Repository codename: `foxgen`.

HappyFox is a production AI media product with a shared generation and billing core exposed through multiple customer channels. Telegram provides the full product experience through a bot and Mini App, while Instagram acts as a separate acquisition and creator channel on top of the same backend domain model.

## Why this project is interesting

HappyFox demonstrates how to keep channel-specific UX separate from core business logic. Telegram and Instagram adapters do not duplicate generation, wallet or payment rules; they call the same underlying services.

## Engineering highlights

- Python backend with aiogram/aiohttp integration.
- PostgreSQL as the production data plane.
- Redis for FSM, cache, idempotency and runtime coordination.
- Telegram Bot + Telegram Mini App.
- Instagram Creator/Business webhook channel.
- Channel-neutral identity mapping and account linking.
- Shared generation lifecycle and billing ledger.
- Image and video generation through provider adapters.
- Next.js 16 + React 19 + TypeScript Mini App frontend.
- Playwright browser gates including Chromium and iPhone WebKit.
- Docker Compose + Nginx production runtime.
- GitHub Actions exact-SHA release and deploy flow.

## Channel architecture

```text
Telegram updates --------+
Telegram Mini App --------+----> shared HappyFox core
Instagram webhooks -------+          |-- identity
                                      |-- generation lifecycle
                                      |-- billing / ledger
                                      |-- PostgreSQL
                                      |-- Redis
                                      |-- media delivery
                                      +-- admin/internal APIs

Next.js / React Mini App -------> public product origin
AI provider adapters ----------> image/video providers
Payment adapters --------------> payment providers
```

## Telegram

Telegram remains the complete product interface and includes generation, wallet, payments, history, prompts, referrals and creator flows.

The Mini App is built independently from provider credentials: browser clients communicate only with the backend and never receive upstream AI secrets.

## Instagram integration

Instagram is implemented as a real channel adapter rather than a separate bot copy. The integration includes:

- webhook signature handling;
- creator/business message flows;
- RU/EN language detection and persistence;
- channel-neutral user identity mapping;
- one-time account linking to Telegram;
- generation orchestration;
- payment/top-up handoff;
- durable job processing and checkpoints.

The channel is fail-closed and only enabled when its runtime configuration is explicitly activated.

## Stack

| Area | Technology |
| --- | --- |
| Backend | Python 3.12, aiogram 3, aiohttp |
| Data | PostgreSQL, Redis |
| Frontend | Next.js 16, React 19, TypeScript |
| Channels | Telegram Bot, Telegram Mini App, Instagram API |
| Testing | pytest, Playwright Chromium + WebKit |
| Delivery | Docker Compose, Nginx, GitHub Actions |

## Quality and release flow

```text
feature/fix branch
      |
      v
     PR
      |
      +--> backend regression
      +--> frontend lint/build
      +--> browser E2E
      +--> release gates
      |
      v
 exact tested main SHA
      |
      v
 production deploy + health/revision smoke
```

The deployment policy avoids shipping arbitrary working-tree state. Production is tied to an exact commit that passed the release gates.

## Local verification

Backend:

```bash
python -m pip install -r requirements.txt
python -m compileall -q bot scripts
pytest tests/ --ignore=tests/live -m 'not live_smoke'
```

Mini App:

```bash
cd frontend/miniapp-v0
npm ci
npm run lint
npm run build
```

## Documentation

Detailed product and operations documentation lives in `docs/`:

- [`docs/README.md`](docs/README.md)
- [`docs/instagram-channel.md`](docs/instagram-channel.md)
- [`docs/architecture.md`](docs/architecture.md)
- [`docs/environment.md`](docs/environment.md)
- [`docs/development-deployment.md`](docs/development-deployment.md)
- [`docs/production-deployment.md`](docs/production-deployment.md)

## Portfolio note

HappyFox is primarily a systems-design case: one product core supports multiple customer channels while keeping identity, billing, provider integrations and release guarantees consistent across them.
