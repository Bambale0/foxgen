# HappyFox

HappyFox — отдельный Telegram AI-продукт: бот + Mini App для генерации изображений и видео, работы с референсами, историей, публикациями, балансом, платежами, партнёрской программой и административным контуром.

## Основа проекта

С 20 августа 2026 `Bambale0/foxgen` использует проверенное production-ядро `Bambale0/banano_kling/tanyapi` вместо прежней параллельной реализации FoxGen.

Точка импорта зафиксирована в [`MIGRATION_SOURCE.md`](MIGRATION_SOURCE.md):

```text
Bambale0/banano_kling@36f92a0504f849c0c591652a880410e33a1c89aa
```

Старый FoxGen сохранён в ветке:

```text
legacy/foxgen-pre-tanyapi-20260820
```

NEUROMIX и HappyFox после точки импорта — независимые продукты в независимых репозиториях. Изменения HappyFox не должны деплоиться в `banano_kling` и не должны использовать его product credentials/data plane.

## Архитектура

```text
Telegram Bot / Telegram WebView
            │
            ├── Next.js 16 + React 19 Mini App
            │       ├── auth/bootstrap
            │       ├── create image/video/motion
            │       ├── uploads/references
            │       ├── history/task status
            │       ├── feed/profile/remix
            │       └── billing/partner/support
            │
            └── Python / aiogram / aiohttp backend
                    ├── generation lifecycle
                    ├── provider adapters
                    ├── payment webhooks
                    ├── PostgreSQL-compatible data layer
                    ├── Redis FSM/cache/locks
                    ├── media delivery
                    └── internal admin APIs
```

Проверенные provider/database/model IDs сохраняются ради совместимости. Пользовательский бренд, credentials, домены, платежные офферы, support/admin config и data-plane identifiers принадлежат HappyFox и изолируются отдельно.

## Стек

- Python 3.12;
- aiogram 3 + aiohttp;
- PostgreSQL в production;
- Redis;
- Next.js 16 + React 19 + TypeScript;
- Playwright browser E2E;
- Docker Compose;
- Nginx/static Next export;
- GitHub Actions CI/CD.

## Основные каталоги

```text
bot/                         backend, handlers, Mini App API, providers
frontend/miniapp-v0/         production Next/React Mini App
data/                        price/model runtime data
scripts/                     deploy, migrations, diagnostics
static/uploads/              media root
ops/                         infrastructure assets
tests/                       backend regression/integration tests
.github/workflows/           HappyFox CI and exact-SHA deployment
```

## Product configuration

Backend product source:

```text
bot/product.py
```

Frontend product source:

```text
frontend/miniapp-v0/lib/product.ts
```

HappyFox defaults:

```text
PRODUCT_ID=happyfox
NEXT_PUBLIC_PRODUCT_ID=happyfox
```

Внутренняя единица расчёта — **кредит**. Текущий production pricing contract сохраняет курс:

```text
1 кредит = 10 ₽
```

Числовая модель ценообразования импортированного production-ядра сохраняется; HappyFox меняет product presentation и собственные платежные/административные настройки, а не алгоритм списаний.

## Локальные проверки

Backend:

```bash
python -m pip install -r requirements.txt
python scripts/apply_visible_copy_fixes.py
python scripts/apply_happyfox_product_copy.py
python -m compileall -q bot scripts
pytest tests/ --ignore=tests/live -m 'not live_smoke'
```

Mini App:

```bash
cd frontend/miniapp-v0
npm ci
npm audit --omit=dev --audit-level=high
npm run lint
npm run build
npx playwright install --with-deps chromium
rm -rf .e2e-server
mkdir -p .e2e-server/mini-app
cp -R out/. .e2e-server/mini-app/
node e2e/critical-flows.mjs
```

## CI

`.github/workflows/ci.yml` является merge/release gate и проверяет:

1. backend dependencies/compile;
2. HappyFox product normalization;
3. Ruff для нового HappyFox Python delta;
4. полный safe regression suite;
5. locked frontend dependencies и production dependency audit;
6. lint + production Next static export;
7. наличие HappyFox branding/logo;
8. Chromium critical browser journeys;
9. production Docker image build и runtime imports.

## Production isolation

Перед первым production deploy обязательно подготовить отдельные HappyFox:

- Telegram bot token;
- backend/webhook domain;
- Mini App domain;
- PostgreSQL database/user;
- Redis DB/prefix;
- KIE/provider webhook secrets;
- payment credentials/offers;
- support contact/admin IDs;
- media/static origin.

Шаблон:

```text
.env.happyfox.example
```

Fail-closed preflight:

```bash
python scripts/validate_happyfox_env.py .env .env.postgres
```

Validator запрещает известные Tanya/NEUROMIX домены, общий legacy Redis namespace, SQLite в production и неполные credentials выбранного payment provider.

Особенно важно: HappyFox **не использует импортированные Lava offer IDs** из старого product config. При `PAYMENT_PROVIDER=lava` все HappyFox `LAVA_OFFER_ID_*` должны быть заданы через environment.

Полный runbook: [`docs/happyfox-production-cutover.md`](docs/happyfox-production-cutover.md).

## Deploy

Production workflow:

```text
.github/workflows/deploy-production.yml
```

Обычный путь:

```text
feature branch
    → PR to main
    → CI green
    → merge exact tested commit
    → CI on main
    → HappyFox production preflight
    → exact-SHA backend + Mini App deploy
    → health/revision smoke
```

Runtime identities:

```text
Compose project: foxgen-happyfox
Container:       foxgen-happyfox-bot
Product:         happyfox
Redis prefix:    foxgen_happyfox (recommended)
```

Deployment status публикуется в GitHub context:

```text
foxgen/production-deploy
```

## Безопасность миграции

Не делать массовый rename технических `banana_*`, `banano_*`, provider IDs, callback values или существующих database enums только ради брендинга. Они являются compatibility surface и меняются лишь отдельной миграцией с тестами.

Не переносить `.env` из NEUROMIX целиком. HappyFox credentials должны создаваться отдельно.

Не возвращать старую экспериментальную FoxGen архитектуру из legacy-ветки. Если в ней есть полезная функция, переносить её точечно поверх текущего tanyapi-derived core с regression/browser E2E.
